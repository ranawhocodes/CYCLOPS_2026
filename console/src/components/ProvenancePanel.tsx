import { useStore } from "../store";
import { fmtAge, fmtUTC } from "../lib/imd";

// Freshness thresholds in minutes. Colour is never the only signal — each row
// also carries a glyph, so the panel reads correctly in greyscale and for a
// colour-blind viewer.
function tone(ageMin: number | null | undefined) {
  if (ageMin === null || ageMin === undefined) return { cls: "absent", glyph: "○" };
  if (ageMin <= 60) return { cls: "fresh", glyph: "●" };
  if (ageMin <= 360) return { cls: "ageing", glyph: "▲" };
  return { cls: "stale", glyph: "■" };
}

export function ProvenancePanel() {
  const p = useStore((s) => s.classify?.provenance);
  const health = useStore((s) => s.health);
  if (!p) return null;

  const envProvider = health?.env_provider?.name ?? "—";
  const rows = [
    { label: "Infrared", src: p.ir?.source, age: p.ir?.age_min ?? null,
      at: p.ir?.observed_at, synth: p.ir?.is_synthetic },
    { label: "Surface wind", src: p.wind?.source ?? "no coincident pass",
      age: p.wind?.age_min ?? null, at: p.wind?.observed_at,
      synth: p.wind?.is_synthetic,
      extra: p.wind ? `${(p.wind.coverage * 100).toFixed(0)}% swath` : undefined },
    { label: "SST", src: p.env?.sst_source, age: null, proxy: p.env?.is_proxy },
    { label: "Wind shear", src: p.env?.shear_source, age: null, proxy: p.env?.is_proxy },
  ];

  const fused = [p.ir && "infrared", p.wind && "scatterometer wind", "environment"]
    .filter(Boolean).join(", ");

  return (
    <section className="panel" aria-label="Data sources">
      <h2 className="panel-title">Data sources</h2>
      <table className="prov">
        <tbody>
          {rows.map((r) => {
            const t = tone(r.age);
            return (
              <tr key={r.label} className={`prov-${t.cls}`}>
                <td className="prov-label">{r.label}</td>
                <td className="prov-src">
                  {r.src}
                  {r.extra && <em> · {r.extra}</em>}
                  {(r.synth || r.proxy) && (
                    <span className="prov-flag">{r.synth ? "synthetic" : "proxy"}</span>
                  )}
                  {r.at && <div className="prov-at">{fmtUTC(r.at)}</div>}
                </td>
                <td className="prov-age">
                  {fmtAge(r.age)} <span aria-hidden>{t.glyph}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="prov-note">
        This estimate fused {fused}. Environment via <strong>{envProvider}</strong>.
      </p>
    </section>
  );
}
