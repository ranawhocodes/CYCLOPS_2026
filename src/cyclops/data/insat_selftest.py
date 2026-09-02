"""
Self-test for the INSAT L1B reader, using a synthetic granule.

The reader was written from the documented L1B layout, not from a real file,
because downloading one needs a MOSDAC account. This builds an HDF5 granule that
matches that layout exactly — counts plus a calibration LUT, 2-D geolocation on a
geostationary-like grid, off-disk fill, the documented time format — and runs the
reader over it end to end.

What this proves: the reader applies the LUT in the right direction, honours the
fill value, resamples to a storm-centred grid correctly, and recovers a known
brightness-temperature field.

What it cannot prove: that MOSDAC's real granules use these variable names. Only
a real file settles that, which is what `describe()` is for.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import ARTIFACTS
from ..domain.imd import KELVIN


def build_synthetic_granule(path: Path, centre=(17.0, 85.0),
                            n: int = 600, span_deg: float = 30.0,
                            eye_temp_c: float = -20.0,
                            eyewall_temp_c: float = -85.0) -> dict:
    """
    Write a granule matching the documented L1B structure.

    Contains a synthetic cyclone with a known eye and eyewall so the round trip
    can be checked against expected values rather than merely "it ran".
    """
    import h5py

    lat0, lon0 = centre
    lats = np.linspace(lat0 + span_deg / 2, lat0 - span_deg / 2, n)
    lons = np.linspace(lon0 - span_deg / 2, lon0 + span_deg / 2, n)
    LON, LAT = np.meshgrid(lons, lats)

    # Ground distance from the storm centre, in km.
    dx = (LON - lon0) * 111.320 * np.cos(np.deg2rad(lat0))
    dy = (LAT - lat0) * 110.574
    r = np.hypot(dx, dy)

    # Warm eye inside a cold eyewall annulus, decaying outwards.
    rmw = 30.0
    eyewall = np.exp(-((r - rmw) / 22.0) ** 2)
    shield = np.exp(-(r / 320.0) ** 2)
    eye = np.exp(-(r / (rmw * 0.55)) ** 4)
    sst_c = 28.0
    temp_c = (sst_c
              + (eyewall_temp_c - sst_c) * np.clip(eyewall + 0.72 * shield, 0, 1)
              + (eye_temp_c - eyewall_temp_c) * eye)
    temp_k = (temp_c + KELVIN).astype(np.float64)

    # Quantise to 10-bit counts through a LUT, exactly as L1B does.
    lut = np.linspace(150.0, 340.0, 1024).astype(np.float32)
    counts = np.clip(np.searchsorted(lut, temp_k), 0, lut.size - 1).astype(np.uint16)

    # Off-disk corners get the fill value and sentinel geolocation, so the fill
    # and off-disk handling are actually exercised.
    FILL = 1023
    corner = r > (span_deg / 2) * 110.0
    counts[corner] = FILL
    LATf, LONf = LAT.copy(), LON.copy()
    LATf[corner] = 999.0
    LONf[corner] = 999.0

    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        f.attrs["Satellite_Name"] = np.bytes_(b"INSAT-3DR")
        f.attrs["Acquisition_Start_Time"] = np.bytes_(b"02-MAY-2019T07:30:00")
        f.attrs["Acquisition_End_Time"] = np.bytes_(b"02-MAY-2019T07:59:59")

        d = f.create_dataset("IMG_TIR1", data=counts[None, ...])   # leading time axis
        d.attrs["_FillValue"] = np.uint16(FILL)
        f.create_dataset("IMG_TIR1_TEMP", data=lut)
        f.create_dataset("IMG_TIR1_RADIANCE", data=np.linspace(0, 20, 1024, dtype=np.float32))
        f.create_dataset("Longitude", data=LONf.astype(np.float32))
        f.create_dataset("Latitude", data=LATf.astype(np.float32))

    return {"path": path, "centre": centre, "eye_temp_c": eye_temp_c,
            "eyewall_temp_c": eyewall_temp_c, "rmw_km": rmw, "fill": FILL}


def run() -> int:
    from .insat_reader import read_storm_scene, read_channel, describe

    tmp = ARTIFACTS / "insat_synthetic_granule.h5"
    truth = build_synthetic_granule(tmp)
    fails = []

    def check(label, cond, detail=""):
        print(f"  {'ok  ' if cond else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
        if not cond:
            fails.append(label)

    print("INSAT L1B reader self-test (synthetic granule)")
    print("=" * 66)
    describe(tmp)
    print()

    field = read_channel(tmp, "TIR1")
    check("channel read", field["values"].shape == (600, 600),
          f"shape={field['values'].shape}")
    check("acquisition time parsed",
          field["start_time"] is not None and field["start_time"].hour == 7,
          str(field["start_time"]))
    check("satellite name", "INSAT" in field["satellite"], field["satellite"])
    check("fill value excluded from valid mask",
          field["valid"].mean() < 0.95,
          f"valid={field['valid'].mean():.1%}")

    v = field["values"][field["valid"]]
    check("LUT applied (values are kelvin, not counts)",
          150.0 < v.min() < 340.0 and 150.0 < v.max() < 340.0,
          f"range {v.min():.1f}-{v.max():.1f} K")
    check("coldest pixel near the synthetic eyewall",
          abs((v.min() - KELVIN) - truth["eyewall_temp_c"]) < 4.0,
          f"{v.min()-KELVIN:.1f}C vs {truth['eyewall_temp_c']:.1f}C expected")

    sc = read_storm_scene(tmp, *truth["centre"], size=256)
    check("storm crop shape", sc.kelvin.shape == (256, 256))
    check("crop coverage high near centre", sc.coverage > 0.85,
          f"{sc.coverage:.1%}")
    check("crop km/px", abs(sc.km_per_px - 4.0) < 0.01, f"{sc.km_per_px:.2f}")

    C = sc.kelvin - KELVIN
    c0 = 128
    eye_read = float(np.nanpercentile(C[c0-3:c0+4, c0-3:c0+4], 90))
    check("warm eye recovered", abs(eye_read - truth["eye_temp_c"]) < 6.0,
          f"{eye_read:.1f}C vs {truth['eye_temp_c']:.1f}C expected")

    px = int(truth["rmw_km"] / sc.km_per_px)
    ring = float(np.nanmin(C[c0, c0+px-2:c0+px+3]))
    check("cold eyewall recovered", abs(ring - truth["eyewall_temp_c"]) < 6.0,
          f"{ring:.1f}C vs {truth['eyewall_temp_c']:.1f}C expected")
    check("eye is warmer than eyewall", eye_read > ring + 30,
          f"contrast {eye_read - ring:.1f}C")

    # The whole point of the reader: the downstream analysis must consume it
    # unchanged, exactly as it consumes a GIBS scene.
    from ..analysis.centre_fix import find_centre
    from ..analysis.dvorak import estimate
    fix = find_centre(sc.kelvin, sc.valid, sc.bbox, sc.km_per_px,
                      first_guess_rc=(128, 128))
    est = estimate(sc.kelvin, sc.valid, fix, sc.km_per_px)
    from pyproj import Geod
    _, _, err = Geod(ellps="WGS84").inv(fix.lon, fix.lat,
                                        truth["centre"][1], truth["centre"][0])
    check("downstream centre_fix runs on an INSAT scene",
          err / 1000 < 30, f"centre error {err/1000:.1f} km")
    check("downstream dvorak runs on an INSAT scene",
          est.pattern in ("EYE", "CDO", "EMBEDDED_CENTER", "SHEAR"),
          f"{est.pattern} T{est.t_number}")

    print()
    if fails:
        print(f"{len(fails)} check(s) FAILED: {', '.join(fails)}")
        return 1
    print("all checks passed — reader is correct against the documented L1B layout")
    print("NOTE: not yet validated on a real MOSDAC granule; run")
    print("      python -m cyclops.data.insat_reader describe <file.h5> on the first one")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
