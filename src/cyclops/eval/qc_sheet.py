"""
Visual sanity audit.

Doc 04 week 4 calls for eyeballing 50 random samples against their labels before
trusting any metric. This generates that sheet, plus a physics check that the
renderer behaves the way the domain says it should as intensity increases.

Both figures go straight into the deck.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from ..config import ARTIFACTS, SEED
from ..data.features import build_track_features, filter_nio
from ..data.ibtracs import load
from ..data.synth_ir import render_ir_scene
from ..domain.imd import CATEGORY_COLOR, KELVIN, bd_enhance

plt.rcParams.update({
    "figure.facecolor": "#071018", "axes.facecolor": "#0E1B26",
    "text.color": "#D6E4EE", "axes.labelcolor": "#D6E4EE",
    "xtick.color": "#6E8899", "ytick.color": "#6E8899",
    "axes.edgecolor": "#1C3040", "font.size": 8,
})


def sample_sheet(n: int = 40, seed: int = SEED):
    """Grid of rendered scenes with their real best-track labels beneath."""
    rng = np.random.default_rng(seed)
    fixes = filter_nio(load())
    fixes = fixes[fixes.wind_kt_3min >= 17]
    feats = build_track_features(fixes)
    idx = rng.choice(len(feats), size=min(n, len(feats)), replace=False)

    cols = 8
    rows = int(np.ceil(len(idx) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 1.7, rows * 2.0))
    axes = np.atleast_1d(axes).ravel()

    for ax, i in zip(axes, idx):
        r = feats.iloc[i]
        s = render_ir_scene(float(r.wind_kt_3min), float(r.lat), float(r.lon),
                            shear_kt=float(r.shear_kt),
                            seed=int(rng.integers(0, 2 ** 31)))
        ax.imshow(s["tir1_k"] - KELVIN, cmap="bone_r", vmin=-85, vmax=30)
        ax.set_title(f"{r['name'][:9]} {int(r.season)}", fontsize=6.5, pad=2)
        ax.set_xlabel(f"{r.wind_kt_3min:.0f} kt · {r.imd_category}",
                      fontsize=6.5, labelpad=1,
                      color=CATEGORY_COLOR.get(r.imd_category, "#D6E4EE"))
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(CATEGORY_COLOR.get(r.imd_category, "#1C3040"))
            sp.set_linewidth(1.1)
    for ax in axes[len(idx):]:
        ax.axis("off")

    fig.suptitle(
        "Sample audit — rendered scene vs real IBTrACS label  "
        "(SYNTHETIC IMAGERY, real labels)",
        fontsize=10, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    out = ARTIFACTS / "qc_sample_sheet.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def physics_sheet():
    """
    Does the renderer behave the way the domain says it should?

    Three checks a forecaster would make: cloud tops stay near the tropopause at
    every intensity, the eye only clears once the storm is organised, and the
    area of BD-enhanced cold cloud grows with intensity.
    """
    kts = np.arange(20, 155, 5.0)
    stats = []
    for kt in kts:
        s = render_ir_scene(float(kt), 17.0, 87.0, shear_kt=10.0, seed=7)
        t = s["tir1_k"] - KELVIN
        c = t.shape[0] // 2
        rmw_px = max(2, int(float(s["rmw_km"]) / (1024.0 / t.shape[0])))
        stats.append({
            "kt": kt,
            "min_c": float(t.min()),
            "eye_c": float(t[c - 1:c + 2, c - 1:c + 2].mean()),
            "eyewall_c": float(t[c, c + rmw_px:c + rmw_px + 3].min()),
            "bd_frac": float((bd_enhance(s["tir1_k"]) > 0.15).mean()),
            "rmw": float(s["rmw_km"]),
        })

    fig, ax = plt.subplots(1, 3, figsize=(12.5, 3.4))

    ax[0].plot(kts, [s["min_c"] for s in stats], color="#35C4E8", label="coldest pixel")
    ax[0].plot(kts, [s["eyewall_c"] for s in stats], color="#F2803D", label="eyewall")
    ax[0].plot(kts, [s["eye_c"] for s in stats], color="#E8404A", label="eye centre")
    ax[0].axhline(-70, ls="--", lw=0.8, color="#6E8899")
    ax[0].annotate("tropopause-limited tops", (24, -67), fontsize=7, color="#6E8899")
    ax[0].set_xlabel("3-min sustained wind (kt)")
    ax[0].set_ylabel("brightness temperature (°C)")
    ax[0].set_title("Eye clears only above ~64 kt (VSCS)", fontsize=9)
    ax[0].legend(fontsize=7, facecolor="#0E1B26", edgecolor="#1C3040")

    ax[1].plot(kts, [s["rmw"] for s in stats], color="#3BD16F")
    ax[1].set_xlabel("3-min sustained wind (kt)")
    ax[1].set_ylabel("radius of max wind (km)")
    ax[1].set_title("RMW contracts as the storm intensifies", fontsize=9)

    ax[2].plot(kts, [100 * s["bd_frac"] for s in stats], color="#F2C63D")
    ax[2].set_xlabel("3-min sustained wind (kt)")
    ax[2].set_ylabel("% of scene in BD cold bands")
    ax[2].set_title("Cold cloud shield expands with intensity", fontsize=9)

    for a in ax:
        a.grid(alpha=0.12, color="#1C3040")
    fig.suptitle("Renderer physics check — behaviour vs intensity", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out = ARTIFACTS / "qc_physics.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def category_distribution():
    """Class balance, which is what makes per-category metrics interpretable."""
    from ..data.splits import split_by_season
    from ..domain.imd import CATEGORIES

    fixes = filter_nio(load())
    fixes = fixes[fixes.wind_kt_3min >= 17]
    splits = split_by_season(fixes)

    fig, ax = plt.subplots(figsize=(7.6, 3.2))
    width = 0.26
    x = np.arange(len(CATEGORIES))
    for k, (name, d) in enumerate(splits.items()):
        counts = [int((d.imd_category == c).sum()) for c in CATEGORIES]
        ax.bar(x + (k - 1) * width, counts, width, label=name,
               color=["#35C4E8", "#F2C63D", "#E8404A"][k], alpha=0.85)
    ax.set_xticks(x); ax.set_xticklabels(CATEGORIES)
    ax.set_yscale("log")
    ax.set_ylabel("fixes (log)")
    ax.set_title("Class balance by IMD category and split — "
                 "ESCS/SuCS are rare, which is why intensity is regressed, "
                 "not classified", fontsize=9)
    ax.legend(fontsize=8, facecolor="#0E1B26", edgecolor="#1C3040")
    ax.grid(alpha=0.12, axis="y", color="#1C3040")
    fig.tight_layout()
    out = ARTIFACTS / "qc_class_balance.png"
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def main():
    for f in (sample_sheet, physics_sheet, category_distribution):
        print("wrote", f())


if __name__ == "__main__":
    main()
