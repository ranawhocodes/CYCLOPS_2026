"""
Real-data case studies — Fani (2019), Amphan (2020), Mocha (2023).

Everything served here is measured, not simulated: MODIS Band 31 infrared from
NASA GIBS, and IBTrACS best track on IMD's 3-minute convention. These are the
cases with no synthetic imagery anywhere in the chain, which is why they have
their own endpoints rather than going through the generic replay.

Fani is where the eye-gate thresholds were chosen. Amphan and Mocha were run
with those thresholds unchanged, so their numbers are the out-of-sample test.
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

CASES = ("fani", "amphan", "mocha")
# Fani is the storm the thresholds were selected on; the other two never were.
THRESHOLD_SOURCE = "fani"


def _paths(case: str):
    case = case.lower()
    if case not in CASES:
        raise HTTPException(404, f"unknown case '{case}' (have: {', '.join(CASES)})")
    return (ARTIFACTS / f"{case}_frames.json", ARTIFACTS / f"{case}_analysis.json")

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


@router.get("/cases-real")
async def real_cases():
    """The storms with a real-imagery analysis available, and which is the control."""
    out = []
    for c in CASES:
        _, sp = _paths(c)
        if not sp.exists():
            continue
        d = json.loads(sp.read_text())
        out.append({
            "key": c, "storm": d["storm"], "season": d["season"],
            "n_scenes": d["data"]["n_scenes"],
            "threshold_source": c == THRESHOLD_SOURCE,
            "centre_error_km": d["identification"]["centre_error_km"]["mean"],
            "rmse_kt": d["classification"]["time_constrained"]["rmse_kt"],
            "bias_kt": d["classification"]["time_constrained"]["bias_kt"],
        })
    return out


@router.get("/case/{case}/summary")
async def case_summary(case: str):
    """Headline identification and classification results."""
    return _load(_paths(case)[1])


@router.get("/case/{case}/frames")
async def case_frames(case: str):
    """
    Every analysed scene: best track, centre fix, Dvorak estimate, errors.

    Each frame carries `corners` so the console can drape the imagery in its true
    geographic position rather than guessing an extent.
    """
    frames = _load(_paths(case)[0])
    for i, fr in enumerate(frames):
        fr["index"] = i
        fr["image_url"] = f"/v1/case/{case.lower()}/frame/{i}.png"
        fr["georef_url"] = f"/v1/case/{case.lower()}/frame/{i}.png?georef=1"
        fr["corners"] = patch_corners(fr["first_guess"]["lat"],
                                      fr["first_guess"]["lon"])
    return frames


@router.get("/case/{case}/frame/{idx}.png")
async def case_frame(case: str, idx: int, request: Request, georef: bool = False):
    """One real MODIS scene, BD-enhanced."""
    from PIL import Image

    frames = _load(_paths(case)[0])
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
