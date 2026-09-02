import { useEffect, useMemo, useState } from "react";
import { catColor, fmtUTC } from "../lib/imd";

/**
 * Cyclone Fani (2019) — the real-data case study.
 *
 * This view exists because Fani is the one case with no synthetic imagery
 * anywhere in the chain: MODIS Band 31 from NASA GIBS, IBTrACS best track on
 * IMD's 3-minute convention, and a rule-based Dvorak estimator whose reasoning
 * is printed on screen rather than hidden in a weight matrix.
 *
 * The design rule from the rest of the console still holds: every estimate is
 * shown next to the truth it is being scored against, and the error is stated
 * rather than left to be eyeballed.
 */

interface Frame {
  index: number;
  date: string;
  pass: string;
  observed_at: string;
  image_url: string;
  first_guess: { lat: number; lon: number };
  truth: { lat: number; lon: number; wind_kt: number; imd_category: string; t_number: number };
  fix: {
    lat: number; lon: number; detected: boolean; refined: boolean;
    confidence: number; symmetry: number; eye_detected: boolean;
    eye_temp_c: number | null; ring_temp_c: number | null;
    cold_fraction: number; reason: string;
  };
  dvorak: {
    pattern: string; t_number: number; wind_kt: number; imd_category: string;
    cdo_diameter_km: number; rule: string;
    t_number_smoothed: number; wind_kt_smoothed: number; imd_category_smoothed: string;
  };
  centre_error_km: number;
  first_guess_error_km: number;
  last_fix_error_km: number;
  scene: { coverage: number; min_c: number };
}

interface Summary {
  data: { n_scenes: number; imagery: string; labels: string; note: string };
  identification: {
    centre_error_km: { mean: number; median: number; p90: number; max: number };
    first_guess_error_km: { mean: number };
    last_fix_error_km: { mean: number };
    skill_vs_first_guess: number;
    frames_refined: number;
    eye_detected_frames: number;
    detection_rate: number;
  };
  classification: {
    method: string;
    raw: { rmse_kt: number; mae_kt: number; bias_kt: number };
    time_constrained: { rmse_kt: number; mae_kt: number; bias_kt: number };
    category_exact: number;
    category_within_one: number;
    patterns: Record<string, number>;
  };
}

const PATTERN_COLOR: Record<string, string> = {
  EYE: "#e8404a", CDO: "#f2803d", EMBEDDED_CENTER: "#f2c63d", SHEAR: "#8ba3b4",
};

export function FaniStudy({ onClose }: { onClose: () => void }) {
  const [frames, setFrames] = useState<Frame[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/v1/fani/frames").then((r) => r.json()),
      fetch("/v1/fani/summary").then((r) => r.json()),
    ])
      .then(([f, s]) => { setFrames(f); setSummary(s); })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!playing || !frames) return;
    const t = setInterval(
      () => setI((v) => (v + 1 >= frames.length ? 0 : v + 1)), 1100);
    return () => clearInterval(t);
  }, [playing, frames]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setI((v) => Math.min(v + 1, (frames?.length ?? 1) - 1));
      if (e.key === "ArrowLeft") setI((v) => Math.max(v - 1, 0));
      if (e.key === " ") { e.preventDefault(); setPlaying((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, frames]);

  const fr = frames?.[i];

  // Sparkline geometry for the intensity strip.
  const spark = useMemo(() => {
    if (!frames?.length) return null;
    const W = 100, H = 30;
    const max = Math.max(...frames.map((f) => Math.max(f.truth.wind_kt, f.dvorak.wind_kt)), 60);
    const pt = (v: number, idx: number) =>
      `${(idx / (frames.length - 1)) * W},${H - (v / max) * H}`;
    return {
      truth: frames.map((f, k) => pt(f.truth.wind_kt, k)).join(" "),
      dvorak: frames.map((f, k) => pt(f.dvorak.wind_kt_smoothed, k)).join(" "),
      W, H, max,
    };
  }, [frames]);

  if (err) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <p className="error">Could not load the Fani study: {err}</p>
          <p className="modal-note">Run <code>make fani</code> to fetch the
            imagery and build the analysis.</p>
        </div>
      </div>
    );
  }
  if (!frames || !summary || !fr) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal"><p className="empty-hint">Loading real MODIS scenes…</p></div>
      </div>
    );
  }

  const idn = summary.identification;
  const cls = summary.classification;
  const dErr = fr.dvorak.wind_kt_smoothed - fr.truth.wind_kt;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="fani" role="dialog" aria-modal="true"
           aria-label="Cyclone Fani case study" onClick={(e) => e.stopPropagation()}>

        <header className="fani-head">
          <div>
            <h2>Cyclone Fani · 2019</h2>
            <p className="fani-sub">
              Real MODIS Band 31 infrared (NASA GIBS) · IBTrACS best track,
              IMD 3-minute convention · {summary.data.n_scenes} day passes
            </p>
          </div>
          <span className="real-tag">100% REAL DATA</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="fani-body">
          {/* ---------- imagery ---------- */}
          <figure className="fani-scene">
            <img src={fr.image_url} alt={`Infrared scene at ${fr.observed_at}`} />
            <figcaption>
              <span className="mono">{fmtUTC(fr.observed_at)}</span>
              <span>{fr.pass.replace("_", " ")}</span>
              <span className="dim">coverage {(fr.scene.coverage * 100).toFixed(0)}%
                · coldest {fr.scene.min_c.toFixed(0)}°C</span>
            </figcaption>
          </figure>

          {/* ---------- readouts ---------- */}
          <div className="fani-side">
            <section className="fani-card">
              <h3>Identification</h3>
              <div className="fani-kv">
                <span>Centre fix</span>
                <b className="mono">{fr.fix.lat.toFixed(2)}N {fr.fix.lon.toFixed(2)}E</b>
                <span>Best track</span>
                <b className="mono">{fr.truth.lat.toFixed(2)}N {fr.truth.lon.toFixed(2)}E</b>
                <span>Error</span>
                <b className="mono hl">{fr.centre_error_km.toFixed(1)} km</b>
                <span>First guess</span>
                <b className="mono dim">{fr.first_guess_error_km.toFixed(1)} km</b>
              </div>
              <p className="fani-reason">{fr.fix.reason}</p>
              <div className="fani-chips">
                <span className={fr.fix.eye_detected ? "chip on" : "chip"}>
                  {fr.fix.eye_detected ? "eye found" : "no eye"}
                </span>
                <span className="chip">symmetry {fr.fix.symmetry.toFixed(2)}</span>
                {fr.fix.refined
                  ? <span className="chip on">refined</span>
                  : <span className="chip">held guess</span>}
              </div>
            </section>

            <section className="fani-card">
              <h3>Classification — objective Dvorak</h3>
              <div className="fani-pattern"
                   style={{ borderColor: PATTERN_COLOR[fr.dvorak.pattern] }}>
                <b style={{ color: PATTERN_COLOR[fr.dvorak.pattern] }}>
                  {fr.dvorak.pattern.replace("_", " ")}
                </b>
                {/* Both T-numbers, because the rule text below explains how the
                    RAW one was derived. Showing only the constrained value next
                    to a rule that computes a different number reads as an
                    inconsistency. */}
                <span className="fani-tnums">
                  <span className="mono">T{fr.dvorak.t_number_smoothed.toFixed(1)}</span>
                  <em className="mono dim">constrained</em>
                  {Math.abs(fr.dvorak.t_number - fr.dvorak.t_number_smoothed) > 0.05 && (
                    <>
                      <span className="mono dim">· raw T{fr.dvorak.t_number.toFixed(1)}</span>
                    </>
                  )}
                </span>
              </div>
              <div className="fani-vs">
                <div>
                  <span className="dim">CYCLOPS</span>
                  <b className="mono" style={{ color: catColor(fr.dvorak.imd_category_smoothed) }}>
                    {fr.dvorak.wind_kt_smoothed.toFixed(0)} kt
                  </b>
                  <span className="mono dim">{fr.dvorak.imd_category_smoothed}</span>
                </div>
                <div className="fani-delta">
                  <b className={Math.abs(dErr) <= 15 ? "ok" : "off"}>
                    {dErr >= 0 ? "+" : ""}{dErr.toFixed(0)} kt
                  </b>
                </div>
                <div>
                  <span className="dim">Best track</span>
                  <b className="mono" style={{ color: catColor(fr.truth.imd_category) }}>
                    {fr.truth.wind_kt.toFixed(0)} kt
                  </b>
                  <span className="mono dim">{fr.truth.imd_category}</span>
                </div>
              </div>
              <p className="fani-reason">
                {fr.dvorak.rule}
                {Math.abs(fr.dvorak.t_number - fr.dvorak.t_number_smoothed) > 0.05 && (
                  <> · rate limit ±0.5 T/step → T{fr.dvorak.t_number_smoothed.toFixed(1)}</>
                )}
              </p>
            </section>
          </div>
        </div>

        {/* ---------- timeline ---------- */}
        <div className="fani-timeline">
          {spark && (
            <svg viewBox={`0 0 ${spark.W} ${spark.H}`} preserveAspectRatio="none"
                 className="fani-spark" aria-hidden>
              <polyline points={spark.truth} fill="none" stroke="#3bd16f" strokeWidth="0.8" />
              <polyline points={spark.dvorak} fill="none" stroke="#35c4e8"
                        strokeWidth="0.8" strokeDasharray="2 1" />
              <line x1={(i / (frames.length - 1)) * spark.W} y1="0"
                    x2={(i / (frames.length - 1)) * spark.W} y2={spark.H}
                    stroke="#ffffff" strokeWidth="0.5" />
            </svg>
          )}
          <div className="fani-scrub">
            <button className="icon-btn" onClick={() => setPlaying((p) => !p)}
                    aria-label={playing ? "Pause" : "Play"}>
              {playing ? "❚❚" : "▶"}
            </button>
            <input type="range" min={0} max={frames.length - 1} value={i}
                   aria-label="Scene" onChange={(e) => setI(Number(e.target.value))} />
            <span className="mono dim">{i + 1}/{frames.length}</span>
          </div>
          <div className="fani-strip">
            {frames.map((f, k) => (
              <button key={k} className={`fani-tick ${k === i ? "on" : ""}`}
                      style={{ background: PATTERN_COLOR[f.dvorak.pattern] }}
                      title={`${f.observed_at} · ${f.dvorak.pattern}`}
                      onClick={() => setI(k)} aria-label={`Scene ${k + 1}`} />
            ))}
          </div>
        </div>

        {/* ---------- headline results ---------- */}
        <footer className="fani-results">
          <div>
            <span className="dim">Centre-fix error</span>
            <b className="mono">{idn.centre_error_km.mean.toFixed(1)} km</b>
            <span className="dim">
              vs {idn.first_guess_error_km.mean.toFixed(1)} km first guess
              ({(idn.skill_vs_first_guess * 100).toFixed(1)}%),
              {" "}{idn.last_fix_error_km.mean.toFixed(1)} km last fix
            </span>
          </div>
          <div>
            <span className="dim">Intensity RMSE</span>
            <b className="mono">{cls.time_constrained.rmse_kt.toFixed(1)} kt</b>
            <span className="dim">
              bias {cls.time_constrained.bias_kt >= 0 ? "+" : ""}
              {cls.time_constrained.bias_kt.toFixed(1)} kt ·
              within-one {(cls.category_within_one * 100).toFixed(0)}%
            </span>
          </div>
          <p className="fani-caveat">
            Dvorak tables are unfitted, but two eye-gate thresholds were chosen by
            inspecting Fani — these figures are <strong>not fully out-of-sample</strong>.
            Objective Dvorak over-estimates weak systems carrying a large cold
            shield, and under-estimates at peak when the eye is not resolved in a
            single polar-orbiter pass.
          </p>
        </footer>
      </div>
    </div>
  );
}
