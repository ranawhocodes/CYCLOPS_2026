import { create } from "zustand";
import type {
  Alert, Case, Classify, Nowcast, ReplayState, TrackPoint, WindGrid,
} from "../api/client";

export interface LayerToggles {
  satellite: boolean;
  wind: boolean;
  cone: boolean;
  forecast: boolean;
  track: boolean;
}

export type Conn = "live" | "connecting" | "reconnecting" | "offline";

interface State {
  connection: Conn;
  health: any | null;
  cases: Case[];
  activeCase: Case | null;
  replay: ReplayState | null;

  stormClock: string | null;
  frameUrl: string | null;
  georefUrl: string | null;
  windGrid: WindGrid | null;
  layers: LayerToggles;
  railOpen: boolean;
  chartOpen: boolean;
  classify: Classify | null;
  nowcast: Nowcast | null;
  observed: TrackPoint[];
  truthNow: { wind_kt: number; imd_category: string; source: string } | null;
  alerts: Alert[];
  history: { ts: string; truth: number; predicted: number }[];

  showCam: boolean;
  camOpacity: number;
  showMetrics: boolean;

  setConnection: (c: Conn) => void;
  setHealth: (h: any) => void;
  setCases: (c: Case[]) => void;
  setActiveCase: (c: Case | null) => void;
  setReplay: (r: ReplayState | null) => void;
  resetCase: () => void;
  applyMessage: (m: any) => void;
  applyPayload: (p: any) => void;
  setShowCam: (v: boolean) => void;
  setCamOpacity: (v: number) => void;
  setShowMetrics: (v: boolean) => void;
  setWindGrid: (g: WindGrid | null) => void;
  toggleLayer: (k: keyof LayerToggles) => void;
  setRailOpen: (v: boolean) => void;
  setChartOpen: (v: boolean) => void;
}

export const useStore = create<State>((set, get) => ({
  connection: "offline",
  health: null,
  cases: [],
  activeCase: null,
  replay: null,
  stormClock: null,
  frameUrl: null,
  georefUrl: null,
  windGrid: null,
  layers: { satellite: true, wind: true, cone: true, forecast: true, track: true },
  railOpen: true,
  chartOpen: true,
  classify: null,
  nowcast: null,
  observed: [],
  truthNow: null,
  alerts: [],
  history: [],
  showCam: true,
  camOpacity: 0.55,
  showMetrics: false,

  setConnection: (connection) => set({ connection }),
  setHealth: (health) => set({ health }),
  setCases: (cases) => set({ cases }),
  setActiveCase: (activeCase) => set({ activeCase }),
  setReplay: (replay) => set({ replay }),
  resetCase: () =>
    set({
      stormClock: null, frameUrl: null, georefUrl: null, windGrid: null,
      classify: null, nowcast: null,
      observed: [], truthNow: null, alerts: [], history: [], replay: null,
    }),

  applyMessage: (m) => {
    switch (m.type) {
      case "frame":
        set({ frameUrl: m.image_url, georefUrl: m.georef_url ?? null,
              stormClock: m.storm_clock });
        set((s) => ({ replay: s.replay ? { ...s.replay, idx: m.idx } : s.replay }));
        break;
      case "prediction":
        get().applyPayload(m);
        break;
      case "alert":
        // Newest first, capped so a long replay does not grow unbounded.
        set((s) => ({ alerts: [m, ...s.alerts].slice(0, 40) }));
        break;
      case "finished":
        set((s) => ({ replay: s.replay ? { ...s.replay, finished: true } : s.replay }));
        break;
      default:
        break;
    }
  },

  applyPayload: (p) =>
    set((s) => {
      const entry = {
        ts: p.ts,
        truth: p.truth_now?.wind_kt ?? NaN,
        predicted: p.classify?.wind_kt ?? NaN,
      };
      const hist = [...s.history.filter((h) => h.ts !== p.ts), entry].sort((a, b) =>
        a.ts < b.ts ? -1 : 1
      );
      return {
        stormClock: p.ts,
        classify: p.classify ?? s.classify,
        nowcast: p.nowcast ?? s.nowcast,
        observed: p.observed ?? s.observed,
        truthNow: p.truth_now ?? s.truthNow,
        history: hist.slice(-120),
      };
    }),

  setShowCam: (showCam) => set({ showCam }),
  setCamOpacity: (camOpacity) => set({ camOpacity }),
  setShowMetrics: (showMetrics) => set({ showMetrics }),
  setWindGrid: (windGrid) => set({ windGrid }),
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setRailOpen: (railOpen) => set({ railOpen }),
  setChartOpen: (chartOpen) => set({ chartOpen }),
}));


// Dev-only handle for inspecting live state from the browser console.
// Stripped from production builds.
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__cyclopsStore = useStore;
}
