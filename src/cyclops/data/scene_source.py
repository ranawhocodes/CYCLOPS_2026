"""
Scene sources — where storm-centred infrared comes from.

The analysis chain (`centre_fix`, `dvorak`, the runners, the console) does not
care which satellite produced a scene, only that it gets brightness temperature
on a storm-centred grid with a validity mask. This module is the seam.

Two implementations:

  GibsSource   NASA GIBS / MODIS. Polar-orbiting: about four looks a day at
               ESTIMATED overpass times. No account needed, works today.

  InsatSource  MOSDAC / INSAT-3D-3DR. Geostationary: a look every 30 minutes at
               PUBLISHED acquisition times. Needs granules on disk, which needs
               a MOSDAC account.

The distinction is not cosmetic. docs/FINDING-eye-detection.md measured that IR
centre-fixing could not beat motion extrapolation, and traced both dominant
error terms to MODIS being polar-orbiting — 4 km sampling and a +/-30 min
*estimated* acquisition time. INSAT removes both, so the source is the variable
that experiment most wants changed.

`resolve_source()` prefers INSAT when granules are present and falls back to
GIBS otherwise, so the pipeline upgrades itself the moment data appears rather
than needing a code change.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..config import PATCH_KM


@dataclass
class Observation:
    """One available look, before the imagery is fetched."""
    time: datetime
    label: str                 # e.g. "aqua_day" or "3RIMG 07:30Z"
    time_is_exact: bool        # False for a MODIS estimated overpass


class SceneSource(ABC):
    """Supplies storm-centred infrared scenes."""

    name: str = "abstract"
    is_real: bool = True
    cadence_note: str = ""
    time_is_exact: bool = True

    @abstractmethod
    def observations(self, start: datetime, end: datetime,
                     ref_lon: float) -> list[Observation]:
        """Looks available in a window, ascending."""

    @abstractmethod
    def scene_at(self, obs: Observation, lat: float, lon: float,
                 patch_km: float = PATCH_KM, size: int = 256):
        """
        Storm-centred scene at one observation, or None if unusable.

        The returned object must expose `kelvin`, `valid`, `bbox`, `km_per_px`,
        `coverage` and `min_c` — the contract the analysis chain consumes.
        """

    def describe(self) -> dict:
        return {"source": self.name, "real": self.is_real,
                "cadence": self.cadence_note, "time_is_exact": self.time_is_exact}


class GibsSource(SceneSource):
    """MODIS Band 31 via NASA GIBS. No account required."""

    name = "NASA GIBS / MODIS Band 31 (11 um)"
    cadence_note = ("polar-orbiting; ~2 usable day passes per day at ESTIMATED "
                    "overpass times (+/-30 min)")
    time_is_exact = False

    # Day passes only. A night overpass falls on the previous UTC calendar day
    # while GIBS dates the granule by local night, which cannot be reconciled
    # cleanly against a UTC best track.
    PASSES = ("terra_day", "aqua_day")

    def observations(self, start, end, ref_lon):
        from .gibs import overpass_utc
        import pandas as pd

        out = []
        for d in pd.date_range(start.date(), end.date(), freq="D"):
            for p in self.PASSES:
                t = overpass_utc(p, d.to_pydatetime(), ref_lon)
                if start <= t <= end:
                    out.append(Observation(t, p, time_is_exact=False))
        return sorted(out, key=lambda o: o.time)

    def scene_at(self, obs, lat, lon, patch_km=PATCH_KM, size=256):
        from .gibs import fetch_scene
        return fetch_scene(lat, lon, obs.time.strftime("%Y-%m-%d"),
                           pass_name=obs.label, patch_km=patch_km, size=size)


class InsatSource(SceneSource):
    """
    INSAT-3D / 3DR L1B granules from the local cache.

    Only sees files already on disk — it never downloads. Fetching is a separate,
    credentialed step (`cyclops.data.insat_cli fetch`), so an analysis run can
    never silently pull tens of gigabytes.
    """

    name = "MOSDAC / INSAT-3DR L1B TIR-1 (10.8 um)"
    cadence_note = ("geostationary; ~30 min full disk plus rapid-scan sectors, "
                    "at PUBLISHED acquisition times")
    time_is_exact = True

    # 3RIMG_02MAY2019_2358_L1B_STD_V01R00.h5
    FNAME = re.compile(r"^(3[DRS]IMG)_(\d{2})([A-Z]{3})(\d{4})_(\d{2})(\d{2})_", re.I)
    MONTHS = {m: i + 1 for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

    def __init__(self, cache: Path | None = None, channel: str = "TIR1",
                 min_gap_minutes: int = 0):
        from .mosdac import CACHE
        self.cache = Path(cache) if cache else CACHE
        self.channel = channel
        self.min_gap_minutes = min_gap_minutes
        self._index: dict[datetime, Path] = {}
        self.reindex()

    def reindex(self) -> int:
        """
        Map acquisition time -> granule path from filenames.

        Filenames are parsed rather than opening every file, because indexing a
        storm window means touching hundreds of ~300 MB granules. The timestamp
        is re-read from the file itself when a scene is actually loaded, so the
        authoritative value is still what gets used.
        """
        self._index.clear()
        if not self.cache.exists():
            return 0
        for p in sorted(self.cache.glob("*.h5")):
            m = self.FNAME.match(p.name)
            if not m:
                continue
            _, dd, mon, yyyy, hh, mm = m.groups()
            mon_i = self.MONTHS.get(mon.upper())
            if not mon_i:
                continue
            try:
                t = datetime(int(yyyy), mon_i, int(dd), int(hh), int(mm),
                             tzinfo=timezone.utc)
            except ValueError:
                continue
            self._index[t] = p
        return len(self._index)

    @property
    def n_granules(self) -> int:
        return len(self._index)

    def observations(self, start, end, ref_lon):
        times = sorted(t for t in self._index if start <= t <= end)
        out, last = [], None
        for t in times:
            # Thin to a minimum spacing so a dense archive does not produce
            # hundreds of near-identical analyses.
            if last is not None and self.min_gap_minutes and \
                    (t - last) < timedelta(minutes=self.min_gap_minutes):
                continue
            out.append(Observation(t, f"{self._index[t].name[:5]} {t:%H:%M}Z",
                                   time_is_exact=True))
            last = t
        return out

    def scene_at(self, obs, lat, lon, patch_km=PATCH_KM, size=256):
        from .insat_reader import InsatFormatError, read_storm_scene
        path = self._index.get(obs.time)
        if path is None:
            return None
        try:
            sc = read_storm_scene(path, lat, lon, self.channel, patch_km, size)
        except (InsatFormatError, OSError):
            return None
        # Same usability floor GIBS applies: below ~20% valid there is not enough
        # scene to centre-fix or classify against.
        return sc if sc.coverage >= 0.20 else None


def resolve_source(prefer: str = "auto", start: datetime | None = None,
                   end: datetime | None = None,
                   min_gap_minutes: int = 180) -> SceneSource:
    """
    Pick the best source that actually has data for the window.

    INSAT when granules covering the window are on disk, GIBS otherwise. The
    pipeline therefore upgrades itself when data appears rather than needing an
    edit, and degrades to a working default when it does not.
    """
    if prefer.lower() in ("gibs", "modis"):
        return GibsSource()

    if prefer.lower() in ("auto", "insat"):
        try:
            src = InsatSource(min_gap_minutes=min_gap_minutes)
        except Exception:
            src = None
        if src is not None and src.n_granules:
            if start and end:
                if src.observations(start, end, 0.0):
                    return src
            else:
                return src
        if prefer.lower() == "insat":
            raise RuntimeError(
                "INSAT requested but no granules cover that window. Fetch them "
                "first:\n  make insat-status\n"
                "  python -m cyclops.data.insat_cli fetch --start ... --end ...")
    return GibsSource()
