import type { MV, Val } from "./types";

export const UNAVAILABLE = "UNAVAILABLE";

/** Pure string formatting. Never converts through float, never turns null into 0. */
function group(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
function splitNum(s: string): { sign: string; int: string; frac: string } | null {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(s.trim());
  return m ? { sign: m[1], int: m[2], frac: m[3] ?? "" } : null;
}

export function formatMoney(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return UNAVAILABLE;
  const p = splitNum(String(v));
  if (!p) return String(v);
  const frac = (p.frac + "00").slice(0, 2);
  return `${p.sign}$${group(p.int)}.${frac}`;
}
export function formatCount(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return UNAVAILABLE;
  const p = splitNum(String(v));
  return p ? `${p.sign}${group(p.int)}${p.frac ? "." + p.frac : ""}` : String(v);
}
/** Fraction string ("0.4") to percent text ("40%") by shifting the decimal point (no float math). */
export function formatPercent(fraction: string | number | null | undefined): string {
  if (fraction === null || fraction === undefined) return UNAVAILABLE;
  const p = splitNum(String(fraction));
  if (!p) return String(fraction);
  const shiftedInt = (p.int + p.frac.padEnd(2, "0").slice(0, 2)).replace(/^0+(?=\d)/, "");
  const rest = p.frac.slice(2);
  return `${p.sign}${group(shiftedInt)}${rest ? "." + rest : ""}%`;
}
export function formatDate(d: string | null | undefined): string {
  return d ? d : UNAVAILABLE;
}

export function formatValue(value: string | number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return UNAVAILABLE;
  switch (unit) {
    case "USD": return formatMoney(value);
    case "USD_per_day": return `${formatMoney(value)}/day`;
    case "count_per_day": return `${formatCount(value)}/day`;
    case "days": return `${formatCount(value)} d`;
    case "ratio": return formatPercent(value);
    default: return formatCount(value);
  }
}

export function isMV(v: unknown): v is MV {
  return typeof v === "object" && v !== null && "metric_key" in v && "status" in v;
}
export function formatMV(mv: MV | null | undefined): string {
  return mv ? formatValue(mv.value, mv.unit) : UNAVAILABLE;
}
/** For diagnostics-style fields that may be a bare value or an MV. USD assumed for bare values unless unit given. */
export function formatVal(v: Val | undefined, unit: string = "USD"): string {
  if (v === undefined || v === null) return UNAVAILABLE;
  return isMV(v) ? formatMV(v) : formatValue(v, unit);
}
