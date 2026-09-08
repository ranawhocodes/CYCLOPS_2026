// IMD scale constants mirrored from src/cyclops/domain/imd.py.
// The Python module is authoritative; this exists so the console can label and
// colour without a round-trip. If one changes, change both.

export type Category = "LOW" | "L" | "D" | "DD" | "CS" | "SCS" | "VSCS" | "ESCS" | "SuCS";

export interface ImdScaleStep {
  abbr: Category;
  label: string;
  min_kt: number;
  max_kt: number;
  color: string;
}

export const IMD_8_SCALE: ImdScaleStep[] = [
  { abbr: "L", label: "Low Pressure Area", min_kt: 0, max_kt: 16.9, color: "#607d8b" },
  { abbr: "D", label: "Depression", min_kt: 17, max_kt: 27, color: "#4592af" },
  { abbr: "DD", label: "Deep Depression", min_kt: 28, max_kt: 33, color: "#00a8cc" },
  { abbr: "CS", label: "Cyclonic Storm", min_kt: 34, max_kt: 47, color: "#2eb872" },
  { abbr: "SCS", label: "Severe Cyclonic Storm", min_kt: 48, max_kt: 63, color: "#f4b41a" },
  { abbr: "VSCS", label: "Very Severe Cyclonic Storm", min_kt: 64, max_kt: 89, color: "#e8630a" },
  { abbr: "ESCS", label: "Extremely Severe Cyclonic Storm", min_kt: 90, max_kt: 119, color: "#e83a3a" },
  { abbr: "SuCS", label: "Super Cyclonic Storm", min_kt: 120, max_kt: 160, color: "#9c27b0" },
];

export const CATEGORY_LABEL: Record<string, string> = {
  LOW: "Low Pressure Area",
  L: "Low Pressure Area",
  D: "Depression",
  DD: "Deep Depression",
  CS: "Cyclonic Storm",
  SCS: "Severe Cyclonic Storm",
  VSCS: "Very Severe Cyclonic Storm",
  ESCS: "Extremely Severe Cyclonic Storm",
  SuCS: "Super Cyclonic Storm",
};

export const CATEGORY_COLOR: Record<string, string> = {
  LOW: "#607d8b",
  L: "#607d8b",
  D: "#4592af",
  DD: "#00a8cc",
  CS: "#2eb872",
  SCS: "#f4b41a",
  VSCS: "#e8630a",
  ESCS: "#e83a3a",
  SuCS: "#9c27b0",
};

export const CATEGORY_RANGE: Record<string, string> = {
  LOW: "< 17 kt",
  L: "< 17 kt",
  D: "17–27 kt",
  DD: "28–33 kt",
  CS: "34–47 kt",
  SCS: "48–63 kt",
  VSCS: "64–89 kt",
  ESCS: "90–119 kt",
  SuCS: "≥ 120 kt",
};

export const ORDER: Category[] = ["L", "D", "DD", "CS", "SCS", "VSCS", "ESCS", "SuCS"];

export const catColor = (c?: string) => {
  const norm = c === "LOW" ? "L" : (c ?? "L");
  return CATEGORY_COLOR[norm] ?? CATEGORY_COLOR[c ?? "LOW"] ?? "#607d8b";
};

export function getCategoryByWind(kt: number): ImdScaleStep {
  for (let i = IMD_8_SCALE.length - 1; i >= 0; i--) {
    if (kt >= IMD_8_SCALE[i].min_kt) return IMD_8_SCALE[i];
  }
  return IMD_8_SCALE[0];
}

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

