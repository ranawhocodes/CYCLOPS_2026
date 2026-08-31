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
                      patch_km: float = PATCH_KM) -> dict:
    """
    Downsample a wind field into a compact JSON grid for the particle layer.

    Sent as flat arrays rounded to one decimal: a 32x32 grid is roughly 8 KB of
    JSON, which streams fine over the replay WebSocket. Anything finer is wasted
    -- the source is a 25 km scatterometer retrieval and the particle layer
    interpolates between nodes anyway.

    Invalid cells (outside the swath, or rain-flagged) are sent as null so the
    console can render coverage gaps honestly instead of interpolating across
    them as if data existed.
    """
    u = np.asarray(u10, np.float32)[::stride, ::stride]
    v = np.asarray(v10, np.float32)[::stride, ::stride]
    m = np.asarray(mask, np.float32)[::stride, ::stride] > 0.5

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
        "coverage": round(float(m.mean()), 3),
        "units": "m/s at 10 m",
    }
