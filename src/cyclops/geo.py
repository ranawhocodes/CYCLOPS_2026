"""
Geographic helpers for placing storm-centred rasters on the map.

The model works on a square, storm-centred grid measured in kilometres. The map
works in degrees. This module is the single place that conversion happens, so
the console and the API cannot disagree about where a frame belongs.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

from .config import PATCH_KM

GEOD = Geod(ellps="WGS84")


def patch_corners(lat: float, lon: float, patch_km: float = PATCH_KM
                  ) -> list[list[float]]:
    """
    Corner coordinates of a storm-centred square patch, for a MapLibre image
    source: [top-left, top-right, bottom-right, bottom-left] as [lon, lat].

    Corners are stepped geodesically from the centre rather than by dividing by
    a fixed km-per-degree, so the patch keeps its true ground extent at every
    latitude in the basin. The render itself is on a local tangent grid, so
    draping it as a quad is an approximation - acceptable at 1024 km near the
    equator, and worth stating rather than hiding.
    """
    half = patch_km * 1000.0 / 2.0
    # North and south edges.
    _, lat_n, _ = GEOD.fwd(lon, lat, 0.0, half)
    _, lat_s, _ = GEOD.fwd(lon, lat, 180.0, half)
    # East and west edges, measured at the centre latitude.
    lon_e, _, _ = GEOD.fwd(lon, lat, 90.0, half)
    lon_w, _, _ = GEOD.fwd(lon, lat, 270.0, half)

    return [
        [round(lon_w, 5), round(lat_n, 5)],   # top-left
        [round(lon_e, 5), round(lat_n, 5)],   # top-right
        [round(lon_e, 5), round(lat_s, 5)],   # bottom-right
        [round(lon_w, 5), round(lat_s, 5)],   # bottom-left
    ]


def patch_bbox(lat: float, lon: float, patch_km: float = PATCH_KM
               ) -> dict[str, float]:
    """Axis-aligned bounds of the same patch, for fitBounds and clipping."""
    c = patch_corners(lat, lon, patch_km)
    lons = [p[0] for p in c]
    lats = [p[1] for p in c]
    return {"west": min(lons), "east": max(lons),
            "south": min(lats), "north": max(lats)}


def wind_grid_payload(u10: np.ndarray, v10: np.ndarray, mask: np.ndarray,
                      lat: float, lon: float, stride: int = 2,
                      patch_km: float = PATCH_KM,
                      analysed: bool = True,
                      observed_coverage: float | None = None) -> dict:
    """
    Downsample a wind field into a compact JSON grid for the particle layer.

    Sent as flat arrays rounded to one decimal: a 32x32 grid is roughly 8 KB of
    JSON, which streams fine over the replay WebSocket. Anything finer is wasted
    -- the source is a 25 km scatterometer retrieval and the particle layer
    interpolates between nodes anyway.

    `analysed=True` sends the full circulation, which is what the flow layer
    draws: a cyclone has wind everywhere, and masking the display to the
    scatterometer swath made the console look broken rather than honest. The
    observed swath coverage is reported separately in `coverage`, and the
    provenance panel is where the observation-versus-analysis distinction is
    stated.

    `analysed=False` masks to what the instrument actually saw, which is what a
    model input must use.
    """
    u = np.asarray(u10, np.float32)[::stride, ::stride]
    v = np.asarray(v10, np.float32)[::stride, ::stride]
    m = np.asarray(mask, np.float32)[::stride, ::stride] > 0.5
    if analysed:
        # Still drop anything non-finite, but do not clip to the swath.
        m = np.isfinite(u) & np.isfinite(v)

    ny, nx = u.shape
    bbox = patch_bbox(lat, lon, patch_km)
    speed = np.hypot(u, v)

    return {
        "nx": int(nx), "ny": int(ny),
        "bbox": bbox,
        # Row 0 is the NORTH edge, matching image convention, so the console
        # does not have to guess the vertical orientation.
        "u": [None if not ok else round(float(a), 1)
              for a, ok in zip(u.ravel(), m.ravel())],
        "v": [None if not ok else round(float(a), 1)
              for a, ok in zip(v.ravel(), m.ravel())],
        "max_speed_ms": round(float(speed[m].max()) if m.any() else 0.0, 1),
        # What the instrument actually saw. Passed in by the caller, because
        # deriving it from the analysed mask reports a swath on frames that had
        # no pass at all.
        "coverage": round(float(observed_coverage), 3)
                    if observed_coverage is not None
                    else round(float(np.asarray(mask, np.float32)[::stride, ::stride].mean()), 3),
        "field": "analysed" if analysed else "observed",
        "units": "m/s at 10 m",
    }
