"""
Storm lifecycle stages.

The problem statement asks for identification, classification and prediction.
Those are not three separate demos — they are three things a forecaster does at
different points in one storm's life, and they become legible only when the
storm is followed from the beginning.

This maps a track onto named stages so the console can say where in the life
cycle the replay currently is, and what the system is being asked to do there.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .imd import RAPID_INTENSIFICATION_KT_24H, category_to_index, to_imd_category


@dataclass
class Stage:
    key: str
    label: str
    task: str          # what the system is doing at this stage
    detail: str


STAGES = {
    "genesis": Stage(
        "genesis", "Genesis",
        "IDENTIFICATION",
        "A disturbance organises. The question is whether a closed circulation "
        "exists at all, and where its centre is."),
    "intensifying": Stage(
        "intensifying", "Intensifying",
        "CLASSIFICATION",
        "Structure consolidates. Cloud pattern now carries intensity "
        "information, so Dvorak analysis becomes meaningful."),
    "rapid": Stage(
        "rapid", "Rapid intensification",
        "CLASSIFICATION + ALERT",
        "At least 30 kt of strengthening in 24 hours — the standard operational "
        "definition, and the hardest thing to forecast."),
    "peak": Stage(
        "peak", "Peak intensity",
        "CLASSIFICATION",
        "A cleared eye. This is where satellite intensity estimation is most "
        "reliable and where the eye-based centre fix is sharpest."),
    "landfall": Stage(
        "landfall", "Approaching landfall",
        "PREDICTION",
        "Track and timing dominate. The uncertainty cone is the output that "
        "matters to a district officer."),
    "decay": Stage(
        "decay", "Decay",
        "IDENTIFICATION",
        "Over land the circulation fills and the eye disappears. Structure-based "
        "estimation degrades, and the system should say so."),
}


def annotate(track: pd.DataFrame) -> pd.DataFrame:
    """
    Label each fix with its lifecycle stage.

    Stages are derived from the track itself — intensity, its 24 h change, and
    distance to land — rather than hand-placed dates, so the same logic applies
    to any storm.
    """
    d = track.sort_values("iso_time").reset_index(drop=True).copy()
    kt = d.wind_kt_3min.to_numpy(float)
    n = len(d)

    # 24 h intensity change, at the 6-hourly synoptic cadence.
    step = 4
    d24 = np.full(n, np.nan)
    d24[step:] = kt[step:] - kt[:-step]

    peak_i = int(np.argmax(kt))
    land = d.dist2land_km.to_numpy(float) if "dist2land_km" in d else np.full(n, np.nan)

    stages = []
    for i in range(n):
        k = kt[i]
        if i > peak_i and (np.isnan(land[i]) or land[i] < 60) and k < kt[peak_i] * 0.8:
            stages.append("decay")
        elif i > peak_i and not np.isnan(land[i]) and land[i] < 250:
            stages.append("landfall")
        elif abs(i - peak_i) <= 1:
            stages.append("peak")
        elif not np.isnan(d24[i]) and d24[i] >= RAPID_INTENSIFICATION_KT_24H:
            stages.append("rapid")
        elif k >= 34:
            stages.append("intensifying")
        else:
            stages.append("genesis")

    d["stage"] = stages
    d["d24_kt"] = d24
    d["cat_index"] = [category_to_index(to_imd_category(v)) for v in kt]
    return d


def summarise(track: pd.DataFrame) -> list[dict]:
    """Contiguous stage spans, for the console's lifecycle strip."""
    d = annotate(track)
    out, cur = [], None
    for r in d.itertuples():
        if cur is None or r.stage != cur["stage"]:
            if cur:
                out.append(cur)
            st = STAGES[r.stage]
            cur = {"stage": r.stage, "label": st.label, "task": st.task,
                   "detail": st.detail, "start": r.iso_time.isoformat(),
                   "end": r.iso_time.isoformat(),
                   "peak_kt": float(r.wind_kt_3min), "n": 1}
        else:
            cur["end"] = r.iso_time.isoformat()
            cur["peak_kt"] = max(cur["peak_kt"], float(r.wind_kt_3min))
            cur["n"] += 1
    if cur:
        out.append(cur)
    return out
