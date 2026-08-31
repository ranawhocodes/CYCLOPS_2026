"""
Domain conventions.

These are the numbers a judge from IMD checks first. Wrong wind convention or a
wrong category boundary undermines everything downstream, so they are pinned.
"""
import numpy as np
import pytest

from cyclops.domain.imd import (ONE_MIN_TO_THREE_MIN, bd_enhance, to_imd_category,
                                usa_1min_to_imd_3min, wind_to_t_number)


@pytest.mark.parametrize("kt,expected", [
    (10, "LOW"), (17, "D"), (27, "D"), (28, "DD"), (33, "DD"),
    (34, "CS"), (47, "CS"), (48, "SCS"), (63, "SCS"),
    (64, "VSCS"), (89, "VSCS"), (90, "ESCS"), (119, "ESCS"), (120, "SuCS"), (165, "SuCS"),
])
def test_imd_category_boundaries(kt, expected):
    assert to_imd_category(kt) == expected


def test_wind_convention_conversion():
    """
    IMD reports 3-minute sustained; JTWC reports 1-minute. Presenting USA_WIND
    against the IMD table overstates every storm by ~12%.
    """
    assert ONE_MIN_TO_THREE_MIN == pytest.approx(0.88)
    assert usa_1min_to_imd_3min(100.0) == pytest.approx(88.0)
    # The trap, made concrete: a storm reported at 130 kt by JTWC (1-min) is
    # 114 kt on IMD's 3-min scale — ESCS, not SuCS. Reading the JTWC number
    # straight off the IMD table promotes it a whole category.
    assert usa_1min_to_imd_3min(130.0) == pytest.approx(114.4)
    assert to_imd_category(usa_1min_to_imd_3min(130.0)) == "ESCS"
    assert to_imd_category(130.0) == "SuCS"


def test_fani_peak_matches_published_imd_intensity():
    """Fani's IMD peak was 115 kt 3-min sustained — ESCS."""
    assert to_imd_category(115) == "ESCS"


def test_t_number_is_monotonic_and_bounded():
    kt = np.arange(20, 160, 5.0)
    t = wind_to_t_number(kt)
    assert np.all(np.diff(t) >= -1e-9), "T-number must not decrease with wind speed"
    assert t.min() >= 1.0 and t.max() <= 8.0


def test_bd_enhancement_is_colder_higher():
    """Colder cloud top must map to a higher BD value."""
    warm = bd_enhance(np.array([[273.15 - 20]], np.float32))
    cold = bd_enhance(np.array([[273.15 - 85]], np.float32))
    assert cold.item() > warm.item()
    assert 0.0 <= warm.item() <= 1.0 and 0.0 <= cold.item() <= 1.0


def test_ibtracs_uses_new_delhi_wind_where_available():
    """The NIO label must come from NEWDELHI_WIND, not USA_WIND, wherever it exists."""
    from cyclops.data.ibtracs import load
    df = load()
    nd = df[df.wind_source.str.contains("NEWDELHI")]
    assert len(nd) > 1000, "NEWDELHI_WIND should supply most NIO labels"
    # Where the label came from USA_WIND, it must have been converted.
    usa = df[df.wind_source.str.contains("USA")]
    assert (usa.wind_source == "IBTrACS:USA(1-min)x0.88").all()
