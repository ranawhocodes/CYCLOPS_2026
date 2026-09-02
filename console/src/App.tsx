import { useCallback, useEffect, useState } from "react";
import { api } from "./api/client";
import { useStore } from "./store";
import { useLiveSocket } from "./hooks/useLiveSocket";
import { MapView } from "./components/MapView";
import { IntensityPanel } from "./components/IntensityPanel";
import { CamViewer } from "./components/CamViewer";
import { ProvenancePanel } from "./components/ProvenancePanel";
import { AlertFeed } from "./components/AlertFeed";
import { IntensityChart } from "./components/IntensityChart";
import { ForecastTable } from "./components/ForecastTable";
import { Timeline } from "./components/Timeline";
import { MetricsView } from "./components/MetricsView";
import { LayerControl } from "./components/LayerControl";
import { Lifecycle } from "./components/Lifecycle";
import { FaniStudy } from "./components/FaniStudy";

const DISCLAIMER =
  "Decision-support aid. Not a substitute for IMD operational warnings.";

export default function App() {
  const [showFani, setShowFani] = useState(false);
  const {
    cases, setCases, setHealth, health, activeCase, setActiveCase,
    replay, setReplay, resetCase, setShowMetrics,
    railOpen, setRailOpen, chartOpen, setChartOpen,
    stormClock, setWindGrid,
  } = useStore();

  useLiveSocket(replay?.session_id ?? null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.cases().then(setCases).catch(() => {});
  }, [setHealth, setCases]);

  // Pull the wind field for the current frame. Kept out of the replay payload
  // because it is ~10 KB of grid per step and only the particle layer wants it;
  // fetching it separately keeps the WebSocket messages small.
  useEffect(() => {
    if (!activeCase || !stormClock) return;
    let cancelled = false;
    api.wind(activeCase.id, stormClock)
      .then((g) => { if (!cancelled) setWindGrid(g.available ? g : null); })
      .catch(() => { if (!cancelled) setWindGrid(null); });
    return () => { cancelled = true; };
  }, [activeCase, stormClock, setWindGrid]);

  const start = useCallback(
    async (caseId: string) => {
      const c = cases.find((x) => x.id === caseId) ?? null;
      if (replay) await api.stop(replay.session_id).catch(() => {});
      resetCase();
      setActiveCase(c);
      const st = await api.startReplay(caseId, 120);
      setReplay(st);
    },
    [cases, replay, resetCase, setActiveCase, setReplay]
  );

  // Rule 1 of the demo: open on a cyclone, not an empty state. The first thing
  // anyone sees should be a storm already running.
  useEffect(() => {
    if (cases.length && !activeCase) start(cases[0].id);
  }, [cases, activeCase, start]);

  const synthetic = health?.data_status?.imagery?.startsWith("SYNTHETIC");

  return (
    <div className="app">
      {/* The map is the page. Everything else floats over it. */}
      <MapView />

      <header className="hud hud-top">
        <div className="brand">
          <span className="logo" aria-hidden>◎</span>
          <div className="brand-text">
            <h1>CYCLOPS</h1>
            <p>Identification · Classification · Prediction</p>
          </div>
        </div>

        {/* One storm, followed properly. The header names it rather than
            offering a picker, because the point is depth on a single case. */}
        {activeCase && (
          <div className="storm-id">
            <span className="storm-name">Cyclone {activeCase.name}</span>
            <span className="storm-meta mono">{activeCase.season}</span>
            <span className="storm-note">{activeCase.note}</span>
          </div>
        )}

        <div className="hud-actions">
          <LayerControl />
          <button className="btn fani-btn" onClick={() => setShowFani(true)}
                  title="Cyclone Fani — real MODIS imagery, end to end">
            <span className="real-dot" aria-hidden />
            Fani · real data
          </button>
          <button className="icon-btn" onClick={() => setShowMetrics(true)}
                  title="Performance against baselines" aria-label="Performance">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M2 13V7M6 13V3M10 13V9M14 13V5" stroke="currentColor"
                    strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <a className="icon-btn" href="/v1/docs" target="_blank" rel="noreferrer"
             title="OpenAPI docs" aria-label="API documentation">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M6 3 2.5 8 6 13M10 3l3.5 5L10 13" stroke="currentColor"
                    strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
          <button className="icon-btn" onClick={() => setRailOpen(!railOpen)}
                  aria-pressed={railOpen} title={railOpen ? "Hide panels" : "Show panels"}
                  aria-label={railOpen ? "Hide panels" : "Show panels"}>
            {railOpen ? "⟩" : "⟨"}
          </button>
        </div>
      </header>

      {railOpen && (
        <aside className="hud rail" aria-label="Analysis panels">
          <Lifecycle caseId={activeCase?.id ?? null} />
          <IntensityPanel />
          <CamViewer />
          <ProvenancePanel />
          <AlertFeed />
        </aside>
      )}

      <div className={`hud dock ${chartOpen ? "" : "collapsed"}`}>
        <button className="dock-toggle" onClick={() => setChartOpen(!chartOpen)}
                aria-expanded={chartOpen}>
          {chartOpen ? "▾" : "▴"} Intensity &amp; nowcast
        </button>
        {chartOpen && (
          <div className="dock-body">
            <IntensityChart />
            <ForecastTable />
          </div>
        )}
      </div>

      <Timeline />

      <footer className="hud disclaimer">
        <span className="warn" aria-hidden>⚠</span>
        <span>{DISCLAIMER}</span>
        {synthetic && (
          <span className="synthetic-banner">
            MVP: best-track positions and intensity labels are real (IBTrACS,
            IMD 3-min); satellite imagery is synthetic.
          </span>
        )}
      </footer>

      <MetricsView />
      {showFani && <FaniStudy onClose={() => setShowFani(false)} />}
    </div>
  );
}
