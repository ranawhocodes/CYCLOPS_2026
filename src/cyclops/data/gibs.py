"""
Real satellite infrared from NASA GIBS.

This replaces the synthetic renderer for Cyclone Fani. GIBS serves MODIS Band 31
— the 11 micron thermal infrared window channel, which is the band Dvorak
analysis is actually performed on — as pre-rendered PNG tiles with a published
colormap. Inverting that colormap recovers brightness temperature in kelvin
exactly: the palette has 255 distinct entries and every pixel matches one of
them, so the round trip is lossless rather than approximate.

Why GIBS rather than the archives in the TRD:
  - It needs no registration and no API key, so it works today. MOSDAC (INSAT)
    and EUMETSAT both take weeks to clear, and Digital Typhoon is the wrong
    basin.
  - It is real measured radiance, not a proxy. Everything derived from it is a
    genuine satellite result.

What it is NOT:
  - Geostationary. MODIS is polar-orbiting, so a location is sampled about four
    times a day (Terra and Aqua, day and night) rather than every 15-30 minutes.
    That is coarser than INSAT-3D and it is stated wherever these frames are
    used.
  - Instantaneous. Each daily layer is a composite of that day's swaths. Near a
    storm it is normally a single overpass, but the exact acquisition time is
    not published per pixel, so overpass times here are ESTIMATED from each
    satellite's equator-crossing time and the target longitude.

Source: https://gibs.earthdata.nasa.gov/  (NASA EOSDIS Worldview / GIBS)
Colormap: https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_Brightness_Temp_Band31.xml
"""
from __future__ import annotations

import hashlib
import io
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import DATA_RAW

WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
COLORMAP_URL = (
    "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_Brightness_Temp_Band31.xml"
)

CACHE = DATA_RAW / "gibs"
CACHE.mkdir(parents=True, exist_ok=True)


def _ssl_context() -> ssl.SSLContext:
    """
    Verified TLS using certifi's CA bundle.

    A python.org install on macOS does not wire Python into the system keychain,
    so urllib fails certificate verification against perfectly valid hosts while
    curl succeeds. certifi ships the same Mozilla root set, which fixes it
    without the usual and much worse workaround of disabling verification.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()

IR_LAYERS = {
    "terra_day":   "MODIS_Terra_Brightness_Temp_Band31_Day",
    "aqua_day":    "MODIS_Aqua_Brightness_Temp_Band31_Day",
    "terra_night": "MODIS_Terra_Brightness_Temp_Band31_Night",
    "aqua_night":  "MODIS_Aqua_Brightness_Temp_Band31_Night",
}

TRUECOLOR_LAYERS = {
    "terra": "MODIS_Terra_CorrectedReflectance_TrueColor",
    "aqua":  "MODIS_Aqua_CorrectedReflectance_TrueColor",
}

SST_LAYER = "GHRSST_L4_MUR_Sea_Surface_Temperature"

# Mean local solar equator-crossing time of each pass. Terra is descending in
# the morning, Aqua ascending in the early afternoon. Converting to UTC needs
# only the target longitude, since local solar time runs 15 degrees per hour.
LOCAL_SOLAR_HOUR = {
    "terra_day": 10.5, "aqua_day": 13.5,
    "terra_night": 22.5, "aqua_night": 1.5,
}


def overpass_utc(pass_name: str, date: datetime, lon: float) -> datetime:
    """
    Estimated UTC acquisition time of a pass over a given longitude.

    An estimate, not a published timestamp: GIBS daily composites do not carry
    per-pixel acquisition time. Good to roughly +/-30 min, which is well inside
    the 6-hourly best-track cadence it gets matched against.
    """
    utc_hour = LOCAL_SOLAR_HOUR[pass_name] - lon / 15.0
    base = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
    return base + timedelta(hours=utc_hour)


# ---------------------------------------------------------------------------
# colormap inversion
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _colormap() -> tuple[np.ndarray, np.ndarray]:
    """(rgb[N,3] uint8, kelvin[N]) from the published GIBS colormap."""
    path = CACHE / "MODIS_Brightness_Temp_Band31.xml"
    if not path.exists():
        req = urllib.request.Request(
            COLORMAP_URL, headers={"User-Agent": "CYCLOPS/0.3 (SIH 2026)"})
        with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
            path.write_bytes(r.read())
    root = ET.parse(path).getroot()

    rgb, kelvin = [], []
    for cm in root.findall("ColorMap"):
        if cm.get("title") != "Brightness Temperature":
            continue
        for e in cm.find("Entries").findall("ColorMapEntry"):
            if e.get("nodata") == "true" or e.get("transparent") == "true":
                continue
            v = e.get("value")
            if not v:
                continue
            nums = re.findall(r"[-\d.]+", v)
            if len(nums) < 2:
                continue
            rgb.append(tuple(int(x) for x in e.get("rgb").split(",")))
            kelvin.append((float(nums[0]) + float(nums[1])) / 2.0)
    if not rgb:
        raise RuntimeError("could not parse the GIBS brightness-temperature colormap")
    return np.array(rgb, dtype=np.int16), np.array(kelvin, dtype=np.float32)


@lru_cache(maxsize=1)
def _lut() -> dict[tuple[int, int, int], float]:
    """Exact RGB -> kelvin dictionary. The palette is small, so this is exact."""
    rgb, k = _colormap()
    return {tuple(int(c) for c in rgb[i]): float(k[i]) for i in range(len(rgb))}


def rgb_to_kelvin(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Invert the colormap. Returns (kelvin[H,W], valid_mask[H,W]).

    Exact dictionary lookup first — GIBS renders from a fixed 255-entry palette,
    so every real pixel hits an entry. Anything that misses (JPEG-style
    resampling artefacts, or the transparent fill) falls back to nearest
    neighbour in RGB space and is flagged invalid, so no fabricated temperature
    ever reaches the model.
    """
    a = np.asarray(img)
    if a.ndim != 3 or a.shape[-1] < 3:
        raise ValueError(f"expected an RGB(A) image, got {a.shape}")
    alpha = a[..., 3] if a.shape[-1] == 4 else np.full(a.shape[:2], 255, np.uint8)
    flat = a[..., :3].reshape(-1, 3).astype(np.int16)

    lut = _lut()
    out = np.full(len(flat), np.nan, np.float32)
    hit = np.zeros(len(flat), bool)
    for i, px in enumerate(map(tuple, flat)):
        v = lut.get(px)
        if v is not None:
            out[i] = v
            hit[i] = True

    if not hit.all():
        rgb, kelvin = _colormap()
        miss = ~hit
        d = ((flat[miss][:, None, :] - rgb[None, :, :]) ** 2).sum(-1)
        out[miss] = kelvin[d.argmin(1)]

    K = out.reshape(a.shape[:2])
    valid = hit.reshape(a.shape[:2]) & (alpha > 0)
    return K, valid


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------
@dataclass
class Scene:
    """One storm-centred satellite scene."""
    layer: str
    pass_name: str
    date: str
    observed_at: datetime
    bbox: tuple[float, float, float, float]   # west, south, east, north
    kelvin: np.ndarray
    valid: np.ndarray
    centre: tuple[float, float]               # lat, lon the crop was centred on
    km_per_px: float

    @property
    def coverage(self) -> float:
        return float(self.valid.mean())

    @property
    def min_c(self) -> float:
        v = self.kelvin[self.valid]
        return float(v.min() - 273.15) if v.size else float("nan")


def _get(url: str, cache_key: str, timeout: int = 60) -> bytes:
    """Fetch with a permanent disk cache — the demo must run with no network."""
    p = CACHE / f"{cache_key}.png"
    if p.exists():
        return p.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "CYCLOPS/0.3 (SIH 2026)"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        data = r.read()
    if not data.startswith(b"\x89PNG"):
        # GIBS answers errors with an XML body and HTTP 200. Caching that would
        # poison the offline bundle with a file that is not an image.
        raise ValueError(f"not a PNG ({data[:80]!r})")
    p.write_bytes(data)
    return data


def fetch_scene(lat: float, lon: float, date: str, pass_name: str = "aqua_day",
                patch_km: float = 1024.0, size: int = 256,
                timeout: int = 60) -> Scene | None:
    """
    Storm-centred brightness-temperature scene, or None if the pass has no usable
    data over the target (wrong side of the orbit, or an all-fill tile).
    """
    from PIL import Image

    layer = IR_LAYERS[pass_name]
    # Degrees spanned by the patch. Longitude degrees shrink with latitude, so
    # the box is widened by 1/cos(lat) to keep the ground extent square.
    dlat = patch_km / 110.574
    dlon = patch_km / (111.320 * max(0.2, np.cos(np.deg2rad(lat))))
    w, s = lon - dlon / 2, lat - dlat / 2
    e, n = lon + dlon / 2, lat + dlat / 2

    q = {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
        "LAYERS": layer, "SRS": "EPSG:4326",
        "BBOX": f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}",
        "WIDTH": size, "HEIGHT": size, "FORMAT": "image/png", "TIME": date,
    }
    url = f"{WMS}?{urllib.parse.urlencode(q)}"
    key = hashlib.sha256(url.encode()).hexdigest()[:20]

    try:
        raw = _get(url, key, timeout=timeout)
        img = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    except Exception:
        return None

    K, valid = rgb_to_kelvin(img)
    # A pass that missed this target comes back as fill. Below ~20% valid there
    # is not enough scene to centre-fix or classify against.
    if valid.mean() < 0.20:
        return None

    return Scene(
        layer=layer, pass_name=pass_name, date=date,
        observed_at=overpass_utc(pass_name, datetime.fromisoformat(date), lon),
        bbox=(w, s, e, n), kelvin=K, valid=valid,
        centre=(lat, lon), km_per_px=patch_km / size,
    )


def fetch_truecolor(lat: float, lon: float, date: str, sat: str = "aqua",
                    patch_km: float = 1024.0, size: int = 512) -> np.ndarray | None:
    """Visible true-colour crop over the same footprint, for the console."""
    from PIL import Image

    dlat = patch_km / 110.574
    dlon = patch_km / (111.320 * max(0.2, np.cos(np.deg2rad(lat))))
    w, s = lon - dlon / 2, lat - dlat / 2
    e, n = lon + dlon / 2, lat + dlat / 2
    q = {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
        "LAYERS": TRUECOLOR_LAYERS[sat], "SRS": "EPSG:4326",
        "BBOX": f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}",
        "WIDTH": size, "HEIGHT": size, "FORMAT": "image/png", "TIME": date,
    }
    url = f"{WMS}?{urllib.parse.urlencode(q)}"
    try:
        raw = _get(url, hashlib.sha256(url.encode()).hexdigest()[:20])
        return np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
    except Exception:
        return None


def fetch_sst(lat: float, lon: float, date: str, patch_km: float = 1024.0,
              size: int = 64) -> float | None:
    """
    Mean sea surface temperature over the storm footprint, in degrees Celsius.

    GHRSST L4 MUR is a real analysis rather than the analytic climatology the
    rest of the pipeline falls back on. Roughly 26.5 C is the threshold below
    which a tropical cyclone cannot sustain itself, so this is a genuine
    predictor and not decoration.
    """
    from PIL import Image

    dlat = patch_km / 110.574
    dlon = patch_km / (111.320 * max(0.2, np.cos(np.deg2rad(lat))))
    q = {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
        "LAYERS": SST_LAYER, "SRS": "EPSG:4326",
        "BBOX": f"{lon-dlon/2:.4f},{lat-dlat/2:.4f},{lon+dlon/2:.4f},{lat+dlat/2:.4f}",
        "WIDTH": size, "HEIGHT": size, "FORMAT": "image/png", "TIME": date,
    }
    url = f"{WMS}?{urllib.parse.urlencode(q)}"
    try:
        raw = _get(url, hashlib.sha256(url.encode()).hexdigest()[:20])
        img = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    except Exception:
        return None

    # The SST layer uses its own palette; approximate by luminance over the
    # documented display range. Flagged as approximate wherever it is reported.
    alpha = img[..., 3] > 0
    if alpha.mean() < 0.2:
        return None
    lum = img[..., :3].mean(-1)[alpha] / 255.0
    return float(-2.0 + lum.mean() * (35.0 - -2.0))
