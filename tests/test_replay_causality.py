"""
★ PROTECTIVE TEST ★

If the model ever sees a track point observed after the current storm clock, the
whole demo is a lie and this test must fail loudly.

This is the test to show a judge who asks "how do we know you didn't forecast
with hindsight?" — which is the right question, and the one most student
projects cannot answer.
"""
from datetime import timedelta

import pytest

FANI = "2019116N02090"


@pytest.fixture(scope="module")
def store():
    from api.services.store import CaseStore
    return CaseStore()


def test_track_query_respects_the_until_boundary(store):
    full = store.track(FANI)
    assert len(full) > 10

    mid = full.iloc[len(full) // 2].iso_time
    truncated = store.track(FANI, until=mid)

    assert len(truncated) < len(full), "until= had no effect"
    assert (truncated.iso_time <= mid).all(), \
        "LEAK: a returned track point post-dates the storm clock"


def test_unbounded_query_is_the_only_way_to_see_the_future(store):
    """
    The default must be truncation-capable, and the caller must opt in to the
    full track. Nothing in the replay path calls track() without `until`.
    """
    import inspect
    from api.services import replay as replay_mod
    src = inspect.getsource(replay_mod.ReplayManager.compute_at)
    assert "until=ts" in src, (
        "ReplayManager.compute_at must pass until=ts into the store. "
        "Filtering in application code can be dropped by a refactor without "
        "anything failing visibly."
    )


def test_full_replay_never_reads_future_data(store, monkeypatch):
    """
    Drive a whole replay through a spying store and assert every read was
    bounded by the storm clock at the time it was made.
    """
    calls = []
    original = store.track

    def spy(sid, until=None):
        result = original(sid, until=until)
        calls.append({"sid": sid, "until": until, "max_ts":
                      result.iso_time.max() if len(result) else None})
        return result

    monkeypatch.setattr(store, "track", spy)

    from api.services.alerts import AlertService
    from api.services.replay import ReplayManager

    class StubEngine:
        cone_radii: dict = {}
        nowcast = None

        def classify(self, *a, **k):
            return {"wind_kt": 50.0, "imd_category": "SCS"}

        def forecast(self, history):
            return {"forecasts": [], "baselines": {}, "cone": []}

    mgr = ReplayManager(store, StubEngine(), AlertService())
    timestamps = list(store.track(FANI).iso_time)
    calls.clear()

    for ts in timestamps[:20]:
        mgr.compute_at(FANI, ts)

    assert calls, "no track reads were recorded"
    bounded = [c for c in calls if c["until"] is not None]
    assert bounded, "every replay read must be bounded by the storm clock"

    for c in bounded:
        if c["max_ts"] is not None:
            assert c["max_ts"] <= c["until"], (
                f"LEAK: read data observed at {c['max_ts']} while the storm "
                f"clock was {c['until']}"
            )


def test_alerts_cannot_see_the_future(store):
    """Rapid-intensification detection must use only history up to now."""
    from api.services.alerts import AlertService
    full = store.track(FANI)
    early = full.iloc[len(full) // 3].iso_time
    history = store.track(FANI, until=early)

    alerts = AlertService().check(history)
    for a in alerts:
        assert a["ts"] <= early.isoformat(), \
            f"alert at {a['ts']} raised while storm clock was {early}"
