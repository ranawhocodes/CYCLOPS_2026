"""
★ SHARED BY TRAINING AND SERVING ★

This module is imported by the training pipeline and by the API. It is never
reimplemented on either side.

If the API normalises differently from training - a different brightness-
temperature range, a different channel order, a different resample radius - the
model receives inputs it has never seen and returns confident nonsense. There is
no exception, no error log, no crash. Just wrong numbers, delivered fluently.

`tests/test_preprocess_parity.py` pins a golden sample through both paths and
fails the build if they ever diverge.
"""
from __future__ import annotations

import numpy as np

from .config import BT_MAX, BT_MIN, IR_SIZE, WIND_SIZE
from .domain.imd import bd_enhance

# Environmental features consumed by the fusion trunk, in this exact order.
# The order is part of the model contract: permuting it silently destroys the
# predictions without changing a tensor shape.
ENV_FEATURE_NAMES = [
    "lat", "lon_sin", "lon_cos",
    "sst_c", "shear_kt", "steer_u_kt", "steer_v_kt",
    "trans_speed_kt", "bearing_sin", "bearing_cos",
    "dwind_6h_kt", "dwind_24h_kt",
    "doy_sin", "doy_cos",
    "hours_since_wind", "wind_coverage",
]
ENV_DIM = len(ENV_FEATURE_NAMES)


def normalise_bt(bt_kelvin: np.ndarray) -> np.ndarray:
    """
    Scale brightness temperature to [0, 1] with COLD MAPPED HIGH.

    Cold-high is deliberate: deep convection is the signal, and having the
    signal live at high activations matches how the pretrained backbone expects
    bright regions to carry information. It also makes the Grad-CAM overlay read
    the way a forecaster expects.
    """
    x = (np.asarray(bt_kelvin, dtype=np.float32) - BT_MIN) / (BT_MAX - BT_MIN)
    return np.clip(1.0 - x, 0.0, 1.0).astype(np.float32)


def build_ir_tensor(tir1_k: np.ndarray, wv_k: np.ndarray) -> np.ndarray:
    """
    Assemble the 3-channel IR input: [TIR-1, WV, BD-enhanced].

    The third channel is the Dvorak BD enhancement of the thermal infrared. It
    is redundant in an information-theoretic sense - it is a function of channel
    0 - but it hands the network the same quantised edge structure a human
    analyst reads off an enhanced image, instead of making it rediscover those
    thresholds from scratch. Cheap, physically motivated, and it ablates.
    """
    if tir1_k.shape != (IR_SIZE, IR_SIZE):
        raise ValueError(f"TIR-1 must be {IR_SIZE}x{IR_SIZE}, got {tir1_k.shape}")
    if wv_k.shape != (IR_SIZE, IR_SIZE):
        raise ValueError(f"WV must be {IR_SIZE}x{IR_SIZE}, got {wv_k.shape}")
    return np.stack([
        normalise_bt(tir1_k),
        normalise_bt(wv_k),
        bd_enhance(tir1_k),
    ]).astype(np.float32)


def build_wind_tensor(u10: np.ndarray, v10: np.ndarray,
                      mask: np.ndarray) -> np.ndarray:
    """
    Assemble the 3-channel wind input: [u10, v10, validity mask].

    Winds are scaled by 40 m/s, comfortably above any scatterometer retrieval,
    so the branch sees values in roughly [-1, 1] without a data-dependent
    normaliser that could drift between training and serving.
    """
    for a, n in ((u10, "u10"), (v10, "v10"), (mask, "mask")):
        if a.shape != (WIND_SIZE, WIND_SIZE):
            raise ValueError(f"{n} must be {WIND_SIZE}x{WIND_SIZE}, got {a.shape}")
    return np.stack([
        np.clip(u10 / 40.0, -1.5, 1.5),
        np.clip(v10 / 40.0, -1.5, 1.5),
        mask,
    ]).astype(np.float32)


def build_env_vector(env: dict) -> np.ndarray:
    """
    Assemble the environmental feature vector in ENV_FEATURE_NAMES order.

    Longitude enters as sin/cos rather than degrees so the basin does not get an
    artificial discontinuity, and so the model cannot learn "large longitude
    number implies Bay of Bengal" as a shortcut.
    """
    lon = float(env.get("lon", 0.0))
    lon_rad = np.deg2rad(lon)
    vals = {
        "lat": float(env.get("lat", 0.0)) / 30.0,
        "lon_sin": float(np.sin(lon_rad)),
        "lon_cos": float(np.cos(lon_rad)),
        "sst_c": (float(env.get("sst_c", 28.0)) - 28.0) / 3.0,
        "shear_kt": float(env.get("shear_kt", 12.0)) / 30.0,
        "steer_u_kt": float(env.get("steer_u_kt", 0.0)) / 25.0,
        "steer_v_kt": float(env.get("steer_v_kt", 0.0)) / 25.0,
        "trans_speed_kt": float(env.get("trans_speed_kt", 8.0)) / 20.0,
        "bearing_sin": float(env.get("bearing_sin", 0.0)),
        "bearing_cos": float(env.get("bearing_cos", 0.0)),
        "dwind_6h_kt": float(env.get("dwind_6h_kt", 0.0)) / 20.0,
        "dwind_24h_kt": float(env.get("dwind_24h_kt", 0.0)) / 40.0,
        "doy_sin": float(env.get("doy_sin", 0.0)),
        "doy_cos": float(env.get("doy_cos", 0.0)),
        # Age of the scatterometer pass, so the model can discount stale wind
        # rather than trusting a 6-hour-old field as if it were coincident.
        "hours_since_wind": float(env.get("hours_since_wind", 6.0)) / 6.0,
        "wind_coverage": float(env.get("wind_coverage", 0.0)),
    }
    out = np.array([vals[k] for k in ENV_FEATURE_NAMES], dtype=np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def preprocess_sample(tir1_k, wv_k, u10, v10, wind_mask, env) -> dict:
    """One call producing every tensor the model needs. Used by training and API alike."""
    has_wind = wind_mask is not None and float(np.asarray(wind_mask).mean()) > 0.02
    if has_wind:
        wind = build_wind_tensor(u10, v10, wind_mask)
    else:
        wind = np.zeros((3, WIND_SIZE, WIND_SIZE), dtype=np.float32)
    return {
        "ir": build_ir_tensor(tir1_k, wv_k),
        "wind": wind,
        "wind_present": np.float32(1.0 if has_wind else 0.0),
        "env": build_env_vector(env),
    }
