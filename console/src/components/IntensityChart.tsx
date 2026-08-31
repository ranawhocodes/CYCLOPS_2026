import {
  Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { useStore } from "../store";

/**
 * Observed-versus-predicted intensity, with the forecast band appended.
 *
 * The band is drawn from the q10/q90 quantile forecasts, so the chart shows an
 * envelope rather than a stroke. Nothing in this console renders a bare point
 * estimate.
 */
export function IntensityChart() {
  const history = useStore((s) => s.history);
  const nowcast = useStore((s) => s.nowcast);
  const stormClock = useStore((s) => s.stormClock);

  const past = history.slice(-16).map((h) => ({
    label: h.ts.slice(5, 16).replace("T", " "),
    truth: Number.isFinite(h.truth) ? h.truth : null,
    predicted: Number.isFinite(h.predicted) ? h.predicted : null,
  }));

  const future = (nowcast?.forecasts ?? []).map((f) => ({
    label: `+${f.lead_h}h`,
    forecast: f.wind_kt,
    band: [f.wind_kt_q10, f.wind_kt_q90] as [number, number],
  }));

  const data = [...past, ...future];
  if (data.length < 2) {
    return (
      <section className="panel chart" aria-label="Intensity trend">
        <h2 className="panel-title">Intensity trend</h2>
        <p className="empty-hint">Collecting frames…</p>
      </section>
    );
  }

  return (
    <section className="panel chart" aria-label="Intensity trend">
      <h2 className="panel-title">
        Intensity trend
        <span className="panel-sub">kt, 3-min sustained</span>
      </h2>
      <ResponsiveContainer width="100%" height={168}>
        <ComposedChart data={data} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fill: "#6E8899", fontSize: 10 }}
                 interval="preserveStartEnd" tickLine={false}
                 axisLine={{ stroke: "#1C3040" }} />
          <YAxis tick={{ fill: "#6E8899", fontSize: 10 }} tickLine={false}
                 axisLine={{ stroke: "#1C3040" }} domain={[0, "dataMax + 20"]} />
          <Tooltip
            contentStyle={{ background: "#0E1B26", border: "1px solid #1C3040",
                            borderRadius: 4, fontSize: 12 }}
            labelStyle={{ color: "#D6E4EE" }} />
          <Area type="monotone" dataKey="band" stroke="none" fill="#F2C63D"
                fillOpacity={0.16} name="90% band" isAnimationActive={false} />
          <Line type="monotone" dataKey="truth" stroke="#3BD16F" strokeWidth={2}
                dot={false} name="Best track" isAnimationActive={false}
                connectNulls={false} />
          <Line type="monotone" dataKey="predicted" stroke="#35C4E8" strokeWidth={2}
                dot={false} name="CYCLOPS estimate" isAnimationActive={false}
                connectNulls={false} />
          <Line type="monotone" dataKey="forecast" stroke="#F2C63D" strokeWidth={2}
                strokeDasharray="4 3" dot={{ r: 2.5, fill: "#F2C63D" }}
                name="Forecast" isAnimationActive={false} connectNulls={false} />
          {stormClock && past.length > 0 && (
            <ReferenceLine x={past[past.length - 1].label} stroke="#2C4658"
                           strokeDasharray="2 2"
                           label={{ value: "now", fill: "#6E8899", fontSize: 10,
                                    position: "top" }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span><i style={{ background: "#3BD16F" }} /> Best track (IBTrACS)</span>
        <span><i style={{ background: "#35C4E8" }} /> CYCLOPS estimate</span>
        <span><i style={{ background: "#F2C63D" }} /> Forecast + 90% band</span>
      </div>
    </section>
  );
}
