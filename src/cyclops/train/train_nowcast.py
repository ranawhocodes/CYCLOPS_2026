"""
Train the nowcast and produce the baseline comparison table.

`make nowcast` runs this. It writes models/nowcast_gbm.joblib,
models/cone_radii.json and artifacts/metrics.json - and metrics.json is the
single file every number in the deck must be traceable to.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import ARTIFACTS, FORECAST_LEADS_H, MODELS
from ..data.features import add_forecast_targets, build_track_features, filter_nio
from ..data.ibtracs import load
from ..data.persistence_frame import add_persistence_frame
from ..data.splits import assert_disjoint, describe, split_by_season
from ..eval import cone as cone_mod
from ..eval.baselines import (climatology_forecast, fit_climatology,
                              persistence_forecast, track_error_km)
from ..eval.metrics import intensity_report, skill, track_report
from ..models.nowcast_gbm import NowcastGBM


def build_frames():
    fixes = filter_nio(load())
    feats = add_persistence_frame(add_forecast_targets(build_track_features(fixes)))
    splits = split_by_season(feats)
    assert_disjoint(splits)
    return feats, splits


def evaluate(model: NowcastGBM, test: pd.DataFrame, clim: dict) -> dict:
    """
    Score model, persistence and climatology on identical rows.

    The same-rows constraint matters. If the model is scored on rows where a
    baseline could not produce a forecast, the comparison flatters the model for
    free. Every lead time is restricted to rows where all three produce a value.
    """
    preds = model.predict(test)
    result = {"track": {}, "intensity": {}, "cone_errors": {}}

    for lead in FORECAST_LEADS_H:
        tlat = test[f"tlat_{lead}h"].to_numpy()
        tlon = test[f"tlon_{lead}h"].to_numpy()
        twind = test[f"twind_{lead}h"].to_numpy()

        p_model = pd.DataFrame({"lat": preds[lead]["lat"], "lon": preds[lead]["lon"]},
                               index=test.index)
        p_pers = persistence_forecast(test, lead)
        p_clim = climatology_forecast(test, clim, lead)

        e_model = track_error_km(p_model, tlat, tlon)
        e_pers = track_error_km(p_pers, tlat, tlon)
        e_clim = track_error_km(p_clim, tlat, tlon)

        common = np.isfinite(e_model) & np.isfinite(e_pers) & np.isfinite(e_clim)
        result["track"][lead] = {
            "n": int(common.sum()),
            "model": track_report(e_model[common]),
            "persistence": track_report(e_pers[common]),
            "climatology": track_report(e_clim[common]),
        }
        result["track"][lead]["skill_vs_persistence"] = skill(
            result["track"][lead]["model"]["mean_km"],
            result["track"][lead]["persistence"]["mean_km"])
        result["track"][lead]["skill_vs_climatology"] = skill(
            result["track"][lead]["model"]["mean_km"],
            result["track"][lead]["climatology"]["mean_km"])
        result["cone_errors"][lead] = e_model[common]

        i_model = preds[lead]["wind_kt"]
        i_pers = p_pers["wind_kt"].to_numpy()
        i_clim = p_clim["wind_kt"].to_numpy()
        ok = (np.isfinite(i_model) & np.isfinite(i_pers)
              & np.isfinite(i_clim) & np.isfinite(twind))
        result["intensity"][lead] = {
            "n": int(ok.sum()),
            "model": intensity_report(i_model[ok], twind[ok]),
            "persistence": intensity_report(i_pers[ok], twind[ok]),
            "climatology": intensity_report(i_clim[ok], twind[ok]),
        }
        result["intensity"][lead]["skill_vs_persistence"] = skill(
            result["intensity"][lead]["model"]["mae_kt"],
            result["intensity"][lead]["persistence"]["mae_kt"])
    return result


def main() -> dict:
    feats, splits = build_frames()
    train, val, test = splits["train"], splits["val"], splits["test"]

    print("\nSplit — by season, storm IDs disjoint by construction")
    print(describe(splits).to_string(index=False))

    print(f"\nTraining nowcast ({len(train):,} train rows, "
          f"{train.sid.nunique()} storms)…")
    model = NowcastGBM().fit(train, val)
    print(f"  backend={model.backend}  models fitted={model.train_meta['n_models']}")

    # Cone radii are calibrated on VALIDATION errors and their coverage is then
    # verified on TEST. Calibrating and verifying on the same set would make the
    # coverage check meaningless.
    val_preds = model.predict(val)
    val_err = {}
    for lead in FORECAST_LEADS_H:
        p = pd.DataFrame({"lat": val_preds[lead]["lat"], "lon": val_preds[lead]["lon"]},
                         index=val.index)
        val_err[lead] = track_error_km(p, val[f"tlat_{lead}h"], val[f"tlon_{lead}h"])
    radii = cone_mod.calibrate(val_err)

    clim = fit_climatology(train)
    res = evaluate(model, test, clim)
    coverage = cone_mod.verify_coverage(radii, res.pop("cone_errors"))

    # ---- report ----------------------------------------------------------
    print("\n" + "=" * 74)
    print("FORECAST SKILL — held-out storms, split by season; storm IDs disjoint")
    print(f"test: {test.sid.nunique()} storms, "
          f"seasons {sorted(set(int(s) for s in test.season))}")
    print("=" * 74)
    print(f"{'Lead':>5} {'n':>5} | {'Track error, mean km':^38} | "
          f"{'Intensity MAE kt':^20}")
    print(f"{'':>5} {'':>5} | {'persist':>9} {'clim':>9} {'CYCLOPS':>9} "
          f"{'skill':>8} | {'persist':>9} {'CYCLOPS':>9}")
    print("-" * 74)
    for lead in FORECAST_LEADS_H:
        t, i = res["track"][lead], res["intensity"][lead]
        print(f"{lead:>4}h {t['n']:>5} | {t['persistence']['mean_km']:>9.1f} "
              f"{t['climatology']['mean_km']:>9.1f} {t['model']['mean_km']:>9.1f} "
              f"{t['skill_vs_persistence']:>7.1%} | "
              f"{i['persistence']['mae_kt']:>9.2f} "
              f"{i['model']['mae_kt']:>9.2f}")
    print("=" * 74)
    print("\nUncertainty cone — 67th-percentile radius from validation errors")
    for lead in FORECAST_LEADS_H:
        print(f"  {lead:>2}h  r = {radii[lead]:6.1f} km   "
              f"measured test coverage {coverage[lead]:.1%}  (target 67%)")

    imp = model.feature_importance()
    if not imp.empty:
        print("\nTop nowcast features by gain:")
        for _, r in imp.head(8).iterrows():
            print(f"  {r.feature:<20} {r.relative_importance:>6.1%}")

    # ---- persist ---------------------------------------------------------
    model.save(MODELS / "nowcast_gbm.joblib")
    (MODELS / "cone_radii.json").write_text(json.dumps(
        {"radii_km": {str(k): round(v, 2) for k, v in radii.items()},
         "percentile": 67,
         "calibrated_on": "validation seasons, storm-disjoint from test",
         "measured_test_coverage": {str(k): round(v, 4) for k, v in coverage.items()}},
        indent=2))
    (MODELS / "climatology.json").write_text(json.dumps(
        {str(k): list(v) for k, v in clim.items()}, default=str))

    payload = {
        "generated_by": "src/cyclops/train/train_nowcast.py",
        "split_policy": "by_season; storm IDs disjoint across splits (asserted)",
        "wind_convention": "3-minute sustained, IMD (IBTrACS NEWDELHI_WIND)",
        "splits": describe(splits).to_dict("records"),
        "train_meta": model.train_meta,
        "cone": {"radii_km": radii, "percentile": 67, "test_coverage": coverage},
        "track": {str(k): v for k, v in res["track"].items()},
        "intensity": {str(k): v for k, v in res["intensity"].items()},
        "feature_importance": imp.head(12).to_dict("records"),
    }
    (ARTIFACTS / "metrics_nowcast.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nwrote {MODELS/'nowcast_gbm.joblib'}")
    print(f"wrote {ARTIFACTS/'metrics_nowcast.json'}")
    return payload


if __name__ == "__main__":
    main()
