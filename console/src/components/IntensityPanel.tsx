import { useStore } from "../store";
import { CATEGORY_RANGE, catColor } from "../lib/imd";

const SCALE_MAX = 160;
const pct = (v: number) => Math.max(0, Math.min(100, (v / SCALE_MAX) * 100));

export function IntensityPanel() {
  const c = useStore((s) => s.classify);
  const truth = useStore((s) => s.truthNow);

  if (!c) return <Empty label="Intensity" hint="Waiting for the first classification" />;
  if ((c as any).unavailable)
    return <Empty label="Intensity" hint={(c as any).reason ?? "Model unavailable"} />;

  const [lo, hi] = c.wind_kt_ci;
  const color = catColor(c.imd_category);

  return (
    <section className="panel" aria-label="Intensity estimate">
      <h2 className="panel-title">Intensity</h2>

      <div className="cat-badge" style={{ borderColor: color }}>
        <span className="cat-abbr" style={{ color }}>{c.imd_category}</span>
        <span className="cat-full">{c.imd_category_label}</span>
        <span className="cat-range">{CATEGORY_RANGE[c.imd_category]}</span>
      </div>

      <div className="kt-readout">
        <span className="kt-value">{c.wind_kt.toFixed(0)}</span>
        <span className="kt-unit">kt</span>
      </div>
      <div className="kt-note">{c.wind_convention}</div>

      {/* The interval is a bar, not text in brackets. "112 (98–126)" is easy to
          mentally discard; a drawn interval is not, and internalising the
          uncertainty is the entire point. */}
      <div className="ci-track" role="img"
           aria-label={`90 percent interval, ${lo} to ${hi} knots`}>
        <div className="ci-band"
             style={{ left: `${pct(lo)}%`, width: `${pct(hi) - pct(lo)}%`,
                      background: color }} />
        <div className="ci-point" style={{ left: `${pct(c.wind_kt)}%` }} />
      </div>
      <div className="ci-labels">
        <span>{lo.toFixed(0)}</span>
        <span className="ci-caption">90% interval</span>
        <span>{hi.toFixed(0)}</span>
      </div>

      <dl className="meta">
        <dt>Dvorak T-number</dt><dd>{c.t_number.toFixed(1)}</dd>
        <dt>Detection conf.</dt><dd>{(c.detection_confidence * 100).toFixed(0)}%</dd>
        <dt>Inference</dt><dd>{c.inference_ms} ms</dd>
        {truth && (
          <>
            <dt>Best track</dt>
            <dd className="truth">
              {truth.wind_kt.toFixed(0)} kt · {truth.imd_category}
              <span className={`delta ${Math.abs(c.wind_kt - truth.wind_kt) <= 10 ? "ok" : "off"}`}>
                {c.wind_kt - truth.wind_kt >= 0 ? "+" : ""}
                {(c.wind_kt - truth.wind_kt).toFixed(0)}
              </span>
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

export function Empty({ label, hint }: { label: string; hint: string }) {
  return (
    <section className="panel panel-empty" aria-label={label}>
      <h2 className="panel-title">{label}</h2>
      <p className="empty-hint">{hint}</p>
    </section>
  );
}
