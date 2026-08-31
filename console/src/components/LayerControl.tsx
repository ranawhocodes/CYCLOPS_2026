import { useState } from "react";
import { useStore } from "../store";
import type { LayerToggles } from "../store";

const LAYERS: { key: keyof LayerToggles; label: string; hint: string }[] = [
  { key: "satellite", label: "Infrared imagery", hint: "Brightness temperature, draped in geographic position" },
  { key: "wind", label: "Surface wind flow", hint: "Animated scatterometer retrieval; stops at the swath edge" },
  { key: "track", label: "Observed track", hint: "IBTrACS best track up to the storm clock" },
  { key: "forecast", label: "Forecast track", hint: "6/12/18/24 h nowcast" },
  { key: "cone", label: "Uncertainty cone", hint: "67th-percentile radius from validation errors" },
];

/**
 * Layer toggles, collapsed to a single icon until opened.
 *
 * Every layer is on by default: the point of the console is that all of it is
 * visible at once. The toggles exist so a specific layer can be isolated when
 * someone asks "show me just the wind field" mid-demo, without narrating.
 */
export function LayerControl() {
  const [open, setOpen] = useState(false);
  const layers = useStore((s) => s.layers);
  const toggle = useStore((s) => s.toggleLayer);
  const windGrid = useStore((s) => s.windGrid);

  return (
    <div className={`layer-ctl ${open ? "open" : ""}`}>
      <button
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Map layers"
        title="Map layers"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path d="M8 1.5 1.5 5 8 8.5 14.5 5 8 1.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          <path d="M1.5 8.5 8 12l6.5-3.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="layer-menu" role="group" aria-label="Map layers">
          {LAYERS.map((l) => (
            <label key={l.key} className="layer-row" title={l.hint}>
              <input
                type="checkbox"
                checked={layers[l.key]}
                onChange={() => toggle(l.key)}
              />
              <span>{l.label}</span>
              {l.key === "wind" && (
                <em className="layer-note">
                  {windGrid?.available
                    ? `${Math.round((windGrid.coverage ?? 0) * 100)}% swath`
                    : "no pass"}
                </em>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
