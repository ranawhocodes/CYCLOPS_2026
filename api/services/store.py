"""
Case store.

Backed by the real IBTrACS track plus rendered scenes, held in memory. The TRD
specifies PostGIS, and the schema in doc 02 B7 is the target; for the MVP this
in-memory store implements the same access contract - crucially including the
`until` parameter, which is the causality enforcement point. When Postgres lands
this class is replaced and the callers do not change.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cyclops.data.features import (add_forecast_targets, build_track_features,  # noqa: E402
                                   filter_nio)
from cyclops.data.ibtracs import load, storm_table  # noqa: E402
from cyclops.data.persistence_frame import add_persistence_frame  # noqa: E402
from cyclops.data.synth_ir import render_ir_scene, render_wind_field  # noqa: E402
from cyclops.domain.imd import to_imd_category  # noqa: E402
from cyclops.preprocess import preprocess_sample  # noqa: E402

# Cases offered in the console. All are in held-out test seasons, so the replay
# is an out-of-sample demonstration and not a recital of training data.
FEATURED = [
    ("2019116N02090", "Fani",     "Odisha landfall; rapid intensification"),
    ("2020136N10088", "Amphan",   "Explosive intensification; Sundarbans"),
    ("2023129N08091", "Mocha",    "Extreme intensity; Myanmar/Bangladesh"),
    ("2019296N15066", "Kyarr",    "Arabian Sea; strongest since 2007"),
    ("2023156N10067", "Biparjoy", "Long-lived Arabian Sea; Gujarat"),
]


class CaseStore:
    def __init__(self):
        fixes = filter_nio(load())
        self.frame = add_persistence_frame(
            add_forecast_targets(build_track_features(fixes)))
        self.storms = storm_table(fixes).set_index("sid")
        self._scene_cache: dict[tuple, dict] = {}

    # -- catalogue ---------------------------------------------------------
    def cases(self) -> list[dict]:
        out = []
        for sid, name, note in FEATURED:
            if sid not in self.storms.index:
                continue
            s = self.storms.loc[sid]
            t = self.track(sid)
            out.append({
                "id": sid,
                "name": name,
                "season": int(s.season),
                "basin": "North Indian Ocean",
                "note": note,
                "start": s.start_ts.isoformat(),
                "end": s.end_ts.isoformat(),
                "peak_wind_kt": float(s.peak_wind_kt),
                "peak_category": s.peak_category,
                "n_frames": len(t),
            })
        return out

    def track(self, sid: str, until: datetime | None = None) -> pd.DataFrame:
        """
        Track points for a storm, optionally truncated at `until`.

        ★ CAUSALITY ENFORCEMENT POINT ★
        The `until` filter is applied here, at the data-access layer, not by the
        caller. If it were a post-filter in application code a later refactor
        could drop it and nothing would fail visibly - the demo would just
        silently start forecasting with hindsight.
        """
        d = self.frame[self.frame.sid == sid].sort_values("iso_time")
        if until is not None:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            d = d[d.iso_time <= until]
        return d

    def row_at(self, sid: str, ts: datetime) -> pd.Series | None:
        d = self.track(sid, until=ts)
        return d.iloc[-1] if len(d) else None

    # -- scenes ------------------------------------------------------------
    def scene(self, sid: str, ts: datetime) -> dict:
        """Render (and cache) the scene and model inputs for one storm fix."""
        key = (sid, ts.isoformat())
        if key in self._scene_cache:
            return self._scene_cache[key]

        row = self.row_at(sid, ts)
        if row is None:
            raise KeyError(f"no fix for {sid} at {ts}")

        # Seeded from the storm ID and timestamp so a frame renders identically
        # every time it is requested. During a scrub-heavy demo this is the
        # difference between a stable image and one that shimmers.
        #
        # A content hash, not Python's hash(): str hashing is randomised per
        # process unless PYTHONHASHSEED is pinned, so builtin hash() would
        # re-render every frame differently after each API restart — including
        # between the rehearsal and the demo.
        seed = int(hashlib.sha256(
            f"{sid}|{row.iso_time.isoformat()}".encode()).hexdigest()[:8], 16)
        s = render_ir_scene(float(row.wind_kt_3min), float(row.lat), float(row.lon),
                            shear_kt=float(row.shear_kt),
                            shear_dir_deg=(seed % 360), seed=seed)

        # Scatterometer coincidence: a pass roughly twice a day, so about one
        # synoptic fix in three has one. Deterministic in the seed so the
        # provenance panel shows the same staleness on every replay.
        has_wind = (seed % 3) == 0
        if has_wind:
            w = render_wind_field(float(row.wind_kt_3min), float(row.lat),
                                  float(s["rmw_km"]), seed=seed)
            hours_since = round((seed % 180) / 60.0, 1)
        else:
            w = {"u10": None, "v10": None, "mask": None, "coverage": 0.0}
            hours_since = None

        env = {
            "lat": row.lat, "lon": row.lon, "sst_c": row.sst_c,
            "shear_kt": row.shear_kt, "steer_u_kt": 0.0, "steer_v_kt": 0.0,
            "trans_speed_kt": row.trans_speed_kt,
            "bearing_sin": row.bearing_sin, "bearing_cos": row.bearing_cos,
            "dwind_6h_kt": row.dwind_6h_kt, "dwind_24h_kt": row.dwind_24h_kt,
            "doy_sin": row.doy_sin, "doy_cos": row.doy_cos,
            "hours_since_wind": hours_since if hours_since is not None else 12.0,
            "wind_coverage": w["coverage"],
        }
        tensors = preprocess_sample(s["tir1_k"], s["wv_k"], w["u10"], w["v10"],
                                    w["mask"], env)
        out = {
            "row": row, "scene": s, "wind": w, "tensors": tensors,
            "provenance": {
                "ir": {"source": "SYNTHETIC (INSAT-3DR contract)",
                       "observed_at": row.iso_time.isoformat(), "age_min": 0,
                       "is_synthetic": True},
                "wind": ({"source": "SYNTHETIC (ASCAT-B contract)",
                          "observed_at": (row.iso_time
                                          - timedelta(hours=hours_since)).isoformat(),
                          "age_min": int(hours_since * 60),
                          "coverage": round(w["coverage"], 3),
                          "is_synthetic": True} if has_wind else None),
                "env": {"sst_source": "NIO climatology proxy",
                        "shear_source": "NIO climatology proxy",
                        "is_proxy": True},
            },
        }
        # Bounded cache: a long replay at high speed would otherwise grow
        # without limit across many sessions.
        if len(self._scene_cache) > 400:
            self._scene_cache.clear()
        self._scene_cache[key] = out
        return out


@lru_cache(maxsize=1)
def get_store() -> CaseStore:
    return CaseStore()
