"""
Print the results table from artifacts/.

Every number in the deck must be traceable to a script that produces it. This is
that script: it reads only what training wrote, so a figure on a slide can
always be reproduced with `make eval`.
"""
from __future__ import annotations

import json

from ..config import ARTIFACTS


def _load(name: str) -> dict | None:
    p = ARTIFACTS / name
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    nc = _load("metrics_nowcast.json")
    it = _load("metrics_intensity.json")

    if not nc and not it:
        print("No artifacts found. Run `make train` first.")
        return

    print("\n" + "=" * 78)
    print("CYCLOPS — RESULTS")
    print("=" * 78)

    if nc:
        print(f"\nData      : {nc['wind_convention']}")
        print(f"Split     : {nc['split_policy']}")
        sp = {r["split"]: r for r in nc["splits"]}
        for k in ("train", "val", "test"):
            if k in sp:
                r = sp[k]
                print(f"  {k:<6} {r['storms']:>4} storms  {r['fixes']:>5} fixes  "
                      f"seasons {r['seasons']}  VSCS+ {r['VSCS+']}")

        print("\n" + "-" * 78)
        print("FORECAST SKILL vs BASELINES — held-out storms")
        print("-" * 78)
        print(f"{'Lead':>5} {'n':>5} | {'Track error, mean km':^36} | "
              f"{'Intensity MAE, kt':^24}")
        print(f"{'':>5} {'':>5} | {'persist':>10} {'clim':>10} {'CYCLOPS':>10} | "
              f"{'persist':>10} {'CYCLOPS':>10}")
        print("-" * 78)
        for lead in ("6", "12", "18", "24"):
            t, i = nc["track"].get(lead), nc["intensity"].get(lead)
            if not t:
                continue
            print(f"{lead:>4}h {t['n']:>5} | {t['persistence']['mean_km']:>10.1f} "
                  f"{t['climatology']['mean_km']:>10.1f} "
                  f"{t['model']['mean_km']:>10.1f} | "
                  f"{i['persistence']['mae_kt']:>10.2f} "
                  f"{i['model']['mae_kt']:>10.2f}")
        print("-" * 78)
        print(f"{'skill':>10} | ", end="")
        for lead in ("6", "12", "18", "24"):
            t = nc["track"].get(lead)
            if t:
                print(f"{lead}h {t['skill_vs_persistence']:>6.1%}  ", end="")
        print("  (track, vs persistence)")
        print(f"{'':>10} | ", end="")
        for lead in ("6", "12", "18", "24"):
            i = nc["intensity"].get(lead)
            if i:
                print(f"{lead}h {i['skill_vs_persistence']:>6.1%}  ", end="")
        print("  (intensity, vs persistence)")

        print("\n" + "-" * 78)
        print("UNCERTAINTY CONE — 67th-percentile radii, calibrated on validation")
        print("-" * 78)
        for lead in ("6", "12", "18", "24"):
            r = nc["cone"]["radii_km"].get(lead) or nc["cone"]["radii_km"].get(int(lead))
            c = (nc["cone"]["test_coverage"].get(lead)
                 or nc["cone"]["test_coverage"].get(int(lead)))
            if r is not None:
                print(f"  {lead:>2}h   r = {r:6.1f} km    "
                      f"measured coverage on test {c:.1%}   (target 67%)")

        if nc.get("feature_importance"):
            print("\n  Top nowcast features by gain:")
            for r in nc["feature_importance"][:6]:
                print(f"    {r['feature']:<20} {r['relative_importance']:>6.1%}")

    if it:
        print("\n" + "-" * 78)
        print("FUSION ABLATION")
        print(f"!! {it['DATA_STATUS']}")
        print("-" * 78)
        base = it["ablation"]["ir_only"]["rmse_kt"]
        print(f"{'variant':<10} {'RMSE kt':>9} {'MAE kt':>9} {'bias':>8} "
              f"{'cat acc':>9} {'within-1':>10} {'vs IR-only':>11}")
        for k, v in it["ablation"].items():
            print(f"{k:<10} {v['rmse_kt']:>9.2f} {v['mae_kt']:>9.2f} "
                  f"{v['bias_kt']:>8.2f} {v['cat_acc']:>8.1%} "
                  f"{v['within_one']:>9.1%} {(base - v['rmse_kt']) / base:>10.1%}")
        cf = it.get("centre_fix")
        if cf:
            print(f"\nCentre-fix error: median {cf['median_km']:.1f} km, "
                  f"p90 {cf['p90_km']:.1f} km  (n={cf['n']})")

    print("\n" + "=" * 78)
    print("Regenerate with `make train`. Every figure above is written by")
    print("src/cyclops/train/*.py into artifacts/*.json — none is typed by hand.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
