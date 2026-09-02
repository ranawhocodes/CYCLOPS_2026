"""
INSAT L1B reader, against a synthetic granule built to the documented layout.

This is in the suite because the reader was written from satpy's documented
structure rather than from a real file. If someone changes the LUT handling, the
fill masking or the resampling, these fail immediately — long before a real
granule is available to catch it.
"""
import numpy as np
import pytest

from cyclops.data.insat_selftest import build_synthetic_granule
from cyclops.domain.imd import KELVIN


@pytest.fixture(scope="module")
def granule(tmp_path_factory):
    p = tmp_path_factory.mktemp("insat") / "synthetic_L1B.h5"
    return build_synthetic_granule(p)


def test_lut_is_applied_not_raw_counts(granule):
    """
    The decisive one. L1B stores counts; brightness temperature is LUT[count].
    Reading the counts directly raises no error and yields plausible-looking
    integers, so only a range check catches it.
    """
    from cyclops.data.insat_reader import read_channel
    f = read_channel(granule["path"], "TIR1")
    v = f["values"][f["valid"]]
    assert 150.0 < v.min() and v.max() < 340.0, "values are not kelvin — LUT not applied"


def test_fill_value_is_masked(granule):
    from cyclops.data.insat_reader import read_channel
    f = read_channel(granule["path"], "TIR1")
    assert not f["valid"].all(), "off-disk fill was not masked"
    assert np.isfinite(f["values"][f["valid"]]).all()


def test_storm_crop_geometry(granule):
    from cyclops.data.insat_reader import read_storm_scene
    sc = read_storm_scene(granule["path"], *granule["centre"], size=256)
    assert sc.kelvin.shape == (256, 256)
    assert abs(sc.km_per_px - 4.0) < 0.01
    w, s, e, n = sc.bbox
    assert w < granule["centre"][1] < e and s < granule["centre"][0] < n


def test_eye_and_eyewall_recovered(granule):
    """Round-trip a known structure through counts, LUT and resampling."""
    from cyclops.data.insat_reader import read_storm_scene
    sc = read_storm_scene(granule["path"], *granule["centre"], size=256)
    C = sc.kelvin - KELVIN
    eye = float(np.nanpercentile(C[125:132, 125:132], 90))
    px = int(granule["rmw_km"] / sc.km_per_px)
    ring = float(np.nanmin(C[128, 128 + px - 2: 128 + px + 3]))
    assert abs(eye - granule["eye_temp_c"]) < 8.0
    assert abs(ring - granule["eyewall_temp_c"]) < 8.0
    assert eye > ring + 30, "eye must be much warmer than the eyewall"


def test_insat_scene_is_a_drop_in_for_gibs(granule):
    """
    The point of the reader: downstream code must not branch on the source.
    """
    from cyclops.data.insat_reader import read_storm_scene
    from cyclops.analysis.centre_fix import find_centre
    from cyclops.analysis.dvorak import estimate

    sc = read_storm_scene(granule["path"], *granule["centre"], size=256)
    for attr in ("kelvin", "valid", "bbox", "km_per_px", "coverage", "min_c"):
        assert hasattr(sc, attr), f"InsatScene is missing {attr} that gibs.Scene has"

    fix = find_centre(sc.kelvin, sc.valid, sc.bbox, sc.km_per_px,
                      first_guess_rc=(128, 128))
    est = estimate(sc.kelvin, sc.valid, fix, sc.km_per_px)
    assert fix.eye_detected, "a textbook synthetic eye should be detected"
    assert est.pattern == "EYE"


def test_unknown_structure_raises_a_useful_error(tmp_path):
    """A real granule with a different layout must fail loudly, not silently."""
    import h5py
    from cyclops.data.insat_reader import InsatFormatError, read_channel

    p = tmp_path / "wrong.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("SOMETHING_ELSE", data=np.zeros((4, 4)))
    with pytest.raises(InsatFormatError) as e:
        read_channel(p, "TIR1")
    assert "describe()" in str(e.value), "the error should say how to diagnose it"
