"""
The uncertainty cone.

NHC convention: the cone radius at lead time t is the radius of a circle
enclosing two-thirds of historical forecast errors at t. We compute it from our
own validation errors, which is the correct and honest thing to do. Saying that
definition out loud in the demo takes one sentence and almost no student team
can - which is exactly why it is worth doing.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

from ..config import CONE_PERCENTILE

GEOD = Geod(ellps="WGS84")


def calibrate(errors_by_lead: dict[int, np.ndarray],
              percentile: int = CONE_PERCENTILE) -> dict[int, float]:
    """Cone radius per lead time, from validation great-circle errors."""
    radii = {}
    for lead, err in errors_by_lead.items():
        e = np.asarray(err, float)
        e = e[np.isfinite(e)]
        radii[int(lead)] = float(np.percentile(e, percentile)) if len(e) else float("nan")
    return radii


def verify_coverage(radii: dict[int, float],
                    errors_by_lead: dict[int, np.ndarray]) -> dict[int, float]:
    """
    Fraction of held-out truth positions falling inside the cone.

    Should land near 0.67. If it comes out at 0.90 the cone is too wide and is
    hiding real skill; at 0.40 it is too narrow and overstates confidence.
    Report the measured number either way.
    """
    out = {}
    for lead, r in radii.items():
        e = np.asarray(errors_by_lead.get(lead, []), float)
        e = e[np.isfinite(e)]
        out[int(lead)] = float((e <= r).mean()) if len(e) else float("nan")
    return out


def cone_polygon(points: list[dict], radii: dict[int, float],
                 n_vertices: int = 48) -> list[list[float]]:
    """
    Union of geodesic circles along the forecast track, as a [lon, lat] ring for
    deck.gl. Circles are generated geodesically so the cone keeps its true shape
    at all latitudes rather than being stretched by a flat-earth approximation.
    """
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError:
        return []

    circles = []
    for p in points:
        r = radii.get(int(p["lead_h"]))
        if not r or not np.isfinite(r):
            continue
        az = np.linspace(0, 360, n_vertices, endpoint=False)
        lons, lats, _ = GEOD.fwd(np.full(n_vertices, p["lon"]),
                                 np.full(n_vertices, p["lat"]),
                                 az, np.full(n_vertices, r * 1000.0))
        circles.append(Polygon(zip(lons, lats)))

    if not circles:
        return []
    merged = unary_union(circles)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    return [[round(x, 4), round(y, 4)] for x, y in merged.exterior.coords]
