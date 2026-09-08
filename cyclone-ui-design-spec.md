# CYCLOPS UI — Industry-Grade Redesign Spec

For: coding agent implementing the frontend
Context: app backend (satellite ingestion, classification, nowcast) is solid. This spec only covers visual/UX — making it look like an operational meteorological tool (NHC / JTWC / CIRA-RAMMB class) instead of a generic AI dashboard.

---

## 1. Diagnosis of current UI (see attached screenshot)

1. **The "fake white air" problem**: a soft, glowing, translucent particle/streamline mass is rendered over the storm center. It doesn't encode any real data (no vector magnitude, no direction tied to an actual wind field) — it's decorative bloom. This is the single biggest thing making the app look "vibe-coded." Real particle-flow wind visualizations (e.g. earth.nullschool.net) work because every streak *is* a real wind vector at that point, rendered thin, low-opacity, and without glow/bloom. Decorative motion graphics without a 1:1 data mapping read as fake immediately to anyone who's seen a real weather tool.
2. **Track/uncertainty line is a dashed trail with floating circles**, not a proper forecast cone. Operational tools (NHC) show a continuously widening cone whose radius at each lead time equals the model's own historical position error — you're already computing this in your "cone R" nowcast table, it just isn't drawn on the map.
3. **Classification bar uses a generic 6-block gradient** ("Genesis / Intensifying / Inten... / Decay") instead of the actual IMD 8-step operational scale your own data uses (D / DD / CS / SCS / VSCS / ESCS / SuCS). Mismatched taxonomy between the bar and the actual classification label ("CS 45 kt") undercuts credibility.
4. **The storm itself is an abstract graphic, not satellite imagery.** Every real operational tool's central visual *is* the actual color-enhanced IR/microwave satellite frame — that's what carries the Dvorak signal in the first place. An abstract radial gradient can't be cross-checked by an expert user and looks synthetic.
5. General visual noise: glow effects, translucent overlays stacked on translucent overlays, no clear z-order of "map data" vs "chrome."

---

## 2. Reference tools (what to study, what to lift)

| Tool | URL | What to borrow |
|---|---|---|
| **CIRA/RAMMB TC Real-Time** | rammb-data.cira.colostate.edu/tc_realtime/ | Central visual = actual color-enhanced IR satellite loop on an earth-fixed Mercator grid, with a labeled temperature colorbar and Dvorak T-number stamped on the frame. This is the direct fix for your central graphic — swap the particle blob for your real MOSDAC/satellite frame, color-enhanced, with the T-number overlaid. |
| **NHC forecast cone graphic** | nhc.noaa.gov | The canonical "cone of uncertainty" — a continuously widening polygon along the track, built from each lead time's own historical error radius. You already have `cone R` numbers (36 km, 71 km, 116 km, 157 km) in your nowcast table — draw them as a filled cone, not separate circles. |
| **Windy.com hurricane tracker** | windy.com | Clean hairline panel dividers, restrained single-accent color, map-first layout with a slide-out data panel — good reference for overall chrome discipline. |
| **Zoom Earth** | zoomearth.com | How to composite a real satellite basemap with a storm track without visual clutter. |
| **earth.nullschool.net** | earth.nullschool.net | If you keep *any* particle/streamline effect, this is the reference implementation: real vector field, thin low-opacity strokes, zero glow/bloom, colored only by magnitude on a defined scale. |
| **Tropical Tidbits / model guidance** | tropicaltidbits.com | Ensemble "spaghetti" plot style and intensity-vs-time model comparison charts — useful if you want to show multiple model runs against your own estimate. |
| **IMD / MOSDAC** | mosdac.gov.in | Since your data is IMD-classed (3-min sustained wind, ESCS terminology), match their category taxonomy and standard color coding rather than inventing a new one — this is your actual domain authority, not a stylistic choice. |

---

## 3. IMD classification scale (use this exact taxonomy, not a generic gradient)

| Category | Abbrev | Wind speed (3-min sustained) |
|---|---|---|
| Low Pressure Area | L | < 17 kt |
| Depression | D | 17–27 kt |
| Deep Depression | DD | 28–33 kt |
| Cyclonic Storm | CS | 34–47 kt |
| Severe Cyclonic Storm | SCS | 48–63 kt |
| Very Severe Cyclonic Storm | VSCS | 64–89 kt |
| Extremely Severe Cyclonic Storm | ESCS | 90–119 kt |
| Super Cyclonic Storm | SuCS | ≥ 120 kt |

The classification bar component should have exactly these 8 segments, sized proportionally or evenly, with the current category highlighted — not the current "Genesis/Intensifying/Inten.../Decay" phase labels, which conflate *lifecycle stage* with *intensity category*. If you want to keep a lifecycle indicator (genesis → intensifying → peak → decay), show it as a **separate, smaller** element — don't merge two different taxonomies into one bar.

---

## 4. Concrete component specs

### 4.1 Central storm visual
- Replace the abstract radial-gradient + particle-streak graphic with the **actual satellite frame** (IR or enhanced IR from your MOSDAC/INSAT source), color-enhanced with a fixed temperature-to-color LUT (coldest cloud tops = brightest color, per standard IR enhancement curves — Google "IR satellite color enhancement curve" for the standard NHC/CIRA palette).
- Overlay: storm center marker, Dvorak T-number, and (optional, thin) radar-style range rings — no glow/blur/bloom filters.
- If real-time imagery isn't available for a given frame, show a clear "last available frame: [timestamp]" state rather than falling back to a decorative placeholder.

### 4.2 Forecast cone (replace dashed-line + circles)
- Draw a filled polygon: at each lead time (+6h, +12h, +18h, +24h...), plot the forecast position ± the cone radius from your nowcast table (36/71/116/157 km etc.), then connect the left and right edges into a continuous cone shape, widening with lead time.
- Track line (best track) stays a solid line through past positions; forecast segment is the cone; do not mix dashed-line-with-circles and cone in the same view — pick the cone.
- Low opacity fill (~15–20%), solid thin border.

### 4.3 Classification bar
- 8 fixed segments per IMD table above, each with its own hue (use a sequential scale, e.g. yellow → orange → red → dark red/magenta, matching IMD/WMO convention rather than arbitrary blues/golds).
- Current category: solid fill + a small marker/caret showing exact position within that band (since your model gives a continuous 26 kt estimate, not just the discrete bucket).
- Drop the "Genesis/Intensifying/Inten.../Decay" row from this component, or move it to a distinct, clearly separate lifecycle indicator.

### 4.4 Intensity trend chart / nowcast table
- These two are already close to industry standard (line chart + tabular forecast) — keep the structure, just:
  - Use tabular (monospaced) figures for all numeric columns so they align vertically.
  - Match line colors 1:1 with a legend that never changes meaning across the app (e.g. green = best track/observed always, blue = model estimate always, amber = forecast band always).

### 4.5 General chrome
- Background: near-black (#0a0d12 or similar), not pure black — matches CIRA/Windy/NHC dark modes.
- Panels: hairline 1px borders (low-opacity white/gray), not drop shadows or glow.
- One accent hue reserved for "live/selected" state (cyan works, matches your current choice) — don't also use glow/bloom on it.
- Red/orange reserved strictly for rate-of-change warnings (e.g. "▲20 kt/24h") and danger states — not decoration.
- Kill all box-shadow blur/glow effects on data elements; real ops tools are flat.
- Typography: tabular/monospaced numerals for all data readouts (kt, km, %, ms) — this alone does a lot to make a UI feel "instrument-grade" rather than "app-like."

---

## 5. Priority order for the agent

1. Swap central storm graphic: real color-enhanced satellite frame instead of particle/gradient blob. (Biggest visual credibility fix.)
2. Replace dashed-line/circle uncertainty indicator with a proper forecast cone built from existing cone-radius data.
3. Rebuild classification bar to the 8-step IMD scale; separate out any lifecycle-stage indicator.
4. Remove glow/blur/bloom filters app-wide; move to flat panels with hairline borders.
5. Switch all numeric displays to tabular/monospaced figures.
6. Polish: consistent color legend across track/trend chart/cone (green=observed, blue=model, amber=forecast).
