"""
End-to-end demonstration of the INSAT path, using synthetic granules.

There are no real MOSDAC granules on this machine (that needs an account), so
this builds granules with the real L1B layout and the real MOSDAC filename
convention, follows Cyclone Fani's actual IBTrACS track, and runs the full
pipeline over them.

What it proves: the wiring works. `resolve_source` picks INSAT when granules are
present, the reader decodes them, `centre_fix` and `dvorak` consume the scenes
unchanged, and the run reports PUBLISHED timestamps at a 30-minute cadence
instead of two estimated looks a day.

What it does not prove: anything about accuracy. The imagery is synthetic, so
the intensity and centre errors from this run are meaningless as skill numbers
and are labelled as such. Replace the granules with real ones and the same
command produces a real result.

    make insat-demo
"""
from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import numpy as np

from ..config import ARTIFACTS
from .features import filter_nio
from .ibtracs import load

DEMO_CACHE = ARTIFACTS / "insat_demo_cache"
FANI = "2019116N02090"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def build_granules(sid: str = FANI, n_granules: int = 30,
                   cache: Path = DEMO_CACHE) -> list[Path]:
    """
    Write synthetic 3RIMG granules along a storm's real track.

    Each granule is centred on the interpolated best-track position at its own
    acquisition time and rendered at that time's real intensity, so the sequence
    behaves like an actual geostationary series rather than a repeated still.
    """
    from .insat_selftest import build_synthetic_granule

    f = filter_nio(load())
    f = f[f.sid == sid].sort_values("iso_time").reset_index(drop=True)
    if f.empty:
        raise SystemExit(f"{sid} not in IBTrACS")

    t = f.iso_time.map(lambda x: x.timestamp()).to_numpy()
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(parents=True, exist_ok=True)

    # Span the WHOLE storm rather than the first N intervals. Sampling from the
    # start at a fixed cadence stopped at day three and never reached the mature
    # phase, so the demo showed no eye detections and looked like a failure.
    out = []
    t0 = f.iso_time.min().to_pydatetime()
    t1 = f.iso_time.max().to_pydatetime()
    step = (t1 - t0) / max(1, n_granules - 1)
    # Round to whole minutes so filenames carry a clean HHMM.
    step = timedelta(minutes=max(30, round(step.total_seconds() / 60)))
    cur, end = t0, t1
    while cur <= end and len(out) < n_granules:
        x = cur.timestamp()
        lat = float(np.interp(x, t, f.lat))
        lon = float(np.interp(x, t, f.lon))
        kt = float(np.interp(x, t, f.wind_kt_3min))

        # Intensity drives eye clearing and eyewall coldness, so the synthetic
        # series shows a life cycle rather than a constant storm.
        frac = float(np.clip((kt - 20.0) / 100.0, 0.0, 1.0))
        eye_c = -70.0 + 55.0 * frac          # eye clears as the storm matures
        wall_c = -60.0 - 28.0 * frac         # eyewall gets colder

        name = (f"3RIMG_{cur.day:02d}{MONTHS[cur.month-1]}{cur.year}"
                f"_{cur.hour:02d}{cur.minute:02d}_L1B_STD_V01R00.h5")
        build_synthetic_granule(cache / name, centre=(lat, lon), n=420,
                                span_deg=24.0, eye_temp_c=eye_c,
                                eyewall_temp_c=wall_c)
        out.append(cache / name)
        cur += step
    return out


def run() -> int:
    from ..analysis.run_case import run_case
    from .scene_source import GibsSource, InsatSource, resolve_source

    print("INSAT pipeline demonstration (SYNTHETIC granules)")
    print("=" * 72)
    print("Imagery here is synthetic. The accuracy numbers below are therefore")
    print("meaningless as skill — what is being demonstrated is the wiring.")
    print()

    paths = build_granules()
    print(f"built {len(paths)} granules in {DEMO_CACHE}")
    print(f"  first: {paths[0].name}")
    print(f"  last:  {paths[-1].name}")
    print(f"  spanning the full storm, so the mature phase is included")

    src = InsatSource(cache=DEMO_CACHE, min_gap_minutes=0)
    print(f"\nindexed {src.n_granules} granules from filenames")

    f = filter_nio(load())
    f = f[f.sid == FANI]
    t0, t1 = f.iso_time.min().to_pydatetime(), f.iso_time.max().to_pydatetime()

    gibs = GibsSource()
    n_gibs = len(gibs.observations(t0, t1, float(f.lon.median())))
    n_insat = len(src.observations(t0, t1, float(f.lon.median())))
    print(f"\nlooks available over Fani's window")
    print(f"  {gibs.name:44s} {n_gibs:3d}   timestamps ESTIMATED")
    print(f"  {src.name:44s} {n_insat:3d}   timestamps PUBLISHED")

    print(f"\nrunning the full pipeline on the INSAT source…\n")
    # Its own artifact key: this run is synthetic and must never overwrite the
    # real MODIS results for Fani.
    summary = run_case(FANI, "Fani", 2019, verbose=True, source=src,
                       artifact_key="fani_insat_demo")

    print()
    print("=" * 72)
    d = summary["data"]
    print(f"  source recorded : {d['source']['source']}")
    print(f"  exact timestamps: {d['source']['time_is_exact']}")
    print(f"  scenes analysed : {d['n_scenes']}")
    i = summary["identification"]
    print(f"  centre fix      : {i['centre_error_km']['mean']} km "
          f"(vs {i['first_guess_error_km']['mean']} km first guess)")
    print(f"  eyes detected   : {i['eye_detected_frames']}/{d['n_scenes']}")
    print()
    print("  Written to artifacts/fani_insat_demo_*.json — the real MODIS")
    print("  results in artifacts/fani_*.json are untouched.")
    print()
    print("  Reminder: synthetic imagery — these are not skill numbers.")
    print("  Fetch real granules and re-run for a real result:")
    print("    python -m cyclops.data.insat_cli fetch --start 2019-04-25 "
          "--end 2019-05-05 --every 180")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
