"""
Build the vision dataset: one sample per best-track fix.

Positions, times and intensity labels are REAL, from IBTrACS. The imagery is
synthetic (see data/synth_ir.py). That split is recorded in the manifest so the
provenance of every sample is explicit and no downstream consumer has to guess.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..config import DATA_PROCESSED, IR_SIZE, SEED, WIND_SIZE
from ..domain.imd import category_to_index, wind_to_t_number
from ..preprocess import ENV_DIM, preprocess_sample
from .features import add_forecast_targets, build_track_features, filter_nio
from .ibtracs import load
from .persistence_frame import add_persistence_frame
from .splits import assert_disjoint, describe, split_by_season
from .synth_ir import render_ir_scene, render_wind_field

# A scatterometer sees a given storm roughly twice a day, against an IR frame
# every 15-30 minutes. Most fixes therefore have no coincident wind pass, and the
# dataset must reflect that or the wind branch learns to expect data it will not
# have. 0.35 approximates a +/-3 h coincidence window at 6-hourly fixes.
WIND_COINCIDENCE_RATE = 0.35

# Infrared cloud pattern is an INDIRECT proxy for surface wind. A storm can carry
# a spectacular cold cloud shield over modest surface winds, or look ragged while
# carrying dangerous ones. Rendering the scene from the exact best-track value
# would make intensity perfectly recoverable from the image alone - which is not
# how the atmosphere works, and it makes the fusion ablation vacuous because
# there is nothing left for a second modality to contribute.
#
# So the scene is rendered from a perturbed intensity while the LABEL stays the
# true best-track value. The spread is set near the inter-analyst disagreement in
# Dvorak estimation (~10 kt), which is the real irreducible floor for a
# pattern-only estimate.
#
# The scatterometer field is rendered from the TRUE wind, because a scatterometer
# measures the ocean surface directly. That asymmetry is the entire physical
# argument for fusing them, and it is what the ablation is designed to test.
IR_PATTERN_NOISE_KT = 9.0


def build(max_samples: int | None = None, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)

    fixes = filter_nio(load())
    feats = add_persistence_frame(add_forecast_targets(build_track_features(fixes)))
    # Sub-cyclone stages carry no Dvorak pattern to read; the classifier is
    # scored on D and above.
    feats = feats[feats.wind_kt_3min >= 17.0].reset_index(drop=True)
    if max_samples and len(feats) > max_samples:
        feats = feats.sample(max_samples, random_state=seed).sort_values(
            ["sid", "iso_time"]).reset_index(drop=True)

    splits = split_by_season(feats)
    assert_disjoint(splits)
    split_of = {}
    for name, d in splits.items():
        for i in d.index:
            split_of[i] = name

    n = len(feats)
    # float16 storage: these are normalised to [0, 1] and the model casts back
    # to float32 on load, so the precision loss is far below the noise floor of
    # the imagery itself, and it halves the dataset on disk.
    ir = np.zeros((n, 3, IR_SIZE, IR_SIZE), np.float16)
    wind = np.zeros((n, 3, WIND_SIZE, WIND_SIZE), np.float16)
    present = np.zeros(n, np.float32)
    env = np.zeros((n, ENV_DIM), np.float32)
    y_kt = np.zeros(n, np.float32)
    y_cat = np.zeros(n, np.int64)
    y_tnum = np.zeros(n, np.float32)
    d_centre = np.zeros((n, 2), np.float32)
    split_arr = np.empty(n, dtype="<U6")

    for i, row in tqdm(feats.iterrows(), total=n, desc="rendering scenes", ncols=78):
        # Off-centre the storm so the detection head learns to find it rather
        # than learning that the storm is always in the middle of the crop.
        off = rng.integers(-28, 29, size=2)
        # Cloud pattern reflects intensity imperfectly (see IR_PATTERN_NOISE_KT).
        apparent_kt = float(np.clip(
            row.wind_kt_3min + rng.normal(0.0, IR_PATTERN_NOISE_KT), 15.0, 165.0))
        s = render_ir_scene(
            wind_kt=apparent_kt, lat=float(row.lat), lon=float(row.lon),
            shear_kt=float(row.shear_kt),
            shear_dir_deg=float(rng.uniform(0, 360)),
            seed=int(rng.integers(0, 2**31)),
            centre_offset_px=(int(off[0]), int(off[1])),
        )

        has_wind = rng.random() < WIND_COINCIDENCE_RATE
        if has_wind:
            w = render_wind_field(float(row.wind_kt_3min), float(row.lat),
                                  float(s["rmw_km"]), size=WIND_SIZE,
                                  seed=int(rng.integers(0, 2**31)))
            hours_since = float(rng.uniform(0.0, 3.0))
        else:
            w = {"u10": None, "v10": None, "mask": None, "coverage": 0.0}
            hours_since = 12.0

        env_d = {
            "lat": row.lat, "lon": row.lon,
            "sst_c": row.sst_c, "shear_kt": row.shear_kt,
            "steer_u_kt": 0.0, "steer_v_kt": 0.0,
            "trans_speed_kt": row.trans_speed_kt,
            "bearing_sin": row.bearing_sin, "bearing_cos": row.bearing_cos,
            "dwind_6h_kt": row.dwind_6h_kt, "dwind_24h_kt": row.dwind_24h_kt,
            "doy_sin": row.doy_sin, "doy_cos": row.doy_cos,
            "hours_since_wind": hours_since, "wind_coverage": w["coverage"],
        }
        p = preprocess_sample(s["tir1_k"], s["wv_k"], w["u10"], w["v10"],
                              w["mask"], env_d)
        ir[i] = p["ir"].astype(np.float16)
        wind[i] = p["wind"].astype(np.float16)
        present[i], env[i] = p["wind_present"], p["env"]
        y_kt[i] = row.wind_kt_3min
        y_cat[i] = category_to_index(row.imd_category)
        y_tnum[i] = wind_to_t_number(row.wind_kt_3min)
        # Detection target: true centre offset from the crop centre, in pixels,
        # normalised. This is what makes centre-fixing a real regression rather
        # than a constant.
        d_centre[i] = (off[0] / (IR_SIZE / 2), off[1] / (IR_SIZE / 2))
        split_arr[i] = split_of[i]

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "vision_dataset.npz"
    np.savez(
        out, ir=ir, wind=wind, wind_present=present, env=env,
        y_kt=y_kt, y_cat=y_cat, y_tnum=y_tnum, d_centre=d_centre,
        split=split_arr, sid=feats.sid.to_numpy().astype("<U16"),
        iso_time=feats.iso_time.astype(str).to_numpy().astype("<U32"),
        lat=feats.lat.to_numpy().astype(np.float32),
        lon=feats.lon.to_numpy().astype(np.float32),
    )

    manifest = {
        "n_samples": int(n),
        "n_storms": int(feats.sid.nunique()),
        "labels": {
            "source": "IBTrACS v04r01 NEWDELHI_WIND (3-min sustained, IMD)",
            "status": "REAL",
        },
        "positions": {"source": "IBTrACS v04r01 best track", "status": "REAL"},
        "imagery": {
            "source": "cyclops.data.synth_ir — parameterised from best track",
            "status": "SYNTHETIC",
            "note": ("Placeholder for Digital Typhoon / INSAT-3D,3DR,3DS. Any "
                     "intensity metric computed on these scenes measures "
                     "invertibility of the renderer, NOT satellite skill."),
        },
        "wind": {"source": "cyclops.data.synth_ir modified-Rankine + swath",
                 "status": "SYNTHETIC",
                 "coincidence_rate": WIND_COINCIDENCE_RATE},
        "ir_pattern_noise_kt": IR_PATTERN_NOISE_KT,
        "ir_pattern_noise_rationale": (
            "IR is an indirect proxy for surface wind; the scene is rendered "
            "from a perturbed intensity while the label stays true best-track, "
            "so a pattern-only estimator faces a realistic ~9 kt floor. The "
            "scatterometer field is rendered from the true wind."),
        "split_policy": "by_season; storm IDs disjoint across splits (asserted)",
        "splits": describe(splits).to_dict("records"),
        "content_sha256": hashlib.sha256(out.read_bytes()).hexdigest()[:16],
        "seed": seed,
        "ir_size": IR_SIZE,
        "storage_dtype": "float16",
    }
    (DATA_PROCESSED / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\nwrote {out}  ({out.stat().st_size/1e6:.0f} MB)")
    print(json.dumps({k: manifest[k] for k in
                      ("n_samples", "n_storms", "split_policy", "content_sha256")},
                     indent=2))
    return manifest


if __name__ == "__main__":
    import sys
    build(max_samples=int(sys.argv[1]) if len(sys.argv) > 1 else None)
