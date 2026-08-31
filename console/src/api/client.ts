// Thin API client. All requests are same-origin via the Vite proxy, so there is
// no API host to configure and no CORS failure mode at demo time.

export interface Case {
  id: string; name: string; season: number; basin: string; note: string;
  start: string; end: string; peak_wind_kt: number; peak_category: string;
  n_frames: number;
}

export interface Provenance {
  ir: { source: string; observed_at: string; age_min: number; is_synthetic: boolean } | null;
  wind: { source: string; observed_at: string; age_min: number; coverage: number; is_synthetic: boolean } | null;
  env: { sst_source: string; shear_source: string; is_proxy: boolean };
}

export interface Classify {
  wind_kt: number;
  wind_kt_ci: [number, number];
  imd_category: string;
  imd_category_label: string;
  t_number: number;
  detection_confidence: number;
  wind_convention: string;
  inference_ms: number;
  model: { name: string; version: string; trained_on: string };
  cam?: { format: string; data: string; opacity_hint: number; expected_focus: string; note: string };
  provenance: Provenance;
  centre: { lat: number; lon: number };
  truth?: { wind_kt: number; imd_category: string; source: string };
}

export interface Forecast {
  lead_h: number; valid_at: string;
  position: { lat: number; lon: number };
  position_q10: { lat: number; lon: number };
  position_q90: { lat: number; lon: number };
  cone_radius_km: number;
  wind_kt: number; wind_kt_q10: number; wind_kt_q90: number;
  imd_category: string;
}

export interface Nowcast {
  forecasts: Forecast[];
  baselines: Record<string, { persistence: { lat: number | null; lon: number | null; wind_kt: number | null } }>;
  cone: [number, number][];
  cone_definition: string;
  cone_measured_coverage: Record<string, number>;
  model: { name: string; backend: string; target: string };
}

export interface TrackPoint {
  ts: string; lat: number; lon: number; wind_kt: number; imd_category: string;
}

export interface Alert {
  kind: string; severity: string; ts: string; message: string;
}

export interface ReplayState {
  session_id: string; case_id: string; idx: number; n_frames: number;
  speed: number; paused: boolean; finished: boolean; storm_clock: string;
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => j<any>("/v1/health"),
  cases: () => j<Case[]>("/v1/cases"),
  track: (id: string, until?: string) =>
    j<{ observed: TrackPoint[]; source: string }>(
      `/v1/cases/${id}/track${until ? `?until=${encodeURIComponent(until)}` : ""}`
    ),
  frameUrl: (id: string, ts: string) =>
    `/v1/cases/${id}/frames/${encodeURIComponent(ts)}`,
  startReplay: (id: string, speed: number) =>
    j<ReplayState>(`/v1/replay/${id}/start`, {
      method: "POST", body: JSON.stringify({ speed }),
    }),
  pause: (sid: string) => j<ReplayState>(`/v1/replay/${sid}/pause`, { method: "POST" }),
  resume: (sid: string) => j<ReplayState>(`/v1/replay/${sid}/resume`, { method: "POST" }),
  seek: (sid: string, idx: number) =>
    j<ReplayState>(`/v1/replay/${sid}/seek/${idx}`, { method: "POST" }),
  setSpeed: (sid: string, s: number) =>
    j<ReplayState>(`/v1/replay/${sid}/speed/${s}`, { method: "POST" }),
  stop: (sid: string) => j<any>(`/v1/replay/${sid}`, { method: "DELETE" }),
  metrics: () => j<any>("/v1/metrics/baselines"),
  disclaimer: () => j<{ text: string }>("/v1/disclaimer"),
};
