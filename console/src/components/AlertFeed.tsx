import { useStore } from "../store";
import { fmtUTC } from "../lib/imd";

const ICON: Record<string, string> = {
  detection: "◉",
  rapid_intensification: "▲",
  category_change: "▲",
  landfall_watch: "◆",
};

export function AlertFeed() {
  const alerts = useStore((s) => s.alerts);

  return (
    <section className="panel alerts" aria-label="Alerts" aria-live="polite">
      <h2 className="panel-title">Alerts</h2>
      {alerts.length === 0 ? (
        <p className="empty-hint">No alerts raised yet</p>
      ) : (
        <ul className="alert-list">
          {alerts.map((a, i) => (
            <li key={`${a.ts}-${a.kind}-${i}`} className={`alert alert-${a.severity}`}>
              <span className="alert-icon" aria-hidden>{ICON[a.kind] ?? "•"}</span>
              <div>
                <div className="alert-msg">{a.message}</div>
                <div className="alert-ts">{fmtUTC(a.ts)}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="alerts-note">
        Rapid intensification uses the standard ≥ 30 kt / 24 h definition.
      </p>
    </section>
  );
}
