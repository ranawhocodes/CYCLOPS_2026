"""
Persistence-relative targets.

Predicting absolute displacement from scratch makes the model re-learn "a storm
keeps moving in roughly the same direction", which persistence already gets
right. It then has to beat persistence from a standing start, and on ~5,000
training rows it barely does.

Instead the model predicts the *residual* from persistence: how much the storm
deviates from simple velocity extrapolation. That is the part that actually
requires meteorology - recurvature, beta drift, steering-flow changes,
land interaction - and it is what the environmental features can explain.

Final forecast = persistence extrapolation + learned correction. The model
therefore starts at persistence skill and the learned part can only add to it.
This is standard practice in operational statistical guidance (the same idea
underlies CLIPER/SHIFOR-anomaly schemes) and it is a good Q&A answer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FORECAST_LEADS_H
from ..eval.baselines import persistence_forecast


def add_persistence_frame(df: pd.DataFrame, leads_h=FORECAST_LEADS_H) -> pd.DataFrame:
    """
    Attach, for every lead time:
      - `plat_{h}h`, `plon_{h}h`, `pwind_{h}h` : the persistence forecast
      - `rlat_{h}h`, `rlon_{h}h`, `rwind_{h}h` : truth minus persistence (target)

    Persistence uses only causal inputs, so adding it as a feature introduces no
    leakage. The residual targets use the future, exactly as any supervised
    target does, and never reach inference.
    """
    out = df.copy()
    for lead in leads_h:
        p = persistence_forecast(out, lead)
        out[f"plat_{lead}h"] = p["lat"].to_numpy()
        out[f"plon_{lead}h"] = p["lon"].to_numpy()
        out[f"pwind_{lead}h"] = p["wind_kt"].to_numpy()

        if f"tlat_{lead}h" in out.columns:
            out[f"rlat_{lead}h"] = out[f"tlat_{lead}h"] - out[f"plat_{lead}h"]
            out[f"rlon_{lead}h"] = out[f"tlon_{lead}h"] - out[f"plon_{lead}h"]
            out[f"rwind_{lead}h"] = out[f"twind_{lead}h"] - out[f"pwind_{lead}h"]
    return out


def persistence_offset_features(df: pd.DataFrame, lead_h: int) -> pd.DataFrame:
    """
    Per-lead features describing where persistence puts the storm.

    Latitude of the persistence endpoint matters because recurvature probability
    is strongly latitude-dependent; distance travelled matters because fast
    movers deviate less. Both are known at forecast time.
    """
    return pd.DataFrame({
        "pers_lat": df[f"plat_{lead_h}h"].to_numpy(),
        "pers_lon": df[f"plon_{lead_h}h"].to_numpy(),
        "pers_dlat": df[f"plat_{lead_h}h"].to_numpy() - df.lat.to_numpy(),
        "pers_dlon": df[f"plon_{lead_h}h"].to_numpy() - df.lon.to_numpy(),
    }, index=df.index)
