import { useCallback, useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useStore } from "../store";
import { catColor } from "../lib/imd";

/**
 * Fully offline map.
 *
 * No tile server, no access token, no network call. The land and boundary
 * geometry is a clipped Natural Earth extract bundled with the app (~250 KB).
 * A Mapbox token would mean a network call, and a venue with a captive portal
 * would leave a grey rectangle on screen in front of judges with nothing to be
 * done about it in the moment.
 */
// A FUNCTION, not a shared constant. MapLibre mutates the style object it is
// handed — it attaches internal state during load. React StrictMode mounts,
// unmounts and remounts in development, so a module-level constant would be
// passed to the second map already consumed by the first, and that map's style
// never finishes loading: no error, no layers, just a blank canvas. Every map
// gets its own object.
const makeStyle = (): maplibregl.StyleSpecification => ({
  version: 8,
  // No `glyphs` key at all. MapLibre validates the style and rejects an
  // explicit `undefined`; omitting it is correct because none of the layers
  // below render text, so no font stack is ever needed. Keeping it out also
  // means no glyph server to reach — part of staying fully offline.
  sources: {
    land: { type: "geojson", data: "/basemap/nio-land.geojson" },
    bounds: { type: "geojson", data: "/basemap/nio-boundaries.geojson" },
  },
  layers: [
    { id: "ocean", type: "background", paint: { "background-color": "#071018" } },
    { id: "land", type: "fill", source: "land",
      paint: { "fill-color": "#0E1B26", "fill-outline-color": "#22384A" } },
    { id: "coast", type: "line", source: "land",
      paint: { "line-color": "#2A4457", "line-width": 0.9 } },
    { id: "bounds", type: "line", source: "bounds",
      paint: { "line-color": "#22384A", "line-width": 0.6, "line-dasharray": [3, 2] } },
  ],
});

// Same reasoning as makeStyle: a fresh object per call, never a shared literal
// handed repeatedly to MapLibre sources.
const empty = (): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features: [] });

export function MapView() {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);

  const observed = useStore((s) => s.observed);
  const nowcast = useStore((s) => s.nowcast);
  const classify = useStore((s) => s.classify);
  const redraw = useRef<(() => void) | null>(null);
  // Once the presenter pans or zooms deliberately, stop auto-fitting the view —
  // fighting the user for control of the camera mid-demo looks broken.
  const userMoved = useRef(false);

  useEffect(() => {
    if (!ref.current || map.current) return;
    const m = new maplibregl.Map({
      container: ref.current,
      style: makeStyle(),
      center: [85, 15],
      zoom: 3.6,
      attributionControl: false,
      dragRotate: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // Dev-only handle, set immediately rather than inside `load`, so a style
    // that fails to load can still be inspected from the browser console.
    if (import.meta.env.DEV) (window as any).__cyclopsMap = m;
    m.on("error", (e: any) => console.error("[maplibre]", e?.error?.message ?? e));
    m.on("dragstart", () => { userMoved.current = true; });
    m.on("zoomstart", (e: any) => { if (e.originalEvent) userMoved.current = true; });
    m.on("load", () => {
      // Cone first so tracks and markers draw over it.
      m.addSource("cone", { type: "geojson", data: empty() });
      m.addLayer({ id: "cone-fill", type: "fill", source: "cone",
        paint: { "fill-color": "#35C4E8", "fill-opacity": 0.15 } });
      m.addLayer({ id: "cone-line", type: "line", source: "cone",
        paint: { "line-color": "#35C4E8", "line-opacity": 0.5, "line-width": 1.2 } });

      m.addSource("observed", { type: "geojson", data: empty() });
      m.addLayer({ id: "observed-line", type: "line", source: "observed",
        paint: { "line-color": "#D6E4EE", "line-width": 2, "line-opacity": 0.85 } });

      // Forecast is dashed and a different hue. If a judge cannot tell at a
      // glance which part of the line is a forecast, the map is misleading.
      m.addSource("forecast", { type: "geojson", data: empty() });
      m.addLayer({ id: "forecast-line", type: "line", source: "forecast",
        paint: { "line-color": "#F2C63D", "line-width": 2.2,
                 "line-dasharray": [2, 1.6] } });

      m.addSource("points", { type: "geojson", data: empty() });
      m.addLayer({ id: "points-c", type: "circle", source: "points",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "kt"], 20, 3.2, 140, 9],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#071018", "circle-stroke-width": 1,
        } });

      m.addSource("fcpoints", { type: "geojson", data: empty() });
      m.addLayer({ id: "fcpoints-c", type: "circle", source: "fcpoints",
        paint: {
          "circle-radius": 4.5, "circle-color": "#071018",
          "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2,
        } });

      m.addSource("now", { type: "geojson", data: empty() });
      m.addLayer({ id: "now-halo", type: "circle", source: "now",
        paint: { "circle-radius": 16, "circle-color": ["get", "color"],
                 "circle-opacity": 0.18 } });
      m.addLayer({ id: "now-c", type: "circle", source: "now",
        paint: { "circle-radius": 6, "circle-color": ["get", "color"],
                 "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 1.5 } });

      ready.current = true;
      // Draw whatever has already arrived. Track data can land before the style
      // finishes loading, and the data effects below bail out while the map is
      // not ready — without this the first frames are silently dropped and the
      // track only appears after the next WebSocket message.
      redraw.current?.();
    });
    map.current = m;
    return () => { m.remove(); map.current = null; ready.current = false; };
  }, []);

  // -- draw everything -------------------------------------------------
  // One draw function rather than two effects, held in a ref so the style's
  // `load` handler can call it too. Track data routinely arrives before the
  // style finishes loading; without that call the first frames are dropped and
  // the track only appears once the next WebSocket message lands.
  const draw = useCallback(() => {
    const m = map.current;
    if (!m || !ready.current) return;

    const src = (id: string) => m.getSource(id) as maplibregl.GeoJSONSource | undefined;

    // --- observed track ---
    const coords = observed.map((p) => [p.lon, p.lat] as [number, number]);
    src("observed")?.setData(
      coords.length > 1
        ? { type: "Feature", properties: {},
            geometry: { type: "LineString", coordinates: coords } }
        : empty()
    );
    src("points")?.setData({
      type: "FeatureCollection",
      features: observed.map((p) => ({
        type: "Feature",
        properties: { kt: p.wind_kt, color: catColor(p.imd_category) },
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      })),
    });

    const last = observed[observed.length - 1];
    if (last) {
      src("now")?.setData({
        type: "Feature",
        properties: { color: catColor(classify?.imd_category ?? last.imd_category) },
        geometry: { type: "Point", coordinates: [last.lon, last.lat] },
      });
    }

    // --- forecast and cone ---
    if (!nowcast?.forecasts?.length) {
      src("cone")?.setData(empty());
      src("forecast")?.setData(empty());
      src("fcpoints")?.setData(empty());
    } else {
      src("cone")?.setData(
        nowcast.cone?.length > 3
          ? { type: "Feature", properties: {},
              geometry: { type: "Polygon", coordinates: [nowcast.cone] } }
          : empty()
      );
      const path: [number, number][] = [
        ...(last ? [[last.lon, last.lat] as [number, number]] : []),
        ...nowcast.forecasts.map(
          (f) => [f.position.lon, f.position.lat] as [number, number]
        ),
      ];
      src("forecast")?.setData(
        path.length > 1
          ? { type: "Feature", properties: {},
              geometry: { type: "LineString", coordinates: path } }
          : empty()
      );
      src("fcpoints")?.setData({
        type: "FeatureCollection",
        features: nowcast.forecasts.map((f) => ({
          type: "Feature",
          properties: { color: catColor(f.imd_category), lead: f.lead_h },
          geometry: { type: "Point", coordinates: [f.position.lon, f.position.lat] },
        })),
      });
    }

    // --- keep the storm and its cone in view ---
    // Fit to the whole picture rather than centring on the last fix, so the
    // cone is never half off-screen and the track history stays visible.
    const all: [number, number][] = [
      ...coords,
      ...(nowcast?.forecasts ?? []).map(
        (f) => [f.position.lon, f.position.lat] as [number, number]
      ),
      ...((nowcast?.cone ?? []) as [number, number][]),
    ];
    if (all.length >= 2 && !userMoved.current) {
      const lons = all.map((c) => c[0]);
      const lats = all.map((c) => c[1]);
      m.fitBounds(
        [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
        { padding: 90, maxZoom: 6.5, duration: 500 }
      );
    }
  }, [observed, nowcast, classify]);

  redraw.current = draw;
  useEffect(() => { draw(); }, [draw]);

  return (
    <div className="map-wrap">
      <div ref={ref} className="map" role="img"
           aria-label="Cyclone track map with forecast and uncertainty cone" />
      <MapLegend />
    </div>
  );
}

function MapLegend() {
  const nowcast = useStore((s) => s.nowcast);
  const cov = nowcast?.cone_measured_coverage ?? {};
  const cov24 = cov["24"];
  return (
    <div className="legend">
      <div className="legend-row"><span className="sw sw-observed" /> Observed best track</div>
      <div className="legend-row"><span className="sw sw-forecast" /> CYCLOPS forecast</div>
      <div className="legend-row">
        <span className="sw sw-cone" /> 67% uncertainty cone
        {cov24 !== undefined && (
          <em title="Fraction of held-out truth positions inside the cone at 24 h">
            {" "}· measured {(cov24 * 100).toFixed(0)}%
          </em>
        )}
      </div>
    </div>
  );
}
