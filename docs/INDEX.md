# CYCLOPS — what is where

## Read first

| File | Why |
|---|---|
| [`../README.md`](../README.md) | Results, architecture, design decisions, gotchas |
| [`DATA-STATUS.md`](DATA-STATUS.md) | **What is real and what is not.** Read before quoting any number |
| [`DEMO-RUNBOOK.md`](DEMO-RUNBOOK.md) | The 6-minute demo script and the full Q&A bank |

## Code map

```
src/cyclops/
  config.py               paths, tensor geometry, seeds — nothing else hard-codes these
  domain/imd.py           IMD scale, wind conventions, Dvorak T-number, BD curve
  preprocess.py           ★ SHARED BY TRAINING AND SERVING — never reimplemented
  data/
    ibtracs.py            real best track; resolves NEWDELHI vs USA wind convention
    features.py           causal kinematic + environmental features
    persistence_frame.py  persistence forecast as a feature and a residual target
    splits.py             storm-wise / season-wise splitting + the disjointness guard
    synth_ir.py           the synthetic renderer — read the docstring before using it
    build_dataset.py      raw -> tensors + manifest
  models/
    fusion.py             IR + wind + env branches, late fusion, modality dropout
    heads.py              intensity regression, physically-justified Huber delta
    cam.py                regression Grad-CAM + PNG rendering
    nowcast_gbm.py        quantile GBM over persistence residuals
  eval/
    baselines.py          persistence and climatology — built before the model
    metrics.py            RMSE, bias, per-category MAE, confusion
    cone.py               67th-percentile cone calibration and coverage check
    report.py             prints the results table from artifacts/
    qc_sheet.py           sample audit, renderer physics check, class balance
    case_study.py         hero-case replay scored frame by frame
  providers/
    base.py               EnvironmentProvider interface + provenance types
    climatology.py        offline analytic NIO climatology (the demo default)
    weathernext.py        WeatherNext 2 adapter — implemented, pending access
  train/                  train_nowcast.py, train_intensity.py (with the ablation)
  export/to_onnx.py       ONNX export + numerical parity verification

api/
  main.py                 app factory, lifespan, warmup
  disclaimer.py           the scope statement, one source
  routers/                cases, classify, nowcast, replay, metrics, health
  services/
    store.py              case store; ★ the `until` causality enforcement point
    replay.py             storm-clock engine
    inference.py          model loading, classification, forecast assembly
    alerts.py             detection, rapid intensification, category change, landfall

console/src/
  components/MapView.tsx  offline map, track, forecast, cone
  components/…            intensity, Grad-CAM, provenance, alerts, chart, metrics
  store/index.ts          zustand; WebSocket messages land here
  hooks/useLiveSocket.ts  reconnect with capped backoff

tests/
  test_split_integrity.py    ★ no storm spans two splits
  test_replay_causality.py   ★ no inference sees the future
  test_preprocess_parity.py  ★ the API uses the training preprocessing module
  test_domain.py             IMD conventions pinned
  test_api_contract.py       every endpoint the console depends on
```

## Commands

```bash
make setup        # venv + npm install
make data         # IBTrACS + dataset
make train        # nowcast + intensity ablation
make eval         # results table
make figures      # QC sheets + case study
make test         # everything
make test-critical # just the three that protect credibility
make demo         # API :8000 + console :5180
make smoke        # verify a running stack
make stop
```

## Artifacts produced

| File | Contents |
|---|---|
| `artifacts/metrics_nowcast.json` | Track/intensity skill vs baselines, cone calibration, feature importance |
| `artifacts/metrics_intensity.json` | Fusion ablation, confusion matrix, per-category MAE, centre-fix error |
| `artifacts/case_study.json` / `.csv` / `.png` | Hero case, scored frame by frame |
| `artifacts/qc_*.png` | Sample audit, renderer physics, class balance |
| `models/cone_radii.json` | Calibrated radii **and measured coverage** |
| `data/processed/manifest.json` | Dataset provenance and content hash |

Every number in the deck must trace to one of these. `make train && make eval`
regenerates them all.
