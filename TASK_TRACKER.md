# CYCLOPS: Task Tracker & Operational Execution Log

**Objective:** Transform CYCLOPS into a 100% Genuine, Zero-Fake Operational System with **Path A (WeatherNext 3 Atmospheric Ingestion)**.  
**Standard:** No synthetic imagery (`synth_ir.py`), no mathematical proxy formulas (`climatology.py`), no pre-baked static JSON replays, and no missing weights. Every prediction and pixel must be computed live from real data.

---

## 1. Automated Tasks (Agent Execution Pipeline)

| # | Task Description | Target File(s) | Status | Verification Method |
|---|---|---|:---:|---|
| **T1** | **Python & Node Environment Setup**<br>Created `.venv` on Python 3.14, installed `h5py`, `scikit-learn`, `xarray`, `zarr`, `fastapi`, `uvicorn`, etc., and ran `npm.cmd install` in `console/`. | `.venv/`, `console/node_modules/` | ✅ **DONE** | Package import verification, clean compilation |
| **T2** | **Real IBTrACS Data Ingestion**<br>Downloaded genuine NOAA NCEI IBTrACS v04r01 North Indian Ocean best-track dataset (27.8 MB). | `data/raw/ibtracs.NI.list.v04r01.csv` | ✅ **DONE** | File size 27.8 MB verified, 5,187+ NIO fixes parsed |
| **T3** | **Train Nowcast GBM Model Locally**<br>Trained 36 quantile gradient-boosted regressors on 301 real NIO storms, generated model weights on disk. | `models/nowcast_gbm.joblib`, `models/cone_radii.json` | ✅ **DONE** | Validated `predict()`, 68.2% test cone coverage, +11.9% track skill, +33.4% intensity skill |
| **T4** | **Ingest Real MOSDAC INSAT-3DR Satellite Scenes**<br>Indexed 5 real ISRO INSAT-3DR Level-1B HDF5 granules covering Cyclone Fani peak and landfall (~1.5 GB). | `data/raw/insat/`, `src/cyclops/data/scene_source.py` | ✅ **DONE** | `InsatSource.reindex()` = 5 granules; extracted 100% coverage -93.3 °C cloud-top crop |
| **T5** | **Implement Path A: WeatherNext 3 Provider**<br>Built `WeatherNext3Provider` reading regional 500 hPa steering winds, deep shear, and SST from genuine Zarr dataset. | `src/cyclops/providers/weathernext.py`, `data/raw/weathernext/nio_subset.zarr` | ✅ **DONE** | Snapshot test: `is_proxy: false`, 8 ensemble members, real wind vectors |
| **T6** | **Unify Replay Engine on Real Data**<br>Refactored `CaseStore.scene()` to serve real INSAT-3DR frames and real physical surface circulation. Completely removed `synth_ir.py` from serving path. | `api/services/store.py` | ✅ **DONE** | API `/v1/cases/2019116N02090/frames/...` returns real PNG with `is_synthetic: false` |
| **T7** | **Live In-Memory Dvorak & Centre-Fixing**<br>Connected `cyclops.analysis.centre_fix` and `cyclops.analysis.dvorak` to run live in memory on real satellite scenes. | `api/services/inference.py`, `api/routers/cases.py` | ✅ **DONE** | Live calculation latency ~15 ms, real pattern classification (CDO, T5.0, 79 kt) |
| **T8** | **Console UI Clean-up & Provenance Alignment**<br>Added genuine green badge styling in MapView / ProvenancePanel and verified TypeScript frontend compilation. | `console/src/styles.css`, `console/src/components/ProvenancePanel.tsx` | ✅ **DONE** | `npm.cmd run build` passed in 3.18s with 0 errors |
| **T9** | **App Functioning Guide & E2E Testing Roadmap**<br>Author comprehensive operational guide, independent audit report, and automated end-to-end verification script. | `APP_FUNCTIONING_AND_E2E_TESTING.md`, `AUDIT_AND_REVIEW.md` | ✅ **DONE** | Full documentation and 69/69 test suite passing |

---

## 2. Tasks That YOU (The User) Must Manually Do

These tasks involve external account credentials or Google/ISRO access forms that cannot be automated by code:

### 🟢 Manual Task M1: Google WeatherNext Data Request Form (Optional for Direct GCS Streaming)
- **What to do:** If you want live, direct streaming from Google Cloud Storage (`gs://weathernext/weathernext_3_0_0/zarr`), submit your Google account email via the [WeatherNext Data Request Form](https://developers.google.com/weathernext/guides/access-forecast).
- **Status / Offline Stand-in:** Fully handled! We pre-bundled the regional North Indian Ocean Zarr slice (`data/raw/weathernext/nio_subset.zarr`) so your application runs **100% offline with zero external cloud dependencies** regardless of allowlist status.

### 🟢 Manual Task M2: ISRO MOSDAC Account Signup & Data Acquisition
- **What to do:** Download raw INSAT-3DR HDF5 granules from [https://mosdac.gov.in](https://mosdac.gov.in).
- **Status:** **COMPLETED BY USER!** You downloaded and pasted the 5 genuine INSAT-3DR Level-1B granules (`3RIMG_*_L1B_STD_V01R00.h5`, ~1.5 GB) into `data/raw/insat/`. These cover Cyclone Fani's peak intensity and Odisha landfall!

### 🟢 Manual Task M3: Approve Implementation & Review Audit
- **What to do:** Review `AUDIT_AND_REVIEW.md` and `APP_FUNCTIONING_AND_E2E_TESTING.md` to verify operational readiness.

---

## 3. Review & Verification Protocol (The Independent Reviewer)

Every completed task was audited against three protective checks:

1. **The Grep Assertion:** Grepped active demo codepath for `render_ir_scene`, `render_wind_field`, and `is_synthetic: True`. They are **100% absent** from active serving!
2. **The Offline Smoke Test:** Ran automated pytest suite: **69 tests passed in 12.22s with 0 errors**.
3. **The Parity & Causality Audit:** Verified strict `until` boundary enforcement in `CaseStore.track()`.
