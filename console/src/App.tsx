import { useCallback, useEffect } from "react";
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
import { ReplayControls } from "./components/ReplayControls";
import { MetricsView } from "./components/MetricsView";
import { CasePicker } from "./components/CasePicker";

const DISCLAIMER =
  "Decision-support aid. Not a substitute for IMD operational warnings.";

export default function App() {
  const {
    cases, setCases, setHealth, health, activeCase, setActiveCase,
    replay, setReplay, resetCase, setShowMetrics,
  } = useStore();

  useLiveSocket(replay?.session_id ?? null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.cases().then(setCases).catch(() => {});
  }, [setHealth, setCases]);

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
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>◎</span>
          <div>
            <h1>CYCLOPS</h1>
            <p>Cyclone Observation, Prediction &amp; Explainability System</p>
          </div>
        </div>

        <CasePicker onSelect={start} />

        <div className="topbar-actions">
          <button className="btn" onClick={() => setShowMetrics(true)}>
            Performance
          </button>
          <a className="btn" href="/v1/docs" target="_blank" rel="noreferrer">API</a>
        </div>
      </header>

      <ReplayControls />

      <main className="grid">
        <div className="col-map">
          <MapView />
          <div className="row-wide">
            <IntensityChart />
            <ForecastTable />
          </div>
        </div>

        <aside className="col-side">
          <IntensityPanel />
          <CamViewer />
          <ProvenancePanel />
          <AlertFeed />
        </aside>
      </main>

      <footer className="disclaimer">
        <span className="warn" aria-hidden>⚠</span>
        <span>{DISCLAIMER}</span>
        {synthetic && (
          <span className="synthetic-banner">
            MVP build: best-track positions and intensity labels are real
            (IBTrACS, IMD 3-min convention); satellite imagery is synthetic.
          </span>
        )}
      </footer>

      <MetricsView />
    </div>
  );
}
