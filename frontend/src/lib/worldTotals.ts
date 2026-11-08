/**
 * Helpers for the World totals page: everything a world's buildings use, make, cost and release,
 * added up by the server (POST /api/scenarios/{id}/evaluate). Unknown is never shown as 0.
 */
import type { Project } from "./api";
import type { Quantity } from "./buildings";

export type TotalsPeriod = "day" | "month" | "year";

/** The period the totals are worked out over (sent as a preview override; nothing is saved). */
export const TOTALS_PERIODS: { value: TotalsPeriod; label: string; days: number; per: string }[] = [
  { value: "day", label: "Per day", days: 1, per: "a day" },
  { value: "month", label: "Per month", days: 30.4375, per: "a month" },
  { value: "year", label: "Per year", days: 365.25, per: "a year" },
];

/** Larger units for big totals, largest first. */
const SCALES: Record<string, [number, string][]> = {
  kWh: [[1e9, "TWh"], [1e6, "GWh"], [1e3, "MWh"], [1, "kWh"]],
  kW: [[1e6, "GW"], [1e3, "MW"], [1, "kW"]],
  kg: [[1e3, "t"], [1, "kg"]],
  "m²": [[1e6, "km²"], [1e4, "ha"], [1, "m²"]],
};

const NO_CURRENCY = "unspecified currency";

/** 3 significant figures, with the largest values in words ("1.2 billion"). */
function readable(v: number): string {
  const a = Math.abs(v);
  const sig = (x: number) => x.toLocaleString("en", { maximumSignificantDigits: 3 });
  if (a >= 1e12) return `${sig(v / 1e12)} trillion`;
  if (a >= 1e9) return `${sig(v / 1e9)} billion`;
  if (a >= 1e6) return `${sig(v / 1e6)} million`;
  return sig(v);
}

/** A total in a readable unit: "1.2 GWh", "350 t", "4.5 ha", "1.2 billion USD", or "unknown". */
export function fmtTotal(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  const scale = SCALES[unit];
  if (scale) {
    const [factor, name] = scale.find(([f]) => Math.abs(value) >= f) ?? scale[scale.length - 1];
    return `${readable(value / factor)} ${name}`;
  }
  if (unit === NO_CURRENCY) return `${readable(value)} (no currency given)`;
  return `${readable(value)} ${unit}`.trim();
}

/** A signed total for balances: "+1.2 GWh" / "−300 MWh". */
export function fmtSigned(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${fmtTotal(Math.abs(value), unit)}`;
}

/** Average power over the whole period (energy ÷ hours in the period), in kW. */
export function averageKw(kwh: number | null, periodDays: number): number | null {
  return kwh === null || !(periodDays > 0) ? null : kwh / (periodDays * 24);
}

/** A value, 0 when it does not apply (nothing missing), null when it is unknown. */
const amount = (q: Quantity) => q.value ?? (q.missing.length ? null : 0);

/** What a building (or the world) generates minus what it uses; null when either side is unknown. */
export function balance(output: Quantity, demand: Quantity): number | null {
  const o = amount(output);
  const d = amount(demand);
  return o === null || d === null ? null : o - d;
}

export type TotalState = "complete" | "partial" | "unknown" | "none";

/** Whether a total is complete, only partly known, unknown, or has nothing to add up. */
export function totalState(q: Quantity): TotalState {
  if (q.value === null) return q.missing.length ? "unknown" : "none";
  return q.missing.length ? "partial" : "complete";
}

/** Distinct names, in first-seen order. */
export const uniqueNames = (...lists: (string[] | undefined)[]) => [...new Set(lists.flatMap((l) => l ?? []))];

/** Placed buildings counted by type, most common first (ties keep first-placed order). */
export function countByType(projects: Pick<Project, "type">[]): { type: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const p of projects) counts.set(p.type, (counts.get(p.type) ?? 0) + 1);
  return [...counts].map(([type, count]) => ({ type, count })).sort((a, b) => b.count - a.count);
}
