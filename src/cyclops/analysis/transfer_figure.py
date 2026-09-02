"""
The transfer test, as one figure.

Thresholds were selected on Fani. Amphan and Mocha ran on those thresholds
unchanged. This draws the comparison, including the parts that did not work.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from ..config import ARTIFACTS

plt.rcParams.update({
    "figure.facecolor": "#04090f", "axes.facecolor": "#0a141c",
    "text.color": "#dfeaf3", "axes.labelcolor": "#dfeaf3",
    "xtick.color": "#8ba3b4", "ytick.color": "#8ba3b4",
    "axes.edgecolor": "#1d3040", "font.size": 9,
})

CASES = [("fani", "Fani 2019\n(threshold source)", "#f2c63d"),
         ("amphan", "Amphan 2020\n(out-of-sample)", "#3bd16f"),
         ("mocha", "Mocha 2023\n(out-of-sample)", "#3bd16f")]


def main():
    data = {k: (json.loads((ARTIFACTS / f"{k}_analysis.json").read_text()),
                json.loads((ARTIFACTS / f"{k}_frames.json").read_text()))
            for k, _, _ in CASES}

    fig, ax = plt.subplots(2, 2, figsize=(13, 8.4))
    x = np.arange(len(CASES))
    labels = [lbl for _, lbl, _ in CASES]
    edge = [c for _, _, c in CASES]

    # --- centre-fix error vs both baselines ---
    a = ax[0, 0]
    fix = [data[k][0]["identification"]["centre_error_km"]["mean"] for k, _, _ in CASES]
    gue = [data[k][0]["identification"]["first_guess_error_km"]["mean"] for k, _, _ in CASES]
    lst = [data[k][0]["identification"]["last_fix_error_km"]["mean"] for k, _, _ in CASES]
    w = 0.26
    a.bar(x - w, lst, w, label="last best-track fix", color="#4a6478")
    a.bar(x, gue, w, label="motion-extrapolated guess", color="#8ba3b4")
    a.bar(x + w, fix, w, label="CYCLOPS centre fix", color="#35c4e8")
    for i, (f, g) in enumerate(zip(fix, gue)):
        a.annotate(f"{(1 - f/g)*100:+.0f}% vs guess", (i + w, f), ha="center",
                   va="bottom", fontsize=7.5,
                   color="#3bd16f" if f < g else "#e8404a")
    a.set_ylabel("mean centre error (km)")
    a.set_title("Identification — beats last-fix everywhere, "
                "roughly ties motion extrapolation", fontsize=9.5)
    a.legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    # --- intensity error, and the bias within it ---
    a = ax[0, 1]
    rmse = [data[k][0]["classification"]["time_constrained"]["rmse_kt"] for k, _, _ in CASES]
    bias = [data[k][0]["classification"]["time_constrained"]["bias_kt"] for k, _, _ in CASES]
    # RMSE and bias are NOT additive — RMSE^2 = bias^2 + variance — so bias is
    # drawn as its own marker rather than a stacked sub-bar, which would imply a
    # decomposition that does not hold.
    scatter = [float(np.sqrt(max(r ** 2 - b ** 2, 0.0))) for r, b in zip(rmse, bias)]
    a.bar(x - 0.16, rmse, 0.3, color="#35c4e8", label="RMSE")
    a.bar(x + 0.16, scatter, 0.3, color="#4a6478",
          label="scatter component  √(RMSE² − bias²)")
    a.plot(x, bias, "D", ms=8, color="#f2803d", label="systematic bias")
    for i, b in enumerate(bias):
        a.annotate(f"{b:+.1f} kt", (i, b), ha="center", va="bottom",
                   fontsize=8, color="#f2803d", xytext=(0, 6),
                   textcoords="offset points")
    a.set_ylabel("kt")
    a.set_title("Classification — the +9 to +11 kt over-estimate recurs on every "
                "storm,\nbut scatter dominates the error", fontsize=9.5)
    a.legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    # --- error vs truth, pooled: is the offset constant across intensity? ---
    a = ax[1, 0]
    for k, lbl, col in CASES:
        fr = data[k][1]
        t = np.array([f["truth"]["wind_kt"] for f in fr])
        p = np.array([f["dvorak"]["wind_kt_smoothed"] for f in fr])
        a.scatter(t, p, s=26, color=col, edgecolor="#04090f", linewidth=0.5,
                  label=lbl.split("\n")[0], alpha=0.9)
    lim = [0, 140]
    a.plot(lim, lim, "--", color="#8ba3b4", lw=1, label="perfect")
    a.plot(lim, [v + 10.5 for v in lim], ":", color="#f2803d", lw=1.2,
           label="+10.5 kt pooled bias")
    a.set_xlim(*lim); a.set_ylim(*lim)
    a.set_xlabel("IBTrACS best track (kt)"); a.set_ylabel("objective Dvorak (kt)")
    a.set_title("Over-estimates weak systems, under-estimates the strongest",
                fontsize=9.5)
    a.legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    # --- leave-one-storm-out bias correction ---
    a = ax[1, 1]
    allp = {k: np.array([f["dvorak"]["wind_kt_smoothed"] for f in data[k][1]])
            for k, _, _ in CASES}
    allt = {k: np.array([f["truth"]["wind_kt"] for f in data[k][1]])
            for k, _, _ in CASES}
    before, after = [], []
    for k, _, _ in CASES:
        others = [j for j, _, _ in CASES if j != k]
        off = float(np.concatenate([allp[j] - allt[j] for j in others]).mean())
        before.append(float(np.sqrt(((allp[k] - allt[k]) ** 2).mean())))
        after.append(float(np.sqrt((((allp[k] - off) - allt[k]) ** 2).mean())))
    a.bar(x - 0.2, before, 0.4, label="as measured", color="#8ba3b4")
    a.bar(x + 0.2, after, 0.4, label="offset from the OTHER two storms", color="#3bd16f")
    for i, (b, af) in enumerate(zip(before, after)):
        a.annotate(f"{(1 - af/b)*100:+.1f}%", (i + 0.2, af), ha="center",
                   va="bottom", fontsize=7.5, color="#3bd16f")
    a.set_ylabel("RMSE (kt)")
    a.set_title("Leave-one-storm-out: the bias is transferable, the scatter is not",
                fontsize=9.5)
    a.legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    for row in ax:
        for a2 in row:
            a2.grid(alpha=0.12, color="#1d3040")
    for a2 in (ax[0, 0], ax[0, 1], ax[1, 1]):
        a2.set_xticks(x); a2.set_xticklabels(labels, fontsize=8)
        for tick, col in zip(a2.get_xticklabels(), edge):
            tick.set_color(col)

    t = json.loads((ARTIFACTS / "fani_analysis.json").read_text())["thresholds_used"]
    fig.suptitle(
        "Out-of-sample test — identical thresholds "
        f"(eye contrast ≥{t['EYE_CONTRAST_C']:.0f}°C, ring ≤{t['RING_ENCLOSURE_C']:.0f}°C, "
        f"symmetry ≥{t['EYE_MIN_SYMMETRY']:.2f}) chosen on Fani, applied unchanged",
        fontsize=11.5, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    out = ARTIFACTS / "transfer_test.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", out)
    return out


if __name__ == "__main__":
    main()
