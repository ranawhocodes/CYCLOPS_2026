import { useStore } from "../store";
import { catColor } from "../lib/imd";

export function ForecastTable() {
  const nowcast = useStore((s) => s.nowcast);
  if (!nowcast?.forecasts?.length) return null;

  return (
    <section className="panel" aria-label="Nowcast">
      <h2 className="panel-title">
        Nowcast
        <span className="panel-sub">{nowcast.model?.target}</span>
      </h2>
      <table className="fc">
        <thead>
          <tr>
            <th>Lead</th><th>Position</th><th>Intensity</th>
            <th title="Radius enclosing 67% of validation errors">Cone r</th>
          </tr>
        </thead>
        <tbody>
          {nowcast.forecasts.map((f) => (
            <tr key={f.lead_h}>
              <td className="fc-lead">+{f.lead_h}h</td>
              <td className="fc-pos">
                {f.position.lat.toFixed(1)}N {f.position.lon.toFixed(1)}E
              </td>
              <td>
                <span className="fc-cat" style={{ color: catColor(f.imd_category) }}>
                  {f.imd_category}
                </span>{" "}
                {f.wind_kt.toFixed(0)}
                <em className="fc-band">
                  {" "}{f.wind_kt_q10.toFixed(0)}–{f.wind_kt_q90.toFixed(0)}
                </em>
              </td>
              <td className="fc-cone">{f.cone_radius_km.toFixed(0)} km</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="fc-note">{nowcast.cone_definition}</p>
    </section>
  );
}
