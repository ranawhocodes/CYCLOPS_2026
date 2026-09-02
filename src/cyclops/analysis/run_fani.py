"""
Run identification + classification over every real MODIS scene of Fani, and
score both against IBTrACS best track.

Writes artifacts/fani_analysis.json and artifacts/fani_frames.json. The console
and every figure read those; no number is typed by hand anywhere downstream.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import ARTIFACTS
from ..data.features import filter_nio
from ..data.gibs import fetch_scene, overpass_utc
from ..data.ibtracs import load
from ..domain.imd import to_imd_category, wind_to_t_number
from ..eval.baselines import GEOD
from .centre_fix import find_centre
from .dvorak import estimate, smooth_series

FANI = "2019116N02090"
PATCH_KM = 1024.0
SIZE = 256

# Day passes only. A night overpass at 86 E falls at roughly 19:46 UTC on the
# PREVIOUS calendar day, while GIBS dates that granule by the local night it
# belongs to. Reconciling the two against a UTC best track introduces a timing
# ambiguity of up to several hours, which at Fani's 10-15 kt translation is tens
# of kilometres of spurious position error. Day passes have no such ambiguity,
# so the result is measured on those and the scene count is reported honestly.
PASSES = ("terra_day", "aqua_day")


def fani_track() -> pd.DataFrame:
    f = filter_nio(load())
    f = f[f.sid == FANI].sort_values("iso_time").reset_index(drop=True)
    if f.empty:
        raise SystemExit("Fani not found in IBTrACS")
    return f


def _interp(f: pd.DataFrame, when) -> tuple[float, float, float] | None:
    """Best-track position and intensity at an arbitrary time."""
    t = f.iso_time.map(lambda x: x.timestamp()).to_numpy()
    x = when.timestamp()
    if x < t[0] or x > t[-1]:
        return None
    return (float(np.interp(x, t, f.lat)),
            float(np.interp(x, t, f.lon)),
            float(np.interp(x, t, f.wind_kt_3min)))


def run() -> dict:
    f = fani_track()
    dates = pd.date_range(f.iso_time.min().normalize(),
                          f.iso_time.max().normalize(), freq="D")

    frames = []
    for d in dates:
        ds = d.strftime("%Y-%m-%d")
        for p in PASSES:
            ov = overpass_utc(p, d.to_pydatetime(), 86.0)
            truth = _interp(f, ov)
            if truth is None:
                continue
            t_lat, t_lon, t_kt = truth

            # IMPORTANT: the crop and the first guess use only data available
            # BEFORE the overpass. Centring on the truth would make the
            # centre-fix error a measure of nothing.
            prior = f[f.iso_time <= ov]
            if len(prior) < 2:
                continue
            last = prior.iloc[-1]
            prev = prior.iloc[-2]

            # First guess: extrapolate the storm's recent motion forward to the
            # overpass time. This is what an operational scheme hands its
            # centre-fixer, and it is a far better starting point than the last
            # fix alone — Fani was moving at 10-15 kt.
            dt_prev = (last.iso_time - prev.iso_time).total_seconds()
            dt_fwd = (ov - last.iso_time).total_seconds()
            if dt_prev > 0:
                rate = min(dt_fwd / dt_prev, 3.0)      # cap wild extrapolation
                g_lat = float(last.lat + (last.lat - prev.lat) * rate)
                g_lon = float(last.lon + (last.lon - prev.lon) * rate)
            else:
                g_lat, g_lon = float(last.lat), float(last.lon)

            c_lat, c_lon = g_lat, g_lon

            sc = fetch_scene(c_lat, c_lon, ds, pass_name=p,
                             patch_km=PATCH_KM, size=SIZE)
            if sc is None:
                continue

            # The crop is centred on the first guess, so the first guess sits at
            # the centre pixel of the scene.
            fix = find_centre(sc.kelvin, sc.valid, sc.bbox, sc.km_per_px,
                              first_guess_rc=(SIZE / 2, SIZE / 2),
                              search_radius_km=120.0)
            est = estimate(sc.kelvin, sc.valid, fix, sc.km_per_px)

            _, _, err_m = GEOD.inv(fix.lon, fix.lat, t_lon, t_lat)
            # Baseline: the motion-extrapolated first guess, unrefined. This is
            # the honest thing to beat — beating "last fix, no motion" would be
            # a softer target than an operational scheme actually faces.
            _, _, base_m = GEOD.inv(g_lon, g_lat, t_lon, t_lat)
            _, _, lastfix_m = GEOD.inv(float(last.lon), float(last.lat), t_lon, t_lat)

            frames.append({
                "date": ds, "pass": p,
                "observed_at": ov.isoformat(),
                "first_guess": {"lat": round(g_lat, 3), "lon": round(g_lon, 3)},
                "truth": {"lat": round(t_lat, 3), "lon": round(t_lon, 3),
                          "wind_kt": round(t_kt, 1),
                          "imd_category": to_imd_category(t_kt),
                          "t_number": round(float(wind_to_t_number(t_kt)), 1)},
                "fix": {"lat": round(fix.lat, 3), "lon": round(fix.lon, 3),
                        "detected": bool(fix.detected),
                        "refined": bool(fix.refined),
                        "confidence": round(fix.confidence, 3),
                        "symmetry": round(fix.symmetry, 3),
                        "eye_detected": bool(fix.eye_detected),
                        "eye_temp_c": fix.eye_temp_c,
                        "ring_temp_c": fix.ring_temp_c,
                        "cold_fraction": round(fix.cold_fraction, 4),
                        "reason": fix.reason},
                "dvorak": {"pattern": est.pattern, "t_number": est.t_number,
                           "wind_kt": est.wind_kt,
                           "imd_category": est.imd_category,
                           "cdo_diameter_km": est.cdo_diameter_km,
                           "rule": est.rule},
                "centre_error_km": round(err_m / 1000.0, 1),
                "first_guess_error_km": round(base_m / 1000.0, 1),
                "last_fix_error_km": round(lastfix_m / 1000.0, 1),
                "scene": {"coverage": round(sc.coverage, 3),
                          "min_c": round(sc.min_c, 1),
                          "bbox": [round(v, 4) for v in sc.bbox]},
            })
            print(f"  {ds} {p:12s} fix={err_m/1000:6.1f}km "
                  f"guess={base_m/1000:6.1f}km {'REF' if fix.refined else 'held'} "
                  f"sym={fix.symmetry:.2f} {est.pattern:16s} T{est.t_number:.1f} "
                  f"-> {est.wind_kt:5.1f}kt vs {t_kt:5.1f}kt", flush=True)

    if not frames:
        raise SystemExit("no frames analysed")

    frames.sort(key=lambda x: x["observed_at"])

    # Time-consistency constraint, reported alongside the raw estimate so the
    # effect of the constraint is visible rather than silently baked in.
    raw_t = [fr["dvorak"]["t_number"] for fr in frames]
    sm_t = smooth_series(raw_t, max_step=0.5)
    from ..domain.imd import t_number_to_wind
    for fr, t in zip(frames, sm_t):
        fr["dvorak"]["t_number_smoothed"] = round(float(t), 1)
        w = float(t_number_to_wind(t))
        fr["dvorak"]["wind_kt_smoothed"] = round(w, 1)
        fr["dvorak"]["imd_category_smoothed"] = to_imd_category(w)

    # ---- scoring ---------------------------------------------------------
    err = np.array([fr["centre_error_km"] for fr in frames])
    base = np.array([fr["first_guess_error_km"] for fr in frames])
    lastfix = np.array([fr["last_fix_error_km"] for fr in frames])
    det = np.array([fr["fix"]["detected"] for fr in frames])

    tw = np.array([fr["truth"]["wind_kt"] for fr in frames])
    pw = np.array([fr["dvorak"]["wind_kt"] for fr in frames])
    sw = np.array([fr["dvorak"]["wind_kt_smoothed"] for fr in frames])

    tcat = [fr["truth"]["imd_category"] for fr in frames]
    pcat = [fr["dvorak"]["imd_category_smoothed"] for fr in frames]
    from ..domain.imd import CATEGORIES
    ti = np.array([CATEGORIES.index(c) if c in CATEGORIES else 0 for c in tcat])
    pi = np.array([CATEGORIES.index(c) if c in CATEGORIES else 0 for c in pcat])

    summary = {
        "storm": "Fani", "sid": FANI, "season": 2019,
        "data": {
            "imagery": "REAL — NASA GIBS, MODIS Terra/Aqua Band 31 (11 um)",
            "labels": "REAL — IBTrACS v04r01 NEWDELHI_WIND (3-min sustained, IMD)",
            "n_scenes": len(frames),
            "note": ("Crops are centred on the PREVIOUS best-track fix, never on "
                     "the truth at overpass time, so the centre-fix error is a "
                     "genuine measurement."),
        },
        "identification": {
            "detection_rate": round(float(det.mean()), 3),
            "centre_error_km": {
                "mean": round(float(err.mean()), 1),
                "median": round(float(np.median(err)), 1),
                "p90": round(float(np.percentile(err, 90)), 1),
                "max": round(float(err.max()), 1),
            },
            "first_guess_error_km": {
                "mean": round(float(base.mean()), 1),
                "median": round(float(np.median(base)), 1),
            },
            "last_fix_error_km": {
                "mean": round(float(lastfix.mean()), 1),
                "median": round(float(np.median(lastfix)), 1),
            },
            "skill_vs_first_guess": round(float(1 - err.mean() / base.mean()), 3),
            "frames_refined": int(sum(fr["fix"]["refined"] for fr in frames)),
            "eye_detected_frames": int(sum(fr["fix"]["eye_detected"] for fr in frames)),
        },
        "classification": {
            "method": "Objective Dvorak (enhanced IR); Dvorak tables unfitted, "
                      "but two eye-gate thresholds were chosen by inspecting "
                      "Fani, so these figures are not fully out-of-sample",
            "raw": {
                "rmse_kt": round(float(np.sqrt(((pw - tw) ** 2).mean())), 2),
                "mae_kt": round(float(np.abs(pw - tw).mean()), 2),
                "bias_kt": round(float((pw - tw).mean()), 2),
            },
            "time_constrained": {
                "rmse_kt": round(float(np.sqrt(((sw - tw) ** 2).mean())), 2),
                "mae_kt": round(float(np.abs(sw - tw).mean()), 2),
                "bias_kt": round(float((sw - tw).mean()), 2),
            },
            "category_exact": round(float((ti == pi).mean()), 3),
            "category_within_one": round(float((np.abs(ti - pi) <= 1).mean()), 3),
            "patterns": {p: int(sum(1 for fr in frames if fr["dvorak"]["pattern"] == p))
                         for p in {fr["dvorak"]["pattern"] for fr in frames}},
        },
    }

    (ARTIFACTS / "fani_frames.json").write_text(json.dumps(frames, indent=2))
    (ARTIFACTS / "fani_analysis.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    s = run()
    print("\n" + "=" * 70)
    print(json.dumps(s, indent=2))
    print("=" * 70)
