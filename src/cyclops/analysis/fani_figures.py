"""
Figures for the Fani case study. Every panel is drawn from real data and from
artifacts/fani_*.json, so nothing here is hand-drawn or hand-typed.
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from ..config import ARTIFACTS
from ..data.gibs import fetch_scene
from ..domain.imd import CATEGORY_COLOR, KELVIN

plt.rcParams.update({
    "figure.facecolor": "#04090f", "axes.facecolor": "#0a141c",
    "text.color": "#dfeaf3", "axes.labelcolor": "#dfeaf3",
    "xtick.color": "#8ba3b4", "ytick.color": "#8ba3b4",
    "axes.edgecolor": "#1d3040", "font.size": 8.5,
})

# Dvorak BD ramp, in the orientation the domain actually displays it: warm sea
# surface is dark, cloud brightens as it cools, and the coldest overshooting tops
# break into the enhancement colours. The ramp runs cold -> warm because the
# scenes are plotted in degrees Celsius, so position 0 is the COLDEST value.
BD_CMAP = matplotlib.colors.LinearSegmentedColormap.from_list("bd", [
    (0.00, "#a82078"),   # coldest overshooting tops
    (0.06, "#e8404a"),
    (0.13, "#f2803d"),
    (0.20, "#f2c63d"),
    (0.28, "#3bd16f"),
    (0.38, "#f2f6f8"),   # deep convection, white
    (0.55, "#8fb8cc"),
    (0.75, "#26506b"),
    (1.00, "#04090f"),   # warm sea surface, dark
])
# MODIS leaves gaps between swaths. Painting those in the ramp makes an
# instrument artefact look like the coldest cloud in the scene, which is exactly
# how a data gap gets mistaken for an overshooting top.
BD_CMAP.set_bad("#0a141c")


def _load():
    frames = json.loads((ARTIFACTS / "fani_frames.json").read_text())
    summary = json.loads((ARTIFACTS / "fani_analysis.json").read_text())
    return frames, summary


def evolution_sheet(n: int = 8):
    """The storm's life in real infrared, with the fix and the estimate on each."""
    frames, _ = _load()
    idx = np.linspace(0, len(frames) - 1, min(n, len(frames))).astype(int)

    cols = 4
    rows = int(np.ceil(len(idx) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.1, rows * 3.9))
    axes = np.atleast_1d(axes).ravel()

    for ax, i in zip(axes, idx):
        fr = frames[i]
        w, s, e, n_ = fr["scene"]["bbox"]
        sc = fetch_scene(fr["first_guess"]["lat"], fr["first_guess"]["lon"],
                         fr["date"], fr["pass"], 1024.0, 256)
        if sc is None:
            ax.axis("off")
            continue
        C = np.ma.masked_where(~sc.valid, sc.kelvin - KELVIN)
        ax.imshow(C, cmap=BD_CMAP, vmin=-95, vmax=25, extent=[w, e, s, n_],
                  origin="upper")

        ax.plot(fr["truth"]["lon"], fr["truth"]["lat"], "o", ms=7, mfc="none",
                mec="#3bd16f", mew=1.6, label="best track")
        ax.plot(fr["fix"]["lon"], fr["fix"]["lat"], "+", ms=9, mec="#35c4e8",
                mew=1.8, label="CYCLOPS fix")

        cat = fr["truth"]["imd_category"]
        ax.set_title(f"{fr['observed_at'][5:16].replace('T', ' ')}Z · "
                     f"{fr['pass'].replace('_', ' ')}", fontsize=7.5, pad=3)
        ax.set_xlabel(
            f"{fr['dvorak']['pattern']}  T{fr['dvorak']['t_number']:.1f} → "
            f"{fr['dvorak']['wind_kt']:.0f} kt   (truth {fr['truth']['wind_kt']:.0f} kt "
            f"{cat})\nfix error {fr['centre_error_km']:.0f} km",
            fontsize=7, labelpad=2,
            color=CATEGORY_COLOR.get(cat, "#dfeaf3"))
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(CATEGORY_COLOR.get(cat, "#1d3040")); sp.set_linewidth(1.2)

    for ax in axes[len(idx):]:
        ax.axis("off")
    axes[0].legend(fontsize=6.5, loc="upper left", facecolor="#0a141c",
                   edgecolor="#1d3040", labelcolor="#dfeaf3")

    fig.suptitle("Cyclone Fani (2019) — real MODIS Band 31 infrared, "
                 "identification and objective Dvorak on every day pass",
                 fontsize=11, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.96), h_pad=3.2)
    out = ARTIFACTS / "fani_evolution.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def performance_sheet():
    """Intensity, centre-fix error and the pattern sequence, against best track."""
    frames, summary = _load()
    ts = [fr["observed_at"][5:16].replace("T", " ") for fr in frames]
    x = np.arange(len(frames))
    truth = np.array([fr["truth"]["wind_kt"] for fr in frames])
    dvo = np.array([fr["dvorak"]["wind_kt"] for fr in frames])
    sm = np.array([fr["dvorak"]["wind_kt_smoothed"] for fr in frames])
    err = np.array([fr["centre_error_km"] for fr in frames])
    guess = np.array([fr["first_guess_error_km"] for fr in frames])
    lastfix = np.array([fr["last_fix_error_km"] for fr in frames])

    fig, ax = plt.subplots(3, 1, figsize=(11.5, 9.2), height_ratios=[1.25, 1, 0.55])

    # --- intensity ---
    ax[0].plot(x, truth, "-o", color="#3bd16f", lw=2, ms=4, label="IBTrACS best track (IMD 3-min)")
    ax[0].plot(x, dvo, "--s", color="#f2c63d", lw=1.4, ms=3.5, label="Objective Dvorak (raw)")
    ax[0].plot(x, sm, "-", color="#35c4e8", lw=1.6, label="Dvorak + time constraint")
    for i, fr in enumerate(frames):
        if fr["dvorak"]["pattern"] == "EYE":
            ax[0].annotate("eye", (i, dvo[i]), fontsize=6.5, color="#e8404a",
                           ha="center", va="bottom")
    ax[0].set_ylabel("3-min sustained wind (kt)")
    c = summary["classification"]
    ax[0].set_title(
        f"Intensity — RMSE {c['time_constrained']['rmse_kt']:.1f} kt, "
        f"bias {c['time_constrained']['bias_kt']:+.1f} kt, "
        f"category within-one {c['category_within_one']:.0%}   (n={len(frames)})",
        fontsize=9.5)
    ax[0].legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    # --- centre fix ---
    wdt = 0.28
    ax[1].bar(x - wdt, lastfix, wdt, label="last best-track fix", color="#4a6478")
    ax[1].bar(x, guess, wdt, label="motion-extrapolated first guess", color="#8ba3b4")
    ax[1].bar(x + wdt, err, wdt, label="CYCLOPS centre fix", color="#35c4e8")
    idn = summary["identification"]
    ax[1].axhline(idn["centre_error_km"]["mean"], ls="--", lw=0.9, color="#35c4e8")
    ax[1].set_ylabel("centre error (km)")
    ax[1].set_title(
        f"Identification — fix {idn['centre_error_km']['mean']:.1f} km mean vs "
        f"first guess {idn['first_guess_error_km']['mean']:.1f} km "
        f"({idn['skill_vs_first_guess']:+.1%}) and last fix "
        f"{idn['last_fix_error_km']['mean']:.1f} km "
        f"({1 - idn['centre_error_km']['mean']/idn['last_fix_error_km']['mean']:+.1%})",
        fontsize=9.5)
    ax[1].legend(fontsize=7.5, facecolor="#0a141c", edgecolor="#1d3040")

    # --- pattern sequence ---
    pat_color = {"EYE": "#e8404a", "CDO": "#f2803d",
                 "EMBEDDED_CENTER": "#f2c63d", "SHEAR": "#8ba3b4"}
    for i, fr in enumerate(frames):
        p = fr["dvorak"]["pattern"]
        ax[2].barh(0, 1, left=i, color=pat_color.get(p, "#4a6478"),
                   edgecolor="#04090f", height=0.6)
    ax[2].set_yticks([]); ax[2].set_ylim(-0.5, 0.5)
    ax[2].set_title("Dvorak cloud pattern per scene", fontsize=9.5)
    handles = [plt.Rectangle((0, 0), 1, 1, color=v) for v in pat_color.values()]
    ax[2].legend(handles, pat_color.keys(), fontsize=7, ncol=4,
                 facecolor="#0a141c", edgecolor="#1d3040")

    for a in ax:
        a.set_xticks(x)
        a.set_xticklabels(ts, rotation=60, fontsize=6.5, ha="right")
        a.grid(alpha=0.12, color="#1d3040")
        a.set_xlim(-0.8, len(frames) - 0.2)

    fig.suptitle("Cyclone Fani (2019) — real MODIS infrared vs IBTrACS best track",
                 fontsize=11.5, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    out = ARTIFACTS / "fani_performance.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def main():
    for f in (evolution_sheet, performance_sheet):
        print("wrote", f())


if __name__ == "__main__":
    main()
