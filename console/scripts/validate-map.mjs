/**
 * Validate the map style and its bundled basemap without a browser.
 *
 * MapLibre only reports a bad style at runtime, and only once something paints.
 * That is a poor place to find out: a headless CI box, a hidden tab, or any
 * environment where requestAnimationFrame never fires will silently render an
 * empty map with no error. This check runs in Node, so a malformed style or a
 * missing basemap fails the build instead of the demo.
 *
 * Covers the failure modes that have actually bitten this project:
 *   - a style property set to `undefined` (MapLibre validates presence, not value)
 *   - a layer pointing at a source that no longer exists
 *   - a basemap file that is missing, unparseable, or has unclosed rings
 *   - geometry that does not intersect the map's initial view
 *
 * Run with `npm run validate:map`.
 */
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const fail = [];
const ok = (m) => console.log(`  ok    ${m}`);
const bad = (m) => { console.log(`  FAIL  ${m}`); fail.push(m); };

// -- 1. extract the STYLE literal from MapView.tsx -------------------------
const src = readFileSync(join(root, "src/components/MapView.tsx"), "utf8");
const start = src.indexOf("const STYLE");
if (start < 0) bad("no STYLE literal found in MapView.tsx");
const open = src.indexOf("{", start);
let depth = 0, end = -1;
for (let i = open; i < src.length; i++) {
  if (src[i] === "{") depth++;
  else if (src[i] === "}") { depth--; if (depth === 0) { end = i + 1; break; } }
}
const STYLE = eval("(" + src.slice(open, end) + ")");

// -- 2. spec validation ----------------------------------------------------
const errors = validateStyleMin(STYLE);
if (errors.length) errors.forEach((e) => bad(`style spec: ${e.message}`));
else ok(`style is spec-valid (${STYLE.layers.length} layers, ` +
        `${Object.keys(STYLE.sources).length} sources)`);

// An explicitly-undefined key passes a naive truthiness check but fails
// MapLibre's validator, which is how the map silently rendered blank once.
for (const [k, v] of Object.entries(STYLE)) {
  if (v === undefined) bad(`style key '${k}' is explicitly undefined — omit it instead`);
}

// -- 3. every layer's source exists ---------------------------------------
const dangling = STYLE.layers.filter((l) => l.source && !STYLE.sources[l.source]);
if (dangling.length) dangling.forEach((l) => bad(`layer '${l.id}' -> missing source '${l.source}'`));
else ok("every layer resolves to a declared source");

// -- 4. bundled basemap files are present and well-formed ------------------
// The map must work with no network at all, so every source has to be a local
// file that actually ships.
const view = { west: 35, east: 105, south: -5, north: 35 };
for (const [name, s] of Object.entries(STYLE.sources)) {
  if (s.type !== "geojson" || typeof s.data !== "string") continue;
  if (/^https?:/i.test(s.data)) { bad(`source '${name}' points at a remote URL: ${s.data}`); continue; }

  const path = join(root, "public", s.data.replace(/^\//, ""));
  if (!existsSync(path)) { bad(`source '${name}': missing file ${s.data}`); continue; }

  let gj;
  try { gj = JSON.parse(readFileSync(path, "utf8")); }
  catch (e) { bad(`source '${name}': unparseable JSON — ${e.message}`); continue; }

  const feats = gj.features ?? [];
  let rings = 0, unclosed = 0, degenerate = 0, intersecting = 0;
  for (const f of feats) {
    const g = f.geometry; if (!g) continue;
    const polys = g.type === "Polygon" ? [g.coordinates]
      : g.type === "MultiPolygon" ? g.coordinates
      : g.type === "LineString" ? [[g.coordinates]]
      : g.type === "MultiLineString" ? [g.coordinates] : [];
    const closedRequired = g.type === "Polygon" || g.type === "MultiPolygon";
    for (const poly of polys) for (const ring of poly) {
      rings++;
      if (ring.length < (closedRequired ? 4 : 2)) degenerate++;
      if (closedRequired) {
        const a = ring[0], b = ring[ring.length - 1];
        if (!a || !b || a[0] !== b[0] || a[1] !== b[1]) unclosed++;
      }
      const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
      if (Math.max(...xs) > view.west && Math.min(...xs) < view.east &&
          Math.max(...ys) > view.south && Math.min(...ys) < view.north) intersecting++;
    }
  }
  const kb = (readFileSync(path).length / 1024).toFixed(0);
  if (!feats.length) bad(`source '${name}': no features`);
  else if (degenerate) bad(`source '${name}': ${degenerate} degenerate rings`);
  else if (unclosed) bad(`source '${name}': ${unclosed} unclosed polygon rings`);
  else if (!intersecting) bad(`source '${name}': nothing intersects the basin view box`);
  else ok(`source '${name}': ${feats.length} features, ${rings} rings, ${kb} KB, local`);
}

console.log();
if (fail.length) { console.log(`map validation FAILED (${fail.length})`); process.exit(1); }
console.log("map validation passed");
