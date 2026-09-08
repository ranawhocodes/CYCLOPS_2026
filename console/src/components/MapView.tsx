import { useCallback, useEffect, useRef, useState } from "react";
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

function makeRing(lon: number, lat: number, km: number, pts = 48): [number, number][] {
  const coords: [number, number][] = [];
  const dLat = km / 111.0;
  const dLon = km / (111.0 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= pts; i++) {
    const a = (i / pts) * Math.PI * 2;
    coords.push([lon + Math.cos(a) * dLon, lat + Math.sin(a) * dLat]);
  }
  return coords;
}

export function MapView() {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const irGen = useRef(0);
  const appliedUrl = useRef<string | null>(null);
  // State, not just the ref, so MapStatus re-runs its checks once the map exists.
  const [mapInstance, setMapInstance] = useState<maplibregl.Map | null>(null);
  const followed = useRef<string | null>(null);
  const railOpen = useStore((s) => s.railOpen);
  const [autoFollow, setAutoFollow] = useState(true);
  const autoFollowRef = useRef(true);
  autoFollowRef.current = autoFollow;
  const lastCenteredPos = useRef<[number, number] | null>(null);

  const observed = useStore((s) => s.observed);
  const nowcast = useStore((s) => s.nowcast);
  const classify = useStore((s) => s.classify);
  const georefUrl = useStore((s) => s.georefUrl);
  const windGrid = useStore((s) => s.windGrid);
  const layers = useStore((s) => s.layers);
  const activeCase = useStore((s) => s.activeCase);
  const stormClock = useStore((s) => s.stormClock);

  const centerOnStorm = useCallback((lon: number, lat: number, snap = false) => {
    const m = map.current;
    if (!m) return;
    const { width: w, height: h } = m.getContainer().getBoundingClientRect();
    const px = m.project([lon, lat]);
    // Clear area: Right rail is 336px when open. Desired horizontal position is centered in open area:
    const desiredX = (w - (railOpen ? 336 : 0)) / 2;
    // Desired vertical position: elevated to middle (h * 0.48) so northward forecast cone has full clearance:
    const desiredY = h * 0.48;
    const shifted = m.unproject([
      px.x + (w / 2 - desiredX),
      px.y + (h / 2 - desiredY),
    ]);

    if (snap) {
      m.jumpTo({ center: shifted, zoom: 5.0 });
    } else {
      m.easeTo({ center: shifted, duration: 650, essential: true });
    }
    lastCenteredPos.current = [lon, lat];
  }, [railOpen]);

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

    // Allow user to pan and inspect freely without the camera hijacking their view
    m.on("dragstart", () => {
      setAutoFollow(false);
    });
    m.on("zoomstart", (e) => {
      if ((e as any).originalEvent) setAutoFollow(false);
    });

    // Superseding an image source's in-flight request makes MapLibre abort it.
    // That is the intended outcome of showing the newest frame, not an error, so
    // it is filtered rather than left to spam the console during a fast replay.
    m.on("error", (e) => {
      const msg = String((e as { error?: Error }).error?.message ?? "");
      const name = String((e as { error?: Error }).error?.name ?? "");
      if (name === "AbortError" || msg.includes("signal is aborted")) return;
      // eslint-disable-next-line no-console
      console.warn("[map]", msg || e);
    });

    m.on("load", () => {
      m.addSource("ir", { type: "image", url: BLANK, coordinates: [
        [80, 20], [90, 20], [90, 10], [80, 10],
      ] });
      m.addLayer({
        id: "ir-layer",
        type: "raster",
        source: "ir",
        paint: { "raster-opacity": 0.95, "raster-fade-duration": 180 },
      });

      m.addSource("rings", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "rings-line",
        type: "line",
        source: "rings",
        paint: { "line-color": "#ffffff", "line-opacity": 0.18, "line-width": 0.8, "line-dasharray": [3, 4] },
      });

      m.addSource("cone", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "cone-fill", type: "fill", source: "cone",
        paint: { "fill-color": "#F2C63D", "fill-opacity": 0.16 } });
      m.addLayer({ id: "cone-line", type: "line", source: "cone",
        paint: { "line-color": "#F2C63D", "line-opacity": 0.65, "line-width": 1.0 } });

      m.addSource("observed", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "observed-line", type: "line", source: "observed",
        paint: { "line-color": "#3BD16F", "line-width": 2.0, "line-opacity": 0.95 } });

      m.addSource("forecast", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "forecast-line", type: "line", source: "forecast",
        paint: { "line-color": "#F2C63D", "line-width": 1.8,
                 "line-dasharray": [3, 2], "line-opacity": 0.90 } });

      m.addSource("points", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "points-c", type: "circle", source: "points",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "kt"], 20, 3, 140, 7.5],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#080c10",
          "circle-stroke-width": 1,
        } });

      m.addSource("fcpoints", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "fcpoints-c", type: "circle", source: "fcpoints",
        paint: {
          "circle-radius": 3.0, "circle-color": "#F2C63D",
          "circle-stroke-color": "#080c10", "circle-stroke-width": 1,
        } });

      m.addSource("now", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "now-halo", type: "circle", source: "now",
        paint: { "circle-radius": 11, "circle-color": "transparent",
                 "circle-stroke-color": "#35C4E8", "circle-stroke-width": 1.4 } });
      m.addLayer({ id: "now-c", type: "circle", source: "now",
        paint: { "circle-radius": 3.5, "circle-color": "#35C4E8",
                 "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 1.2 } });

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
    set("rings-line", layers.satellite);
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

    // Only apply the LATEST frame.
    //
    // Three console errors came from this block. Pre-decoding the image and then
    // asking MapLibre to fetch the same URL again meant two requests per frame;
    // during a 120x replay the next updateImage aborted the previous in-flight
    // one (AbortError) and occasionally handed the GL layer a half-decoded
    // bitmap (InvalidStateError: the source image could not be decoded). There
    // was also no cancellation, so a slow load for an old frame could land after
    // a newer one and put stale imagery on the map.
    //
    // Now: a generation counter discards stale loads, the URL is skipped if it
    // is already applied, and coordinates travel with the image in a single
    // atomic updateImage rather than a separate setCoordinates that could
    // interleave with it.
    if (appliedUrl.current === georefUrl) return;

    const gen = ++irGen.current;
    let cancelled = false;

    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      if (cancelled || gen !== irGen.current) return;   // a newer frame won
      try {
        const [tl, tr, br, bl] = corners;
        src.updateImage({ url: georefUrl, coordinates: [tl, tr, br, bl] });
        appliedUrl.current = georefUrl;
      } catch {
        /* source torn down mid-flight during a teardown */
      }
    };
    img.onerror = () => {
      if (cancelled || gen !== irGen.current) return;
      // Leave the previous frame up rather than blanking the imagery: a dropped
      // frame during replay is far less confusing than the storm vanishing.
    };
    img.src = georefUrl;

    return () => { cancelled = true; };
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

      const rings = m.getSource("rings") as maplibregl.GeoJSONSource | undefined;
      if (rings) {
        rings.setData({
          type: "FeatureCollection",
          features: [50, 100, 200].map((km) => ({
            type: "Feature",
            properties: { km },
            geometry: { type: "LineString", coordinates: makeRing(last.lon, last.lat, km) },
          })),
        });
      }
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
      const target: [number, number] = [last.lon, last.lat];
      const firstFix = followed.current !== activeCase?.id;

      if (activeCase) {
        if (firstFix) {
          followed.current = activeCase.id;
          setAutoFollow(true);
          centerOnStorm(last.lon, last.lat, true);
        } else if (autoFollowRef.current) {
          const prev = lastCenteredPos.current;
          const stepDrift = prev ? Math.hypot(target[0] - prev[0], target[1] - prev[1]) : 999;
          if (stepDrift > 0.04) {
            centerOnStorm(last.lon, last.lat, stepDrift > 4);
          }
        }
      }
    }
  }, [observed, classify, ready, activeCase, centerOnStorm]);

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

      {/* CIRA / JTWC style operational frame badge */}
      {classify && (
        <div className="map-hud-stamp" aria-label="Center analysis and Dvorak classification">
          <div className="stamp-row">
            <span className="stamp-tnum">T{classify.t_number.toFixed(1)}</span>
            <span className="stamp-cat" style={{ color: catColor(classify.imd_category) }}>
              {classify.imd_category} · {classify.wind_kt.toFixed(0)} kt
            </span>
          </div>
          <div className="stamp-meta">
            <span>{classify.imd_category_label}</span>
            <span className="stamp-sep">|</span>
            <span>{classify.centre.lat.toFixed(1)}°N {classify.centre.lon.toFixed(1)}°E</span>
            <span className="stamp-sep">|</span>
            <span>{stormClock ? stormClock.slice(0, 16).replace("T", " ") + "Z" : "MOSDAC"}</span>
          </div>
        </div>
      )}

      {/* Floating Re-center button when user has manually panned */}
      {!autoFollow && observed.length > 0 && (
        <button
          className="map-recenter-btn"
          onClick={() => {
            setAutoFollow(true);
            const latest = observed[observed.length - 1];
            if (latest) centerOnStorm(latest.lon, latest.lat);
          }}
          title="Re-lock camera to follow the cyclone"
        >
          <span className="recenter-icon">◎</span>
          <span>Follow Cyclone</span>
        </button>
      )}
    </div>
  );
}
