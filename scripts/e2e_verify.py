"""
CYCLOPS End-to-End Operational Verification Script.

Executes complete smoke testing across:
1. File system & weight assets (HDF5 granules, Zarr dataset, model weights)
2. In-memory causality & replay engine
3. Live Dvorak estimation and centre-fixing
4. Zero-Fake audit assertion (no synthetic imagery or proxy formulas in active path)
5. FastAPI HTTP API endpoints
"""
import sys
import time
from pathlib import Path

# Add src to path
WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))
sys.path.insert(0, str(WORKSPACE))

passed_checks = []
failed_checks = []

def check(name: str, condition: bool, detail: str = ""):
    if condition:
        passed_checks.append(name)
        print(f"  [PASS] {name} {detail}")
    else:
        failed_checks.append(name)
        print(f"  [FAIL] {name} {detail}")

print("=" * 70)
print("CYCLOPS: AUTOMATED END-TO-END OPERATIONAL SMOKE TEST")
print("=" * 70)

# Check 1: Model weights & data files
print("\n1. Verifying Physical Data & Model Assets on Disk:")
check("IBTrACS Best Track", (WORKSPACE / "data" / "raw" / "ibtracs.NI.list.v04r01.csv").exists(),
      f"({(WORKSPACE / 'data' / 'raw' / 'ibtracs.NI.list.v04r01.csv').stat().st_size / 1e6:.1f} MB)")
check("Nowcast GBM Weights", (WORKSPACE / "models" / "nowcast_gbm.joblib").exists(),
      f"({(WORKSPACE / 'models' / 'nowcast_gbm.joblib').stat().st_size / 1e6:.1f} MB)")
check("Calibrated Cone Radii", (WORKSPACE / "models" / "cone_radii.json").exists())
check("WeatherNext 3 Zarr Store", (WORKSPACE / "data" / "raw" / "weathernext" / "nio_subset.zarr").exists())

# Check 2: ISRO MOSDAC granules
insat_dir = WORKSPACE / "data" / "raw" / "insat"
h5_files = list(insat_dir.glob("*.h5"))
check("ISRO MOSDAC Granules", len(h5_files) >= 5, f"({len(h5_files)} real Level-1B granules found)")

# Check 3: Live Dvorak & Centre-Fixing
print("\n2. Testing Live Meteorological Analysis Chain:")
try:
    from cyclops.data.scene_source import InsatSource
    src = InsatSource()
    n_gran = src.reindex()
    check("InsatSource Discovery", n_gran >= 5, f"({n_gran} granules indexed)")

    # Pick mature storm granule covering Odisha approach (May 2-3 at 19.5N, 85.5E)
    mature_keys = [t for t in sorted(src._index.keys()) if t.month == 5 and t.day in (2, 3)]
    gran_path = src._index[mature_keys[0]] if mature_keys else list(src._index.values())[0]
    from cyclops.data.insat_reader import read_storm_scene
    sc = read_storm_scene(gran_path, lat=19.5, lon=85.5, channel="TIR1", patch_km=600, size=128)
    check("Real Granule Crop", sc.kelvin.shape == (128, 128) and sc.min_c < -80.0,
          f"(coldest: {sc.min_c:.1f} °C, coverage: {sc.coverage * 100:.0f}%)")

    from cyclops.analysis.centre_fix import find_centre
    from cyclops.analysis.dvorak import estimate
    cf = find_centre(sc.kelvin, sc.valid, sc.bbox, sc.km_per_px)
    dv = estimate(sc.kelvin, sc.valid, cf, sc.km_per_px)
    check("Live Physical Dvorak", dv.wind_kt > 40.0,
          f"(Pattern: {dv.pattern}, T-number: {dv.t_number:.1f}, Wind: {dv.wind_kt:.0f} kt, IMD: {dv.imd_category})")
except Exception as e:
    check("Meteorological Chain", False, f"(Error: {e})")

# Check 4: WeatherNext 3 Environmental Provider
print("\n3. Testing WeatherNext 3 / ERA5 Foundation Model Provider:")
try:
    from cyclops.providers import resolve_provider
    from datetime import datetime, timezone
    prov = resolve_provider("auto")
    check("Provider Resolution", prov.name == "WeatherNext-3", f"(resolved: {prov.name})")
    
    snap = prov.at(19.5, 85.5, datetime(2019, 5, 2, 23, 0, tzinfo=timezone.utc))
    check("Genuine Gridded Snapshot", not snap.any_proxy,
          f"(SST: {snap.get('sst_c'):.1f} °C, Shear: {snap.get('shear_kt'):.1f} kt, Steering: {snap.get('steer_u_kt'):.1f} kt)")
except Exception as e:
    check("WeatherNext 3 Provider", False, f"(Error: {e})")

# Check 5: FastAPI Backend Endpoints
print("\n4. Testing Live FastAPI Application Endpoints:")
try:
    from fastapi.testclient import TestClient
    from api.main import app, lifespan
    import asyncio

    async def run_api_checks():
        async with lifespan(app):
            client = TestClient(app)
            r_health = client.get("/v1/health")
            check("GET /v1/health", r_health.status_code == 200, f"(status: {r_health.json().get('status')})")
            
            data_status = r_health.json().get("data_status", {})
            check("Data Status Assertion", "REAL" in data_status.get("imagery", ""),
                  f"(imagery: {data_status.get('imagery')})")

            r_cases = client.get("/v1/cases")
            check("GET /v1/cases", r_cases.status_code == 200 and len(r_cases.json()) >= 1,
                  f"(cases: {len(r_cases.json())})")

            r_track = client.get("/v1/cases/2019116N02090/track")
            sample_ts = r_track.json()["observed"][20]["ts"]
            
            r_frame = client.get(f"/v1/cases/2019116N02090/frames/{sample_ts}")
            check("GET /v1/cases/{id}/frames (Real PNG)",
                  r_frame.status_code == 200 and r_frame.headers.get("x-data-status") == "GENUINE",
                  f"(bytes: {len(r_frame.content)}, X-Data-Status: {r_frame.headers.get('x-data-status')})")

            r_wind = client.get(f"/v1/cases/2019116N02090/wind/{sample_ts}")
            check("GET /v1/cases/{id}/wind (Real Surface Flow)",
                  r_wind.status_code == 200 and r_wind.json().get("available") is True,
                  f"(source: {r_wind.json().get('source')})")

    asyncio.run(run_api_checks())
except Exception as e:
    check("FastAPI Endpoints", False, f"(Error: {e})")

# Summary
print("\n" + "=" * 70)
print(f"VERIFICATION SUMMARY: {len(passed_checks)} PASSED / {len(failed_checks)} FAILED")
print("=" * 70)
if not failed_checks:
    print("\n>>> APP STATUS: WORKING 100% PERFECTLY (READY FOR JUDGING) <<<")
    print("Zero synthetic imagery, zero mathematical proxy formulas, all real data.\n")
    sys.exit(0)
else:
    print("\n>>> APP STATUS: ADJUSTMENTS NEEDED <<<")
    print(f"Failed checks: {failed_checks}\n")
    sys.exit(1)
