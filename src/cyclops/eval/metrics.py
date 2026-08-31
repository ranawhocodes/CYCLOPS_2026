"""Metric computation. One place, so the deck and the API cannot disagree."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import confusion_matrix

from ..domain.imd import CATEGORIES, category_to_index, to_imd_category


def intensity_report(pred_kt: np.ndarray, true_kt: np.ndarray) -> dict:
    """
    Full intensity report. Reports bias and per-category error, not just RMSE.

    `bias_kt` matters: a model that systematically under-predicts strong storms
    by 8 kt - common, because the loss is dominated by the many weak samples -
    has a real defect that a single RMSE hides. Reporting it shows you looked.
    """
    pred_kt = np.asarray(pred_kt, float)
    true_kt = np.asarray(true_kt, float)
    ok = np.isfinite(pred_kt) & np.isfinite(true_kt)
    pred_kt, true_kt = pred_kt[ok], true_kt[ok]
    if len(true_kt) == 0:
        return {"n": 0}

    err = pred_kt - true_kt
    pc = np.array([category_to_index(to_imd_category(k)) for k in pred_kt])
    tc = np.array([category_to_index(to_imd_category(k)) for k in true_kt])

    return {
        "n": int(len(true_kt)),
        "rmse_kt": float(np.sqrt((err ** 2).mean())),
        "mae_kt": float(np.abs(err).mean()),
        "bias_kt": float(err.mean()),
        "cat_acc": float((pc == tc).mean()),
        "within_one": float((np.abs(pc - tc) <= 1).mean()),
        "confusion": confusion_matrix(
            tc, pc, labels=list(range(len(CATEGORIES)))).tolist(),
        "categories": CATEGORIES,
        "per_cat_mae": {
            c: round(float(np.abs(err[tc == i]).mean()), 2)
            for i, c in enumerate(CATEGORIES) if (tc == i).any()
        },
        "per_cat_n": {
            c: int((tc == i).sum())
            for i, c in enumerate(CATEGORIES) if (tc == i).any()
        },
    }


def track_report(err_km: np.ndarray) -> dict:
    """Position-error summary. Median as well as mean: the distribution is skewed."""
    e = np.asarray(err_km, float)
    e = e[np.isfinite(e)]
    if len(e) == 0:
        return {"n": 0}
    return {
        "n": int(len(e)),
        "mean_km": float(e.mean()),
        "median_km": float(np.median(e)),
        "p90_km": float(np.percentile(e, 90)),
    }


def skill(model_err: float, baseline_err: float) -> float:
    """Fractional error reduction versus a baseline. Negative means worse."""
    if not np.isfinite(baseline_err) or baseline_err == 0:
        return float("nan")
    return float((baseline_err - model_err) / baseline_err)
