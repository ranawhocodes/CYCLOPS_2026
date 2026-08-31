"""
★ PROTECTIVE TEST ★

Consecutive frames of the same cyclone are near-duplicates. Split by frame and
the same storm lands in train and test, the model recalls rather than
generalises, and every reported number is fiction. This is the single most
common fatal mistake in this problem domain and the first thing a domain judge
probes.

This test fails the build if any storm ID ever spans two splits.
"""
import pytest

from cyclops.data.features import build_track_features, filter_nio
from cyclops.data.ibtracs import load
from cyclops.data.splits import assert_disjoint, split_by_season, split_by_storm


@pytest.fixture(scope="module")
def fixes():
    return filter_nio(load())


def test_season_split_has_no_shared_storms(fixes):
    splits = split_by_season(fixes)
    assert_disjoint(splits)

    sids = {k: set(v.sid) for k, v in splits.items()}
    assert not (sids["train"] & sids["test"]), "train/test storm leak"
    assert not (sids["train"] & sids["val"]), "train/val storm leak"
    assert not (sids["val"] & sids["test"]), "val/test storm leak"


def test_season_split_has_no_shared_seasons(fixes):
    """Storms in one season share a large-scale environment; leaking a season
    leaks context even when no individual storm is shared."""
    splits = split_by_season(fixes)
    seasons = {k: set(v.season.astype(int)) for k, v in splits.items()}
    assert not (seasons["train"] & seasons["test"])
    assert not (seasons["val"] & seasons["test"])


def test_storm_split_has_no_shared_storms(fixes):
    assert_disjoint(split_by_storm(fixes))


def test_every_split_is_non_empty_and_has_intense_storms(fixes):
    """A test set with no VSCS+ storms cannot support any claim about them."""
    splits = split_by_season(fixes)
    for name, d in splits.items():
        assert len(d) > 0, f"{name} split is empty"
    assert (splits["test"].wind_kt_3min >= 64).sum() > 20, \
        "test set has too few VSCS+ samples to support per-category claims"


def test_detects_a_deliberate_leak(fixes):
    """The guard must actually fire — a test that cannot fail protects nothing."""
    splits = split_by_season(fixes)
    leaked = splits["test"].iloc[[0]]
    splits["train"] = __import__("pandas").concat([splits["train"], leaked])
    with pytest.raises(AssertionError, match="leak"):
        assert_disjoint(splits)
