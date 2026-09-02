import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useStore } from "../store";
import { catColor } from "../lib/imd";
import { WindParticles } from "./WindParticles";
import { MapStatus } from "./MapStatus";

/**
 * Full-bleed map.
 *
 * No tile server, no access token, no network call. Land and boundary geometry
 * is a clipped Natural Earth extract bundled with the app (~250 KB). A Mapbox
 * token would mean a network call, and a venue behind a captive portal would
 * leave a grey rectangle on screen with nothing to be done in the moment.
 *
 * Layer order, bottom to top: ocean, land, coast, boundaries, IR imagery, cone,
 * tracks, points, wind particles (separate canvas). Imagery sits under the
 * vector layers so the track stays readable over bright cloud.
 */
// No `glyphs` key at all: MapLibre validates it as a string when present, and
// an explicit `undefined` fails the check. There are no symbol layers here, so
// no glyph source is needed — which also means no font fetch, keeping the map
// fully offline.
const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    land: { type: "geojson", data: "/basemap/nio-land.geojson" },
    bounds: { type: "geojson", data: "/basemap/nio-boundaries.geojson" },
  },
  layers: [
    { id: "ocean", type: "background", paint: { "background-color": "#04090f" } },
    {
      id: "land",
      type: "fill",
      source: "land",
      paint: { "fill-color": "#0c1620", "fill-outline-color": "#1d3040" },
    },
    {
      id: "coast",
      type: "line",
      source: "land",
      paint: { "line-color": "#2f4d63", "line-width": 0.9 },
    },
    {
      id: "bounds",
      type: "line",
      source: "bounds",
      paint: { "line-color": "#1d3040", "line-width": 0.6, "line-dasharray": [3, 2] },
    },
  ],
};

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
// A 1x1 transparent pixel, so the imagery source exists from map load and each
// new frame is an updateImage() rather than an addSource/removeSource cycle --
// which would flash on every replay step.
const BLANK =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

export function MapView() {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  // State, not just the ref, so MapStatus re-runs its checks once the map exists.
  const [mapInstance, setMapInstance] = useState<maplibregl.Map | null>(null);
  const followed = useRef<string | null>(null);

  const observed = useStore((s) => s.observed);
  const nowcast = useStore((s) => s.nowcast);
  const classify = useStore((s) => s.classify);
  const georefUrl = useStore((s) => s.georefUrl);
  const windGrid = useStore((s) => s.windGrid);
  const layers = useStore((s) => s.layers);
  const activeCase = useStore((s) => s.activeCase);

  useEffect(() => {
    if (!ref.current || map.current) return;
    const m = new maplibregl.Map({
      container: ref.current,
      style: STYLE,
      center: [86, 15],
      zoom: 4.2,
      attributionControl: false,
      dragRotate: false,
      maxZoom: 9,
      minZoom: 2.5,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    m.on("load", () => {
      m.addSource("ir", { type: "image", url: BLANK, coordinates: [
        [80, 20], [90, 20], [90, 10], [80, 10],
      ] });
      m.addLayer({
        id: "ir-layer",
        type: "raster",
        source: "ir",
        // The renderer already carries alpha per pixel, so this should not dim
        // it a second time — at 0.82 with the old weak ramp the storm was a grey
        // smudge. Held slightly under 1.0 so the flow layer above still reads
        // over the brightest cloud, where the strongest winds are.
        paint: { "raster-opacity": 0.88, "raster-fade-duration": 220 },
      });

      m.addSource("cone", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "cone-fill", type: "fill", source: "cone",
        paint: { "fill-color": "#35C4E8", "fill-opacity": 0.13 } });
      m.addLayer({ id: "cone-line", type: "line", source: "cone",
        paint: { "line-color": "#35C4E8", "line-opacity": 0.55, "line-width": 1.2 } });

      m.addSource("observed", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "observed-line", type: "line", source: "observed",
        paint: { "line-color": "#E4EEF6", "line-width": 2, "line-opacity": 0.9 } });

      // Forecast is dashed and a different hue. If a judge cannot tell at a
      // glance which part of the line is a forecast, the map is misleading.
      m.addSource("forecast", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "forecast-line", type: "line", source: "forecast",
        paint: { "line-color": "#F2C63D", "line-width": 2.2,
                 "line-dasharray": [2, 1.6], "line-opacity": 0.95 } });

      m.addSource("points", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "points-c", type: "circle", source: "points",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "kt"], 20, 3, 140, 8.5],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#04090f",
          "circle-stroke-width": 1,
        } });

      m.addSource("fcpoints", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "fcpoints-c", type: "circle", source: "fcpoints",
        paint: {
          "circle-radius": 4.5, "circle-color": "#04090f",
          "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2,
        } });

      m.addSource("now", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "now-halo", type: "circle", source: "now",
        paint: { "circle-radius": 20, "circle-color": ["get", "color"],
                 "circle-opacity": 0.16 } });
      m.addLayer({ id: "now-c", type: "circle", source: "now",
        paint: { "circle-radius": 6, "circle-color": ["get", "color"],
                 "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 1.5 } });

      m.resize();
      setReady(true);
    });

    // Dev-only handle so the map can be inspected from the browser console.
    // Stripped from production builds by the bundler's dead-code elimination.
    if (import.meta.env.DEV) (window as unknown as Record<string, unknown>).__map = m;

    // MapLibre measures the container at construction. Under React 18 the
    // effect runs before the flex/absolute layout has settled, so it can latch
    // onto the 400x300 fallback and never correct itself — a full-bleed map that
    // silently renders at a quarter size. A ResizeObserver fixes both the
    // initial measurement and later window changes.
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(ref.current);

    map.current = m;
    setMapInstance(m);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
      setMapInstance(null);
      setReady(false);
    };
  }, []);

  // -- layer visibility toggles -----------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const set = (id: string, on: boolean) => {
      if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    };
    set("ir-layer", layers.satellite);
    set("cone-fill", layers.cone);
    set("cone-line", layers.cone);
    set("forecast-line", layers.forecast);
    set("fcpoints-c", layers.forecast);
    set("observed-line", layers.track);
    set("points-c", layers.track);
  }, [layers, ready]);

  // -- georeferenced infrared imagery ------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const src = m.getSource("ir") as maplibregl.ImageSource | undefined;
    const corners = classify?.frame_corners;
    if (!src || !georefUrl || !corners || corners.length !== 4) return;

    // Decode before handing the bitmap to MapLibre. updateImage with a URL that
    // has not loaded yet leaves the previous frame on screen for a beat, which
    // during a fast replay shows imagery one step behind the track.
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const [tl, tr, br, bl] = corners;
        src.setCoordinates([tl, tr, br, bl]);
        src.updateImage({ url: georefUrl });
      } catch {
        /* source torn down mid-flight during a case switch */
      }
    };
    img.src = georefUrl;
  }, [georefUrl, classify?.frame_corners, ready]);

  // -- observed track ----------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const src = m.getSource("observed") as maplibregl.GeoJSONSource | undefined;
    const pts = m.getSource("points") as maplibregl.GeoJSONSource | undefined;
    if (!src || !pts) return;

    const coords = observed.map((p) => [p.lon, p.lat] as [number, number]);
    src.setData(
      coords.length > 1
        ? { type: "Feature", properties: {},
            geometry: { type: "LineString", coordinates: coords } }
        : EMPTY
    );
    pts.setData({
      type: "FeatureCollection",
      features: observed.map((p) => ({
        type: "Feature",
        properties: { kt: p.wind_kt, color: catColor(p.imd_category) },
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      })),
    });

    const last = observed[observed.length - 1];
    if (last) {
      (m.getSource("now") as maplibregl.GeoJSONSource)?.setData({
        type: "Feature",
        properties: { color: catColor(classify?.imd_category ?? last.imd_category) },
        geometry: { type: "Point", coordinates: [last.lon, last.lat] },
      });
      // Keep the storm framed.
      //
      // Three attempts got here. Recentring on every step jittered. Recentring
      // only on a case change lost the storm completely — Fani travels about 20
      // degrees of latitude, so it walked off the top of the screen and took the
      // imagery and the wind field with it. A "only when it leaves the middle
      // third" test still drifted several degrees at the ends of the track,
      // because a scrub can move the storm further in one step than the margin.
      //
      // So the camera simply follows the subject, eased, and offset left of
      // centre because the right rail covers roughly a third of the canvas. A
      // long jump (scrubbing) snaps instead of easing, since a two-second glide
      // across the basin is worse than an instant cut.
      const target: [number, number] = [last.lon, last.lat];
      const c = m.getCenter();
      const drift = Math.hypot(c.lng - target[0], c.lat - target[1]);
      const firstFix = followed.current !== activeCase?.id;

      if (activeCase && (firstFix || drift > 0.25)) {
        // Shift the look-at point so the storm sits in the clear left-of-centre
        // area rather than under the rail.
        const { width: w } = m.getContainer().getBoundingClientRect();
        const px = m.project(target);
        px.x += w * 0.16;
        const shifted = m.unproject(px);

        if (firstFix) {
          followed.current = activeCase.id;
          m.easeTo({ center: shifted, zoom: 5.0, duration: 900, essential: true });
        } else if (drift > 4) {
          m.jumpTo({ center: shifted });
        } else {
          m.easeTo({ center: shifted, duration: 700, essential: true });
        }
      }
    }
  }, [observed, classify, ready, activeCase]);

  // -- forecast and cone -------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const cone = m.getSource("cone") as maplibregl.GeoJSONSource | undefined;
    const fc = m.getSource("forecast") as maplibregl.GeoJSONSource | undefined;
    const fp = m.getSource("fcpoints") as maplibregl.GeoJSONSource | undefined;
    if (!cone || !fc || !fp) return;

    if (!nowcast?.forecasts?.length) {
      cone.setData(EMPTY); fc.setData(EMPTY); fp.setData(EMPTY);
      return;
    }

    cone.setData(
      nowcast.cone?.length > 3
        ? { type: "Feature", properties: {},
            geometry: { type: "Polygon", coordinates: [nowcast.cone] } }
        : EMPTY
    );

    const here = observed[observed.length - 1];
    const path: [number, number][] = [
      ...(here ? [[here.lon, here.lat] as [number, number]] : []),
      ...nowcast.forecasts.map((f) => [f.position.lon, f.position.lat] as [number, number]),
    ];
    fc.setData(
      path.length > 1
        ? { type: "Feature", properties: {},
            geometry: { type: "LineString", coordinates: path } }
        : EMPTY
    );
    fp.setData({
      type: "FeatureCollection",
      features: nowcast.forecasts.map((f) => ({
        type: "Feature",
        properties: { color: catColor(f.imd_category), lead: f.lead_h },
        geometry: { type: "Point", coordinates: [f.position.lon, f.position.lat] },
      })),
    });
  }, [nowcast, observed, ready]);

  return (
    <div className="map-root">
      <div ref={ref} className="map" role="img"
           aria-label="Cyclone track map with satellite imagery, forecast and uncertainty cone" />
      <WindParticles map={mapInstance} grid={windGrid} visible={layers.wind} />
      <MapStatus map={mapInstance} />
    </div>
  );
}
