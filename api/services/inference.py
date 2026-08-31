"""
Inference engine.

Models load once at startup, never per request. Loading a checkpoint per request
turns a 200 ms call into a 3 s call and makes the replay stutter in front of
whoever is watching.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cyclops.domain.imd import (CATEGORY_LABEL, to_imd_category,  # noqa: E402
                                wind_to_t_number)
from cyclops.eval.baselines import persistence_forecast  # noqa: E402
from cyclops.eval.cone import cone_polygon  # noqa: E402
from cyclops.models.cam import (EXPECTED_CAM_FOCUS, IntensityCAM,  # noqa: E402
                                frame_png, frame_png_georef, overlay_png)
from cyclops.models.fusion import CyclopsFusion  # noqa: E402
from cyclops.models.nowcast_gbm import NowcastGBM  # noqa: E402


class InferenceEngine:
    def __init__(self, intensity_path: Path, nowcast_path: Path,
                 cone_path: Path, artifacts_dir: Path):
        self.ready = False
        self.intensity_model = None
        self.cam = None
        self.nowcast = None
        self.cone_radii: dict[int, float] = {}
        self.notes: list[str] = []
        self.version = "unloaded"

        if Path(intensity_path).exists():
            ckpt = torch.load(intensity_path, map_location="cpu", weights_only=False)
            m = CyclopsFusion()
            m.load_state_dict(ckpt["state_dict"])
            m.eval()
            self.intensity_model = m
            self.cam = IntensityCAM(m, device="cpu")
            self.trained_on = ckpt.get("trained_on", "unknown")
            import hashlib
            self.version = hashlib.sha256(
                Path(intensity_path).read_bytes()).hexdigest()[:12]
        else:
            self.notes.append(f"intensity model missing at {intensity_path}")
            self.trained_on = "n/a"

        if Path(nowcast_path).exists():
            self.nowcast = NowcastGBM.load(nowcast_path)
        else:
            self.notes.append(f"nowcast model missing at {nowcast_path}")

        if Path(cone_path).exists():
            blob = json.loads(Path(cone_path).read_text())
            self.cone_radii = {int(k): float(v) for k, v in blob["radii_km"].items()}
            self.cone_meta = blob
        else:
            self.cone_meta = {}

        self.metrics = {}
        for f in ("metrics_nowcast.json", "metrics_intensity.json"):
            p = Path(artifacts_dir) / f
            if p.exists():
                self.metrics[f.replace("metrics_", "").replace(".json", "")] = \
                    json.loads(p.read_text())

        # Interval width is driven by the model's ACTUAL held-out RMSE, read from
        # the metrics the training run wrote. Hard-coding a width would let the
        # displayed uncertainty drift away from the measured error the moment
        # the model was retrained.
        self.rmse_kt = 9.0
        try:
            self.rmse_kt = float(
                self.metrics["intensity"]["ablation"]["fusion"]["rmse_kt"])
        except (KeyError, TypeError, ValueError):
            self.notes.append("intensity metrics missing — interval width "
                              "falls back to 9.0 kt")

    def warmup(self) -> None:
        """
        First inference includes graph setup and allocator warm-up and can take
        seconds. Doing it at startup means it never happens on a judge's first
        click, which is what the sub-5-second latency claim depends on.
        """
        if self.intensity_model is not None:
            from cyclops.config import IR_SIZE, WIND_SIZE
            z_ir = np.zeros((1, 3, IR_SIZE, IR_SIZE), np.float32)
            z_w = np.zeros((1, 3, WIND_SIZE, WIND_SIZE), np.float32)
            from cyclops.preprocess import ENV_DIM
            self.classify(z_ir[0], z_w[0], 0.0, np.zeros(ENV_DIM, np.float32),
                          include_cam=True, category_hint="CS")
        self.ready = True

    # -- classification ----------------------------------------------------
    def classify(self, ir, wind, wind_present, env, include_cam=True,
                 category_hint: str | None = None) -> dict:
        # Degrade visibly rather than crash. If the intensity checkpoint is
        # missing, the console shows an empty panel with a reason instead of the
        # whole replay dying — the nowcast, track and cone still work, which is
        # most of the demo.
        if self.intensity_model is None:
            return {"unavailable": True,
                    "reason": "intensity model not loaded — run `make intensity`"}
        t0 = time.perf_counter()
        ir_t = torch.from_numpy(np.asarray(ir, np.float32)[None])
        w_t = torch.from_numpy(np.asarray(wind, np.float32)[None])
        p_t = torch.tensor([float(wind_present)], dtype=torch.float32)
        e_t = torch.from_numpy(np.asarray(env, np.float32)[None])

        with torch.no_grad():
            out = self.intensity_model(ir_t, w_t, p_t, e_t)
        kt = float(out["wind_kt"][0])
        cat = to_imd_category(kt)

        payload = {
            "wind_kt": round(kt, 1),
            "wind_kt_ci": self._interval(kt),
            "imd_category": cat,
            "imd_category_label": CATEGORY_LABEL.get(cat, cat),
            "t_number": round(float(wind_to_t_number(kt)), 1),
            "t_number_head": round(float(out["t_number"][0]), 1),
            "detection_confidence": round(float(torch.sigmoid(out["det_logit"][0])), 3),
            "centre_offset_px": [round(float(v), 2) for v in out["d_centre"][0]],
            "wind_convention": "3-minute sustained (IMD)",
            "model": {"name": "CyclopsFusion", "version": self.version,
                      "trained_on": self.trained_on},
            "inference_ms": int((time.perf_counter() - t0) * 1000),
        }

        if include_cam and self.cam is not None:
            heat = self.cam(ir_t, w_t, p_t, e_t)
            payload["cam"] = {
                "format": "png;base64",
                "data": base64.b64encode(
                    overlay_png(np.asarray(ir)[0], heat, alpha=0.55)).decode(),
                "opacity_hint": 0.55,
                "expected_focus": EXPECTED_CAM_FOCUS.get(category_hint or cat, ""),
                "note": ("Regression Grad-CAM: brighter regions increased the "
                         "predicted wind speed."),
            }
            payload["inference_ms"] = int((time.perf_counter() - t0) * 1000)
        return payload

    def _interval(self, kt: float) -> list[float]:
        """
        90% interval around the point estimate.

        Half-width is the model's own held-out RMSE scaled by 1.645, the
        two-sided 90% normal quantile, and widened above 60 kt where the
        training set thins out and the error is measurably larger.

        This is a calibrated heuristic, NOT an ensemble. It assumes the error is
        roughly normal and homoscedastic within an intensity band, which is only
        approximately true. The honest upgrade is MC-dropout or a deep ensemble,
        which would give a per-sample interval that widens when the model is
        actually unsure rather than merely when the storm is strong.
        """
        sigma = self.rmse_kt + 0.06 * max(kt - 60.0, 0.0)
        half = 1.645 * sigma
        return [round(max(kt - half, 0.0), 1), round(kt + half, 1)]

    def frame_png(self, ir_channel0: np.ndarray) -> bytes:
        return frame_png(np.asarray(ir_channel0))

    def frame_png_georef(self, ir_channel0: np.ndarray) -> bytes:
        return frame_png_georef(np.asarray(ir_channel0))

    # -- nowcast -----------------------------------------------------------
    def forecast(self, history: pd.DataFrame) -> dict:
        """
        Track and intensity nowcast at 6/12/18/24 h with quantile bands.

        `history` must already be truncated to the current storm clock by the
        caller's data access; this function never reaches back for more.
        """
        if self.nowcast is None or history.empty:
            return {"forecasts": [], "baselines": {}, "cone": []}

        row = history.iloc[[-1]]
        preds = self.nowcast.predict(row)
        forecasts, cone_pts = [], []
        t0 = row.iloc[0].iso_time

        for lead in self.nowcast.leads_h:
            p = preds[lead]
            lat, lon = float(p["lat"][0]), float(p["lon"][0])
            kt = float(p["wind_kt"][0])
            if not np.isfinite(lat) or not np.isfinite(lon):
                continue
            forecasts.append({
                "lead_h": int(lead),
                "valid_at": (t0 + timedelta(hours=int(lead))).isoformat(),
                "position": {"lat": round(lat, 3), "lon": round(lon, 3)},
                "position_q10": {"lat": round(float(p["lat_q10"][0]), 3),
                                 "lon": round(float(p["lon_q10"][0]), 3)},
                "position_q90": {"lat": round(float(p["lat_q90"][0]), 3),
                                 "lon": round(float(p["lon_q90"][0]), 3)},
                "cone_radius_km": round(self.cone_radii.get(int(lead), float("nan")), 1),
                "wind_kt": round(kt, 1),
                "wind_kt_q10": round(float(p["wind_kt_q10"][0]), 1),
                "wind_kt_q90": round(float(p["wind_kt_q90"][0]), 1),
                "imd_category": to_imd_category(kt),
            })
            cone_pts.append({"lead_h": int(lead), "lat": lat, "lon": lon})

        baselines = {}
        for lead in self.nowcast.leads_h:
            pf = persistence_forecast(row, lead)
            baselines[str(lead)] = {
                "persistence": {
                    "lat": _f(pf.lat.iloc[0]), "lon": _f(pf.lon.iloc[0]),
                    "wind_kt": _f(pf.wind_kt.iloc[0]),
                },
            }

        return {
            "forecasts": forecasts,
            "baselines": baselines,
            "cone": cone_polygon(cone_pts, self.cone_radii),
            "cone_definition": ("Radius enclosing 67% of this model's own "
                                "validation position errors at each lead time "
                                "(NHC convention)."),
            "cone_measured_coverage": self.cone_meta.get("measured_test_coverage", {}),
            "model": {"name": "NowcastGBM-quantile",
                      "backend": self.nowcast.backend,
                      "target": "residual from persistence extrapolation"},
        }


def _f(v):
    return round(float(v), 3) if v is not None and np.isfinite(v) else None
