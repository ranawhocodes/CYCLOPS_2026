"""
Physically-parameterised infrared scene renderer.

READ THIS BEFORE USING ANY NUMBER THAT COMES OUT OF IT
-----------------------------------------------------
These are NOT satellite observations. They are synthetic brightness-temperature
fields generated from best-track parameters. They exist for exactly one reason:
the real archives (Digital Typhoon, and INSAT-3D/3DR/3DS via MOSDAC) both
require registration with multi-week lead time, and a pipeline that cannot be
run end to end until that clears is a pipeline nobody debugs.

What this legitimately buys:
  - The IR branch, the fusion trunk, Grad-CAM, the ONNX export, the API and the
    console are all built, wired and tested against the real tensor contract.
  - Swapping in the real archive is a change to one loader, not a rewrite.

What it does NOT buy, and must never be claimed:
  - Any intensity accuracy figure. A CNN trained on these is measuring how well
    it inverts THIS renderer, not how well it reads a cyclone. That number is
    reported as a pipeline check and is labelled SYNTHETIC everywhere it appears
    - in the metrics file, in the API response, and on the console itself.

The structure below follows the features Dvorak analysis actually keys on, so a
Grad-CAM over these scenes is at least asking the right question: eye size and
warmth scale with intensity, the eyewall is the coldest annulus, banding wraps
cyclonically (counter-clockwise in the Northern Hemisphere), and vertical shear
displaces the convection from the low-level centre.
"""
from __future__ import annotations

import numpy as np

from ..config import IR_SIZE, PATCH_KM
from ..domain.imd import KELVIN

SYNTHETIC_BANNER = "SYNTHETIC — parameterised from best-track, not a satellite observation"


def _radius_of_max_wind_km(wind_kt: float, lat: float) -> float:
    """
    RMW shrinks as a storm intensifies and grows with latitude.

    Follows the sense of the Willoughby et al. (2006) empirical relation rather
    than its exact coefficients; enough to make eye size track intensity the way
    a forecaster expects to see.
    """
    return float(np.clip(46.4 * np.exp(-0.0155 * wind_kt + 0.0169 * lat), 18.0, 120.0))


def render_ir_scene(
    wind_kt: float,
    lat: float,
    lon: float,
    shear_kt: float = 12.0,
    shear_dir_deg: float = 250.0,
    size: int = IR_SIZE,
    patch_km: float = PATCH_KM,
    seed: int | None = None,
    centre_offset_px: tuple[int, int] = (0, 0),
) -> dict[str, np.ndarray]:
    """
    Render a storm-centred IR (TIR-1) and water-vapour scene.

    Returns brightness temperature in kelvin, which is what a real reader
    produces, so downstream normalisation is identical for synthetic and real
    input. `centre_offset_px` deliberately allows an off-centre storm: training
    only on perfectly centred crops teaches the detection head that "the storm is
    in the middle", which is a tautology, not detection.
    """
    rng = np.random.default_rng(seed)
    km_per_px = patch_km / size

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cy, cx = size / 2.0 + centre_offset_px[1], size / 2.0 + centre_offset_px[0]
    dx = (xx - cx) * km_per_px
    dy = (yy - cy) * km_per_px
    r = np.hypot(dx, dy)
    theta = np.arctan2(dy, dx)

    intensity = float(np.clip(wind_kt, 15.0, 160.0))
    frac = (intensity - 15.0) / 145.0                     # 0 weak .. 1 extreme
    rmw = _radius_of_max_wind_km(intensity, abs(lat))

    # --- shear displacement --------------------------------------------
    # Vertical shear tilts the vortex and pushes deep convection downshear.
    # This is why a sheared storm shows an exposed low-level centre with the
    # cold cloud offset - the single most common misread in manual Dvorak.
    shear_rad = np.deg2rad(shear_dir_deg)
    disp_km = np.clip(shear_kt - 8.0, 0.0, None) * 4.5 * (1.0 - 0.55 * frac)
    dxs = dx - disp_km * np.cos(shear_rad)
    dys = dy - disp_km * np.sin(shear_rad)
    rs = np.hypot(dxs, dys)

    # --- central dense overcast ----------------------------------------
    # Cloud shield radius and coldness both grow with intensity.
    cdo_radius = 130.0 + 210.0 * frac
    # Cloud-top temperature in deep tropical convection is set by the tropopause,
    # not by storm intensity: even a depression carries tops near -70 C. What
    # intensity actually changes is how *organised* and how *extensive* that cold
    # cloud is, and whether an eye clears. Scaling absolute temperature with
    # intensity would be physically wrong and would make the BD bands - which
    # only begin at -30 C - meaningless for weak systems.
    coldest_k = KELVIN - (68.0 + 14.0 * frac)             # -68 C .. -82 C
    shield = np.exp(-(rs / cdo_radius) ** 2.1)

    # --- spiral banding -------------------------------------------------
    # Logarithmic spiral. Northern Hemisphere circulation is counter-clockwise,
    # so the winding sign flips with hemisphere. A horizontal flip of a NH storm
    # produces a SH storm, which is why augmentation must not flip blindly.
    hemi = 1.0 if lat >= 0 else -1.0
    n_arms = 2
    pitch = 0.16 + 0.10 * (1.0 - frac)                     # tighter when stronger
    phase = rng.uniform(0, 2 * np.pi)
    spiral = np.cos(n_arms * (theta * hemi - np.log(np.maximum(rs, 8.0)) / pitch) + phase)
    band_env = np.exp(-((rs - rmw * 2.6) / (150.0 + 90.0 * frac)) ** 2)
    banding = 0.5 * (spiral + 1.0) * band_env * (0.30 + 0.45 * frac)

    # --- eyewall and eye ------------------------------------------------
    # An eye only clears once the storm is organised; below ~64 kt (VSCS) it is
    # a central dense overcast with no warm centre.
    eyewall = np.exp(-((rs - rmw) / (rmw * 0.42)) ** 2) * (0.35 + 0.65 * frac)
    eye_strength = float(np.clip((intensity - 60.0) / 55.0, 0.0, 1.0))
    eye = np.exp(-(rs / (rmw * 0.72)) ** 3.0) * eye_strength

    cloud = np.clip(shield * 0.85 + banding + eyewall * 0.55, 0.0, 1.6)
    cloud = np.clip(cloud - eye * 1.25, 0.0, None)         # warm, cloud-free eye

    texture = rng.normal(0.0, 0.045, cloud.shape) * np.clip(cloud, 0.05, 1.0)
    cloud = np.clip(cloud + texture, 0.0, 1.6)

    sst_bg = 300.0 - 0.12 * np.clip(abs(lat) - 10.0, 0, None)
    tir = sst_bg - (sst_bg - coldest_k) * np.clip(cloud, 0.0, 1.0)

    # Water vapour senses the mid-upper troposphere: less contrast, colder
    # background, and it shows the dry slot a shear-affected storm develops.
    wv_bg = 250.0
    dry_slot = np.exp(-((rs - cdo_radius * 1.3) / 190.0) ** 2) * \
        np.clip((shear_kt - 12.0) / 25.0, 0, 1) * \
        (0.5 * (np.cos(theta - shear_rad + np.pi) + 1.0))
    wv = wv_bg - (wv_bg - coldest_k - 8.0) * np.clip(cloud * 0.82, 0, 1) + dry_slot * 9.0

    return {
        "tir1_k": tir.astype(np.float32),
        "wv_k": wv.astype(np.float32),
        "rmw_km": np.float32(rmw),
        "centre_px": np.array([cx, cy], dtype=np.float32),
        "synthetic": True,
    }


def render_wind_field(wind_kt: float, lat: float, rmw_km: float,
                      size: int = 64, patch_km: float = PATCH_KM,
                      seed: int | None = None,
                      swath_fraction: float = 0.55) -> dict[str, np.ndarray]:
    """
    Render a scatterometer-like 10 m wind field on the storm grid.

    Modelled as a modified Rankine vortex, the standard idealisation for a
    tropical cyclone wind profile. The partial swath is the important part: a
    polar-orbiting scatterometer sees a strip, not a disc, so the validity mask
    is mostly zero. Training against full discs would teach the wind branch to
    expect data it will never get.
    """
    rng = np.random.default_rng(seed)
    km_per_px = patch_km / size
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx = (xx - size / 2.0) * km_per_px
    dy = (yy - size / 2.0) * km_per_px
    r = np.maximum(np.hypot(dx, dy), 1.0)

    # Modified Rankine: solid-body rotation inside the RMW, r^-x decay outside.
    vmax = wind_kt * 0.5144                                # kt -> m/s
    x_exp = 0.55
    v = np.where(r <= rmw_km, vmax * (r / rmw_km), vmax * (rmw_km / r) ** x_exp)

    # Cyclonic (counter-clockwise in NH) with ~20 deg inflow across the isobars.
    hemi = 1.0 if lat >= 0 else -1.0
    theta = np.arctan2(dy, dx)
    inflow = np.deg2rad(20.0)
    u = -v * np.sin(theta * hemi + inflow) * hemi
    vv = v * np.cos(theta * hemi + inflow)

    u += rng.normal(0, 0.8, u.shape)
    vv += rng.normal(0, 0.8, vv.shape)

    # Swath: an oblique strip covering part of the scene.
    ang = rng.uniform(0, np.pi)
    off = rng.uniform(-0.3, 0.3) * size * km_per_px
    d_perp = np.abs(dx * np.cos(ang) + dy * np.sin(ang) - off)
    mask = (d_perp < swath_fraction * patch_km / 2.0).astype(np.float32)

    # Ku/C-band retrievals degrade in heavy rain at high wind - the exact regime
    # where infrared is most confident. That complementarity is the physical
    # argument for fusing them, so the failure mode is modelled rather than
    # assumed away.
    rain_flag = (r < rmw_km * 1.4) & (wind_kt > 75)
    mask[rain_flag] = 0.0

    # Two distinct things, kept separate on purpose:
    #
    #   u10/v10   the ANALYSED wind field over the whole storm. A cyclone has a
    #             circulation everywhere, so this is what a forecaster reasons
    #             about and what the flow visualisation should show.
    #   *_obs     the same field masked to what a scatterometer actually SAW on
    #             this pass. That is a narrow swath with rain-flagged gaps.
    #
    # Conflating them made the console render motion only inside a diagonal
    # band, which is physically honest about the observation but reads as a
    # broken renderer. The model consumes the observed field; the display shows
    # the analysed one and labels it as analysed.
    return {
        "u10": u.astype(np.float32),
        "v10": vv.astype(np.float32),
        "u10_obs": (u * mask).astype(np.float32),
        "v10_obs": (vv * mask).astype(np.float32),
        "mask": mask.astype(np.float32),
        "mask_obs": mask.astype(np.float32),
        "coverage": float(mask.mean()),
        "synthetic": True,
    }
