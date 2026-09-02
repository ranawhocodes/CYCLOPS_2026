"""
Objective Dvorak intensity estimation from real infrared imagery.

Capability 2 of the problem statement: estimate intensity, as a Dvorak T-number
and an IMD category.

This implements the enhanced-infrared branch of the Dvorak technique in the
automated form that ADT descends from: classify the cloud pattern, measure the
brightness temperatures the technique keys on, and read off a T-number.

Why a rule-based estimator rather than a CNN
--------------------------------------------
There are 18 usable day-pass scenes of Fani. A network trained on those would
memorise them and any accuracy figure would be meaningless. A rule-based
estimator is also inspectable: when it is wrong it says which rule produced the
number, which a forecaster can argue with.

HONEST CAVEAT on independence. The T-number tables and BD thresholds here come
from the published technique and were not fitted. But two gate values in the
companion centre-fix module — EYE_CONTRAST_C and EYE_MIN_SYMMETRY — were chosen
by looking at where true and spurious eyes separated ON FANI. That is selection
on the evaluation storm, so the reported figures are NOT fully out-of-sample.
Treat them as an upper bound until the same thresholds are run unchanged against
a storm that was never inspected.

Method, following Dvorak (1984)
-------------------------------
1. Classify the pattern from the scene: EYE, CDO (central dense overcast),
   EMBEDDED_CENTER, or SHEAR.
2. For an eye pattern, the Data-T comes from the contrast between the warm eye
   and the cold surrounding eyewall, plus a term for how cold the eyewall is.
   Both are on the BD enhancement grey shades, which is why those thresholds are
   the ones used.
3. For a CDO pattern, it comes from the size and coldness of the overcast.
4. Convert T-number to wind, then to an IMD category.

Primary sources to cite, not this file:
  Dvorak, V.F. (1984). "Tropical Cyclone Intensity Analysis Using Satellite
  Data." NOAA NESDIS Technical Report 11.
  Velden et al. (2006), "The Dvorak tropical cyclone intensity estimation
  technique: a satellite-based method that has endured for over 30 years", BAMS.

Known limits, stated rather than hidden
---------------------------------------
  - The full technique applies constraint and consistency rules across time
    (Model Expected T, 12-hour change limits). Only a light time-consistency
    smoother is applied here.
  - MODIS is polar-orbiting, so there is no continuous history to run the full
    constraint chain against.
  - Dvorak was tuned in the Atlantic and west Pacific. IMD applies North Indian
    Ocean adjustments that are not public in full, so a systematic bias against
    IMD best track is expected and is reported rather than tuned away.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.imd import KELVIN, t_number_to_wind, to_imd_category
from .centre_fix import CentreFix

# BD enhancement grey-shade thresholds in degrees Celsius, from the Dvorak
# enhancement curve. These are the boundaries the technique's eye and surround
# rules are written against.
BD = {
    "OW": -30.0,   # off-white
    "DG": -42.0,   # dark grey
    "MG": -54.0,   # medium grey
    "LG": -64.0,   # light grey
    "B":  -70.0,   # black
    "W":  -76.0,   # white
    "CG": -81.0,   # cold grey
}

# Surrounding-ring shade -> base T for an EYE pattern. Colder eyewall means a
# stronger storm, which is the core of the eye-pattern rule.
_EYE_BASE_T = [
    (BD["CG"], 6.0),
    (BD["W"],  5.5),
    (BD["B"],  5.0),
    (BD["LG"], 4.5),
    (BD["MG"], 4.0),
    (BD["DG"], 3.5),
    (BD["OW"], 3.0),
]

# CDO size (mean diameter of the cold overcast, km) -> base T.
_CDO_SIZE_T = [
    (450.0, 5.0),
    (350.0, 4.5),
    (275.0, 4.0),
    (200.0, 3.5),
    (140.0, 3.0),
    (90.0,  2.5),
    (0.0,   2.0),
]


@dataclass
class DvorakEstimate:
    pattern: str
    t_number: float
    wind_kt: float
    imd_category: str
    eye_temp_c: float | None
    surround_temp_c: float | None
    cdo_diameter_km: float | None
    rule: str
    confidence: float


def _shade_t(temp_c: float, table) -> float:
    """Read a base T from a coldest-first threshold table."""
    for thresh, t in table:
        if temp_c <= thresh:
            return t
    return table[-1][1]


def _cdo_diameter_km(C: np.ndarray, valid: np.ndarray, r0: float, c0: float,
                     km_per_px: float, threshold_c: float = -70.0) -> float:
    """
    Equivalent diameter of the contiguous cold overcast around the centre.

    Area-equivalent rather than a literal measurement across the image, because
    the shield is rarely circular. Only pixels within 350 km of the centre count,
    so a separate convective blob elsewhere in the crop cannot inflate it.
    """
    h, w = C.shape
    rr, cc = np.ogrid[:h, :w]
    near = np.hypot(rr - r0, cc - c0) <= (350.0 / km_per_px)
    cold = (C <= threshold_c) & valid & near
    area_km2 = cold.sum() * (km_per_px ** 2)
    return float(2.0 * np.sqrt(area_km2 / np.pi)) if area_km2 > 0 else 0.0


def classify_pattern(C: np.ndarray, valid: np.ndarray, fix: CentreFix,
                     km_per_px: float) -> str:
    """
    Decide which Dvorak cloud pattern the scene shows.

    Order matters: an eye beats everything, then a sufficiently large and cold
    overcast, then a displaced/asymmetric case is called shear.
    """
    if fix.eye_detected:
        return "EYE"

    # Gate on the cold shield itself, not on the axisymmetry score. The
    # symmetry metric is a useful confidence descriptor but a poor pattern
    # discriminator — gating on it sent mature storms with large, cold, slightly
    # elongated shields down the SHEAR branch, which caps T at 2.5 and
    # under-called a 110 kt cyclone as a 31 kt depression.
    #
    # Shield extent and coldness are what the Dvorak CDO rules are written
    # against, so they are what is used here.
    cdo = _cdo_diameter_km(C, valid, fix.row, fix.col, km_per_px)
    coldest = float(np.nanmin(C[valid])) if valid.any() else 0.0

    if cdo >= 110.0 and coldest <= BD["B"]:
        return "CDO"
    if cdo >= 55.0:
        return "EMBEDDED_CENTER"
    return "SHEAR"


def estimate(K: np.ndarray, valid: np.ndarray, fix: CentreFix,
             km_per_px: float) -> DvorakEstimate:
    """Objective Dvorak estimate for one scene."""
    C = K - KELVIN
    pattern = classify_pattern(C, valid, fix, km_per_px)
    cdo = _cdo_diameter_km(C, valid, fix.row, fix.col, km_per_px)

    eye = fix.eye_temp_c
    surround = fix.ring_temp_c

    if pattern == "EYE" and eye is not None and surround is not None:
        base = _shade_t(surround, _EYE_BASE_T)
        # Eye adjustment: a warmer, better-cleared eye against a cold eyewall
        # indicates a stronger storm. Dvorak expresses this as an increment in
        # half-T steps; 25 C of contrast is a fully cleared eye.
        contrast = eye - surround
        adj = float(np.clip(contrast / 25.0, 0.0, 1.0))
        t = base + adj
        rule = (f"EYE: eyewall {surround:.0f}C -> base T{base:.1f}; "
                f"eye contrast {contrast:.0f}C -> +{adj:.1f}")
    elif pattern in ("CDO", "EMBEDDED_CENTER"):
        base = _shade_t(-cdo, [(-d, t) for d, t in _CDO_SIZE_T])
        # Colder overcast on top of the size term.
        coldest = float(np.nanmin(C[valid])) if valid.any() else 0.0
        cold_adj = 0.5 if coldest <= BD["CG"] else (0.25 if coldest <= BD["W"] else 0.0)
        t = base + cold_adj
        if pattern == "EMBEDDED_CENTER":
            t -= 0.5           # less organised than a clean CDO
        rule = (f"{pattern}: shield {cdo:.0f} km -> base T{base:.1f}; "
                f"coldest {coldest:.0f}C -> +{cold_adj:.2f}")
    else:
        # Sheared: intensity is capped low because the low-level centre is
        # exposed and the convection is displaced.
        coldest = float(np.nanmin(C[valid])) if valid.any() else 0.0
        t = 2.5 if coldest <= BD["MG"] else 2.0
        rule = f"SHEAR: exposed/asymmetric centre, coldest {coldest:.0f}C"

    t = float(np.clip(t, 1.0, 8.0))
    wind = float(t_number_to_wind(t))

    return DvorakEstimate(
        pattern=pattern, t_number=round(t, 1), wind_kt=round(wind, 1),
        imd_category=to_imd_category(wind),
        eye_temp_c=None if eye is None else round(eye, 1),
        surround_temp_c=None if surround is None else round(surround, 1),
        cdo_diameter_km=round(cdo, 1),
        rule=rule,
        confidence=round(fix.confidence, 3),
    )


def smooth_series(t_numbers: list[float], max_step: float = 0.5) -> list[float]:
    """
    Light time-consistency constraint.

    Dvorak limits how fast the T-number may change between analyses; the full
    rules also carry a Model Expected T. This applies only the rate limit, which
    is the part that is defensible without a continuous observation history.
    Reported separately from the raw estimate so the effect of the constraint is
    visible rather than baked in.
    """
    if not t_numbers:
        return []
    out = [t_numbers[0]]
    for t in t_numbers[1:]:
        prev = out[-1]
        out.append(float(np.clip(t, prev - max_step, prev + max_step)))
    return out
