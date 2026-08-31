"""
Storm-wise data splitting.

This is the single most common fatal mistake in this problem domain. Consecutive
frames of the same cyclone are near-duplicates: split by frame and the same storm
appears in train and test, the model recalls rather than generalises, and the
reported accuracy is fiction. `tests/test_split_integrity.py` fails the build if
any SID ever spans two splits.

Splitting is by storm *and* by season, because storms within a season share the
same large-scale environment and leaking a season leaks environmental context
even when no individual storm is shared.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SEED


def split_by_season(
    fixes: pd.DataFrame,
    val_seasons: tuple[int, ...] = (2018, 2021),
    test_seasons: tuple[int, ...] = (2019, 2020, 2023),
) -> dict[str, pd.DataFrame]:
    """
    Hold out entire seasons. Preferred over a random storm split because it is
    reproducible, defensible in a sentence, and gives a test set that contains
    the well-known storms a judge will ask about.

    Test seasons deliberately include 2019 (Fani, Kyarr, Maha) and 2020 (Amphan)
    so the hero case is genuinely held out and the replay is an honest
    out-of-sample demonstration, not a recital of training data.
    """
    val_seasons, test_seasons = set(val_seasons), set(test_seasons)
    overlap = val_seasons & test_seasons
    if overlap:
        raise ValueError(f"Seasons appear in both val and test: {sorted(overlap)}")

    season = fixes["season"].astype(int)
    out = {
        "train": fixes[~season.isin(val_seasons | test_seasons)].copy(),
        "val": fixes[season.isin(val_seasons)].copy(),
        "test": fixes[season.isin(test_seasons)].copy(),
    }
    for k, v in out.items():
        v["split"] = k
    return out


def split_by_storm(fixes: pd.DataFrame, frac=(0.7, 0.15, 0.15),
                   seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Random split at storm granularity, stratified by peak category."""
    rng = np.random.default_rng(seed)
    peak = fixes.groupby("sid")["wind_kt_3min"].max()
    strata = pd.cut(peak, [0, 33, 63, 89, 999], labels=False)

    assign: dict[str, str] = {}
    for s in strata.dropna().unique():
        sids = strata[strata == s].index.to_numpy()
        rng.shuffle(sids)
        n_tr = int(len(sids) * frac[0])
        n_va = int(len(sids) * (frac[0] + frac[1]))
        for i, sid in enumerate(sids):
            assign[sid] = "train" if i < n_tr else ("val" if i < n_va else "test")

    fixes = fixes.copy()
    fixes["split"] = fixes["sid"].map(assign)
    return {k: fixes[fixes.split == k].copy() for k in ("train", "val", "test")}


def assert_disjoint(splits: dict[str, pd.DataFrame]) -> None:
    """Raise if any storm ID appears in more than one split. Called by the test."""
    sids = {k: set(v["sid"]) for k, v in splits.items()}
    for a in sids:
        for b in sids:
            if a < b and (shared := sids[a] & sids[b]):
                raise AssertionError(
                    f"Storm IDs leak between {a} and {b}: {sorted(shared)[:5]}"
                )


def describe(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Summary table of the split, for the deck and for `make data` output."""
    rows = []
    for name, d in splits.items():
        if d.empty:
            continue
        rows.append({
            "split": name,
            "storms": d.sid.nunique(),
            "fixes": len(d),
            "seasons": f"{int(d.season.min())}-{int(d.season.max())}",
            "peak_kt": round(float(d.wind_kt_3min.max()), 1),
            "VSCS+": int((d.wind_kt_3min >= 64).sum()),
        })
    return pd.DataFrame(rows)
