import { useStore } from "../store";
import { api } from "../api/client";
import { fmtUTC } from "../lib/imd";

const SPEEDS = [60, 120, 300, 600];

export function ReplayControls() {
  const replay = useStore((s) => s.replay);
  const setReplay = useStore((s) => s.setReplay);
  const stormClock = useStore((s) => s.stormClock);
  const conn = useStore((s) => s.connection);
  const activeCase = useStore((s) => s.activeCase);

  if (!replay || !activeCase) return null;

  const pctDone = replay.n_frames > 1 ? (replay.idx / (replay.n_frames - 1)) * 100 : 0;

  return (
    <div className="replay-bar">
      <div className="replay-id">
        <span className={`conn conn-${conn}`} aria-live="polite">
          {conn === "live" ? "● LIVE" : conn === "offline" ? "○ OFFLINE" : "◐ " + conn.toUpperCase()}
        </span>
        <strong>REPLAY</strong>
        <span className="case-name">{activeCase.name} {activeCase.season}</span>
      </div>

      <div className="replay-clock">
        <span className="clock-label">storm clock</span>
        <span className="clock-value">{fmtUTC(stormClock)}</span>
        <span className="clock-idx">frame {replay.idx + 1}/{replay.n_frames}</span>
      </div>

      <div className="replay-controls">
        <button className="btn" aria-label="Step back"
                onClick={() => api.seek(replay.session_id, replay.idx - 1).then(setReplay)}>
          ◀◀
        </button>
        <button className="btn btn-primary"
                aria-label={replay.paused ? "Play" : "Pause"}
                onClick={() =>
                  (replay.paused ? api.resume(replay.session_id) : api.pause(replay.session_id))
                    .then(setReplay)}>
          {replay.paused ? "▶ Play" : "❚❚ Pause"}
        </button>
        <button className="btn" aria-label="Step forward"
                onClick={() => api.seek(replay.session_id, replay.idx + 1).then(setReplay)}>
          ▶▶
        </button>

        <label className="speed">
          <span>speed</span>
          <select value={replay.speed}
                  onChange={(e) =>
                    api.setSpeed(replay.session_id, Number(e.target.value)).then(setReplay)}>
            {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
      </div>

      <input className="scrub" type="range" min={0} max={Math.max(0, replay.n_frames - 1)}
             value={replay.idx} aria-label="Scrub replay position"
             style={{ ["--pct" as string]: `${pctDone}%` }}
             onChange={(e) => api.seek(replay.session_id, Number(e.target.value)).then(setReplay)} />
    </div>
  );
}
