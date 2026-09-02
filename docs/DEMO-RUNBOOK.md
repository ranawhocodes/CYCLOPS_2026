# Demo runbook

Everything needed to run the demo and survive the questions. Read the Q&A bank
before you present — it is the part that decides the room.

---

## Before you start

```bash
make demo      # API :8000, console :5180
make smoke     # verify every path before anyone is watching
```

Open <http://localhost:5180>. The console opens on a cyclone already replaying.

**Port 5180, not 5173.** Vite defaults to 5173 and another project on this
machine owns it; `demo.sh` greps the served HTML for `CYCLOPS` and refuses to
start if something else answers.

**Rehearse the recovery path.** If the WebSocket drops the header badge goes
amber and recovers on its own. If it does not, click a different case chip —
that starts a fresh session. If the map fails, the console names the cause on
screen rather than showing a black rectangle; the rest of the console keeps
working.

---

## The 7-minute run

**0:00 — Open on Fani.** It is already playing. Let them watch a cyclone move
for ten seconds before explaining anything.

> "Cyclone Fani, May 2019, replayed hour by hour. Every forecast you see was
> made using only the data available at that moment in the storm's life."

**0:30 — The intensity panel.** Point at the interval bar, not the number.

> "It reads 97 knots, but the panel shows an interval, not a number. Nothing in
> this console displays a point estimate without its uncertainty. The convention
> is three-minute sustained wind, which is what IMD uses — JTWC uses one-minute
> and the two differ by about twelve percent, so getting that wrong inflates
> every storm by roughly a category."

**1:15 — The cone.**

> "The cone radius at each lead time is the circle enclosing two-thirds of this
> model's own validation errors — the NHC convention. We calibrated on validation
> storms and measured coverage on test storms, which are a disjoint set. It comes
> out at 66 to 69 percent against a 67 percent target."

**2:00 — Performance button.** One click, not a narration.

> "Against persistence and climatology on 31 held-out storms. Intensity is
> 34 percent better than persistence at 24 hours. Track is 11 percent. That gap
> is the most interesting thing here and I'll come back to it."

**2:45 — Real data view.** Click **"Fani · real data"**. This is the strongest
part of the demo.

> "This is real MODIS Band 31 — the 11 micron thermal channel Dvorak analysis is
> actually performed on — from NASA GIBS. No synthetic imagery anywhere in this
> view. GIBS serves it as PNG with a published colormap, and inverting that
> colormap recovers brightness temperature in kelvin exactly: 255 palette
> entries, every pixel matches one."

Scrub to 2 May. The eye is unmistakable.

> "The system finds the centre by looking for an eye: a warm core enclosed by
> cold convection at every azimuth, sitting at the centre of a radially organised
> storm. Both conditions, because enclosure alone fires on cloud edges. Here it
> lands 19 kilometres from best track. The rule that produced the intensity is
> printed underneath — you can argue with it, which you cannot do with a network."

**4:00 — The out-of-sample test.** Switch to Amphan, then Mocha. Point at the
picker labels.

> "The eye thresholds were chosen by looking at Fani. Amphan and Mocha were run
> with those thresholds unchanged — that's what the labels mean. The bias comes
> out at plus eleven, plus eleven, plus nine knots on three independent storms.
> That's a real transferable property, and it's consistent with Dvorak's
> Atlantic-tuned tables against IMD's North Indian Ocean adjustments — which we
> predicted in the code before we measured it."

**5:00 — The honest part.** This is the slide that wins the room.

> "Three things I want to be straight about.
>
> Our centre-fixing does not beat motion extrapolation — plus fifteen percent,
> minus one, minus seven. It does beat the last best-track fix by fifty to sixty
> percent on all three, and that's the claim we'd defend.
>
> We chased why. The eye fix has an error floor of about thirteen kilometres
> from pixel size and overpass-time uncertainty alone. The first guess is already
> good to ten or twenty. There's almost no headroom — and both those terms come
> from MODIS being polar-orbiting.
>
> So the ceiling is temporal, not algorithmic."

**5:45 — INSAT.** This is where the honesty pays off.

> "Which is exactly what INSAT-3D fixes. It's geostationary — a look every thirty
> minutes with a published timestamp instead of one we estimate to plus or minus
> thirty minutes. Over Fani's window MOSDAC holds one thousand nine hundred and
> forty-seven granules against our eighteen MODIS passes.
>
> Search is working now, no account needed. The HDF5 reader is written and
> tested. The pipeline picks INSAT automatically the moment granules appear. The
> only thing missing is the account, which is a registration form."

**6:30 — Close on scope.** Point at the footer.

> "It's a decision-support aid. IMD remains the sole warning authority for this
> basin. That line is on screen the whole time, not in an About page."

---

## Q&A bank

**"How did you split your data?"**
By season, storm IDs disjoint — `test_split_integrity` fails the build if any
storm appears in two splits, and includes a test that the guard itself fires.
Frames of one cyclone are near-duplicates; frame-level splitting would put the
same storm in train and test and inflate everything. Test seasons are 2019, 2020
and 2023, so Fani, Amphan and Mocha are genuinely held out.

**"How do I know you didn't forecast with hindsight?"**
`test_replay_causality`. It drives a full replay through a spying data store and
asserts every read was bounded by the storm clock. The `until` filter is applied
in the store's query, not in application code, so a refactor cannot silently drop
it. Happy to run it now.

**"What's your ground truth?"**
IBTrACS best track, `NEWDELHI_WIND` — IMD's three-minute convention. Worth being
precise: there is no aircraft reconnaissance in the North Indian Ocean, so
best-track intensity is itself largely a satellite estimate, often a Dvorak
estimate by a human analyst. We reproduce a skilled analyst, not physical truth.
That also caps our honest accuracy claim.

**"Is the imagery real?"**
For Fani, Amphan and Mocha in the real-data view — yes, MODIS Band 31 via NASA
GIBS, no registration required. The fusion CNN still trains on synthetic imagery
because Digital Typhoon needs registration; that number is labelled as a pipeline
check, not a satellite skill claim.

**"Your Dvorak RMSE is 28 knots. That's poor."**
It is. Objective Dvorak on single polar-orbiter passes is a ~28 kt estimator, and
operational systems need 10–15. Two things in our favour: the bias is a stable
+9 to +11 kt across three storms, so it is correctable in principle; and the
scatter that dominates is largely the timing and resolution problem INSAT fixes.
We would not present this as an operational intensity estimator today.

**"Why rule-based Dvorak instead of a CNN?"**
Eighteen scenes. A network trained on those memorises them and any accuracy
figure is meaningless. The rule-based estimator also prints the rule that
produced each number, which a forecaster can argue with.

**"Why did Mocha find no eyes?"**
The symmetry gate rejected them — Mocha had a compact eye inside a lopsided outer
cloud shield, and the gate scores symmetry at 30–250 km. But it was right for the
wrong reason: forcing those candidates through would have made the centre fix
worse in two of three cases. Written up in `docs/FINDING-eye-detection.md`.

**"Are your thresholds overfit to Fani?"**
Partly, and we say so. Two eye-gate values were chosen by inspecting Fani. We
then ran them unchanged on Amphan and Mocha — the picker labels which is which.
Behaviour held: the gate stayed conservative, did not misfire, and on Amphan's
eye scenes cut centre error from 33 km to 11 km.

**"Why not classify categories directly?"**
Cross-entropy treats confusing Super Cyclonic Storm with Depression as no worse
than with ESCS, which is physically absurd. The boundaries are human conventions —
47 kt is CS and 48 is SCS. And SuCS is rare enough that a classifier learns never
to predict it. We regress knots and bucket, which also makes our RMSE comparable
to the ADT literature.

**"Why late fusion?"**
The modalities do not share a grid. Infrared is 4 km every 15–30 minutes from
geostationary orbit; a scatterometer is 12.5–25 km twice a day from a polar
orbiter. Resampling 25 km winds onto a 4 km grid fabricates detail nobody
measured.

**"How do you handle the temporal mismatch between the two?"**
Modality dropout at p=0.3: we randomly hide the wind branch on samples that do
have wind, so the model learns to work without it. The branch has a learned
"missing" embedding rather than a zero tensor, so absence is a state it
recognises rather than something it reads as a very calm ocean.

**"Only 11% better than persistence on track — isn't that weak?"**
It is modest and we report it rather than hide it. Persistence is a genuinely
strong short-horizon baseline; beating it by 90% would mean we had a bug. The
diagnosis is specific: our steering flow is climatological. That is what
WeatherNext 2 fixes, and why the environment layer is an interface.

**"What happens if the network goes down?"**
Nothing. The basemap is a bundled Natural Earth extract, no tile server, no API
token, and the models are on disk. Unplug the cable and try it.

**"Is SCATSAT-1 in this?"**
Only as a historical archive — its last contact was 28 February 2021. The live
Indian wind path is OSCAT-3 on Oceansat-3; ASCAT on MetOp-B/C is our primary
because it is public and unregistered.

**"What would you do with three more months?"**
In order: the MOSDAC and WeatherNext 2 access that is already filed; fetch real
INSAT granules and re-run — the pipeline needs no changes and that is the
experiment that tests whether removing the timing error lets centre-fixing beat
motion extrapolation; swap synthetic training imagery for Digital Typhoon; then
the piece I actually think is novel, conditioning cone width on ensemble spread
so uncertainty is per-case rather than per-lead-time.

---

## Things not to say

- Any accuracy number without saying which data it came from.
- "97% accurate." Report the confusion matrix and which categories confuse.
- That it replaces or competes with IMD forecasts.
- That WeatherNext 2 is integrated. It is *implemented and pending access*.
- That INSAT is producing results. Search works, the reader is tested, downloads
  need an account.
- That the fusion ablation numbers are satellite skill. That imagery is synthetic.

---

## Failure drills — rehearse these

| failure | recovery |
|---|---|
| WebSocket drops | Badge shows RECONNECTING and recovers; if not, click another case chip |
| API not running | `make demo` again; check `.run/api.log` |
| Map blank | The console names the cause on screen. Hard-reload (Cmd/Ctrl+Shift+R) clears a stale bundle; everything else keeps working |
| Console shows another app | You are on 5173. Use **5180** |
| Real-data view empty | `make cases` has not been run, or `artifacts/*_analysis.json` is missing |
| Asked for a metric you don't have | "That's in `artifacts/`, let me pull it up" — do not guess |

---

## One-command reference

```bash
make demo            # API + console
make smoke           # verify a running stack
make cases           # re-run the three real-imagery storms
make eval            # print the results table
make test            # 68 tests
make insat-status    # INSAT access
make insat-demo      # INSAT pipeline on synthetic granules
make validate-map    # map style + basemap, no browser needed
```
