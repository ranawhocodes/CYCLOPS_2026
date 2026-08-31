"""
Persistence and climatology baselines.

These are built before the model, not after. A bare accuracy number is not a
result; "38% better than persistence at 24 h on storms the model has never seen"
is. Persistence in particular is a genuinely strong short-horizon baseline -
beating it by 30-40% at 24 h is a real result, and beating it by 90% means there
is a bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Geod

GEOD = Geod(ellps="WGS84")


def persistence_forecast(df: pd.DataFrame, lead_h: int) -> pd.DataFrame:
    """
    Extrapolate the storm's current velocity vector forward, and hold intensity
    constant. Uses only `disp_6h_km` and `bearing_deg`, both of which are causal.
    """
    n_steps = lead_h / 6.0
    speed_kmh = df["disp_6h_km"] / 6.0
    dist_m = (speed_kmh * lead_h * 1000.0).to_numpy()
    az = df["bearing_deg"].to_numpy()

    ok = np.isfinite(dist_m) & np.isfinite(az)
    lat = np.full(len(df), np.nan)
    lon = np.full(len(df), np.nan)
    if ok.any():
        lo, la, _ = GEOD.fwd(df.lon.to_numpy()[ok], df.lat.to_numpy()[ok],
                             az[ok], dist_m[ok])
        lat[ok], lon[ok] = la, lo

    return pd.DataFrame(
        {"lat": lat, "lon": lon, "wind_kt": df["wind_kt_3min"].to_numpy()},
        index=df.index,
    )


def fit_climatology(train: pd.DataFrame, leads_h=(6, 12, 18, 24)) -> dict:
    """
    CLIPER-style climatology-persistence table.

    Keyed by (5-degree latitude band, month, intensity band). Captures the real
    basin behaviour a bare persistence model misses - that storms in the Bay of
    Bengal in May tend to recurve north-northeast, for instance. Stores the mean
    historical displacement and intensity change for each cell.
    """
    t = train.copy()
    t["_latb"] = (t.lat // 5 * 5).astype(int)
    t["_intb"] = pd.cut(t.wind_kt_3min, [0, 33, 63, 89, 999], labels=False)

    table: dict = {}
    for lead in leads_h:
        cols = [f"dlat_{lead}h", f"dlon_{lead}h", f"dwind_{lead}h"]
        grp = t.dropna(subset=cols).groupby(["_latb", "month", "_intb"], observed=True)
        agg = grp[cols].mean()
        counts = grp.size()
        # Cells with too few historical analogues are noise, not climatology.
        agg = agg[counts >= 5]
        for key, row in agg.iterrows():
            table[(key, lead)] = (row[cols[0]], row[cols[1]], row[cols[2]])
        # Basin-wide fallback for cells with no analogue.
        fb = t.dropna(subset=cols)[cols].mean()
        table[("_global", lead)] = (fb[cols[0]], fb[cols[1]], fb[cols[2]])
    return table


def climatology_forecast(df: pd.DataFrame, table: dict, lead_h: int) -> pd.DataFrame:
    """Apply the fitted climatology table to produce a forecast."""
    latb = (df.lat // 5 * 5).astype(int)
    intb = pd.cut(df.wind_kt_3min, [0, 33, 63, 89, 999], labels=False)
    glob = table[("_global", lead_h)]

    d = np.array([
        table.get(((la, mo, ib), lead_h), glob)
        for la, mo, ib in zip(latb, df.month, intb)
    ])
    return pd.DataFrame(
        {"lat": df.lat.to_numpy() + d[:, 0],
         "lon": df.lon.to_numpy() + d[:, 1],
         "wind_kt": df.wind_kt_3min.to_numpy() + d[:, 2]},
        index=df.index,
    )


def track_error_km(pred: pd.DataFrame, truth_lat, truth_lon) -> np.ndarray:
    """Great-circle position error in km. Geodesic, never Euclidean."""
    pl, pn = pred.lat.to_numpy(), pred.lon.to_numpy()
    tl, tn = np.asarray(truth_lat, float), np.asarray(truth_lon, float)
    ok = np.isfinite(pl) & np.isfinite(pn) & np.isfinite(tl) & np.isfinite(tn)
    out = np.full(len(pred), np.nan)
    if ok.any():
        _, _, d = GEOD.inv(pn[ok], pl[ok], tn[ok], tl[ok])
        out[ok] = d / 1000.0
    return out
