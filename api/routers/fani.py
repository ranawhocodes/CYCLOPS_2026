"""
Cyclone Fani (2019) — the real-data case study.

Everything served here is measured, not simulated: MODIS Band 31 infrared from
NASA GIBS, and IBTrACS best track on IMD's 3-minute convention. This is the one
case in the system with no synthetic imagery anywhere in the chain, which is why
it has its own endpoints rather than going through the generic replay.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cyclops.config import ARTIFACTS  # noqa: E402
from cyclops.data.gibs import fetch_scene  # noqa: E402
from cyclops.domain.imd import KELVIN  # noqa: E402
from cyclops.geo import patch_corners  # noqa: E402

router = APIRouter(tags=["fani"])

FRAMES = ARTIFACTS / "fani_frames.json"
SUMMARY = ARTIFACTS / "fani_analysis.json"

# Same ramp as the figures: warm sea surface dark, cloud brightening as it cools,
# the coldest overshooting tops breaking into the Dvorak enhancement colours.
_BD_STOPS = [
    (-95.0, (168, 32, 120)),
    (-88.0, (232, 64, 74)),
    (-81.0, (242, 128, 61)),
    (-74.0, (242, 198, 61)),
    (-66.0, (59, 209, 111)),
    (-56.0, (242, 246, 248)),
    (-35.0, (143, 184, 204)),
    (-10.0, (38, 80, 107)),
    (30.0, (4, 9, 15)),
]


def _load(p: Path):
    if not p.exists():
        raise HTTPException(
            503, f"{p.name} not built — run `make fani` to fetch and analyse")
    return json.loads(p.read_text())


def _bd_rgba(C: np.ndarray, valid: np.ndarray, georef: bool) -> np.ndarray:
    """Colour a brightness-temperature field on the BD ramp."""
    xs = np.array([s[0] for s in _BD_STOPS])
    cols = np.array([s[1] for s in _BD_STOPS], dtype=float)
    out = np.zeros((*C.shape, 4), np.uint8)
    for ch in range(3):
        out[..., ch] = np.interp(np.clip(C, xs[0], xs[-1]), xs, cols[:, ch]).astype(np.uint8)

    if georef:
        # Draped on the map, clear air must be transparent so the coastline and
        # track read through; opaque cloud only where there is cloud.
        a = np.clip((-C - 10.0) / 40.0, 0.0, 1.0) ** 0.8
        out[..., 3] = (a * 255).astype(np.uint8)
    else:
        out[..., 3] = 255
    out[~valid] = (10, 20, 28, 0 if georef else 255)
    return out


@router.get("/fani/summary")
async def fani_summary():
    """Headline identification and classification results."""
    return _load(SUMMARY)


@router.get("/fani/frames")
async def fani_frames():
    """
    Every analysed scene: best track, centre fix, Dvorak estimate, errors.

    Each frame carries `corners` so the console can drape the imagery in its true
    geographic position rather than guessing an extent.
    """
    frames = _load(FRAMES)
    for i, fr in enumerate(frames):
        fr["index"] = i
        fr["image_url"] = f"/v1/fani/frame/{i}.png"
        fr["georef_url"] = f"/v1/fani/frame/{i}.png?georef=1"
        fr["corners"] = patch_corners(fr["first_guess"]["lat"],
                                      fr["first_guess"]["lon"])
    return frames


@router.get("/fani/frame/{idx}.png")
async def fani_frame(idx: int, request: Request, georef: bool = False):
    """One real MODIS scene, BD-enhanced."""
    from PIL import Image

    frames = _load(FRAMES)
    if not 0 <= idx < len(frames):
        raise HTTPException(404, f"frame {idx} out of range (0..{len(frames)-1})")
    fr = frames[idx]

    sc = fetch_scene(fr["first_guess"]["lat"], fr["first_guess"]["lon"],
                     fr["date"], fr["pass"], 1024.0, 256)
    if sc is None:
        raise HTTPException(503, "scene unavailable — GIBS cache may be missing")

    rgba = _bd_rgba(sc.kelvin - KELVIN, sc.valid, georef)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, "PNG", optimize=True)
    return Response(
        buf.getvalue(), media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400",
                 "X-Data-Status": "REAL - MODIS Band 31 via NASA GIBS"},
    )
