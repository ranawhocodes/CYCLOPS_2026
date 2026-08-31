import { useEffect, useState } from "react";
import type maplibregl from "maplibre-gl";

/**
 * Tells you why the map is blank.
 *
 * A WebGL map that fails to initialise renders a black rectangle and reports
 * nothing: no exception, no console error, no visual difference between "still
 * loading", "this browser cannot run it" and "the basemap 404'd". That is the
 * worst possible failure mode in front of an audience, and it is exactly what
 * happened during development — the style silently never loaded because the
 * render loop was not running, and the only symptom was an empty screen.
 *
 * This watches the three things that actually break and names the one that did.
 */

type Diagnosis =
  | { state: "ok" }
  | { state: "checking" }
  | { state: "failed"; title: string; detail: string; fix: string };

const GRACE_MS = 6000;

export function MapStatus({ map }: { map: maplibregl.Map | null }) {
  const [dx, setDx] = useState<Diagnosis>({ state: "checking" });

  useEffect(() => {
    if (!map) return;
    let done = false;

    const settle = (d: Diagnosis) => { if (!done) { done = true; setDx(d); } };

    // If the style loads, everything upstream of it worked.
    const onIdle = () => { if (map.isStyleLoaded()) settle({ state: "ok" }); };
    map.on("idle", onIdle);
    map.on("load", onIdle);
    if (map.isStyleLoaded()) settle({ state: "ok" });

    // Count animation frames. MapLibre defers style loading into a rAF
    // callback, so a browser that never paints never finishes loading the map.
    let frames = 0;
    let raf = requestAnimationFrame(function tick() {
      frames++;
      raf = requestAnimationFrame(tick);
    });

    const timer = window.setTimeout(async () => {
      cancelAnimationFrame(raf);
      if (done) return;
      if (map.isStyleLoaded()) return settle({ state: "ok" });

      // 1. Can this browser do WebGL at all?
      const probe = document.createElement("canvas");
      const gl = probe.getContext("webgl2") || probe.getContext("webgl");
      if (!gl) {
        return settle({
          state: "failed",
          title: "WebGL is unavailable",
          detail: "This browser cannot create a WebGL context, which MapLibre needs to draw the map.",
          fix: "Enable hardware acceleration, or open the console in Chrome or Firefox.",
        });
      }
      if ((gl as WebGLRenderingContext).isContextLost?.()) {
        return settle({
          state: "failed",
          title: "The WebGL context was lost",
          detail: "The GPU context went away after the page loaded.",
          fix: "Reload the page. If it recurs, disable hardware acceleration.",
        });
      }

      // 2. Is the page actually painting?
      if (frames === 0) {
        return settle({
          state: "failed",
          title: "The page is not rendering",
          detail:
            `No animation frames ran in ${GRACE_MS / 1000}s (tab is ` +
            `"${document.visibilityState}"). MapLibre finishes loading its ` +
            "style inside an animation frame, so the map never completes.",
          fix: "Bring this tab to the foreground and reload.",
        });
      }

      // 3. Did the bundled basemap actually arrive?
      try {
        const r = await fetch("/basemap/nio-land.geojson", { method: "HEAD" });
        if (!r.ok) {
          return settle({
            state: "failed",
            title: "Basemap is missing",
            detail: `/basemap/nio-land.geojson returned HTTP ${r.status}.`,
            fix: "Check console/public/basemap/ exists, then run `make validate-map`.",
          });
        }
      } catch {
        return settle({
          state: "failed",
          title: "Basemap could not be fetched",
          detail: "The request for /basemap/nio-land.geojson failed outright.",
          fix: "Confirm the dev server is serving console/public/, then run `make validate-map`.",
        });
      }

      // Painting, WebGL present, basemap reachable — but no style.
      settle({
        state: "failed",
        title: "Map style did not load",
        detail: "WebGL works, the page is painting and the basemap is reachable, but MapLibre never finished loading the style.",
        fix: "Run `make validate-map`, then hard-reload (Cmd/Ctrl + Shift + R) to clear a stale bundle.",
      });
    }, GRACE_MS);

    return () => {
      done = true;
      window.clearTimeout(timer);
      cancelAnimationFrame(raf);
      map.off("idle", onIdle);
      map.off("load", onIdle);
    };
  }, [map]);

  if (dx.state !== "failed") return null;

  return (
    <div className="map-status" role="alert">
      <h2>{dx.title}</h2>
      <p>{dx.detail}</p>
      <p className="map-status-fix">{dx.fix}</p>
      <p className="map-status-note">
        Everything else on this screen — intensity, explainability, nowcast and
        the baseline metrics — is unaffected and still live.
      </p>
    </div>
  );
}
