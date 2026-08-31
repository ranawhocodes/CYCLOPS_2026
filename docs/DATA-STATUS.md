# Data status — what is real and what is not

The single most important page in this repo. Everything below is also enforced
in code: the API reports it on `/v1/health`, the console shows a banner, and the
metrics files carry a `DATA_STATUS` field.

---

## Real

| Item | Source | Notes |
|---|---|---|
| Storm positions | IBTrACS v04r01, NOAA NCEI | 6-hourly synoptic fixes, 1990–2025 |
| Intensity labels | IBTrACS `NEWDELHI_WIND` | 3-minute sustained, IMD convention |
| Fallback labels | IBTrACS `USA_WIND` × 0.88 | Used only where New Delhi is absent; recorded per-row in `wind_source` |
| Distance to land | IBTrACS `DIST2LAND` | Feeds the landfall-watch alert |
| Storm names, seasons, basins | IBTrACS | |
| Coastlines and boundaries | Natural Earth 50 m, clipped to 35–105 °E / −5–35 °N | Bundled, ~250 KB |

**4,234 of 7,054 fixes carry a genuine New Delhi 3-minute wind.** The remaining
2,816 are converted from the US 1-minute value and are labelled as such.

## Synthetic

| Item | What it is | Why |
|---|---|---|
| Infrared / water-vapour imagery | Parameterised render from best track | Digital Typhoon and MOSDAC both need registration with weeks of lead time |
| Scatterometer wind field | Modified-Rankine vortex on a partial swath | Same reason; ASCAT is public but the coincidence pipeline is not built yet |

The renderer produces brightness temperature in kelvin on the **same tensor
contract** the real readers will produce, so swapping in the archive is a change
to one loader.

### The one number that matters

`IR_PATTERN_NOISE_KT = 9.0`

The scene is rendered from `true_wind + N(0, 9 kt)` while the **label stays the
true best-track value**. Without this the image would be a deterministic
function of intensity, the CNN would invert it to ~1.5 kt RMSE, and the fusion
ablation would measure nothing. With it, a pattern-only estimator faces a
realistic irreducible floor — 9 kt is near the inter-analyst disagreement in
Dvorak estimation.

The scatterometer field is rendered from the **true** wind, because a
scatterometer measures the ocean surface directly. That asymmetry is the whole
physical argument for fusing the two, and it is what the ablation tests.

**This means intensity metrics from this build measure whether the fusion
machinery works. They are not a claim about reading real satellites.**

## Proxy

| Item | What it is | Replace with |
|---|---|---|
| Sea surface temperature | Analytic NIO climatology — bimodal seasonal cycle, cooler Arabian Sea, falloff north of 20 °N | NOAA OISST v2.1, or WeatherNext 2 |
| Deep-layer wind shear | Analytic — low pre/post-monsoon, high during the summer monsoon | ERA5 850–200 hPa, or WeatherNext 2 |
| Steering flow | Analytic mean | **WeatherNext 2 500 hPa ensemble** — this is the one that would move track skill |

Every proxy field carries `is_proxy: true` through the provider interface into
the API response and onto the console's Data Sources panel.

---

## What to say about this

Good:
> "Positions and intensity labels are real IBTrACS, on IMD's three-minute
> convention. The imagery is synthetic because MOSDAC registration takes weeks —
> the renderer is on the same tensor contract, so it's one loader to swap. Our
> intensity numbers show the pipeline is correct; they aren't a satellite skill
> claim, and the banner says so."

Not good:
> "Our model achieves 6.7 kt RMSE on cyclone intensity."

Nothing about the first version is a weakness. A team that can state precisely
what its own experiment does and does not show is a team a domain expert trusts
with the numbers that *are* real — the track and intensity skill against
persistence and climatology, which come entirely from real best-track data.

---

## Removing the asterisk

1. **Register with MOSDAC** (INSAT-3D/3DR/3DS) and **request WeatherNext 2
   access**. Both take weeks. Nothing else here does. Do these first.
2. **Digital Typhoon** for training volume — Western Pacific, so the basin
   domain shift must be disclosed and measured (WP-only vs WP-pretrain +
   NIO-finetune is experiment 8 in doc 06 §12).
3. **ASCAT from NOAA CoastWatch** — public, no registration. This is the
   quickest genuine second modality and should probably come before INSAT.
4. **ERA5 from Copernicus CDS** for real shear, or skip straight to WeatherNext 2.
