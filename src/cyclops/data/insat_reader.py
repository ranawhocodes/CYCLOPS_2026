"""
INSAT-3D / 3DR Level-1B HDF5 reader.

Turns a MOSDAC L1B granule into the same storm-centred brightness-temperature
`Scene` that `gibs.py` produces, so INSAT is a drop-in replacement for MODIS
everywhere downstream — `centre_fix`, `dvorak`, the runners and the console all
consume it unchanged.

FILE LAYOUT
-----------
L1B stores raw detector COUNTS plus a lookup table per calibration, rather than
physical values. Brightness temperature is `IMG_TIR1_TEMP[IMG_TIR1]` — the LUT is
indexed by the count. Reading `IMG_TIR1` directly and treating it as a
temperature would silently produce numbers in the hundreds-to-thousands with no
error raised, so the LUT step is not optional.

    IMG_TIR1              counts, 2-D (GeoY, GeoX), 4 km      + _FillValue attr
    IMG_TIR1_TEMP         LUT: count -> brightness temp (K)
    IMG_TIR1_RADIANCE     LUT: count -> radiance
    Longitude, Latitude   2-D geolocation on the same 4 km grid
    IMG_WV / IMG_WV_TEMP  water vapour, 8 km, Longitude_WV / Latitude_WV
    IMG_VIS / IMG_SWIR    1 km, Longitude_VIS / Latitude_VIS

    attrs: Acquisition_Start_Time / Acquisition_End_Time, "%d-%b-%YT%H:%M:%S"

Dimension names vary by resolution: GeoX/GeoY at 4 km, GeoX1/GeoY1 at 1 km,
GeoX2/GeoY2 at 8 km.

Layout taken from satpy's `insat3d_img_l1b_h5` reader
(https://github.com/pytroll/satpy), which is the maintained reference
implementation for this product.

VALIDATION STATUS
-----------------
Written against that documented layout and tested end-to-end against a synthetic
granule built to match it (`make insat-selftest`). It has NOT yet been run on a
real MOSDAC granule, because downloading one needs an account this project does
not have. `describe()` exists for exactly that moment: point it at the first real
file and it prints the actual structure, so any mismatch is visible immediately
rather than surfacing as wrong temperatures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import PATCH_KM

# Per-channel variable naming. The LUT suffix differs by channel: reflective
# channels carry ALBEDO, emissive ones carry TEMP.
CHANNEL_VARS = {
    "TIR1": ("IMG_TIR1", "IMG_TIR1_TEMP", "", 4000),
    "TIR2": ("IMG_TIR2", "IMG_TIR2_TEMP", "", 4000),
    "MIR":  ("IMG_MIR", "IMG_MIR_TEMP", "", 4000),
    "WV":   ("IMG_WV", "IMG_WV_TEMP", "_WV", 8000),
    "VIS":  ("IMG_VIS", "IMG_VIS_ALBEDO", "_VIS", 1000),
    "SWIR": ("IMG_SWIR", "IMG_SWIR_RADIANCE", "_VIS", 1000),
}

TIME_FMT = "%d-%b-%YT%H:%M:%S"


class InsatFormatError(RuntimeError):
    """The granule does not have the expected L1B structure."""


@dataclass
class InsatScene:
    """
    Storm-centred INSAT scene.

    Mirrors `gibs.Scene` so downstream code does not branch on the source.
    """
    channel: str
    satellite: str
    observed_at: datetime
    bbox: tuple[float, float, float, float]   # west, south, east, north
    kelvin: np.ndarray
    valid: np.ndarray
    centre: tuple[float, float]
    km_per_px: float
    source_file: str

    @property
    def coverage(self) -> float:
        return float(self.valid.mean())

    @property
    def min_c(self) -> float:
        v = self.kelvin[self.valid]
        return float(v.min() - 273.15) if v.size else float("nan")


def _decode_time(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = str(raw).strip().strip("'\"")
    for fmt in (TIME_FMT, "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def describe(path: str | Path) -> dict:
    """
    Print and return the actual structure of a granule.

    Run this on the first real file. If MOSDAC's layout differs from satpy's
    documented one, this shows it immediately instead of letting a wrong
    variable name become wrong temperatures.
    """
    import h5py

    out: dict = {"file": str(path), "datasets": {}, "attrs": {}}
    with h5py.File(path, "r") as f:
        for k, v in f.attrs.items():
            out["attrs"][k] = v.decode() if isinstance(v, bytes) else v

        def visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                out["datasets"][name] = {
                    "shape": tuple(obj.shape), "dtype": str(obj.dtype),
                    "attrs": {k: (v.decode() if isinstance(v, bytes) else
                                  (v.tolist() if hasattr(v, "tolist") else v))
                              for k, v in obj.attrs.items()},
                }
        f.visititems(visit)

    print(f"{path}")
    print(f"  global attrs: {', '.join(sorted(out['attrs'])[:8])}")
    for name, d in sorted(out["datasets"].items()):
        print(f"  {name:24s} {str(d['shape']):18s} {d['dtype']:10s}")
    return out


def read_channel(path: str | Path, channel: str = "TIR1") -> dict:
    """
    Read one channel, applying the count -> physical LUT.

    Returns brightness temperature in kelvin (or albedo for VIS), plus the 2-D
    geolocation and a validity mask.
    """
    import h5py

    channel = channel.upper()
    if channel not in CHANNEL_VARS:
        raise ValueError(f"unknown channel {channel!r}; have {list(CHANNEL_VARS)}")
    var, lut_var, geo_suffix, res_m = CHANNEL_VARS[channel]

    with h5py.File(path, "r") as f:
        missing = [n for n in (var, lut_var) if n not in f]
        if missing:
            raise InsatFormatError(
                f"{Path(path).name} is missing {missing}. Present: "
                f"{sorted(k for k in f)[:12]}. Run describe() on this file — the "
                f"product layout may differ from the documented L1B structure."
            )

        counts_ds = f[var]
        counts = np.asarray(counts_ds)
        # Granules carry a leading singleton time axis; squeeze it so the array
        # is (rows, cols) regardless of product variant.
        counts = np.squeeze(counts)
        lut = np.asarray(f[lut_var]).ravel()

        fill = counts_ds.attrs.get("_FillValue")
        fill = int(np.asarray(fill).ravel()[0]) if fill is not None else None

        lon_name, lat_name = f"Longitude{geo_suffix}", f"Latitude{geo_suffix}"
        if lon_name not in f or lat_name not in f:
            raise InsatFormatError(
                f"{Path(path).name} is missing {lon_name}/{lat_name}")
        lon = np.squeeze(np.asarray(f[lon_name])).astype(np.float64)
        lat = np.squeeze(np.asarray(f[lat_name])).astype(np.float64)

        # Geolocation is often stored as scaled integers.
        for arr, ds in ((lon, f[lon_name]), (lat, f[lat_name])):
            sf = ds.attrs.get("scale_factor")
            if sf is not None:
                arr *= float(np.asarray(sf).ravel()[0])

        sat = str(f.attrs.get("Satellite_Name", b"")).strip("b'\" ") or "INSAT"
        t0 = _decode_time(f.attrs.get("Acquisition_Start_Time"))
        t1 = _decode_time(f.attrs.get("Acquisition_End_Time"))

    if counts.shape != lon.shape or counts.shape != lat.shape:
        raise InsatFormatError(
            f"geolocation shape {lon.shape} does not match {var} {counts.shape}")

    idx = counts.astype(np.int64)
    valid = np.ones(counts.shape, bool)
    if fill is not None:
        valid &= counts != fill
    # A count outside the LUT means the value cannot be calibrated. Clipping
    # would silently invent a temperature, so mark it invalid instead.
    valid &= (idx >= 0) & (idx < lut.size)

    physical = np.full(counts.shape, np.nan, np.float32)
    physical[valid] = lut[idx[valid]]
    valid &= np.isfinite(physical)

    # Geostationary geolocation is filled off-disk with large sentinels.
    valid &= np.isfinite(lon) & np.isfinite(lat)
    valid &= (np.abs(lat) <= 90.0) & (np.abs(lon) <= 180.0)

    return {"values": physical, "valid": valid, "lon": lon, "lat": lat,
            "channel": channel, "satellite": sat, "resolution_m": res_m,
            "start_time": t0, "end_time": t1, "units": "K" if channel != "VIS" else "albedo"}


def storm_crop(field: dict, lat: float, lon: float,
               patch_km: float = PATCH_KM, size: int = 256,
               max_dist_km: float | None = None) -> InsatScene:
    """
    Resample a full-disk field onto a storm-centred square grid.

    Nearest-neighbour via a KD-tree, which is what pyresample's `resample_nearest`
    does internally — done here with scipy so the demo does not need the whole
    geospatial stack. Source pixels further than `max_dist_km` from a target cell
    are left invalid rather than stretched, so the edge of the disk and any data
    gap stay visible as gaps.
    """
    from scipy.spatial import cKDTree

    vals, valid = field["values"], field["valid"]
    slon, slat = field["lon"], field["lat"]
    km_per_px = patch_km / size
    if max_dist_km is None:
        # Half a source pixel diagonal, plus the target cell — beyond this the
        # nearest source pixel is not really covering the target.
        max_dist_km = (field["resolution_m"] / 1000.0) * 0.75 + km_per_px

    # Target grid. Longitude degrees shrink with latitude, so the box is widened
    # by 1/cos(lat) to keep a square ground footprint.
    dlat = patch_km / 110.574
    dlon = patch_km / (111.320 * max(0.2, np.cos(np.deg2rad(lat))))
    west, east = lon - dlon / 2, lon + dlon / 2
    south, north = lat - dlat / 2, lat + dlat / 2

    ty = np.linspace(north, south, size)          # row 0 is the north edge
    tx = np.linspace(west, east, size)
    tlon, tlat = np.meshgrid(tx, ty)

    # Restrict the source to a generous window before building the tree; a full
    # disk is ~8M points and searching all of it per granule is wasteful.
    pad = 2.0
    win = (valid & (slat > south - pad) & (slat < north + pad)
           & (slon > west - pad) & (slon < east + pad))
    if win.sum() < 16:
        return InsatScene(
            channel=field["channel"], satellite=field["satellite"],
            observed_at=field["start_time"] or datetime.now(timezone.utc),
            bbox=(west, south, east, north),
            kelvin=np.full((size, size), np.nan, np.float32),
            valid=np.zeros((size, size), bool),
            centre=(lat, lon), km_per_px=km_per_px, source_file="",
        )

    # Work in local kilometres so the distance cutoff is metric rather than
    # degrees, which would be latitude-dependent.
    lat0 = float(np.deg2rad(lat))
    def to_km(la, lo):
        return np.column_stack([(lo - lon) * 111.320 * np.cos(lat0),
                                (la - lat) * 110.574])

    tree = cKDTree(to_km(slat[win], slon[win]))
    dist, nn = tree.query(to_km(tlat.ravel(), tlon.ravel()), k=1,
                          distance_upper_bound=max_dist_km)

    src_vals = vals[win]
    out = np.full(size * size, np.nan, np.float32)
    ok = np.isfinite(dist) & (nn < src_vals.size)
    out[ok] = src_vals[nn[ok]]

    grid = out.reshape(size, size)
    gvalid = np.isfinite(grid)

    return InsatScene(
        channel=field["channel"], satellite=field["satellite"],
        observed_at=field["start_time"] or datetime.now(timezone.utc),
        bbox=(west, south, east, north),
        kelvin=grid, valid=gvalid, centre=(lat, lon),
        km_per_px=km_per_px, source_file="",
    )


def read_storm_scene(path: str | Path, lat: float, lon: float,
                     channel: str = "TIR1", patch_km: float = PATCH_KM,
                     size: int = 256) -> InsatScene:
    """One call: granule on disk -> storm-centred scene ready for analysis."""
    field = read_channel(path, channel)
    scene = storm_crop(field, lat, lon, patch_km, size)
    scene.source_file = str(path)
    return scene


def _main(argv=None) -> int:
    """
    `python -m cyclops.data.insat_reader describe <file.h5>`
    `python -m cyclops.data.insat_reader read <file.h5> <lat> <lon>`

    `describe` is the first thing to run on a real MOSDAC granule: it prints the
    actual variable layout so any difference from the documented one is visible
    immediately.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="insat_reader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("describe"); d.add_argument("path")
    r = sub.add_parser("read")
    r.add_argument("path"); r.add_argument("lat", type=float); r.add_argument("lon", type=float)
    r.add_argument("--channel", default="TIR1")
    a = ap.parse_args(argv)

    if a.cmd == "describe":
        describe(a.path)
        return 0

    sc = read_storm_scene(a.path, a.lat, a.lon, a.channel)
    print(f"{sc.satellite}  {sc.channel}  {sc.observed_at:%Y-%m-%d %H:%M}Z")
    print(f"  grid       {sc.kelvin.shape}  {sc.km_per_px:.2f} km/px")
    print(f"  coverage   {sc.coverage:.1%}")
    print(f"  coldest    {sc.min_c:.1f} C")
    print(f"  bbox       {tuple(round(v, 3) for v in sc.bbox)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
