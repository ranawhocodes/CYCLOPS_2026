# CYCLOPS

**Cyclone Observation, Prediction & Explainability System**
SIH 2026 · PS 26070 · Ministry of Earth Sciences / India Meteorological Department

Identification, classification and nowcasting of tropical cyclones in the North
Indian Ocean, from real satellite data, with explainability and honest
uncertainty.

```bash
make setup && make data && make train    # build it
make cases                               # real-imagery analysis, 3 storms
make demo                                # API :8000 + console :5180
```

---

## What is real

| | status |
|---|---|
| Best track — positions, times, intensity | **Real.** IBTrACS v04r01, `NEWDELHI_WIND`, 3-min sustained (IMD convention) |
| Satellite infrared — Fani, Amphan, Mocha | **Real.** MODIS Band 31 (11 µm) via NASA GIBS |
| Track & intensity nowcast, baselines, cone | **Real.** Trained and scored on the above |
| INSAT-3D/3DR access | **Search working**, downloads need a MOSDAC account |
| Fusion CNN training imagery | **Synthetic** — placeholder for Digital Typhoon |
| SST, wind shear | **Climatology proxy** — real providers behind an interface |

Everything is labelled at the point of use: the API reports data status on
`/v1/health`, the console shows a banner, and every metrics file carries the
provenance of its inputs. See [docs/DATA-STATUS.md](docs/DATA-STATUS.md).

---

## Results

### Nowcast — real data, held-out storms

31 storms, seasons 2019/2020/2023. Split by season; storm IDs are disjoint
across splits and a test asserts it.

| Lead | Persistence | Climatology | **CYCLOPS** | Skill |
|---|---|---|---|---|
| +6 h | 34.6 km | 62.9 km | **33.3 km** | +3.8% |
| +12 h | 70.5 km | 120.8 km | **65.1 km** | +7.6% |
| +18 h | 108.8 km | 177.1 km | **98.6 km** | +9.3% |
| +24 h | 153.7 km | 230.5 km | **137.3 km** | +10.7% |

| Lead | Persistence MAE | **CYCLOPS MAE** | Skill |
|---|---|---|---|
| +6 h | 4.10 kt | **3.49 kt** | +14.9% |
| +12 h | 7.99 kt | **5.70 kt** | +28.6% |
| +18 h | 11.58 kt | **7.81 kt** | +32.6% |
| +24 h | 15.02 kt | **9.94 kt** | +33.8% |

**Uncertainty cone.** Radii are the 67th percentile of the model's own
*validation* position errors (NHC convention); coverage is then measured on the
*test* storms, a disjoint set.

| Lead | Radius | Measured coverage | Target |
|---|---|---|---|
| +6 h | 36.3 km | 68.9% | 67% |
| +12 h | 73.2 km | 68.4% | 67% |
| +18 h | 111.8 km | 66.1% | 67% |
| +24 h | 158.3 km | 65.8% | 67% |

### Identification & classification — real MODIS imagery

Objective Dvorak on real 11 µm brightness temperature. Thresholds were chosen on
Fani, then applied **unchanged** to Amphan and Mocha, so those two are the
out-of-sample test.

| | Fani 2019 *(threshold source)* | Amphan 2020 *(unseen)* | Mocha 2023 *(unseen)* |
|---|---|---|---|
| scenes | 18 | 12 | 12 |
| centre fix | 19.5 km | 17.7 km | 25.2 km |
| vs motion extrapolation | −7.1% | **+15.4%** | −1.3% |
| vs last best-track fix | **+59.5%** | **+59.7%** | **+51.4%** |
| eyes detected | 1 | 2 | 0 |
| intensity RMSE | 28.4 kt | 33.1 kt | 26.2 kt |
| bias | **+11.1 kt** | **+11.0 kt** | **+9.1 kt** |
| category within-one | 50% | 67% | 50% |

### Fusion ablation — synthetic imagery

Four models trained identically, scored on the same held-out storms.

| variant | RMSE | category acc. | within-one |
|---|---|---|---|
| **fusion** | **7.21 kt** | **64.9%** | 89.6% |
| ir + wind | 7.49 kt | 64.0% | 89.9% |
| ir + env | 8.11 kt | 56.4% | 87.8% |
| ir only | 8.16 kt | 48.7% | 83.6% |

Fusion beats IR-only by 11.6%. **The imagery is synthetic**, so this measures
that the fusion machinery works — not that the system reads satellites well.

---

## Reading these numbers honestly

**Intensity nowcast is the strongest result** (+33.8% over persistence at 24 h)
and it is entirely real data.

**Track nowcast skill is modest** (+10.7%). The diagnosis is specific: the
steering flow is a climatology that knows "storms near 15 N in May tend to go
north-northwest", not where the ridge actually is this week. That is what
WeatherNext 2 fixes, and why the environment layer is an interface.

**The Dvorak bias is a real, transferable finding.** +11.07, +11.03, +9.08 kt on
three independent storms. Leave-one-storm-out — derive the offset from two, apply
to the third — cuts RMSE 5.7–7.9%. Consistent with Dvorak's Atlantic-tuned tables
against IMD's North Indian Ocean adjustments, which was predicted in the module
docstring before it was measured. But bias removal only takes pooled RMSE from
29.2 to 27.3 kt: **scatter dominates, so a calibration offset is not the fix.**

**Centre-fixing does not reliably beat motion extrapolation.** +15%, −1%, −7%.
The defensible claim is the one that holds everywhere: **+51 to +60% over the
last best-track fix.** [docs/FINDING-eye-detection.md](docs/FINDING-eye-detection.md)
traces why, and it is the most interesting result in the project.

---

## The finding that shaped the roadmap

Mocha detected zero eyes across 12 passes. Chasing that produced the answer to a
bigger question — why IR centre-fixing cannot beat motion extrapolation:

| error source | contribution |
|---|---|
| 4 km nearest-neighbour centring | ~4–6 km |
| ±30 min **estimated** overpass time × ~12 kt | ~11 km |
| quadrature floor | ~12–13 km |
| observed | ~33 km |

The motion-extrapolated first guess is already accurate to 10–20 km. There is
almost no headroom. **Both dominant terms come from MODIS being polar-orbiting**,
so the ceiling is temporal, not algorithmic — which is what INSAT-3D fixes.

---

## INSAT-3D / 3DR

Search works today with no account. Downloads need a free MOSDAC account.

```bash
make insat-status     # what is reachable
make insat-plan       # size a download before committing
make insat-selftest   # verify the HDF5 reader, 14 checks
make insat-demo       # full pipeline on the INSAT path
```

| | MODIS (current) | INSAT-3DR |
|---|---|---|
| Fani-window granules | 18 usable day passes | **1,947** |
| cadence | ~4 per day | 8.1 min measured |
| timestamp | **estimated**, ±30 min | **published**, exact |

**Done:** catalogue client, credential handling, the L1B HDF5 reader (counts +
calibration LUT), and the pipeline wiring. `resolve_source()` picks INSAT the
moment granules appear — no code change.

**Your one step:** register at <https://mosdac.gov.in/signup/>, export
`MOSDAC_USERNAME` / `MOSDAC_PASSWORD`, then fetch. ~88 granules at 180 min
cadence is 25 GB. Details in [docs/INSAT-ACCESS.md](docs/INSAT-ACCESS.md).

---

## WeatherNext 2

Environmental fields sit behind a pluggable provider
(`src/cyclops/providers/`). `ClimatologyProvider` is offline and always works;
`WeatherNext2Provider` is implemented and **pending access** — requests are
reviewed weekly and take 5–7 business days, so file early.

It supplies a *forecast* steering wind rather than a climatological average, and
supplies it as an *ensemble* — so cone width could become per-case rather than
one fixed radius per lead time. See [docs/WEATHERNEXT-2.md](docs/WEATHERNEXT-2.md).

---

## The console

The map is the page: full-bleed, with every panel floating over it — the layout
language of zoom.earth and earth.nullschool.net.

| layer | what it is |
|---|---|
| Basemap | Clipped Natural Earth extract, bundled (~250 KB). No tile server, no token, no network. |
| Infrared | Frame draped in its true geographic position, clear air transparent |
| Surface wind flow | Particles advected through the scatterometer field; stops at the swath edge |
| Track, forecast, cone | Observed solid, forecast dashed, cone translucent |

Two extra views: **Performance** (baselines, ablation, confusion matrix) and
**Real data** — Fani, Amphan and Mocha on real MODIS imagery, with the picker
labelling which storm is the threshold source and which are out-of-sample.

`make validate-map` checks the style and basemap in Node. MapLibre only reports a
bad style once something paints, so a headless box renders an empty map with no
error; this catches it at build time. If the map fails at runtime the console
names the cause rather than showing a black rectangle.

---

## Protective tests

```bash
make test            # everything, 68 tests
make test-critical   # the three that protect credibility
```

| test | guards against |
|---|---|
| `test_split_integrity` | A storm in both train and test. Includes a test that the guard itself fires. |
| `test_replay_causality` | Forecasting with hindsight. Drives a full replay through a spying store. |
| `test_preprocess_parity` | Training/serving skew. Asserts the API imports the training module rather than copying it. |
| `test_mosdac_credentials` | A password reaching disk, a log, or a commit. |
| `test_insat_reader` | Reading raw counts as if they were temperature. |
| `test_scene_source` | INSAT silently not being a drop-in for MODIS. |

---

## Architecture

```
IBTrACS ─────────┐
                 ├─→ features ──→ storm-wise splits ──→ nowcast (quantile GBM)
scene source ────┤                                      fusion CNN
  ├ GIBS/MODIS   │                                        │
  └ INSAT-3DR    │                                        ├─ intensity (kt → IMD)
env provider ────┘                                        ├─ objective Dvorak
  ├ climatology (offline)                                 ├─ centre fix
  ├ ERA5                                                  └─ Grad-CAM
  └ WeatherNext 2                                         │
                        FastAPI ──── replay engine ───────┤
                        (causality enforced in the query) │
                              └─ WebSocket ──→ React console
```

### Design decisions worth defending

- **Regress knots, then bucket into IMD categories.** Not a 7-class classifier:
  cross-entropy treats confusing SuCS with D as no worse than with ESCS, the
  boundaries are human conventions, and SuCS is rare enough that a classifier
  learns never to predict it.
- **Nowcast predicts a residual from persistence.** Persistence already gets "the
  storm keeps moving" right; making the model relearn it wastes capacity on
  5,000 rows.
- **Objective Dvorak is rule-based, not learned.** 18 scenes cannot train a
  network without memorising, and the rule behind each number prints on screen
  where a forecaster can argue with it.
- **An eye needs enclosure *and* symmetry.** Enclosure alone fires on cloud
  edges; symmetry alone fires on gaps in convective bands.
- **Late fusion, not early.** Geostationary IR is 4 km every 15–30 min; a
  scatterometer is 12.5–25 km twice a day. Resampling winds to 4 km fabricates
  detail nobody measured.
- **Huber loss with δ=10 kt.** Chosen physically: ~the inter-analyst
  disagreement in Dvorak estimation, so residuals below it sit inside the
  label's own noise floor.
- **Offline basemap.** A venue with a captive portal would otherwise leave a grey
  rectangle on screen with nothing to be done in the moment.

---

## Scope statement

> CYCLOPS is a decision-support and nowcasting aid intended to assist trained
> forecasters. It is not a substitute for the operational warnings issued by the
> India Meteorological Department, which remains the sole authority for tropical
> cyclone warnings in the North Indian Ocean. Prediction is limited to a 6–24
> hour horizon. Intensity estimates are trained against best-track records that
> are themselves partly derived from subjective Dvorak analysis, and the
> system's accuracy is therefore bounded by the consistency of that record.

On the console, not buried in an About page. It is not a hedge — it is what makes
a domain expert take the rest of the numbers seriously.

---

## Gotchas already hit, and why the code looks the way it does

Each of these cost real time and each left a guard behind.

| symptom | cause | guard |
|---|---|---|
| A 27 kt depression displayed as **Super Cyclonic Storm** | `to_imd_category` had gaps between whole-knot bands; 27.5 matched nothing and fell through to the last return | bands are half-open; a test sweeps 0–200 kt |
| Every scene classified CDO, never EYE | eye temperature in **°C** compared against ring temperature in **kelvin** | — |
| Centre search locked onto empty ocean | minimising raw azimuthal spread has a degenerate optimum in any uniform region | normalised to variance explained by radius |
| A 110 kt cyclone called 31 kt | pattern gating on the symmetry score sent mature storms down the SHEAR branch | gate on shield extent and coldness, as Dvorak specifies |
| Map rendered blank, no error | a style key set to `undefined` passes a truthiness check but fails MapLibre's validator | `make validate-map` |
| Map rendered at quarter size | MapLibre latched onto its 400×300 fallback before layout settled | ResizeObserver |
| Console served **someone else's app** | Vite defaults to 5173, which another project owned | port 5180, `strictPort`, and `demo.sh` greps the served HTML for `CYCLOPS` |
| `urllib` failed TLS against valid hosts | python.org macOS build is not wired to the system keychain | certifi |
| Fani's real results replaced by synthetic ones | the INSAT demo wrote to the same artifact key | `artifact_key` parameter |

---

## Next, in order

1. **File the MOSDAC and WeatherNext 2 access requests.** Both have multi-week
   lead times and both are on the critical path. Nothing else here is.
2. **Fetch real INSAT granules and re-run `make cases`.** This is the experiment
   that tests whether removing the ±30 min timing error lets centre-fixing beat
   motion extrapolation. The pipeline needs no changes.
3. **Run `describe` on the first real granule** to confirm MOSDAC's layout
   matches the documented one.
4. **Swap synthetic training imagery for Digital Typhoon**, then fine-tune on
   INSAT. One loader changes.
5. **Wire WeatherNext 2 steering flow into the nowcast** and re-measure track skill.
6. **Ensemble-spread-conditioned cone width** — the genuinely novel piece.
