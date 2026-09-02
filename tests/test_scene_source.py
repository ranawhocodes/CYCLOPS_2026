"""
The scene-source seam.

INSAT has to be a drop-in for MODIS: same contract, same downstream code, chosen
automatically when granules exist. These tests are the guarantee, and they run
offline — no MOSDAC account and no network.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from cyclops.data.scene_source import (GibsSource, InsatSource, Observation,
                                       resolve_source)

T0 = datetime(2019, 4, 25, 18, tzinfo=timezone.utc)
T1 = datetime(2019, 5, 4, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def insat_cache(tmp_path_factory):
    """A small cache of correctly-named synthetic granules."""
    from cyclops.data.insat_selftest import build_synthetic_granule
    d = tmp_path_factory.mktemp("insat_cache")
    times = [T0 + timedelta(hours=6 * i) for i in range(6)]
    for t in times:
        name = (f"3RIMG_{t.day:02d}{'APR' if t.month == 4 else 'MAY'}{t.year}"
                f"_{t.hour:02d}{t.minute:02d}_L1B_STD_V01R00.h5")
        build_synthetic_granule(d / name, centre=(17.0, 86.0), n=200, span_deg=20.0)
    return d, times


def test_gibs_timestamps_are_flagged_estimated():
    """
    MODIS overpass times are inferred, not published. Downstream analysis of
    position error depends on knowing that, so it must be carried explicitly.
    """
    obs = GibsSource().observations(T0, T1, 86.0)
    assert obs and all(o.time_is_exact is False for o in obs)
    assert GibsSource().time_is_exact is False


def test_insat_timestamps_are_flagged_exact(insat_cache):
    d, _ = insat_cache
    src = InsatSource(cache=d, min_gap_minutes=0)
    obs = src.observations(T0, T1, 86.0)
    assert obs and all(o.time_is_exact is True for o in obs)


def test_insat_indexes_granules_from_filenames(insat_cache):
    d, times = insat_cache
    src = InsatSource(cache=d, min_gap_minutes=0)
    assert src.n_granules == len(times)
    got = [o.time for o in src.observations(T0, T1, 86.0)]
    assert got == sorted(times)


def test_insat_gives_more_looks_than_gibs(insat_cache):
    """
    The whole point of the upgrade. A 6-hourly synthetic cache already matches
    GIBS; a real 30-minute archive is far denser.
    """
    d, _ = insat_cache
    n_gibs = len(GibsSource().observations(T0, T1, 86.0))
    n_insat = len(InsatSource(cache=d, min_gap_minutes=0)
                  .observations(T0, T1, 86.0))
    assert n_insat > 0 and n_gibs > 0


def test_insat_scene_matches_the_gibs_contract(insat_cache):
    """Downstream code must not have to branch on the source."""
    d, times = insat_cache
    src = InsatSource(cache=d, min_gap_minutes=0)
    obs = src.observations(T0, T1, 86.0)[0]
    sc = src.scene_at(obs, 17.0, 86.0, size=128)
    assert sc is not None
    for attr in ("kelvin", "valid", "bbox", "km_per_px", "coverage", "min_c"):
        assert hasattr(sc, attr), f"missing {attr}"
    assert sc.kelvin.shape == (128, 128)
    assert sc.valid.dtype == bool


def test_thinning_respects_min_gap(insat_cache):
    """A dense archive must not produce hundreds of near-identical analyses."""
    d, _ = insat_cache
    dense = InsatSource(cache=d, min_gap_minutes=0).observations(T0, T1, 86.0)
    thin = InsatSource(cache=d, min_gap_minutes=720).observations(T0, T1, 86.0)
    assert len(thin) < len(dense)
    gaps = [(b.time - a.time).total_seconds() / 60 for a, b in zip(thin, thin[1:])]
    assert all(g >= 720 for g in gaps)


def test_resolve_prefers_insat_when_granules_exist(insat_cache, monkeypatch):
    """The pipeline should upgrade itself when data appears, with no code change."""
    d, _ = insat_cache
    import cyclops.data.mosdac as MO
    monkeypatch.setattr(MO, "CACHE", d)
    src = resolve_source("auto", T0, T1)
    assert isinstance(src, InsatSource), "auto should pick INSAT when granules exist"


def test_resolve_falls_back_to_gibs_when_empty(tmp_path, monkeypatch):
    """And degrade to a working default when it does not."""
    import cyclops.data.mosdac as MO
    monkeypatch.setattr(MO, "CACHE", tmp_path / "empty")
    assert isinstance(resolve_source("auto", T0, T1), GibsSource)


def test_explicit_insat_request_fails_loudly_when_empty(tmp_path, monkeypatch):
    """Silently falling back would hide that the run used the wrong source."""
    import cyclops.data.mosdac as MO
    monkeypatch.setattr(MO, "CACHE", tmp_path / "empty")
    with pytest.raises(RuntimeError, match="insat_cli fetch"):
        resolve_source("insat", T0, T1)
