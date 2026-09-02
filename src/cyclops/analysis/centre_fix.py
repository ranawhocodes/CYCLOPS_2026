"""
Identification and centre-fixing on real infrared imagery.

Capability 1 of the problem statement: decide whether a tropical cyclone is
present in a scene, and locate its centre.

The method is the one automated centre-fixing actually uses, not a learned
shortcut: a mature tropical cyclone is close to axisymmetric about its centre.
So score each candidate centre by how much of the local brightness-temperature
variance is explained by radius alone — sample concentric rings, then take
between-ring variance over total variance — and maximise it.

The normalisation is the part that matters. Scoring on raw azimuthal spread
alone has a degenerate optimum, because any large uniform patch (deep inside the
cloud shield, or open ocean to one side) is flat at every radius and wins on
featurelessness rather than on structure. Asking instead "how much of what
varies here is explained by distance from this point?" is only answered well at
a real centre.

Why this and not a CNN. With one storm there are 35 scenes, which is far too few
to train a detector without it memorising. This estimator has no fitted
parameters at all, so its error against best track is a genuine out-of-sample
measurement rather than a training artefact. It is also the method a forecaster
would recognise and can be argued for on physical grounds.

Reference for the idea: axisymmetry-based centre determination is the basis of
the ARCHER scheme (Wimmers & Velden), and of the centre-fixing step inside ADT.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.imd import KELVIN


@dataclass
class CentreFix:
    """Estimated storm centre and the evidence behind it."""
    lat: float
    lon: float
    row: float                     # pixel coordinates within the scene
    col: float
    symmetry: float                # 0..1, higher is more axisymmetric
    refined: bool                  # False => held the first guess
    detected: bool
    confidence: float              # 0..1
    eye_detected: bool
    eye_temp_c: float | None       # warmest point inside the eye
    ring_temp_c: float | None      # coldest annulus mean (the eyewall)
    cold_fraction: float           # fraction of scene below -70 C
    reason: str


def _pixel_to_lonlat(row: float, col: float, shape: tuple[int, int],
                     bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Scene pixel -> (lat, lon). Row 0 is the north edge."""
    h, w = shape
    west, south, east, north = bbox
    lon = west + (col + 0.5) / w * (east - west)
    lat = north - (row + 0.5) / h * (north - south)
    return lat, lon


def _radial_profile(K: np.ndarray, valid: np.ndarray, r0: int, c0: int,
                    radii_px: np.ndarray, n_az: int = 36):
    """
    Sample brightness temperature on concentric rings about (r0, c0).

    Returns (mean_per_ring, std_per_ring, count_per_ring). Bilinear sampling
    would be smoother, but nearest-neighbour is enough at ~4 km/px and keeps the
    search fast enough to run over a dense candidate grid.
    """
    h, w = K.shape
    az = np.linspace(0, 2 * np.pi, n_az, endpoint=False)
    ca, sa = np.cos(az), np.sin(az)

    means = np.full(len(radii_px), np.nan)
    stds = np.full(len(radii_px), np.nan)
    counts = np.zeros(len(radii_px), int)

    for i, rad in enumerate(radii_px):
        rr = np.rint(r0 + rad * sa).astype(int)
        cc = np.rint(c0 + rad * ca).astype(int)
        ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
        if ok.sum() < n_az * 0.6:      # ring mostly off-scene; unusable
            continue
        rr, cc = rr[ok], cc[ok]
        v = valid[rr, cc]
        if v.sum() < n_az * 0.5:
            continue
        vals = K[rr, cc][v]
        means[i] = vals.mean()
        stds[i] = vals.std()
        counts[i] = vals.size
    return means, stds, counts


# Below this fraction of variance explained, the scene has no organised
# structure to lock onto and the search will happily latch onto an unrelated
# convective cluster. Measured on Fani: well-organised scenes score 0.6-0.8,
# a disorganised depression scores under 0.4.
# Minimum eye-to-eyewall contrast, in Celsius, to call a scene an eye pattern.
# Measured on Fani: a cleared eye runs 25-50 C of contrast; a central dense
# overcast with no eye stays under about 10 C.
EYE_CONTRAST_C = 15.0

# Every azimuth of the eyewall ring must be at least this cold for the feature to
# count as enclosed. -50 C is deep convection; a clear-air gap in the ring means
# it is a cloud edge, not an eye.
RING_ENCLOSURE_C = -50.0

# A candidate eye must also sit at the centre of a radially organised storm.
# Measured on Fani: true eyes score 0.39-0.64, spurious enclosed gaps 0.04-0.29.
EYE_MIN_SYMMETRY = 0.35


def find_centre(K: np.ndarray, valid: np.ndarray,
                bbox: tuple[float, float, float, float],
                km_per_px: float,
                first_guess_rc: tuple[float, float] | None = None,
                search_radius_km: float = 120.0,
                coarse_step_px: int = 3) -> CentreFix:
    """
    Locate the storm centre by maximising axisymmetry of the infrared field.

    Constrained search, which is what makes this operationally honest rather than
    a global blob-finder:

      - The search is centred on `first_guess_rc` (the caller's extrapolated
        position), not on the middle of the crop.
      - It is bounded to `search_radius_km`. A tropical cyclone does not leave a
        120 km neighbourhood of a motion-extrapolated position between passes,
        so anything outside it is a different cloud system.
      - If the scene is not organised enough to lock onto, the first guess is
        returned unchanged and the fix is flagged low confidence. An unconstrained
        search on a disorganised depression is worse than not searching: it will
        confidently move the centre several hundred kilometres onto whichever
        unrelated blob happens to look roundest.

    ADT does the same thing for the same reason — it runs against a forecast
    first-guess position rather than searching the whole scene.
    """
    h, w = K.shape
    C = K - KELVIN

    cold_fraction = float((C[valid] < -70).mean()) if valid.any() else 0.0

    # Radii to score over, in pixels. 30-250 km spans the eyewall and the inner
    # cloud shield without reaching the ragged outer edge of the crop.
    radii_km = np.arange(30, 255, 15)
    radii_px = radii_km / km_per_px

    # ---- locate the eye --------------------------------------------------
    # Automated centre-fixing on infrared is reliable when there is an eye and
    # unreliable when there is not. That is not a limitation of this
    # implementation, it is what the technique can and cannot see: a cleared eye
    # is a sharp, unambiguous feature, whereas a cold cloud shield is roughly
    # axisymmetric about a wide range of points, so any objective evaluated on
    # it has a broad, flat optimum. Refining against a flat optimum moves the
    # centre a long way for no information gain, which measurably degraded a
    # good first guess when tried here.
    #
    # So: snap to the eye when one is present, otherwise hold the first guess
    # and say so. This is the same division ARCHER reports — highest confidence
    # on eye scenes.
    span = int(search_radius_km / km_per_px)
    if first_guess_rc is not None:
        r_c, c_c = int(round(first_guess_rc[0])), int(round(first_guess_rc[1]))
    else:
        r_c, c_c = h // 2, w // 2
    guess_r, guess_c = r_c, c_c

    eye_px = max(2, int(round(28.0 / km_per_px)))    # eye radius to average over
    ring_in = max(eye_px + 1, int(round(35.0 / km_per_px)))
    ring_out = int(round(90.0 / km_per_px))

    rr_g, cc_g = np.ogrid[:h, :w]

    n_az = 24
    _az = np.linspace(0, 2 * np.pi, n_az, endpoint=False)
    _ca, _sa = np.cos(_az), np.sin(_az)

    def eye_contrast(r0: int, c0: int) -> tuple[float, float, float]:
        """
        (contrast, eye_temp_c, eyewall_temp_c) for a candidate eye centre.

        The decisive test is ENCLOSURE, not contrast. A cloud edge trivially has
        a warm side and a cold side, so scoring "warm core against the coldest
        part of the ring" finds every cloud boundary in the scene — which is
        exactly what it did, firing EYE on 22 kt depressions.

        An eye is different: it is surrounded by cold convection at essentially
        every azimuth. So the ring is sampled around the full circle and the
        WARMEST azimuth has to still be cold. A cloud edge fails that
        immediately, because half its azimuths are clear air.
        """
        d = np.hypot(rr_g - r0, cc_g - c0)
        core = (d <= eye_px) & valid
        if core.sum() < 4:
            return -np.inf, np.nan, np.nan

        r_mid = (ring_in + ring_out) / 2.0
        rr = np.rint(r0 + r_mid * _sa).astype(int)
        cc = np.rint(c0 + r_mid * _ca).astype(int)
        ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
        if ok.sum() < n_az:
            return -np.inf, np.nan, np.nan
        vr, vc = rr[ok], cc[ok]
        good = valid[vr, vc]
        if good.sum() < n_az * 0.85:
            return -np.inf, np.nan, np.nan

        ring_vals = C[vr, vc][good]
        warmest_azimuth = float(ring_vals.max())
        if warmest_azimuth > RING_ENCLOSURE_C:
            return -np.inf, np.nan, np.nan      # not enclosed: a cloud edge

        e = float(np.percentile(C[core], 90))
        g = float(np.median(ring_vals))
        return e - g, e, g

    best_contrast, best_rc = -np.inf, (guess_r, guess_c)
    lo_r, hi_r = max(ring_out, guess_r - span), min(h - ring_out, guess_r + span + 1)
    lo_c, hi_c = max(ring_out, guess_c - span), min(w - ring_out, guess_c + span + 1)
    if hi_r > lo_r and hi_c > lo_c:
        for r0 in range(lo_r, hi_r, coarse_step_px):
            for c0 in range(lo_c, hi_c, coarse_step_px):
                ct, _, _ = eye_contrast(r0, c0)
                if ct > best_contrast:
                    best_contrast, best_rc = ct, (r0, c0)
        # one-pixel refinement around the best coarse candidate
        br, bc = best_rc
        for r0 in range(max(ring_out, br - coarse_step_px),
                        min(h - ring_out, br + coarse_step_px + 1)):
            for c0 in range(max(ring_out, bc - coarse_step_px),
                            min(w - ring_out, bc + coarse_step_px + 1)):
                ct, _, _ = eye_contrast(r0, c0)
                if ct > best_contrast:
                    best_contrast, best_rc = ct, (r0, c0)

    def sym_at(r0: int, c0: int) -> float:
        """Fraction of local variance explained by radius about (r0, c0)."""
        means, stds, counts = _radial_profile(K, valid, r0, c0, radii_px)
        ok = counts > 0
        if ok.sum() < len(radii_px) * 0.5:
            return 0.0
        within = float((stds[ok] ** 2).mean())
        between = float(means[ok].var())
        return between / (between + within + 1e-9)

    ct, e_c, g_c = eye_contrast(*best_rc)
    cand_sym = sym_at(*best_rc) if np.isfinite(ct) else 0.0

    # TWO independent conditions, both required.
    #
    # Enclosure alone is not sufficient: a gap in a convective band can be ringed
    # by cold cloud at every azimuth and pass the contrast test while sitting
    # nowhere near the circulation centre. Every bad refinement measured on Fani
    # had that signature — enclosure satisfied, but the surrounding field showed
    # almost no radial organisation (symmetry 0.04-0.29, against 0.39-0.64 for
    # the true eyes).
    #
    # A real eye is both enclosed by cold convection AND at the centre of an
    # axisymmetric storm. Requiring both separates them cleanly.
    eye_found = (np.isfinite(ct) and ct >= EYE_CONTRAST_C
                 and cand_sym >= EYE_MIN_SYMMETRY)

    if eye_found:
        r_best, c_best = best_rc
        refined = True
    else:
        r_best, c_best = guess_r, guess_c
        refined = False

    sym_frac = sym_at(r_best, c_best)

    # ---- eye / eyewall measurement --------------------------------------
    means, stds, counts = _radial_profile(K, valid, r_best, c_best, radii_px)
    eye_temp_c = ring_temp_c = None
    eye_detected = False

    inner_px = int(round(35.0 / km_per_px))
    rr, cc = np.ogrid[:h, :w]
    d_px = np.hypot(rr - r_best, cc - c_best)

    inner = (d_px <= inner_px) & valid
    if inner.sum() > 4:
        # The eye is the warmest part of the core, so a high percentile rather
        # than the mean, which would be dragged down by eyewall pixels.
        eye_temp_c = float(np.percentile(C[inner], 90))
    eye_detected = bool(eye_found)

    ok = counts > 0
    if ok.any():
        # _radial_profile samples K, which is kelvin. eye_temp_c is Celsius.
        # Comparing the two directly made the eye test compare -35 against 189
        # and it could never fire, so every scene fell through to CDO.
        ring_temp_c = float(np.nanmin(means[ok]) - KELVIN)
        # A true eye is a warm centre inside a much colder ring. 8 C is a
        # deliberately conservative floor: below that it is a central dense
        # overcast, not a cleared eye.


    # ---- detection and confidence ---------------------------------------
    # Two independent conditions: enough deep convection to be a real system,
    # and enough axisymmetry to be organised rather than a random cluster.
    symmetry = float(np.clip(sym_frac, 0.0, 1.0)) if np.isfinite(sym_frac) else 0.0
    detected = cold_fraction > 0.02 and symmetry > 0.25
    confidence = float(np.clip(0.5 * symmetry + 0.5 * min(cold_fraction / 0.25, 1.0), 0, 1))

    if not refined:
        reason = (f"no eye pattern (best contrast {ct:.0f}C < {EYE_CONTRAST_C:.0f}C); "
                  f"held the motion-extrapolated first guess")
    elif not detected:
        reason = ("no organised cold cloud mass: "
                  f"cold_fraction={cold_fraction:.3f}, symmetry={symmetry:.2f}")
    elif eye_detected:
        reason = f"eye pattern; eye {eye_temp_c:.1f}C vs eyewall {ring_temp_c:.1f}C"
    else:
        reason = f"central dense overcast; coldest ring {ring_temp_c:.1f}C"

    lat, lon = _pixel_to_lonlat(r_best, c_best, K.shape, bbox)
    return CentreFix(
        lat=lat, lon=lon, row=float(r_best), col=float(c_best),
        symmetry=symmetry, refined=refined, detected=detected,
        confidence=confidence if refined else confidence * 0.5,
        eye_detected=eye_detected, eye_temp_c=eye_temp_c, ring_temp_c=ring_temp_c,
        cold_fraction=cold_fraction, reason=reason,
    )
