# CYCLOPS

**Cyclone Observation, Prediction & Explainability System**
SIH 2026 · PS 26070 · Ministry of Earth Sciences / India Meteorological Department

AI/ML identification, classification and nowcasting of tropical cyclone patterns
in the North Indian Ocean, with explainability and honest uncertainty.

---

## What this build actually is

This is the **MVP**, targeted at the internal university demo day. It is a
complete end-to-end system — data → model → API → console — not a mock-up. But
what is real and what is a placeholder is stated everywhere, including on the
console itself, because that distinction is the difference between a credible
submission and a caught one.

| Layer | Status |
|---|---|
| Best-track positions, timestamps, intensity labels | **Real** — IBTrACS v04r01, `NEWDELHI_WIND`, 3-min sustained (IMD convention) |
| Track & intensity nowcast, baselines, uncertainty cone | **Real** — trained and evaluated on the above |
| Satellite infrared / water-vapour imagery | **Synthetic** — physically parameterised from best track |
| Scatterometer surface winds | **Synthetic** — modified-Rankine vortex with a partial swath |
| Environmental fields (SST, shear) | **Climatology proxy** — real providers behind an interface |

The imagery is synthetic because Digital Typhoon and MOSDAC/INSAT both need
registration with weeks of lead time. Rather than block the whole pipeline on
paperwork, the renderer produces scenes on the **same tensor contract** the real
readers will produce, so swapping in the archive is a change to one loader.

**Any intensity accuracy figure from this build measures how well the model
inverts the renderer, not how well it reads a satellite.** That is stated in the
metrics file, in the API response, and on screen.

---

## Results — real data, held-out storms

31 storms from seasons 2019, 2020 and 2023. Split by season; storm IDs are
disjoint across splits and a test asserts it.

### Forecast skill against baselines

| Lead | n | Persistence | Climatology | **CYCLOPS** | Skill |
|---|---|---|---|---|---|
| +6 h | 607 | 34.6 km | 62.9 km | **33.3 km** | +3.8% |
| +12 h | 576 | 70.5 km | 120.8 km | **65.1 km** | +7.6% |
| +18 h | 546 | 108.8 km | 177.1 km | **98.6 km** | +9.3% |
| +24 h | 517 | 153.7 km | 230.5 km | **137.3 km** | +10.7% |

| Lead | Persistence MAE | **CYCLOPS MAE** | Skill |
|---|---|---|---|
| +6 h | 4.10 kt | **3.49 kt** | +14.9% |
| +12 h | 7.99 kt | **5.70 kt** | +28.6% |
| +18 h | 11.58 kt | **7.81 kt** | +32.6% |
| +24 h | 15.02 kt | **9.94 kt** | +33.8% |

### Uncertainty cone calibration

Radii are the 67th percentile of the model's own **validation** position errors
(NHC convention). Coverage is then measured on the **test** storms — a disjoint
set, so this is a real check and not a restatement of the calibration.

| Lead | Radius | Measured coverage | Target |
|---|---|---|---|
| +6 h | 36.3 km | 68.9% | 67% |
| +12 h | 73.2 km | 68.4% | 67% |
| +18 h | 111.8 km | 66.1% | 67% |
| +24 h | 158.3 km | 65.8% | 67% |

### Fusion ablation

Four models trained identically, scored on the same held-out storms.
**Synthetic imagery** — this shows the fusion machinery works, not that the
system reads real satellites. See [`docs/DATA-STATUS.md`](docs/DATA-STATUS.md).

| Variant | RMSE | MAE | Bias | Category acc. | Within one | vs IR-only |
|---|---|---|---|---|---|---|
| **fusion** (IR + wind + env) | 7.21 kt | 5.00 kt | -1.36 kt | 64.9% | 89.6% | +11.6% |
| IR + wind | 7.49 kt | 5.26 kt | -1.45 kt | 64.0% | 89.9% | +8.2% |
| IR + env | 8.11 kt | 6.03 kt | -1.47 kt | 56.4% | 87.8% | +0.6% |
| IR only | 8.16 kt | 6.25 kt | +0.25 kt | 48.7% | 83.6% | +0.0% |

The wind branch carries the gain, which is what the physical argument predicts:
a scatterometer measures the ocean surface directly, and that is exactly the
information infrared lacks. Environment alone adds almost nothing here because
the environmental fields in this build are climatological proxies — the same
finding that motivates WeatherNext 2.

Centre-fix error: **median 24.4 km**, 90th percentile
80.8 km (n=633), against a 60 km target.

### Reading these numbers honestly

**Intensity skill is strong (+34% at 24 h). Track skill is modest (+11%).**
That gap is not a bug and it is the most interesting finding in the build.

Intensity is largely determined by the storm's own structure and recent history,
which the model can see. Track is determined by the synoptic steering flow the
storm sits in — and this build's steering comes from an analytic climatology
that knows "storms near 15 N in May tend to go north-northwest", not where the
subtropical ridge actually is this week.

That diagnosis points at a specific fix, which is why the environment layer is
an interface rather than a hard-coded function. See **WeatherNext 2** below.

---

## WeatherNext 2

Environmental fields come from a pluggable `EnvironmentProvider`
(`src/cyclops/providers/`). Three implementations:

| Provider | Fidelity | Status |
|---|---|---|
| `ClimatologyProvider` | analytic NIO climatology | **working, offline, zero setup** — what the demo runs on |
| `ERA5Provider` | reanalysis | needs a Copernicus CDS account |
| `WeatherNext2Provider` | Google DeepMind AI ensemble | **implemented, pending access** |

WeatherNext 2 supplies exactly what the track model is missing, in the two forms
that matter:

1. A **forecast** deep-layer steering wind at +6/12/18/24 h, rather than a
   climatological average. This is the physically correct predictor for where a
   cyclone goes.
2. An **ensemble**. Members disagree most when the synoptic situation is
   genuinely uncertain, so ensemble spread is a physically grounded predictor of
   forecast error — which turns the uncertainty cone from one fixed radius per
   lead time into a per-case width. Narrow in a well-determined steering regime,
   wide near a ridge break. That is what operational centres actually do.

**Access is on the critical path.** WeatherNext 2 is not open data: requests go
through the [WeatherNext Data Request form](https://developers.google.com/weathernext/guides/access-forecast),
are reviewed weekly, and take roughly 5–7 business days. **File the request now.**
Once granted, `prefetch_case()` pulls the NIO subset to local Zarr so the demo
still makes zero network calls at the venue.

Until then `resolve_provider()` falls back to climatology automatically, logs
which provider it resolved, and reports it on `/v1/health` — so nobody has to
guess what the demo is running on.

The adapter is written against the documented schema and unit-tested against a
synthetic store. It has **not** been validated against the real archive. Say
"implemented and pending access", which is true and still a good answer.

---

## Quick start

```bash
make setup      # venv + npm install
make data       # download IBTrACS, build the dataset
make train      # nowcast + intensity ablation
make demo       # API on :8000, console on :5180
```

Then open **<http://localhost:5180>**. The console opens on a cyclone already
playing — never an empty state.

> The map needs a **visible, foreground** browser tab. MapLibre does its style
> loading inside the `requestAnimationFrame` loop, which browsers pause in
> hidden or background tabs, so a headless or backgrounded tab shows a blank
> map. It recovers on its own the moment the tab is fronted. Not a concern for
> a live demo; worth knowing if you screenshot from a script.

Verify a running stack:

```bash
make smoke
```

---

## The console

The map is the page: full-bleed, with every panel floating over it as
translucent chrome — the layout language of zoom.earth and
earth.nullschool.net, chosen because the subject of the screen is a cyclone,
not a dashboard.

| Layer | What it is |
|---|---|
| Basemap | Clipped Natural Earth extract, bundled (~250 KB). No tile server, no token, no network. |
| Infrared imagery | The IR frame draped in its true geographic position, with clear air transparent so the coast and track show through. |
| Surface wind flow | Particles advected through the scatterometer retrieval. Stops at the swath edge and respawns in rain-flagged cells, so coverage gaps stay visible as gaps rather than being interpolated over. |
| Track, forecast, cone | Observed solid, forecast dashed in a different hue, cone translucent. |

The timeline strip is tinted by IMD category across the part of the storm already
revealed, and is built from the track the replay has released — the console never
requests data past the storm clock, so the network tab shows no future-looking
request either.

`make validate-map` checks the style and the bundled basemap in Node. MapLibre
only reports a bad style once something paints, which means a headless CI box or
a hidden tab renders an empty map with no error at all — this catches it at build
time instead. It was written after exactly that bug: a style key set to
`undefined` passes a truthiness check, fails MapLibre's validator, and leaves a
blank map behind.

## The three protective tests

These exist because each one guards a claim that, if false, ends the submission.

```bash
make test-critical
```

| Test | Guards against |
|---|---|
| `test_split_integrity.py` | A storm appearing in train and test. Frames of one cyclone are near-duplicates; frame-level splitting inflates every metric. Includes a test that the guard itself fires. |
| `test_replay_causality.py` | Forecasting with hindsight. Drives a full replay through a spying store and asserts every read was bounded by the storm clock. **Show this to a judge who asks how they know.** |
| `test_preprocess_parity.py` | Training-serving skew. Asserts the API imports the training preprocessing module rather than copying it — skew fails silently, with no exception and no log, just wrong numbers. |

---

## Architecture

```
IBTrACS v04r01 ──┐
                 ├─→ features ──→ storm-wise splits ──→ ┌─ nowcast (quantile GBM)
synthetic IR ────┤                                      └─ fusion CNN
synthetic wind ──┤                                          │
env provider ────┘                                          ├─ intensity (kt → IMD)
  ├ climatology (offline)                                   ├─ T-number
  ├ ERA5                                                    ├─ centre fix
  └ WeatherNext 2                                           └─ Grad-CAM
                                                            │
                            FastAPI ──── replay engine ─────┤
                            (causality enforced in the      │
                             store's query, not in app      │
                             code)                          │
                                 │                          │
                            WebSocket ──→ React console ────┘
```

### Design decisions worth defending

- **Regress knots, then bucket into IMD categories.** Not a 7-class classifier.
  Cross-entropy treats confusing SuCS with D as no worse than confusing SuCS with
  ESCS, the category boundaries are human conventions rather than physical
  thresholds, and SuCS is rare enough that a classifier learns never to predict it.
- **Nowcast predicts a residual from persistence.** Persistence already gets
  "the storm keeps moving" right. Making the model re-learn that from scratch
  wastes its capacity on 5,000 rows. Predicting the correction means the model
  starts at persistence skill and the learned part can only add.
- **Late fusion, not early.** Geostationary IR is 4 km every 15–30 min; a
  scatterometer is 12.5–25 km twice a day. Resampling winds to 4 km would
  fabricate detail that was never measured.
- **Modality dropout at p=0.3.** Most timesteps have no coincident scatterometer
  pass. Without it, the model becomes dependent on a modality that is usually
  absent. This is the answer to "how do you handle the temporal mismatch?"
- **Huber loss with δ=10 kt.** Chosen physically, not by search: 10 kt is roughly
  the inter-analyst disagreement in Dvorak estimation, so residuals below it sit
  inside the label's own noise floor.
- **Offline basemap.** A clipped Natural Earth extract (~250 KB) bundled with the
  app. No tile server, no token. A venue with a captive portal would otherwise
  leave a grey rectangle on screen with nothing to be done in the moment.

---

## Scope statement

> CYCLOPS is a decision-support and nowcasting aid intended to assist trained
> forecasters. It is not a substitute for the operational warnings issued by the
> India Meteorological Department, which remains the sole authority for tropical
> cyclone warnings in the North Indian Ocean. Prediction is limited to a 6–24
> hour horizon. Intensity estimates are trained against best-track records that
> are themselves partly derived from subjective Dvorak analysis, and the system's
> accuracy is therefore bounded by the consistency of that record.

This paragraph is on the console, not buried in an About page. It is not a
hedge — it is what makes a domain expert take the rest of the numbers seriously.

---

## Gotchas already hit, and why the code looks the way it does

These cost real time. They are written down so nobody rediscovers them at 2am
during the Finale.

| Symptom | Cause | Fix in this repo |
|---|---|---|
| API segfaults, or **hangs**, at startup | LightGBM and PyTorch each link their own OpenMP runtime on macOS. Deserialising a LightGBM booster after importing torch crashes; the other import order deadlocks. | Nowcast uses scikit-learn's `HistGradientBoostingRegressor` — same quantile objective, no second OpenMP. `CYCLOPS_GBM=lightgbm` opts back in for offline experiments only. |
| Console shows **somebody else's app** | Vite defaults to port 5173, so any other Vite project on the laptop takes it first and silently shadows this one. | Console is on **5180** with `strictPort`, and `scripts/demo.sh` refuses to start if a port is taken and then greps the served HTML for `CYCLOPS`. |
| Map is a blank rectangle | Passing a module-level style constant to MapLibre: it mutates the object during load, so React StrictMode's second mount gets an already-consumed style. Also: a hidden browser tab never fires `requestAnimationFrame`, so MapLibre's render loop — and therefore style loading — never starts. | `makeStyle()` / `empty()` return fresh objects per map. The tab issue is browser behaviour and resolves as soon as the tab is visible. |
| Frames re-render differently after a restart | Seeded from Python's `hash()`, which is randomised per process for strings. | Seeded from a SHA-256 of `sid|timestamp`. |
| `?until=...` returns a 500 | A `+` in an ISO-8601 UTC offset decodes as a space in a query string. The console encodes correctly; curl and the `/docs` Try-it-out button do not. | `api/routers/_timeparse.py` repairs it and returns 422 rather than 500 on genuinely bad input. |
| Centre-fix error ~166 km | The offset was regressed from the globally-pooled embedding. Global average pooling is translation-invariant, so it carries almost no information about *where* the storm is. | `CentreHead`: a soft-argmax over a spatial heatmap on the layer3 feature map. |
| Intensity RMSE of 1.5 kt | The renderer made intensity perfectly recoverable from the image, so the ablation measured nothing. | `IR_PATTERN_NOISE_KT = 9.0` — see `docs/DATA-STATUS.md`. |

## Next, in order

1. **File the MOSDAC and WeatherNext 2 access requests.** Both have multi-week
   lead times and both are on the critical path. Nothing else here is.
2. **Swap synthetic imagery for Digital Typhoon**, then fine-tune on INSAT.
   One loader changes; the rest of the pipeline does not.
3. **Wire WeatherNext 2 steering flow into the nowcast** and re-measure track
   skill. This is the identified fix for the +11% figure.
4. **Ensemble-spread-conditioned cone width** — the genuinely novel piece.
5. PostGIS + Docker Compose for one-command startup (schema is in doc 02 §B7).
6. ONNX export so the API image drops torch and starts in seconds.
