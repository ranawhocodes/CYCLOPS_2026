"""
Nowcast v1: gradient-boosted trees with quantile objectives.

One model per (target, lead, quantile) = 3 x 4 x 3 = 36 small models. Sounds
like a lot; each trains in seconds and the whole set is a few MB.

Quantile regression gives the uncertainty band directly from the model, with no
ensembling and no assumption that the error is Gaussian. That is both cheaper
and more honest than fitting a normal distribution to a skewed error.

Backend: scikit-learn's HistGradientBoostingRegressor by default.

LightGBM is what doc 03 specifies and it trains marginally faster, but on macOS
its native library links a second OpenMP runtime alongside the one PyTorch
already loaded. Deserialising a LightGBM booster in a process that has imported
torch segfaults; importing them the other way round DEADLOCKS. Either failure
takes down the API at startup, and a hang in front of judges is worse than a
crash because there is nothing to read.

scikit-learn's HistGradientBoostingRegressor has the same native quantile
objective, trains this problem in seconds, and links no separate OpenMP runtime.
Removing a fragile native dependency from the machine that has to boot at a
venue is worth more than the training-speed difference.

Set CYCLOPS_GBM=lightgbm to opt back in for offline experiments — never for the
serving path.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import FORECAST_LEADS_H, SEED
from ..data.features import NOWCAST_FEATURES

# Targets are residuals from the persistence extrapolation, not raw
# displacements. See data/persistence_frame.py for why.
TARGETS = ("rlat", "rlon", "rwind")
QUANTILES = (0.1, 0.5, 0.9)

# Per-lead features describing the persistence endpoint. Known at forecast time,
# so including them is causal.
PERS_FEATURES = ["pers_lat", "pers_lon", "pers_dlat", "pers_dlon"]

import os

_BACKEND = "sklearn-hgb"
lgb = None
if os.environ.get("CYCLOPS_GBM", "").lower() == "lightgbm":
    try:
        import lightgbm as lgb                       # noqa: F401
        _BACKEND = "lightgbm"
    except Exception:                                # pragma: no cover
        lgb = None


def _make_model(alpha: float):
    if _BACKEND == "lightgbm":
        return lgb.LGBMRegressor(
            objective="quantile", alpha=alpha,
            n_estimators=400, learning_rate=0.05, num_leaves=31,
            min_child_samples=25, subsample=0.85, subsample_freq=1,
            colsample_bytree=0.85, reg_lambda=1.0,
            random_state=SEED, verbose=-1, n_jobs=2,
        )
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(
        loss="quantile", quantile=alpha, max_iter=400, learning_rate=0.05,
        max_leaf_nodes=31, min_samples_leaf=25, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=SEED,
    )


class NowcastGBM:
    """Quantile-regression nowcast over the causal kinematic/environmental features."""

    def __init__(self, leads_h=FORECAST_LEADS_H):
        self.leads_h = tuple(leads_h)
        self.models: dict[tuple[str, int, float], object] = {}
        self.features = list(NOWCAST_FEATURES) + list(PERS_FEATURES)
        self.backend = _BACKEND
        self.train_meta: dict = {}

    def _design(self, df: pd.DataFrame, lead_h: int) -> pd.DataFrame:
        """Feature matrix for one lead time: shared features + persistence frame."""
        from ..data.persistence_frame import persistence_offset_features
        base = df[NOWCAST_FEATURES]
        pers = persistence_offset_features(df, lead_h)
        return pd.concat([base, pers], axis=1)[self.features]

    def fit(self, train: pd.DataFrame, val: pd.DataFrame | None = None) -> "NowcastGBM":
        n_fit = 0
        for tgt in TARGETS:
            for lead in self.leads_h:
                col = f"{tgt}_{lead}h"
                X_all = self._design(train, lead)
                # Require the target and the persistence frame; leave gaps in the
                # history features as NaN. LightGBM learns a default split
                # direction for missing values, which is strictly better than
                # discarding a fifth of the storms - young systems have no 24 h
                # history by definition, and they are the ones forecasters most
                # need help with.
                keep = (train[col].notna()
                        & X_all[PERS_FEATURES].notna().all(axis=1))
                sub = train[keep]
                if len(sub) < 50:
                    continue
                X, y = X_all[keep], train.loc[keep, col]
                for q in QUANTILES:
                    m = _make_model(q)
                    if self.backend == "lightgbm" and val is not None:
                        Xv = self._design(val, lead)
                        vk = (val[col].notna()
                              & Xv[PERS_FEATURES].notna().all(axis=1))
                        v_X, v_y = Xv[vk], val.loc[vk, col]
                        v = v_X
                        fit_kw = {}
                        if len(v) >= 30:
                            # LightGBM 4.7 renamed eval_set -> eval_X/eval_y.
                            # Support both so the pinned range in doc 03 works.
                            import inspect
                            sig = inspect.signature(m.fit).parameters
                            es = [lgb.early_stopping(40, verbose=False),
                                  lgb.log_evaluation(0)]
                            if "eval_X" in sig:
                                fit_kw = {"eval_X": v_X, "eval_y": v_y,
                                          "callbacks": es}
                            else:
                                fit_kw = {"eval_set": [(v_X, v_y)],
                                          "callbacks": es}
                        m.fit(X, y, **fit_kw)
                    else:
                        m.fit(X, y)
                    self.models[(tgt, lead, q)] = m
                    n_fit += 1
        self.train_meta = {
            "backend": self.backend,
            "n_models": n_fit,
            "n_train_rows": int(len(train)),
            "n_train_storms": int(train.sid.nunique()),
            "train_seasons": sorted(int(s) for s in train.season.unique()),
            "features": self.features,
        }
        return self

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Forecast every lead time and quantile.

        Returns absolute positions and winds so the caller never has to remember
        whether a value is a delta. Every forecast carries q10/q50/q90 - there is
        deliberately no code path that produces a bare point forecast, because if
        one existed somebody would eventually render it as a line.
        """
        out: dict[int, dict] = {}
        for lead in self.leads_h:
            X = self._design(df, lead)
            entry: dict = {}
            for tgt in TARGETS:
                for q in QUANTILES:
                    m = self.models.get((tgt, lead, q))
                    if m is None:
                        entry[f"{tgt}_q{int(q * 100)}"] = np.full(len(df), np.nan)
                        continue
                    r = np.full(len(df), np.nan)
                    ok = X[PERS_FEATURES].notna().all(axis=1).to_numpy()
                    if ok.any():
                        r[ok] = m.predict(X[ok])
                    entry[f"{tgt}_q{int(q * 100)}"] = r

            # Forecast = persistence extrapolation + learned correction.
            plat = df[f"plat_{lead}h"].to_numpy()
            plon = df[f"plon_{lead}h"].to_numpy()
            pwind = df[f"pwind_{lead}h"].to_numpy()
            out[lead] = {
                "lat": plat + entry["rlat_q50"],
                "lon": plon + entry["rlon_q50"],
                "lat_q10": plat + entry["rlat_q10"],
                "lon_q10": plon + entry["rlon_q10"],
                "lat_q90": plat + entry["rlat_q90"],
                "lon_q90": plon + entry["rlon_q90"],
                "wind_kt": pwind + entry["rwind_q50"],
                "wind_kt_q10": pwind + entry["rwind_q10"],
                "wind_kt_q90": pwind + entry["rwind_q90"],
            }
        return out

    def feature_importance(self) -> pd.DataFrame:
        """
        Mean gain importance across the median-quantile track models.

        Worth plotting: if current intensity, recent intensity change, SST and
        shear dominate, that is physically correct and is real evidence the model
        learned meteorology rather than noise. It is a free slide.
        """
        rows = []
        for (tgt, lead, q), m in self.models.items():
            if q != 0.5:
                continue
            imp = getattr(m, "feature_importances_", None)
            if imp is None:
                continue
            for f, v in zip(self.features, imp):
                rows.append({"target": tgt, "lead_h": lead, "feature": f,
                             "importance": float(v)})
        if not rows:
            return pd.DataFrame(columns=["feature", "importance"])
        d = pd.DataFrame(rows)
        agg = d.groupby("feature")["importance"].mean().sort_values(ascending=False)
        return (agg / agg.sum()).reset_index().rename(
            columns={"importance": "relative_importance"})

    def save(self, path: Path) -> None:
        import joblib
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"models": self.models, "leads_h": self.leads_h,
                     "features": self.features, "backend": self.backend,
                     "train_meta": self.train_meta}, path)
        path.with_suffix(".meta.json").write_text(json.dumps(self.train_meta, indent=2))

    @classmethod
    def load(cls, path: Path) -> "NowcastGBM":
        import joblib
        blob = joblib.load(path)
        obj = cls(leads_h=blob["leads_h"])
        obj.models = blob["models"]
        obj.features = blob["features"]
        obj.backend = blob["backend"]
        obj.train_meta = blob.get("train_meta", {})
        return obj
