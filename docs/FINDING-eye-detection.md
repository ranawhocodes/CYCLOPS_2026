# Why Mocha never detected an eye

Mocha (2023) returned zero eye detections across all 12 day passes, while Fani
got 1/18 and Amphan 2/12. Mocha had a well-defined eye at peak, so this looked
like a detector failure. It is more interesting than that.

## The mechanical answer

The outer-field symmetry gate rejected them.

`find_centre` accepts an eye only when it is (a) enclosed by cold convection at
every azimuth and (b) sits at a centre scoring `EYE_MIN_SYMMETRY >= 0.35`, where
symmetry is the fraction of brightness-temperature variance explained by radius,
sampled over **30–250 km**.

Mocha's candidates at peak:

| pass | truth | eye contrast | symmetry | verdict |
|---|---|---|---|---|
| 13 May 04:33 | 104 kt | **50 °C** | **0.06** | rejected on symmetry |
| 13 May 07:33 | 106 kt | 18 °C | 0.26 | rejected on symmetry |
| 14 May 04:33 | 104 kt | 13 °C | 0.44 | rejected on contrast |
| 14 May 07:33 | 94 kt | 13 °C | 0.46 | rejected on contrast |

The 13 May 04:33 scene has a 50 °C eye-to-eyewall contrast — an unambiguous
cleared eye — and the candidate sits 27 km from best track. It was rejected
because the **outer** cloud shield was lopsided, which is a property of the
shield, not of the eye. Sampling from 10 km instead of 30 km barely moves the
score (0.06 → 0.10), so this is genuine outer-field asymmetry, not a resolution
artefact.

By 14 May the eye had filled: core brightness temperature is −65 °C, which is
still deep convection, not a cleared eye. Mocha crossed the coast near Sittwe
around 14 May 06:00–08:30 UTC, so those two passes bracket landfall. Rejecting
them is correct.

## The more useful answer: it was right, for the wrong reason

Forcing Mocha's rejected candidates through would have made its centre fix
**worse**, not better. For the three Mocha candidates that clear the contrast
gate and sit within 60 km of the first guess:

| pass | eye fix | first guess | better? |
|---|---|---|---|
| 12 May 07:33 | 36.9 km | 4.0 km | guess |
| 13 May 04:33 | 24.1 km | 59.4 km | **eye** |
| 13 May 07:33 | 45.1 km | 9.1 km | guess |

Two of three would have degraded the answer. The symmetry gate was suppressing
refinements that should be suppressed — but via a quantity that has nothing to
do with why they should be.

## Root cause

**The eye fix has an error floor comparable to the thing it is trying to improve.**

| source | contribution |
|---|---|
| 4 km/px nearest-neighbour centring | ~4–6 km |
| ±30 min overpass-time estimate × ~12 kt translation | ~11 km |
| quadrature floor | ~12–13 km |
| observed mean eye-fix error | ~33 km |

The motion-extrapolated first guess is typically accurate to 10–20 km. There is
almost no headroom. Pooled across all three storms, on candidates within 60 km of
the guess:

- when the guess error is **> 20 km** (n=3): eye 13.5 km vs guess 42.1 km, **+68%**
- when the guess error is **<= 20 km** (n=5): eye 45.5 km vs guess 10.6 km, **−329%**

Small n, so this is a mechanism with supporting evidence rather than a
calibrated rule. But it explains the aggregate result directly: centre-fix skill
against the first guess was −7%, +15%, −1% across the three storms, which is
what "a refinement whose floor matches the baseline's error" looks like.

It also explains why the eye fix wins big exactly where it should: Amphan
18 May 04:43 (guess 46.7 km → eye 8.2 km) and Mocha 13 May 04:43 (guess 59.4 km
→ eye 24.1 km) are the two cases where the guess had gone stale.

## What follows

1. **Do not relax the symmetry gate to "fix" Mocha.** It would admit refinements
   that are worse than the baseline.
2. **The gate is measuring the wrong thing**, even though it gets the right
   answer here. A plausibility check on distance from the first guess is the
   physically direct statement of the constraint — a cyclone eye is not 150 km
   from a motion-extrapolated position — and the empirical gap looked clean:
   candidates cluster at ≤59 km then jump to ≥88 km.

   **It was added, and measured, and it turns out to be redundant.** Across all
   three storms, of the candidates that clear the contrast gate: 3 pass both
   gates, 4 are rejected by symmetry alone, **0 are rejected by distance alone**,
   and 12 fail both. On this evidence the distance guard never catches anything
   symmetry does not already catch.

   It is kept as a cheap, physically meaningful bound — it encodes the real
   constraint rather than a proxy, and it would still hold on a storm where the
   symmetry accident does not — but it earns no credit for the current numbers
   and is not presented as an improvement.
3. **The real ceiling is temporal, not algorithmic.** Both dominant error terms
   come from MODIS being polar-orbiting: 4 km sampling and an *estimated*
   overpass time. Geostationary INSAT-3D at 15-minute cadence with a published
   timestamp removes both, and is the change that would actually make IR
   centre-fixing beat motion extrapolation.
4. **Report the defensible claim.** Against the last best-track fix the method
   wins by 51–60% on all three storms. Against motion extrapolation it is a wash.
   The second number is the honest headline.

## Reproduce

```bash
make cases
```
