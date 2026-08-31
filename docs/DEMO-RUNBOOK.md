# Demo runbook — internal university demo day

Everything needed to run the demo and survive the questions. Read the Q&A bank
before you present; it is the part that decides the room.

---

## Before you start

```bash
make demo          # API :8000, console :5173
make smoke         # verify every path before anyone is watching
```

Console opens at <http://localhost:5173> already replaying a cyclone. Do not
open on an empty state.

**Rehearse the recovery path.** If the WebSocket drops, the header badge goes
amber and says RECONNECTING, then recovers on its own. If it does not, click a
different case chip — that starts a fresh session. Know this before you need it.

---

## The 6-minute run

**0:00 — Open on Fani.** It is already playing. Do not explain the architecture
yet; let them watch a cyclone move for ten seconds.

> "This is Cyclone Fani, May 2019, replayed hour by hour. Every forecast you see
> was made using only the data available at that moment in the storm's life."

**0:30 — The intensity panel.** Point at the interval bar, not the number.

> "It reads 97 knots — but the panel shows an interval, not a number. Nothing in
> this console displays a point estimate without its uncertainty. The convention
> is three-minute sustained wind, which is what IMD uses. JTWC uses one-minute
> and the two differ by about twelve percent — getting that wrong would inflate
> every storm by roughly a category."

**1:15 — Grad-CAM.** Scrub to where the eye forms (around 1 May).

> "This shows which parts of the image pushed the estimate up. It's a regression
> Grad-CAM, so it answers 'what increased the predicted wind', not 'what supports
> a class'. In a mature cyclone attention should sit on the eyewall, not the warm
> eye centre — if it lit up the eye, something would be wrong."

**2:15 — Data sources panel.** Let the wind row's age tick over.

> "This is what makes multi-source fusion visible rather than a claim. A
> scatterometer passes twice a day; infrared comes every half hour. So most
> frames have no coincident wind, the row goes amber, and the model degrades
> gracefully because we trained it with modality dropout."

**3:00 — The cone.**

> "The cone radius at each lead time is the circle enclosing two-thirds of this
> model's own validation errors — the NHC convention. We calibrated on validation
> storms and measured coverage on test storms, which are a disjoint set. It comes
> out at 67.7 to 68.0 percent against a 67 percent target."

**3:45 — Performance button.** One click, not a narration.

> "Against persistence and climatology on 31 held-out storms. Intensity is
> 33 percent better than persistence at 24 hours. Track is 11 percent. That gap
> is the most interesting thing here and I'll come back to it."

**4:30 — The honest part.** This is the slide that wins the room.

> "Two things I want to be straight about. First, the imagery in this build is
> synthetic — Digital Typhoon and MOSDAC both need registration with weeks of
> lead time, so we built the renderer against the same tensor contract the real
> readers will produce. The banner says so, the API says so, the metrics file
> says so. The intensity numbers show the pipeline works; they are not a claim
> about reading satellites.
>
> Second, our track skill is only 11 percent. That's because our steering flow
> is a climatology — it knows storms in May tend to go north-northwest, not where
> the ridge is this week. That's the fix, and it's why the environment layer is
> an interface."

**5:15 — WeatherNext 2.**

> "WeatherNext 2 gives a forecast steering wind instead of an average, and gives
> it as an ensemble. Ensemble spread is a physically grounded predictor of
> forecast error, so the cone becomes narrow when the steering is well
> determined and wide near a ridge break — instead of one fixed radius per lead
> time. The adapter is written; access takes five to seven business days and
> we've filed for it."

**5:45 — Close on scope.** Point at the footer.

> "It's a decision-support aid. IMD remains the sole warning authority for this
> basin. That line is on screen the whole time, not in an About page."

---

## Q&A bank

**"How did you split your data?"**
By season, and storm IDs are disjoint across splits — `tests/test_split_integrity.py`
fails the build if any storm appears in two splits, and it includes a test that
the guard itself fires. Frames of one cyclone are near-duplicates; splitting by
frame would put the same storm in train and test and every number would be
inflated. Test seasons are 2019, 2020 and 2023, so Fani, Amphan and Mocha are
genuinely held out.

**"How do I know you didn't forecast with hindsight?"**
`tests/test_replay_causality.py`. It drives a full replay through a spying data
store and asserts every read was bounded by the storm clock at the time it was
made. The `until` filter is applied in the store's query, not in application
code, so a refactor cannot silently drop it. Happy to run it now.

**"What's your ground truth?"**
IBTrACS best track, `NEWDELHI_WIND` — IMD's three-minute sustained convention.
Worth being precise: there is no aircraft reconnaissance in the North Indian
Ocean, so best-track intensity is itself largely a satellite estimate, often a
Dvorak estimate made by a human analyst. We are learning to reproduce a skilled
analyst, not measuring physical truth. That also caps our honest accuracy claim.

**"Your intensity RMSE looks too good / too bad."**
On this build it reflects synthetic imagery. We deliberately render the scene
from a perturbed intensity — about 9 kt, near the inter-analyst Dvorak
disagreement — because infrared is an indirect proxy for surface wind. Without
that the image would be perfectly invertible and the fusion ablation would be
meaningless. On real imagery, published automated-Dvorak systems sit around
10–15 kt RMSE and that is the range we would expect.

**"Why not classify categories directly?"**
Three reasons. Cross-entropy treats confusing Super Cyclonic Storm with
Depression as no worse than confusing it with ESCS, which is physically absurd.
The boundaries are human conventions — 47 kt is CS and 48 is SCS — so forcing a
hard decision boundary there wastes capacity. And SuCS is rare enough that a
classifier learns never to predict it. We regress knots and bucket, which also
makes our RMSE directly comparable to the ADT literature.

**"How do you handle the temporal mismatch between geostationary and polar orbits?"**
Modality dropout at p = 0.3 during training: we randomly hide the wind branch on
samples that do have wind, so the model learns to work without it and degrades
gracefully. The wind branch has a learned "missing" embedding rather than a zero
tensor, so absence is a state the model recognises rather than something it
reads as a very calm ocean. We also feed hours-since-wind so it can discount
stale passes.

**"Why late fusion?"**
The modalities do not share a grid. Infrared is 4 km every 15–30 minutes from
geostationary orbit; a scatterometer is 12.5–25 km twice a day from a polar
orbiter. Resampling 25 km winds onto a 4 km grid would fabricate spatial detail
that was never measured. Separate encoders and concatenated embeddings respect
each sensor's native information content.

**"Only 11% better than persistence on track — isn't that weak?"**
It is modest, and we are reporting it rather than hiding it. Persistence is a
genuinely strong short-horizon baseline; beating it by 90% would mean we had a
bug. The diagnosis is specific: our steering flow is climatological. That is
exactly what WeatherNext 2 fixes, and it is why the environment layer is an
interface rather than a hard-coded function.

**"Why is your cone that size?"**
It is the 67th percentile of our own validation position errors at each lead
time — the NHC convention. We calibrated on validation storms and measured
coverage on test storms. If we had got 90% coverage the cone would be too wide
and hiding real skill; at 40% it would be overstating confidence. We measured
67.7–68.0%.

**"What happens if the network goes down?"**
Nothing. The basemap is a bundled Natural Earth extract, there is no tile server
and no API token, and the models are on disk. Unplug the cable and try it.

**"Is SCATSAT-1 in this?"**
Only as a historical archive. SCATSAT-1's last contact was 28 February 2021. The
live Indian wind path is OSCAT-3 on Oceansat-3/EOS-06; ASCAT on MetOp-B/C is our
primary because it is public and unregistered.

**"What would you do with three more months?"**
In order: get the MOSDAC and WeatherNext 2 access that is already filed, swap
synthetic imagery for Digital Typhoon then fine-tune on INSAT-3D/3DR/3DS, wire
the WeatherNext steering flow into the nowcast and re-measure track skill, and
then the piece I actually think is novel — conditioning cone width on ensemble
spread so uncertainty is per-case rather than per-lead-time.

---

## Things not to say

- Any accuracy number without saying which data it came from.
- "97% accurate." Report the confusion matrix and which categories confuse.
- That it replaces or competes with IMD forecasts.
- That WeatherNext 2 is integrated. It is *implemented and pending access*.
- That the imagery is real. It is not, and the banner on screen says so.

## Failure drills — rehearse these

| Failure | Recovery |
|---|---|
| WebSocket drops | Badge shows RECONNECTING and recovers; if not, click another case chip |
| API not running | `make demo` again; check `.run/api.log` |
| Console blank | Hard reload; the API is independent and `/docs` proves it |
| Someone asks for a metric you don't have | "That's in `artifacts/metrics_nowcast.json`, let me pull it up" — do not guess |
