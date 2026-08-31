# WeatherNext 2 — why, how, and what it would change

## The case for it, from our own numbers

Our held-out evaluation splits cleanly:

| | 24 h skill vs persistence |
|---|---|
| Intensity | **+33%** |
| Track | **+11%** |

That gap is diagnostic, not incidental. Intensity is largely set by the storm's
own structure and recent history — things the model can observe. Track is set by
the **synoptic steering flow the storm is embedded in**, and this build's
steering comes from an analytic climatology that knows "storms near 15 °N in May
tend to go north-northwest". It does not know where the subtropical ridge
actually is this week.

Feature importance confirms it: the nowcast leans on `disp_24h_km`,
`dist_to_coast_km`, `lon`, `wind_kt_3min` — geometry and persistence. The
environmental features it *should* be leaning on for track carry no real signal
because they are climatological constants.

## What WeatherNext 2 supplies

Google DeepMind's WeatherNext 2 is a generative ensemble forecast model —
hourly resolution to 15 days, hundreds of scenario members, roughly 8× faster
than its predecessor. Two properties matter here.

### 1. A forecast steering wind, not an average

The 500 hPa wind at +6/12/18/24 h from an actual forecast, rather than a
seasonal mean. This is the physically correct predictor for cyclone motion, and
it is precisely the input the residual-from-persistence model is set up to
exploit: persistence handles the inertia, and the learned correction handles the
part the flow explains.

### 2. Ensemble spread as a per-case uncertainty signal

This is the more interesting one, and the part worth calling a contribution.

Today the cone radius at 24 h is a single number (158 km) — the 67th percentile
of validation errors across all storms. It is well calibrated in aggregate
(measured 65.8% coverage against a 67% target) but it is the same width for a
storm locked in a well-determined easterly flow and one sitting in a col where
the steering could go either way.

Ensemble members disagree most when the synoptic situation is genuinely
uncertain. So ensemble spread is a physically grounded, *a priori* predictor of
forecast error. Conditioning the cone on it gives a per-case width:

```
r(t, case) = f(spread_500hPa(t, case))     fitted on validation, coverage
                                            verified on test as today
```

Narrow when the flow is well determined, wide near a ridge break. That is what
operational centres do with their own ensembles, and no student team we are
aware of does it.

## Access — this is on the critical path

WeatherNext 2 is **not open data**.

- Request via the [WeatherNext Data Request form](https://developers.google.com/weathernext/guides/access-forecast)
- Reviewed **weekly**; typically **5–7 business days**
- **File it now.** Nothing else in this project has that lead time except MOSDAC.

Once granted, three access paths exist:

| Path | Identifier |
|---|---|
| Zarr on GCS | `gs://weathernext/weathernext_2_0_0/zarr` (ensemble)<br>`gs://weathernext/weathernext_2_0_0_mean/zarr` (mean) |
| Earth Engine | `projects_gcp-public-data-weathernext_assets_weathernext_2_0_0` |
| BigQuery | WeatherNext 2 / WeatherNext 2 Mean tables |

## How it is wired in

`src/cyclops/providers/` — environmental fields are behind an interface, not
hard-coded:

```python
from cyclops.providers import resolve_provider

provider = resolve_provider()        # WeatherNext 2 if access exists, else climatology
snap = provider.at(lat=19.8, lon=86.5, when=t)
snap.get("steer_u_kt")               # value
snap.fields["steer_u_kt"].ensemble_spread   # the per-case uncertainty signal
snap.fields["steer_u_kt"].is_proxy          # False for real data, True for climatology
```

`resolve_provider()` probes for access and falls back silently to climatology,
logs which one it picked, and reports it on `/v1/health`. Nobody has to guess
what the demo is running on.

### Offline at the venue

`WeatherNext2Provider.prefetch_case()` pulls the North Indian Ocean subset for a
case window to local Zarr. Run it once with a network; at demo time the provider
reads the local file and makes **zero** network calls. That is the only form in
which a cloud dataset can be part of a venue demo at all.

## Honest status

**Implemented and pending access.** The adapter is written against the published
variable schema and exercised against a synthetic store. It has **not** been run
against the real WeatherNext 2 archive.

Say "implemented and pending access". Do not say "integrated". The first is true
and still a strong answer; the second is a claim a judge can puncture with one
question.

## The experiment to run once access lands

1. Prefetch the NIO subset for the test seasons (2019, 2020, 2023).
2. Re-run `make nowcast` with `CYCLOPS_ENV_PROVIDER=weathernext`.
3. Report track skill **before and after**, on the same held-out storms. The
   before-number is already recorded in `artifacts/metrics_nowcast.json`, so
   this is a clean controlled comparison rather than a re-baselining.
4. Fit cone radius as a function of ensemble spread; verify coverage on test as
   today.
5. If it does not help — report that too, and analyse why. A measured null
   result on a well-motivated experiment is a better slide than a vague claim.
