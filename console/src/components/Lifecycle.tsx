import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { catColor } from "../lib/imd";

/**
 * The storm's life, and which capability each stage exercises.
 *
 * Identification, classification and prediction are not three separate demos —
 * they are three things a forecaster does at different points in one storm's
 * life. Following one cyclone from the depression that formed on 26 April to
 * landfall near Puri is what makes that legible: the strip says where the
 * replay is, and the caption says what the system is being asked to do there.
 *
 * Stages come from the track itself (intensity, its 24 h change, distance to
 * land), not from hand-placed dates.
 */

interface StageSpan {
  stage: string; label: string; task: string; detail: string;
  start: string; end: string; peak_kt: number; n: number;
}
interface PerFix {
  ts: string; stage: string; wind_kt: number;
  imd_category: string; d24_kt: number | null;
}

const TASK_COLOR: Record<string, string> = {
  IDENTIFICATION: "#8fb8cc",
  CLASSIFICATION: "#35c4e8",
  "CLASSIFICATION + ALERT": "#e8404a",
  PREDICTION: "#f2c63d",
};

export function Lifecycle({ caseId }: { caseId: string | null }) {
  const [spans, setSpans] = useState<StageSpan[] | null>(null);
  const [fixes, setFixes] = useState<PerFix[]>([]);
  const stormClock = useStore((s) => s.stormClock);

  useEffect(() => {
    if (!caseId) return;
    fetch(`/v1/cases/${caseId}/lifecycle`)
      .then((r) => r.json())
      .then((d) => { setSpans(d.stages); setFixes(d.per_fix ?? []); })
      .catch(() => setSpans(null));
  }, [caseId]);

  const { t0, t1, nowPct, current } = useMemo(() => {
    if (!fixes.length) return { t0: 0, t1: 1, nowPct: 0, current: null as PerFix | null };
    const a = new Date(fixes[0].ts).getTime();
    const b = new Date(fixes[fixes.length - 1].ts).getTime();
    const now = stormClock ? new Date(stormClock).getTime() : a;
    // Only fixes at or before the storm clock exist yet — the future is not
    // previewed here any more than it is on the map.
    const seen = fixes.filter((f) => new Date(f.ts).getTime() <= now);
    return {
      t0: a, t1: b,
      nowPct: Math.max(0, Math.min(100, ((now - a) / Math.max(1, b - a)) * 100)),
      current: seen.length ? seen[seen.length - 1] : fixes[0],
    };
  }, [fixes, stormClock]);

  if (!spans?.length) return null;

  const pct = (iso: string) =>
    ((new Date(iso).getTime() - t0) / Math.max(1, t1 - t0)) * 100;

  const active = spans.find(
    (s) => current && new Date(current.ts) >= new Date(s.start)
      && new Date(current.ts) <= new Date(s.end)
  ) ?? spans[0];

  return (
    <section className="lifecycle" aria-label="Storm lifecycle">
      <header className="lc-head">
        <div className="lc-task" style={{ color: TASK_COLOR[active.task] ?? "#dfeaf3" }}>
          <span className="lc-dot" style={{ background: TASK_COLOR[active.task] }} />
          {active.task}
        </div>
        <div className="lc-stage">{active.label}</div>
        {current?.d24_kt != null && Math.abs(current.d24_kt) >= 5 && (
          <div className={`lc-trend ${current.d24_kt > 0 ? "up" : "down"}`}>
            {current.d24_kt > 0 ? "▲" : "▼"} {Math.abs(current.d24_kt).toFixed(0)} kt / 24 h
          </div>
        )}
      </header>

      <div className="lc-track" role="img"
           aria-label={`Lifecycle: currently ${active.label}`}>
        {spans.map((s, i) => {
          const left = pct(s.start);
          const width = Math.max(1.5, pct(s.end) - left);
          return (
            <div key={i} className={`lc-span ${s === active ? "on" : ""}`}
                 style={{ left: `${left}%`, width: `${width}%`,
                          background: TASK_COLOR[s.task] ?? "#4a6478" }}
                 title={`${s.label} — ${s.task}`} />
          );
        })}
        {/* Intensity trace over the stages, revealed only up to the storm clock */}
        <svg className="lc-trace" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden>
          <polyline
            points={fixes
              .filter((f) => new Date(f.ts).getTime() <= (t0 + (t1 - t0) * nowPct / 100))
              .map((f) => `${pct(f.ts)},${22 - (f.wind_kt / 140) * 22}`)
              .join(" ")}
            fill="none" stroke="#ffffff" strokeOpacity="0.85" strokeWidth="0.9" />
        </svg>
        <div className="lc-head-marker" style={{ left: `${nowPct}%` }} />
      </div>

      <div className="lc-labels">
        {spans.map((s, i) => {
          const left = pct(s.start);
          const width = pct(s.end) - left;
          if (width < 9) return null;
          return (
            <span key={i} className="lc-label"
                  style={{ left: `${left}%`, width: `${width}%` }}>
              {s.label}
            </span>
          );
        })}
      </div>

      <p className="lc-detail">{active.detail}</p>

      {current && (
        <div className="lc-now">
          <span className="lc-now-cat" style={{ color: catColor(current.imd_category) }}>
            {current.imd_category}
          </span>
          <span className="mono">{current.wind_kt.toFixed(0)} kt</span>
          <span className="dim">best track</span>
        </div>
      )}
    </section>
  );
}
