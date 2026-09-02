"""
Run identification + objective Dvorak over the real MODIS scenes of any NIO
storm, and score both against IBTrACS best track.

This is the generalisation of the Fani runner, and it exists to answer one
question: do the eye-gate thresholds that were chosen by looking at Fani hold up
on storms that were never inspected?

Nothing in centre_fix.py or dvorak.py is parameterised per storm. The only
per-storm value here is the longitude used to convert a satellite's local
equator-crossing time into UTC, which is a geometric fact about where the storm
is, not a tunable.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import ARTIFACTS
from ..data.features import filter_nio
from ..data.gibs import fetch_scene, overpass_utc
from ..data.ibtracs import load
from ..domain.imd import CATEGORIES, to_imd_category, t_number_to_wind, wind_to_t_number
from ..eval.baselines import GEOD
from .centre_fix import EYE_CONTRAST_C, EYE_MIN_SYMMETRY, RING_ENCLOSURE_C, find_centre
from .dvorak import estimate, smooth_series

PATCH_KM = 1024.0
SIZE = 256

# Day passes only. A night overpass falls on the previous UTC calendar day while
# GIBS dates the granule by local night; reconciling that against a UTC best
# track adds hours of timing ambiguity.
PASSES = ("terra_day", "aqua_day")

CASES = {
    "fani":   ("2019116N02090", "Fani", 2019),
    "amphan": ("2020136N10088", "Amphan", 2020),
    "mocha":  ("2023129N08091", "Mocha", 2023),
}


def _track(sid: str) -> pd.DataFrame:
    f = filter_nio(load())
    f = f[f.sid == sid].sort_values("iso_time").reset_index(drop=True)
    if f.empty:
        raise SystemExit(f"{sid} not found in IBTrACS")
    return f


def _interp(f: pd.DataFrame, when) -> tuple[float, float, float] | None:
    t = f.iso_time.map(lambda x: x.timestamp()).to_numpy()
    x = when.timestamp()
    if x < t[0] or x > t[-1]:
        return None
    return (float(np.interp(x, t, f.lat)),
            float(np.interp(x, t, f.lon)),
            float(np.interp(x, t, f.wind_kt_3min)))


def run_case(sid: str, name: str, season: int, verbose: bool = True) -> dict:
    f = _track(sid)
    # Local solar time depends on where the storm is, so the UTC overpass time
    # is computed from this storm's own longitude rather than a constant.
    ref_lon = float(f.lon.median())
    dates = pd.date_range(f.iso_time.min().normalize(),
                          f.iso_time.max().normalize(), freq="D")

    frames = []
    for d in dates:
        ds = d.strftime("%Y-%m-%d")
        for p in PASSES:
            ov = overpass_utc(p, d.to_pydatetime(), ref_lon)
            truth = _interp(f, ov)
            if truth is None:
                continue
            t_lat, t_lon, t_kt = truth

            prior = f[f.iso_time <= ov]
            if len(prior) < 2:
                continue
            last, prev = prior.iloc[-1], prior.iloc[-2]

            dt_prev = (last.iso_time - prev.iso_time).total_seconds()
            dt_fwd = (ov - last.iso_time).total_seconds()
            if dt_prev > 0:
                rate = min(dt_fwd / dt_prev, 3.0)
                g_lat = float(last.lat + (last.lat - prev.lat) * rate)
                g_lon = float(last.lon + (last.lon - prev.lon) * rate)
            else:
                g_lat, g_lon = float(last.lat), float(last.lon)

            sc = fetch_scene(g_lat, g_lon, ds, pass_name=p,
                             patch_km=PATCH_KM, size=SIZE)
            if sc is None:
                continue

            fix = find_centre(sc.kelvin, sc.valid, sc.bbox, sc.km_per_px,
                              first_guess_rc=(SIZE / 2, SIZE / 2),
                              search_radius_km=120.0)
            est = estimate(sc.kelvin, sc.valid, fix, sc.km_per_px)

            _, _, err_m = GEOD.inv(fix.lon, fix.lat, t_lon, t_lat)
            _, _, base_m = GEOD.inv(g_lon, g_lat, t_lon, t_lat)
            _, _, lastfix_m = GEOD.inv(float(last.lon), float(last.lat), t_lon, t_lat)

            frames.append({
                "date": ds, "pass": p, "observed_at": ov.isoformat(),
                "first_guess": {"lat": round(g_lat, 3), "lon": round(g_lon, 3)},
                "truth": {"lat": round(t_lat, 3), "lon": round(t_lon, 3),
                          "wind_kt": round(t_kt, 1),
                          "imd_category": to_imd_category(t_kt),
                          "t_number": round(float(wind_to_t_number(t_kt)), 1)},
                "fix": {"lat": round(fix.lat, 3), "lon": round(fix.lon, 3),
                        "detected": bool(fix.detected), "refined": bool(fix.refined),
                        "confidence": round(fix.confidence, 3),
                        "symmetry": round(fix.symmetry, 3),
                        "eye_detected": bool(fix.eye_detected),
                        "eye_temp_c": fix.eye_temp_c, "ring_temp_c": fix.ring_temp_c,
                        "cold_fraction": round(fix.cold_fraction, 4),
                        "reason": fix.reason},
                "dvorak": {"pattern": est.pattern, "t_number": est.t_number,
                           "wind_kt": est.wind_kt, "imd_category": est.imd_category,
                           "cdo_diameter_km": est.cdo_diameter_km, "rule": est.rule},
                "centre_error_km": round(err_m / 1000.0, 1),
                "first_guess_error_km": round(base_m / 1000.0, 1),
                "last_fix_error_km": round(lastfix_m / 1000.0, 1),
                "scene": {"coverage": round(sc.coverage, 3),
                          "min_c": round(sc.min_c, 1),
                          "bbox": [round(v, 4) for v in sc.bbox]},
            })
            if verbose:
                print(f"  {ds} {p:10s} fix={err_m/1000:6.1f}km "
                      f"guess={base_m/1000:6.1f}km "
                      f"{'REF' if fix.refined else 'held'} sym={fix.symmetry:.2f} "
                      f"{est.pattern:16s} T{est.t_number:.1f} -> "
                      f"{est.wind_kt:5.1f}kt vs {t_kt:5.1f}kt", flush=True)

    if not frames:
        raise SystemExit(f"no frames analysed for {name}")

    frames.sort(key=lambda x: x["observed_at"])
    sm_t = smooth_series([fr["dvorak"]["t_number"] for fr in frames], max_step=0.5)
    for fr, t in zip(frames, sm_t):
        w = float(t_number_to_wind(t))
        fr["dvorak"]["t_number_smoothed"] = round(float(t), 1)
        fr["dvorak"]["wind_kt_smoothed"] = round(w, 1)
        fr["dvorak"]["imd_category_smoothed"] = to_imd_category(w)

    err = np.array([fr["centre_error_km"] for fr in frames])
    base = np.array([fr["first_guess_error_km"] for fr in frames])
    lastfix = np.array([fr["last_fix_error_km"] for fr in frames])
    det = np.array([fr["fix"]["detected"] for fr in frames])

    tw = np.array([fr["truth"]["wind_kt"] for fr in frames])
    pw = np.array([fr["dvorak"]["wind_kt"] for fr in frames])
    sw = np.array([fr["dvorak"]["wind_kt_smoothed"] for fr in frames])
    ti = np.array([CATEGORIES.index(fr["truth"]["imd_category"])
                   if fr["truth"]["imd_category"] in CATEGORIES else 0 for fr in frames])
    pi = np.array([CATEGORIES.index(fr["dvorak"]["imd_category_smoothed"])
                   if fr["dvorak"]["imd_category_smoothed"] in CATEGORIES else 0
                   for fr in frames])

    # Eye scenes are scored separately: the centre-fixer only claims to refine
    # when it finds an eye, so lumping held frames in hides what it actually did.
    eye = np.array([fr["fix"]["refined"] for fr in frames])

    summary = {
        "storm": name, "sid": sid, "season": season,
        "thresholds_used": {
            "EYE_CONTRAST_C": EYE_CONTRAST_C,
            "RING_ENCLOSURE_C": RING_ENCLOSURE_C,
            "EYE_MIN_SYMMETRY": EYE_MIN_SYMMETRY,
            "note": "chosen on Fani; unchanged for every storm",
        },
        "data": {
            "imagery": "REAL - NASA GIBS, MODIS Terra/Aqua Band 31 (11 um)",
            "labels": "REAL - IBTrACS v04r01 NEWDELHI_WIND (3-min sustained, IMD)",
            "n_scenes": len(frames), "ref_lon": round(ref_lon, 2),
        },
        "identification": {
            "detection_rate": round(float(det.mean()), 3),
            "centre_error_km": {"mean": round(float(err.mean()), 1),
                                "median": round(float(np.median(err)), 1),
                                "p90": round(float(np.percentile(err, 90)), 1),
                                "max": round(float(err.max()), 1)},
            "first_guess_error_km": {"mean": round(float(base.mean()), 1),
                                     "median": round(float(np.median(base)), 1)},
            "last_fix_error_km": {"mean": round(float(lastfix.mean()), 1)},
            "skill_vs_first_guess": round(float(1 - err.mean() / base.mean()), 3),
            "skill_vs_last_fix": round(float(1 - err.mean() / lastfix.mean()), 3),
            "frames_refined": int(eye.sum()),
            "eye_detected_frames": int(sum(fr["fix"]["eye_detected"] for fr in frames)),
            "eye_scenes_only": ({
                "n": int(eye.sum()),
                "fix_mean_km": round(float(err[eye].mean()), 1),
                "first_guess_mean_km": round(float(base[eye].mean()), 1),
                "skill": round(float(1 - err[eye].mean() / base[eye].mean()), 3),
            } if eye.any() else None),
        },
        "classification": {
            "method": "Objective Dvorak (enhanced IR)",
            "raw": {"rmse_kt": round(float(np.sqrt(((pw - tw) ** 2).mean())), 2),
                    "mae_kt": round(float(np.abs(pw - tw).mean()), 2),
                    "bias_kt": round(float((pw - tw).mean()), 2)},
            "time_constrained": {
                "rmse_kt": round(float(np.sqrt(((sw - tw) ** 2).mean())), 2),
                "mae_kt": round(float(np.abs(sw - tw).mean()), 2),
                "bias_kt": round(float((sw - tw).mean()), 2)},
            "category_exact": round(float((ti == pi).mean()), 3),
            "category_within_one": round(float((np.abs(ti - pi) <= 1).mean()), 3),
            "patterns": {p: int(sum(1 for fr in frames if fr["dvorak"]["pattern"] == p))
                         for p in {fr["dvorak"]["pattern"] for fr in frames}},
        },
    }

    key = name.lower()
    (ARTIFACTS / f"{key}_frames.json").write_text(json.dumps(frames, indent=2))
    (ARTIFACTS / f"{key}_analysis.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(which: list[str] | None = None) -> dict:
    out = {}
    for key in (which or list(CASES)):
        sid, name, season = CASES[key]
        print(f"\n=== {name} {season} ({sid}) ===", flush=True)
        out[key] = run_case(sid, name, season)
    return out


if __name__ == "__main__":
    import sys
    res = main(sys.argv[1:] or None)
    print("\n" + "=" * 78)
    print(json.dumps(res, indent=2))
