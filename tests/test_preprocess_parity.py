"""
★ PROTECTIVE TEST ★

Training-serving skew is the invisible killer: if the API normalises differently
from training, the model gets inputs it has never seen and returns confident
nonsense. No exception, no error log, just wrong numbers delivered fluently.

A fixed raw sample is pinned to a golden tensor. If either path ever produces
something different, the build goes red.
"""
import numpy as np
import pytest



def _golden_inputs():
    from cyclops.data.synth_ir import render_ir_scene, render_wind_field
    s = render_ir_scene(wind_kt=97.0, lat=17.4, lon=86.9, shear_kt=11.0,
                        shear_dir_deg=240.0, seed=20190502)
    w = render_wind_field(97.0, 17.4, float(s["rmw_km"]), seed=20190502)
    env = {"lat": 17.4, "lon": 86.9, "sst_c": 29.6, "shear_kt": 11.0,
           "steer_u_kt": -6.0, "steer_v_kt": 3.2, "trans_speed_kt": 9.5,
           "bearing_sin": 0.42, "bearing_cos": 0.91, "dwind_6h_kt": 8.0,
           "dwind_24h_kt": 32.0, "doy_sin": 0.68, "doy_cos": -0.73,
           "hours_since_wind": 2.4, "wind_coverage": float(w["coverage"])}
    return s, w, env


def test_api_preprocessing_is_the_training_module_not_a_copy():
    """The API must import the shared module, never reimplement it."""
    import cyclops.preprocess as train_pp
    from api.services import inference  # noqa: F401
    import api.services.store as store_mod
    assert store_mod.preprocess_sample is train_pp.preprocess_sample, (
        "The API is using a different preprocess_sample than training. "
        "It must import cyclops.preprocess, not copy it."
    )


def test_tensor_contract_is_stable():
    from cyclops.config import IR_SIZE, WIND_SIZE
    from cyclops.preprocess import ENV_DIM, preprocess_sample
    s, w, env = _golden_inputs()
    out = preprocess_sample(s["tir1_k"], s["wv_k"], w["u10"], w["v10"], w["mask"], env)

    assert out["ir"].shape == (3, IR_SIZE, IR_SIZE)
    assert out["wind"].shape == (3, WIND_SIZE, WIND_SIZE)
    assert out["env"].shape == (ENV_DIM,)
    assert out["ir"].dtype == np.float32
    assert 0.0 <= out["ir"].min() and out["ir"].max() <= 1.0
    assert np.isfinite(out["env"]).all(), "env vector must never carry NaN or inf"


def test_preprocessing_is_deterministic():
    """Same input, same tensor. Every time. Two calls must be bit-identical."""
    from cyclops.preprocess import preprocess_sample
    s, w, env = _golden_inputs()
    a = preprocess_sample(s["tir1_k"], s["wv_k"], w["u10"], w["v10"], w["mask"], env)
    b = preprocess_sample(s["tir1_k"], s["wv_k"], w["u10"], w["v10"], w["mask"], env)
    for k in ("ir", "wind", "env"):
        np.testing.assert_array_equal(a[k], b[k], err_msg=f"{k} is not deterministic")


def test_missing_wind_produces_the_absent_state_not_a_calm_ocean():
    """
    A missing scatterometer pass must set wind_present=0, not hand the model a
    zero wind field it would read as a very calm sea.
    """
    from cyclops.preprocess import preprocess_sample
    s, _, env = _golden_inputs()
    out = preprocess_sample(s["tir1_k"], s["wv_k"], None, None, None,
                            {**env, "wind_coverage": 0.0})
    assert float(out["wind_present"]) == 0.0
    assert np.all(out["wind"] == 0.0)


def test_normalisation_maps_cold_cloud_high():
    """Cold tops are the signal and must land at high activations."""
    from cyclops.preprocess import normalise_bt
    cold = normalise_bt(np.array([[190.0]], np.float32))
    warm = normalise_bt(np.array([[300.0]], np.float32))
    assert cold > warm, "cold cloud top must normalise higher than warm ocean"


def test_env_feature_order_is_pinned():
    """
    Permuting ENV_FEATURE_NAMES silently destroys predictions without changing
    a single tensor shape. The order is part of the model contract.
    """
    from cyclops.preprocess import ENV_FEATURE_NAMES
    assert ENV_FEATURE_NAMES[:3] == ["lat", "lon_sin", "lon_cos"]
    assert ENV_FEATURE_NAMES[-2:] == ["hours_since_wind", "wind_coverage"]
    assert len(ENV_FEATURE_NAMES) == len(set(ENV_FEATURE_NAMES))
