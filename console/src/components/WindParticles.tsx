import { useEffect, useRef } from "react";
import type maplibregl from "maplibre-gl";

/**
 * Animated particle-flow layer over the storm's wind field.
 *
 * Parcels are advected through the 10 m wind and leave decaying trails, the same
 * idea as earth.nullschool.net. It is not decoration: a static arrow field makes
 * the circulation hard to read, whereas motion makes the vortex and the inflow
 * angle immediately legible.
 *
 * WHICH FIELD THIS DRAWS
 * ----------------------
 * The ANALYSED wind field — the storm's full circulation. A cyclone has wind
 * everywhere, so that is what a forecaster reasons about and what a flow
 * visualisation should show.
 *
 * It is deliberately NOT the scatterometer retrieval. Drawing only what the
 * instrument saw confined the animation to a narrow diagonal swath, which is
 * honest about the observation but reads as a broken renderer. The
 * observation-versus-analysis distinction is made where it belongs: the
 * provenance panel reports actual swath coverage and flags the field as
 * analysed, and the model still consumes the masked observation, not this.
 *
 * The field covers a 1024 km box around the storm rather than the whole basin,
 * so the animation still stops at the data boundary rather than extrapolating
 * motion nobody analysed.
 */

export interface WindGrid {
  available: boolean;
  nx: number;
  ny: number;
  bbox: { west: number; east: number; south: number; north: number };
  u: (number | null)[];
  v: (number | null)[];
  max_speed_ms: number;
  coverage: number;
}

interface Particle {
  lon: number;
  lat: number;
  age: number;
  life: number;
}

const PARTICLE_COUNT = 3200;
// Higher = longer trails. At 0.90 the streaks were too short to read as motion;
// a cyclone's signature is the ARC a parcel traces, and an arc needs length.
const TRAIL_FADE = 0.955;
const SPEED_SCALE = 0.00085; // degrees per m/s per frame

// Particles are spawned with a bias toward the core rather than uniformly over
// the box. In a modified-Rankine vortex the wind falls off as r^-0.55 outside
// the radius of maximum wind, so a uniform spawn puts most particles in the
// slow outer field where they drift almost straight and the rotation is
// invisible. Concentrating them where the flow actually curves is what makes
// the circulation legible.
const CORE_BIAS = 1.9;

export function WindParticles({
  map,
  grid,
  visible,
}: {
  map: maplibregl.Map | null;
  grid: WindGrid | null;
  visible: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const raf = useRef<number>();
  const particles = useRef<Particle[]>([]);
  const gridRef = useRef<WindGrid | null>(null);

  gridRef.current = grid;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !map || !visible || !grid?.available) {
      const ctx = canvasRef.current?.getContext("2d");
      if (ctx && canvasRef.current) {
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
      }
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const r = map.getContainer().getBoundingClientRect();
      // Cap the backing store at 2x. On a 5K display a full-DPR canvas of this
      // size costs more per frame than the animation is worth.
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = r.width * dpr;
      canvas.height = r.height * dpr;
      canvas.style.width = `${r.width}px`;
      canvas.style.height = `${r.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const { west, east, south, north } = grid.bbox;

    const cLon = (west + east) / 2;
    const cLat = (south + north) / 2;
    const halfLon = (east - west) / 2;
    const halfLat = (north - south) / 2;

    const spawn = (p: Particle) => {
      // Radius sampled with a core bias; angle uniform. u**CORE_BIAS pulls the
      // distribution inward, so most parcels start where the vortex is tight.
      const u = Math.random();
      const r = Math.pow(u, CORE_BIAS);
      const th = Math.random() * Math.PI * 2;
      p.lon = cLon + Math.cos(th) * r * halfLon;
      p.lat = cLat + Math.sin(th) * r * halfLat;
      p.age = 0;
      // Varied lifetimes stop every particle respawning on the same frame,
      // which otherwise pulses visibly.
      p.life = 60 + Math.random() * 120;
    };

    particles.current = Array.from({ length: PARTICLE_COUNT }, () => {
      const p: Particle = { lon: 0, lat: 0, age: 0, life: 0 };
      spawn(p);
      p.age = Math.random() * p.life;
      return p;
    });

    /** Bilinear sample of the wind field; null anywhere without a retrieval. */
    const sample = (lon: number, lat: number): [number, number] | null => {
      const g = gridRef.current;
      if (!g?.available) return null;
      const fx = ((lon - g.bbox.west) / (g.bbox.east - g.bbox.west)) * (g.nx - 1);
      // Row 0 is the north edge, matching image convention.
      const fy = ((g.bbox.north - lat) / (g.bbox.north - g.bbox.south)) * (g.ny - 1);
      if (fx < 0 || fy < 0 || fx > g.nx - 1 || fy > g.ny - 1) return null;

      const x0 = Math.floor(fx);
      const y0 = Math.floor(fy);
      const x1 = Math.min(x0 + 1, g.nx - 1);
      const y1 = Math.min(y0 + 1, g.ny - 1);
      const tx = fx - x0;
      const ty = fy - y0;

      const idx = (x: number, y: number) => y * g.nx + x;
      const us = [g.u[idx(x0, y0)], g.u[idx(x1, y0)], g.u[idx(x0, y1)], g.u[idx(x1, y1)]];
      const vs = [g.v[idx(x0, y0)], g.v[idx(x1, y0)], g.v[idx(x0, y1)], g.v[idx(x1, y1)]];
      // Any missing corner means this cell straddles the swath edge. Treat the
      // whole sample as absent rather than averaging real data with a gap.
      if (us.some((a) => a === null) || vs.some((a) => a === null)) return null;

      const lerp2 = (a: number, b: number, c: number, d: number) =>
        (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
      return [
        lerp2(us[0]!, us[1]!, us[2]!, us[3]!),
        lerp2(vs[0]!, vs[1]!, vs[2]!, vs[3]!),
      ];
    };

    const maxSpeed = Math.max(1, grid.max_speed_ms);

    const frame = () => {
      const w = canvas.width / (Math.min(window.devicePixelRatio || 1, 2));
      const h = canvas.height / (Math.min(window.devicePixelRatio || 1, 2));

      // Fade rather than clear, so each particle leaves a decaying trail.
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = `rgba(0,0,0,${1 - TRAIL_FADE})`;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";

      ctx.lineCap = "round";

      for (const p of particles.current) {
        p.age += 1;
        if (p.age > p.life) {
          spawn(p);
          continue;
        }

        const uv = sample(p.lon, p.lat);
        if (!uv) {
          spawn(p);
          continue;
        }

        const [u, v] = uv;
        const nextLon = p.lon + u * SPEED_SCALE;
        // Longitude degrees shrink with latitude; without this correction the
        // flow looks stretched east-west near the top of the basin.
        const nextLat = p.lat + v * SPEED_SCALE * Math.cos((p.lat * Math.PI) / 180);

        const a = map.project([p.lon, p.lat]);
        const b = map.project([nextLon, nextLat]);

        if (a.x > -50 && a.x < w + 50 && a.y > -50 && a.y < h + 50) {
          const speed = Math.hypot(u, v);
          const t = Math.min(1, speed / maxSpeed);
          // Cyan through amber to red, matching the intensity ramp used
          // everywhere else in the console.
          const r = Math.round(53 + t * 199);
          const g = Math.round(196 - t * 132);
          const bl = Math.round(232 - t * 158);
          // Fade in and out over the particle's life so streaks appear and
          // vanish smoothly instead of popping.
          const lifeFade = Math.min(1, Math.min(p.age, p.life - p.age) / 12);
          // Lifted so streaks stay legible over bright cloud tops, which is
          // exactly where the fastest air is and where the rotation most needs
          // to be visible.
          ctx.globalAlpha = (0.45 + 0.55 * t) * lifeFade;
          ctx.strokeStyle = `rgb(${r},${g},${bl})`;
          // Fast air draws heavier, so the eyewall reads as the strongest part
          // of the field rather than every streak weighing the same.
          ctx.lineWidth = 1.0 + 1.7 * t;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }

        p.lon = nextLon;
        p.lat = nextLat;
      }

      ctx.globalAlpha = 1;
      raf.current = requestAnimationFrame(frame);
    };

    raf.current = requestAnimationFrame(frame);

    const onResize = () => resize();
    map.on("resize", onResize);
    window.addEventListener("resize", onResize);

    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      map.off("resize", onResize);
      window.removeEventListener("resize", onResize);
    };
  }, [map, grid, visible]);

  return <canvas ref={canvasRef} className="wind-canvas" aria-hidden />;
}
