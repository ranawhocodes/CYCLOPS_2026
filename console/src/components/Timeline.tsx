import { useStore } from "../store";
import { api } from "../api/client";
import { catColor, fmtUTC } from "../lib/imd";

const SPEEDS = [60, 120, 300, 600];

/**
 * Bottom timeline bar.
 *
 * The scrub track is tinted by IMD category along the storm's life, so the
 * intensification history is legible before pressing play — the same idea as a
 * video scrubber showing chapter markers. The filled portion is what the model
 * has been allowed to see; everything to the right of the head is the future
 * and is deliberately dimmed.
 */
export function Timeline() {
  const replay = useStore((s) => s.replay);
  const setReplay = useStore((s) => s.setReplay);
  const stormClock = useStore((s) => s.stormClock);
  const conn = useStore((s) => s.connection);
  const activeCase = useStore((s) => s.activeCase);
  const observed = useStore((s) => s.observed);

  if (!replay || !activeCase) return null;

  const n = Math.max(1, replay.n_frames - 1);
  const pct = (replay.idx / n) * 100;

  // The strip is tinted by IMD category, but ONLY over the portion already
  // revealed. It is built from `observed` — the track the replay has released so
  // far — rather than fetching the full storm, so the console never requests
  // data past the storm clock. The remainder stays neutral: the future is not
  // previewed, and the network tab shows no future-looking request either.
  const gradient =
    observed.length > 1
      ? `linear-gradient(to right, ${observed
          .map(
            (p, i) =>
              `${catColor(p.imd_category)} ${((i / (observed.length - 1)) * pct).toFixed(2)}%`
          )
          .join(", ")}, #16232e ${pct.toFixed(2)}%, #16232e 100%)`
      : "#16232e";

  return (
    <div className="timeline">
      <div className="tl-left">
        <span className={`conn conn-${conn}`} aria-live="polite">
          {conn === "live" ? "● LIVE" : conn === "offline" ? "○ OFFLINE" : `◐ ${conn.toUpperCase()}`}
        </span>
        <span className="tl-case">{activeCase.name}</span>
        <span className="tl-season">{activeCase.season}</span>
      </div>

      <div className="tl-controls">
        <button className="icon-btn" aria-label="Step back"
                onClick={() => api.seek(replay.session_id, replay.idx - 1).then(setReplay)}>
          ⏮
        </button>
        <button className="icon-btn play"
                aria-label={replay.paused ? "Play" : "Pause"}
                onClick={() =>
                  (replay.paused ? api.resume(replay.session_id) : api.pause(replay.session_id))
                    .then(setReplay)}>
          {replay.paused ? "▶" : "❚❚"}
        </button>
        <button className="icon-btn" aria-label="Step forward"
                onClick={() => api.seek(replay.session_id, replay.idx + 1).then(setReplay)}>
          ⏭
        </button>
      </div>

      <div className="tl-scrub">
        <div className="tl-strip" style={{ background: gradient }} aria-hidden>
          <div className="tl-future" style={{ left: `${pct}%` }} />
          <div className="tl-head" style={{ left: `${pct}%` }} />
        </div>
        <input
          type="range" min={0} max={n} value={replay.idx}
          aria-label="Scrub replay position"
          aria-valuetext={fmtUTC(stormClock)}
          onChange={(e) => api.seek(replay.session_id, Number(e.target.value)).then(setReplay)}
        />
      </div>

      <div className="tl-right">
        <div className="tl-clock">
          <span className="tl-clock-v">{fmtUTC(stormClock)}</span>
          <span className="tl-frame">{replay.idx + 1}/{replay.n_frames}</span>
        </div>
        <label className="tl-speed">
          <select value={replay.speed} aria-label="Replay speed"
                  onChange={(e) =>
                    api.setSpeed(replay.session_id, Number(e.target.value)).then(setReplay)}>
            {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
