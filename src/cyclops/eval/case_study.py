"""
Hero-case study: replay one real cyclone frame by frame, forecast at every step,
and compare against what actually happened.

More persuasive than any aggregate metric, and it is also the honest way to show
failure modes — the write-up is required to name where the model was wrong, not
only where it was right.

Causality: at each step the model is given only the track up to that step. The
truth is used solely to score the forecast afterwards.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..config import ARTIFACTS, FORECAST_LEADS_H, MODELS
from ..data.features import add_forecast_targets, build_track_features, filter_nio
from ..data.ibtracs import load
from ..data.persistence_frame import add_persistence_frame
from ..domain.imd import CATEGORY_COLOR, KELVIN
from ..eval.baselines import persistence_forecast, track_error_km
from ..eval.cone import cone_polygon
from ..models.nowcast_gbm import NowcastGBM

plt.rcParams.update({
    "figure.facecolor": "#071018", "axes.facecolor": "#0E1B26",
    "text.color": "#D6E4EE", "axes.labelcolor": "#D6E4EE",
    "xtick.color": "#6E8899", "ytick.color": "#6E8899",
    "axes.edgecolor": "#1C3040", "font.size": 9,
})

HERO = "2019116N02090"      # Fani, 2019 — held-out season


def run(sid: str = HERO, name: str = "Fani 2019") -> dict:
    model = NowcastGBM.load(MODELS / "nowcast_gbm.joblib")
    radii = json.loads((MODELS / "cone_radii.json").read_text())
    radii_km = {int(k): v for k, v in radii["radii_km"].items()}

    fixes = filter_nio(load())
    feats = add_persistence_frame(add_forecast_targets(build_track_features(fixes)))
    storm = feats[feats.sid == sid].sort_values("iso_time").reset_index(drop=True)
    if storm.empty:
        raise SystemExit(f"storm {sid} not found")

    rows = []
    for i in range(len(storm)):
        # ---- CAUSALITY BOUNDARY: only fixes up to and including i ----------
        history = storm.iloc[: i + 1]
        cur = history.iloc[[-1]]
        if not np.isfinite(cur[f"plat_6h"].iloc[0]):
            continue

        pred = model.predict(cur)
        pers = {L: persistence_forecast(cur, L) for L in FORECAST_LEADS_H}

        for L in FORECAST_LEADS_H:
            tlat, tlon = cur[f"tlat_{L}h"].iloc[0], cur[f"tlon_{L}h"].iloc[0]
            twind = cur[f"twind_{L}h"].iloc[0]
            if not np.isfinite(tlat):
                continue
            pm = pd.DataFrame({"lat": pred[L]["lat"], "lon": pred[L]["lon"]},
                              index=cur.index)
            rows.append({
                "i": i, "ts": cur.iso_time.iloc[0], "lead_h": L,
                "obs_lat": cur.lat.iloc[0], "obs_lon": cur.lon.iloc[0],
                "obs_kt": cur.wind_kt_3min.iloc[0],
                "obs_cat": cur.imd_category.iloc[0],
                "pred_lat": float(pred[L]["lat"][0]), "pred_lon": float(pred[L]["lon"][0]),
                "pred_kt": float(pred[L]["wind_kt"][0]),
                "pred_kt_q10": float(pred[L]["wind_kt_q10"][0]),
                "pred_kt_q90": float(pred[L]["wind_kt_q90"][0]),
                "true_lat": float(tlat), "true_lon": float(tlon), "true_kt": float(twind),
                "err_km": float(track_error_km(pm, [tlat], [tlon])[0]),
                "pers_err_km": float(track_error_km(pers[L], [tlat], [tlon])[0]),
                "kt_err": float(pred[L]["wind_kt"][0]) - float(twind),
                "pers_kt_err": float(cur.wind_kt_3min.iloc[0]) - float(twind),
                "in_cone": float(track_error_km(pm, [tlat], [tlon])[0]) <= radii_km[L],
            })

    df = pd.DataFrame(rows)
    summary = {"storm": name, "sid": sid, "n_fixes": int(len(storm)),
               "n_forecasts": int(len(df)), "by_lead": {}}
    for L in FORECAST_LEADS_H:
        d = df[df.lead_h == L]
        if d.empty:
            continue
        summary["by_lead"][str(L)] = {
            "n": int(len(d)),
            "track_err_km_mean": round(float(d.err_km.mean()), 1),
            "persistence_err_km_mean": round(float(d.pers_err_km.mean()), 1),
            "track_skill": round(float(1 - d.err_km.mean() / d.pers_err_km.mean()), 3),
            "intensity_mae_kt": round(float(d.kt_err.abs().mean()), 2),
            "persistence_mae_kt": round(float(d.pers_kt_err.abs().mean()), 2),
            "cone_coverage": round(float(d.in_cone.mean()), 3),
            "worst_track_err_km": round(float(d.err_km.max()), 1),
            "worst_at": str(d.loc[d.err_km.idxmax(), "ts"]),
        }

    _plot(storm, df, radii_km, name, summary)
    (ARTIFACTS / "case_study.json").write_text(json.dumps(summary, indent=2, default=str))
    df.to_csv(ARTIFACTS / "case_study_forecasts.csv", index=False)
    return summary


def _plot(storm, df, radii_km, name, summary):
    # Map on the left spanning both rows, charts stacked on the right. A NIO
    # track is tall and narrow — Fani runs 2 N to 25 N across barely 8 degrees of
    # longitude — so a full-width map panel forces a geographically correct
    # aspect into a thin column with empty space either side.
    fig = plt.figure(figsize=(14.0, 7.6))
    gs = fig.add_gridspec(2, 2, width_ratios=[1, 1.55], hspace=0.42, wspace=0.18)

    # --- map: full observed track, with forecasts issued at four moments ---
    ax = fig.add_subplot(gs[:, 0])
    ax.plot(storm.lon, storm.lat, "-", color="#D6E4EE", lw=1.6, zorder=3,
            label="Observed best track (IBTrACS)")
    ax.scatter(storm.lon, storm.lat, s=[9 + w * 0.9 for w in storm.wind_kt_3min],
               c=[CATEGORY_COLOR.get(c, "#8FA3B0") for c in storm.imd_category],
               edgecolors="#071018", linewidths=0.5, zorder=4)

    d24 = df[df.lead_h == 24]
    picks = d24.i.unique()
    picks = picks[:: max(1, len(picks) // 4)][:4]
    for k, i in enumerate(picks):
        sub = df[(df.i == i)].sort_values("lead_h")
        if sub.empty:
            continue
        o = sub.iloc[0]
        path_lon = [o.obs_lon] + list(sub.pred_lon)
        path_lat = [o.obs_lat] + list(sub.pred_lat)
        ax.plot(path_lon, path_lat, "--", color="#F2C63D", lw=1.4, zorder=5,
                label="CYCLOPS forecast" if k == 0 else None)
        pts = [{"lead_h": int(r.lead_h), "lat": r.pred_lat, "lon": r.pred_lon}
               for r in sub.itertuples()]
        ring = cone_polygon(pts, radii_km)
        if ring:
            ax.fill(*zip(*ring), color="#35C4E8", alpha=0.11, zorder=2,
                    label="67% cone" if k == 0 else None)

    ax.set_xlabel("longitude °E"); ax.set_ylabel("latitude °N")
    ax.set_title(f"{name} — four forecasts, each using only\n"
                 f"data available at issue time", fontsize=9.5)
    ax.legend(fontsize=7.5, loc="upper left", facecolor="#0E1B26",
              edgecolor="#1C3040", framealpha=0.9)
    ax.grid(alpha=0.12, color="#1C3040")
    # Pad the extent so the cones are not clipped, and set the aspect so a
    # degree of longitude and a degree of latitude are drawn at their true
    # relative ground distance at this latitude — a square aspect would make the
    # track look more meridional than it is.
    lo0, lo1 = float(storm.lon.min()), float(storm.lon.max())
    la0, la1 = float(storm.lat.min()), float(storm.lat.max())
    padx = max(2.0, (lo1 - lo0) * 0.30)
    pady = max(1.5, (la1 - la0) * 0.08)
    ax.set_xlim(lo0 - padx, lo1 + padx)
    ax.set_ylim(la0 - pady, la1 + pady)
    ax.set_aspect(1.0 / np.cos(np.deg2rad((la0 + la1) / 2)))

    # --- intensity: observed vs 24 h forecast, with band ---
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(storm.iso_time, storm.wind_kt_3min, color="#3BD16F", lw=2,
             label="Observed (best track)")
    if not d24.empty:
        vt = d24.ts + pd.Timedelta(hours=24)
        ax2.plot(vt, d24.pred_kt, "--", color="#F2C63D", lw=1.6,
                 label="CYCLOPS +24 h")
        ax2.fill_between(vt, d24.pred_kt_q10, d24.pred_kt_q90,
                         color="#F2C63D", alpha=0.16, label="90% band")
    ax2.set_ylabel("3-min sustained wind (kt)")
    ax2.set_title("Intensity — observed vs 24 h forecast", fontsize=9)
    ax2.legend(fontsize=7.5, facecolor="#0E1B26", edgecolor="#1C3040")
    ax2.grid(alpha=0.12, color="#1C3040")
    ax2.tick_params(axis="x", rotation=25, labelsize=7)

    # --- error growth vs persistence ---
    ax3 = fig.add_subplot(gs[1, 1])
    leads = sorted(df.lead_h.unique())
    m = [df[df.lead_h == L].err_km.mean() for L in leads]
    p = [df[df.lead_h == L].pers_err_km.mean() for L in leads]
    w = 0.36
    x = np.arange(len(leads))
    ax3.bar(x - w / 2, p, w, label="Persistence", color="#6E8899")
    ax3.bar(x + w / 2, m, w, label="CYCLOPS", color="#35C4E8")
    for xi, (mi, pi) in enumerate(zip(m, p)):
        ax3.annotate(f"{(1 - mi / pi) * 100:+.0f}%", (xi + w / 2, mi),
                     ha="center", va="bottom", fontsize=7.5,
                     color="#3BD16F" if mi < pi else "#E8404A")
    ax3.set_xticks(x); ax3.set_xticklabels([f"+{L}h" for L in leads])
    ax3.set_ylabel("mean track error (km)")
    ax3.set_title(f"Track error on {name} — this storm only", fontsize=9)
    ax3.legend(fontsize=7.5, facecolor="#0E1B26", edgecolor="#1C3040")
    ax3.grid(alpha=0.12, axis="y", color="#1C3040")

    fig.suptitle(f"Case study — {name}  ·  held-out season, "
                 f"every forecast made with data available at issue time",
                 fontsize=11, y=0.985)
    out = ARTIFACTS / "case_study.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else HERO
    nm = sys.argv[2] if len(sys.argv) > 2 else "Fani 2019"
    s = run(sid, nm)
    print(json.dumps(s, indent=2))
