import { useEffect, useMemo, useState } from "react";
import { useStore } from "../store";
import { IMD_8_SCALE, catColor, getCategoryByWind } from "../lib/imd";

/**
 * Operational IMD Classification Scale & Storm Lifecycle Component.
 *
 * Implements the official 8-step IMD operational taxonomy (L, D, DD, CS, SCS, VSCS, ESCS, SuCS)
 * with a continuous wind speed indicator needle, and presents the storm's lifecycle
 * stage (Genesis -> Intensifying -> Peak -> Decaying) as a separate, clearly distinguished badge.
 */

interface StageSpan {
  stage: string;
  label: string;
  task: string;
  detail: string;
  start: string;
  end: string;
  peak_kt: number;
  n: number;
}

interface PerFix {
  ts: string;
  stage: string;
  wind_kt: number;
  imd_category: string;
  d24_kt: number | null;
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
  const classify = useStore((s) => s.classify);

  useEffect(() => {
    if (!caseId) return;
    fetch(`/v1/cases/${caseId}/lifecycle`)
      .then((r) => r.json())
      .then((d) => {
        setSpans(d.stages);
        setFixes(d.per_fix ?? []);
      })
      .catch(() => setSpans(null));
  }, [caseId]);

  const current = useMemo(() => {
    if (!fixes.length) return null;
    const now = stormClock ? new Date(stormClock).getTime() : new Date(fixes[0].ts).getTime();
    const seen = fixes.filter((f) => new Date(f.ts).getTime() <= now);
    return seen.length ? seen[seen.length - 1] : fixes[0];
  }, [fixes, stormClock]);

  if (!spans?.length) return null;

  const active = spans.find(
    (s) => current && new Date(current.ts) >= new Date(s.start)
      && new Date(current.ts) <= new Date(s.end)
  ) ?? spans[0];

  // Continuous wind speed for the needle (prefers live CYCLOPS fix, falls back to best-track)
  const continuousKt = classify?.wind_kt ?? current?.wind_kt ?? 0;
  const currentStep = getCategoryByWind(continuousKt);
  const currentCat = classify?.imd_category ?? current?.imd_category ?? currentStep.abbr;

  // Compute needle percentage position across the 8-segment IMD bar
  const activeIdx = IMD_8_SCALE.findIndex((s) => s.abbr === currentStep.abbr);
  const safeIdx = activeIdx >= 0 ? activeIdx : 0;
  const step = IMD_8_SCALE[safeIdx];
  const stepSpan = Math.max(1, step.max_kt - step.min_kt);
  const stepFrac = Math.max(0, Math.min(1, (continuousKt - step.min_kt) / stepSpan));
  const caretPct = Math.max(1, Math.min(99, ((safeIdx + stepFrac) / IMD_8_SCALE.length) * 100));

  return (
    <section className="lifecycle" aria-label="IMD Classification & Lifecycle">
      {/* 1. Distinct Lifecycle Stage Badge (Separated from Intensity Taxonomy) */}
      <div className="lc-badge-row">
        <div className="lc-stage-tag" style={{ borderColor: `${TASK_COLOR[active.task] ?? "#4a6478"}66` }}>
          <span className="lc-dot" style={{ background: TASK_COLOR[active.task] ?? "#8fb8cc" }} />
          <span style={{ color: TASK_COLOR[active.task] ?? "#dfeaf3" }}>{active.task}</span>
          <span className="dim">·</span>
          <span>{active.label}</span>
        </div>

        {current?.d24_kt != null && Math.abs(current.d24_kt) >= 5 && (
          <div className={`lc-trend ${current.d24_kt > 0 ? "up" : "down"}`}>
            {current.d24_kt > 0 ? "▲" : "▼"} {Math.abs(current.d24_kt).toFixed(0)} kt / 24 h
          </div>
        )}
      </div>

      {/* 2. Official 8-Step IMD Operational Scale Bar */}
      <div className="lc-imd-container" role="img" aria-label={`IMD Classification: ${currentCat}, ${continuousKt.toFixed(0)} knots`}>
        <div className="lc-imd-meta">
          <span>IMD SCALE (3-MIN SUSTAINED)</span>
          <span className="lc-active-lbl" style={{ color: catColor(currentCat) }}>
            {currentCat} · {continuousKt.toFixed(0)} kt
          </span>
        </div>

        <div className="lc-imd-track">
          {IMD_8_SCALE.map((s, idx) => {
            const isActive = idx === safeIdx;
            const isPast = idx < safeIdx;
            return (
              <div
                key={s.abbr}
                className={`lc-imd-seg ${isActive ? "active" : isPast ? "past" : ""}`}
                style={{
                  background: s.color,
                }}
                title={`${s.label} (${s.abbr}): ${s.min_kt}–${s.max_kt >= 160 ? "120+" : s.max_kt} kt`}
              >
                <span>{s.abbr}</span>
              </div>
            );
          })}

          {/* Continuous Caret Needle Indicator */}
          <div
            className="lc-imd-caret"
            style={{ left: `${caretPct}%` }}
            title={`Exact intensity: ${continuousKt.toFixed(1)} kt`}
          />
        </div>

        {/* Operational threshold ticks */}
        <div className="lc-imd-ticks" aria-hidden>
          <span>0</span>
          <span>17</span>
          <span>28</span>
          <span>34</span>
          <span>48</span>
          <span>64</span>
          <span>90</span>
          <span>120+</span>
        </div>
      </div>

      {/* Operational Task Context */}
      <p className="lc-detail">{active.detail}</p>

      {/* 3. Verification Readouts (Best-track truth vs Model estimate) */}
      {current && (
        <div className="lc-readout">
          <span className="mono dim">
            IBTrACS: <strong style={{ color: "var(--ink)" }}>{current.wind_kt.toFixed(0)} kt</strong> ({current.imd_category})
          </span>
          {classify && (
            <span className="mono" style={{ color: catColor(classify.imd_category) }}>
              CYCLOPS: <strong>{classify.wind_kt.toFixed(0)} kt</strong> ({classify.imd_category})
            </span>
          )}
        </div>
      )}
    </section>
  );
}
