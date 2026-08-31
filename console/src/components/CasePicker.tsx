import { useStore } from "../store";
import { catColor } from "../lib/imd";

export function CasePicker({ onSelect }: { onSelect: (id: string) => void }) {
  const cases = useStore((s) => s.cases);
  const active = useStore((s) => s.activeCase);

  return (
    <div className="case-picker" role="group" aria-label="Historical cases">
      {cases.map((c) => (
        <button key={c.id}
                className={`case-chip ${active?.id === c.id ? "on" : ""}`}
                onClick={() => onSelect(c.id)}
                title={c.note}>
          <span className="case-dot" style={{ background: catColor(c.peak_category) }} />
          <span className="case-nm">{c.name}</span>
          <span className="case-yr">{c.season}</span>
          <span className="case-pk">{c.peak_category}</span>
        </button>
      ))}
    </div>
  );
}
