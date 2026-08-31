// IMD scale constants mirrored from src/cyclops/domain/imd.py.
// The Python module is authoritative; this exists so the console can label and
// colour without a round-trip. If one changes, change both.

export type Category = "LOW" | "D" | "DD" | "CS" | "SCS" | "VSCS" | "ESCS" | "SuCS";

export const CATEGORY_LABEL: Record<string, string> = {
  LOW: "Low Pressure Area",
  D: "Depression",
  DD: "Deep Depression",
  CS: "Cyclonic Storm",
  SCS: "Severe Cyclonic Storm",
  VSCS: "Very Severe Cyclonic Storm",
  ESCS: "Extremely Severe Cyclonic Storm",
  SuCS: "Super Cyclonic Storm",
};

// Ramp taken from the Dvorak BD enhancement curve rather than an arbitrary
// gradient, so the map legend and the enhanced imagery speak one language.
export const CATEGORY_COLOR: Record<string, string> = {
  LOW: "#8FA3B0",
  D: "#8FA3B0",
  DD: "#35C4E8",
  CS: "#3BD16F",
  SCS: "#F2C63D",
  VSCS: "#F2803D",
  ESCS: "#E8404A",
  SuCS: "#A82078",
};

export const CATEGORY_RANGE: Record<string, string> = {
  LOW: "< 17 kt",
  D: "17–27 kt",
  DD: "28–33 kt",
  CS: "34–47 kt",
  SCS: "48–63 kt",
  VSCS: "64–89 kt",
  ESCS: "90–119 kt",
  SuCS: "≥ 120 kt",
};

export const ORDER: Category[] = ["D", "DD", "CS", "SCS", "VSCS", "ESCS", "SuCS"];

export const catColor = (c?: string) => CATEGORY_COLOR[c ?? "LOW"] ?? "#8FA3B0";

export function fmtUTC(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(
    d.getUTCHours()
  )}:${p(d.getUTCMinutes())}Z`;
}

export function fmtAge(min?: number | null): string {
  if (min === null || min === undefined) return "—";
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  return `${h}h ${Math.round(min % 60)}m`;
}
