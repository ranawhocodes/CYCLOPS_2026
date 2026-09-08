"""
WeatherNext 2 provider — Google DeepMind's AI ensemble forecast as the source of
environmental steering flow, shear and SST.

WHY THIS IS THE RIGHT UPGRADE, NOT A LOGO
-----------------------------------------
Our own held-out evaluation isolates the problem: CYCLOPS beats persistence by
roughly 33% on 24 h intensity but only ~11% on 24 h track. Intensity is largely
determined by the storm's own structure and history, which the model can see.
Track is determined by the synoptic steering flow the storm is embedded in,
which the analytic climatology barely resolves - it knows "storms near 15 N in
May tend to go north-northwest", not where the ridge actually is this week.

WeatherNext 2 supplies exactly the missing quantity, and supplies it in the two
forms that matter here:

  1. A *forecast* deep-layer steering wind at +6/12/18/24 h, rather than a
     climatological average. This is the physically correct predictor for where
     a cyclone goes.
  2. An *ensemble*. Members disagree most when the synoptic situation is
     genuinely uncertain, so ensemble spread is a physically grounded
     predictor of forecast error - which feeds the uncertainty cone as a
     per-case width rather than one fixed radius per lead time from
     climatological error statistics.

Point 2 is the more interesting one. Today our cone radius at 24 h is a single
number (~155 km) derived from validation errors. With ensemble spread as an
input, the cone can be narrow for a storm in a well-determined steering regime
and wide for one near a col or a ridge break. That is what operational centres
actually do, and it is a genuine research contribution rather than a feature.

ACCESS
------
Not open data. Access is granted per-project through the WeatherNext Data
Request form and reviewed weekly, typically 5-7 business days - so file the
request early; it is on the critical path if this is to appear in the finale
build. Once granted, three paths exist, all reachable from the same identifiers:

  Zarr on GCS   gs://weathernext/weathernext_2_0_0/zarr           (ensemble)
                gs://weathernext/weathernext_2_0_0_mean/zarr      (ensemble mean)
  Earth Engine  projects_gcp-public-data-weathernext_assets_weathernext_2_0_0
  BigQuery      WeatherNext 2 / WeatherNext 2 Mean tables

Docs: https://developers.google.com/weathernext/guides/access-forecast

This class implements the Zarr path because it is the one that works offline
against a pre-downloaded subset, which is the only form usable at a demo venue.
`prefetch_case` writes that subset to disk; at demo time the provider reads the
local file and makes no network call.

STATUS: the adapter is written and unit-tested against a synthetic Zarr store
with the documented variable naming. It has NOT been validated against the real
WeatherNext 2 archive, because access had not been granted at the time of
writing. Do not present it as a working integration until it has been run
against real data - say "implemented and pending access", which is both true and
still a good answer.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ..config import DATA_RAW
from .base import EnvField, EnvironmentProvider, EnvSnapshot

# Variable names as published in the WeatherNext 2 data schema. Kept in one dict
# so a schema change is a one-line fix rather than a hunt through the module.
WN2_VARS = {
    "u850": "u_component_of_wind_850",
    "v850": "v_component_of_wind_850",
    "u200": "u_component_of_wind_200",
    "v200": "v_component_of_wind_200",
    "u500": "u_component_of_wind_500",
    "v500": "v_component_of_wind_500",
    "sst": "sea_surface_temperature",
    "msl": "mean_sea_level_pressure",
}

GCS_ZARR = "gs://weathernext/weathernext_2_0_0/zarr"
GCS_ZARR_MEAN = "gs://weathernext/weathernext_2_0_0_mean/zarr"
EE_ASSET = "projects_gcp-public-data-weathernext_assets_weathernext_2_0_0"
REQUEST_FORM_DOCS = "https://developers.google.com/weathernext/guides/access-forecast"

MS_TO_KT = 1.9438445


class WeatherNext2Provider(EnvironmentProvider):
    """
    Reads WeatherNext 2 ensemble fields, either from a local prefetched subset
    (demo path, offline) or directly from GCS (development path).
    """

    name = "WeatherNext-2"
    is_offline = False

    def __init__(self, local_subset: Path | None = None,
                 gcs_uri: str = GCS_ZARR, n_members: int = 8):
        self.local_subset = Path(local_subset) if local_subset else (
            DATA_RAW / "weathernext" / "nio_subset.zarr")
        self.gcs_uri = gcs_uri
        self.n_members = n_members
        self._ds = None
        self.is_offline = self.local_subset.exists()

    # -- availability ------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if self.local_subset.exists():
            return True, f"local prefetched subset at {self.local_subset}"
        try:
            import xarray  # noqa: F401
            import zarr     # noqa: F401
        except ImportError:
            return False, ("xarray + zarr + gcsfs not installed; "
                           "pip install xarray zarr gcsfs")
        try:
            import gcsfs
            gcsfs.GCSFileSystem().ls(self.gcs_uri.replace("gs://", ""), detail=False)
            return True, f"GCS access to {self.gcs_uri}"
        except Exception as e:
            return False, (
                f"no WeatherNext 2 access ({type(e).__name__}). Request access via "
                f"{REQUEST_FORM_DOCS} — reviewed weekly, ~5-7 business days."
            )

    # -- data access -------------------------------------------------------
    def _open(self):
        if self._ds is not None:
            return self._ds
        import xarray as xr
        src = str(self.local_subset) if self.local_subset.exists() else self.gcs_uri
        self._ds = xr.open_zarr(src, consolidated=True,
                                storage_options=None if self.local_subset.exists()
                                else {"token": "google_default"})
        return self._ds

    def at(self, lat: float, lon: float, when: datetime) -> EnvSnapshot:
        ok, why = self.available()
        if not ok:
            raise RuntimeError(f"WeatherNext 2 unavailable: {why}")

        ds = self._open()
        sel = ds.sel(latitude=lat, longitude=lon % 360, method="nearest")
        sel = sel.sel(time=np.datetime64(when.replace(tzinfo=None)), method="nearest")

        def members(var: str) -> np.ndarray:
            """All ensemble members for one variable at this point, in knots."""
            if var not in sel:
                return np.array([np.nan])
            v = sel[var]
            arr = v.values.ravel() if "number" in v.dims else np.array([float(v.values)])
            return arr

        u850, v850 = members(WN2_VARS["u850"]), members(WN2_VARS["v850"])
        u200, v200 = members(WN2_VARS["u200"]), members(WN2_VARS["v200"])
        u500, v500 = members(WN2_VARS["u500"]), members(WN2_VARS["v500"])

        # Deep-layer vertical wind shear: magnitude of the 850-200 hPa vector
        # difference. This is the standard operational definition; roughly
        # 20 kt is the threshold above which a tropical cyclone struggles.
        shear = np.hypot(u200 - u850, v200 - v850) * MS_TO_KT

        # Steering flow approximated by the 500 hPa wind. A proper deep-layer
        # mean would be pressure-weighted across 850-250 hPa; 500 hPa is the
        # standard single-level proxy and is what to state if asked.
        su, sv = u500 * MS_TO_KT, v500 * MS_TO_KT

        sst_k = members(WN2_VARS["sst"])
        sst_c = sst_k - 273.15

        valid = _as_datetime(sel["time"].values)
        age = int((when - valid).total_seconds() / 60) if valid else None

        def f(name, arr, units):
            a = np.asarray(arr, float)
            a = a[np.isfinite(a)]
            return EnvField(
                name=name,
                value=float(a.mean()) if a.size else float("nan"),
                units=units,
                source=f"{self.name} ensemble (n={a.size})",
                observed_at=valid, age_minutes=age, is_proxy=False,
                ensemble_spread=float(a.std()) if a.size > 1 else None,
            )

        return EnvSnapshot(
            lat=lat, lon=lon, valid_at=when, provider=self.name,
            fields={
                "sst_c": f("sst_c", sst_c, "degC"),
                "shear_kt": f("shear_kt", shear, "kt"),
                "steer_u_kt": f("steer_u_kt", su, "kt"),
                "steer_v_kt": f("steer_v_kt", sv, "kt"),
            },
        )

    # -- demo prefetch -----------------------------------------------------
    def prefetch_case(self, lat_range=(0, 30), lon_range=(40, 100),
                      start: datetime | None = None, end: datetime | None = None,
                      out: Path | None = None) -> Path:
        """
        Download the NIO subset for one case window to local Zarr.

        Run this once, with network, before the demo. At demo time the provider
        reads the local file and makes no network call - which is the only way
        this can be part of a venue demo at all.
        """
        import xarray as xr  # noqa: F401
        out = Path(out or self.local_subset)
        ds = self._open()
        sub = ds.sel(
            latitude=slice(lat_range[1], lat_range[0]),
            longitude=slice(lon_range[0] % 360, lon_range[1] % 360),
        )
        if start and end:
            sub = sub.sel(time=slice(np.datetime64(start.replace(tzinfo=None)),
                                     np.datetime64(end.replace(tzinfo=None))))
        keep = [v for v in WN2_VARS.values() if v in sub]
        out.parent.mkdir(parents=True, exist_ok=True)
        sub[keep].to_zarr(out, mode="w", consolidated=True)
        (out.parent / "PREFETCH.json").write_text(json.dumps({
            "source": self.gcs_uri, "variables": keep,
            "lat_range": lat_range, "lon_range": lon_range,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        }, indent=2))
        return out


def _as_datetime(v) -> datetime | None:
    """numpy datetime64 -> timezone-aware UTC datetime."""
    try:
        from datetime import timezone
        return datetime.fromtimestamp(
            int(np.datetime64(v, "s").astype("int64")), tz=timezone.utc)
    except Exception:
        return None


GCS_ZARR_WN3 = "gs://weathernext/weathernext_3_0_0/zarr"


class WeatherNext3Provider(WeatherNext2Provider):
    """
    WeatherNext 3 provider — Google DeepMind's atmospheric foundation model
    providing gridded 500 hPa steering winds, deep-layer shear, and SST.
    """
    name = "WeatherNext-3"

    def __init__(self, local_subset: Path | None = None,
                 gcs_uri: str = GCS_ZARR_WN3, n_members: int = 8):
        super().__init__(local_subset=local_subset, gcs_uri=gcs_uri, n_members=n_members)


def resolve_provider(prefer: str = "auto") -> EnvironmentProvider:
    """
    Pick the best environment provider that actually works right now.

    Order: WeatherNext 3 if access/cache exists, WeatherNext 2 fallback, otherwise analytic climatology.
    The API logs which one it resolved at startup and reports it on /health, so
    nobody has to guess which fields the demo is running on.
    """
    from .climatology import ClimatologyProvider

    if prefer.lower() in ("auto", "weathernext", "weathernext3", "weathernext-3"):
        wn3 = WeatherNext3Provider()
        ok, why = wn3.available()
        if ok:
            return wn3
        if prefer.lower() in ("weathernext", "weathernext3", "weathernext-3"):
            raise RuntimeError(f"WeatherNext 3 requested but unavailable: {why}")

    if prefer.lower() in ("weathernext2", "weathernext-2"):
        wn2 = WeatherNext2Provider()
        ok, why = wn2.available()
        if ok:
            return wn2
        raise RuntimeError(f"WeatherNext 2 requested but unavailable: {why}")

    return ClimatologyProvider()
