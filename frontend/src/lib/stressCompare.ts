// Helpers for the per-building unstressed vs stressed comparison (Projects tab → Scenario controls).
import type { BuildingEvaluation, CheckResult, CriterionKind, Quantity } from "./buildings";

/** Checks that compare a building's demand with a declared supply, in display order. */
export const SUPPLY_CHECKS: { kind: CriterionKind; label: string }[] = [
  { kind: "water_budget", label: "Water allocation" },
  { kind: "energy_budget", label: "Energy budget" },
  { kind: "power_capacity", label: "Power capacity" },
];

export type SupplyPair = { id: string; label: string; unit: string; period: string | null; a?: CheckResult; b?: CheckResult };

/** Supply checks of one building, paired between the unstressed (a) and stressed (b) results. */
export function supplyPairs(a?: BuildingEvaluation, b?: BuildingEvaluation): SupplyPair[] {
  const out: SupplyPair[] = [];
  for (const { kind, label } of SUPPLY_CHECKS) {
    const ca = (a?.assessment.checks ?? []).filter((c) => c.kind === kind);
    const cb = (b?.assessment.checks ?? []).filter((c) => c.kind === kind);
    const ids = [...new Set([...ca, ...cb].map((c) => c.criterionId))];
    for (const id of ids) {
      const x = ca.find((c) => c.criterionId === id);
      const y = cb.find((c) => c.criterionId === id);
      const any = (x ?? y)!;
      out.push({ id, label: ids.length > 1 ? any.label : label, unit: any.unit, period: any.period, a: x, b: y });
    }
  }
  return out;
}

/**
 * Unmet demand = max(0, demand − supply), or null (unknown) when either side is unknown.
 * When part of the supply is unknown, only a zero shortfall is certain.
 */
export function shortfall(c?: CheckResult): number | null {
  if (!c || c.actual == null || c.requiredValue == null) return null;
  const gap = Math.max(0, c.actual - c.requiredValue);
  return c.status === "unknown" && gap > 0 ? null : gap;
}

/** A check value as a Quantity, so it renders like every other figure ("unknown", never 0, when null). */
export function checkQuantity(value: number | null | undefined, unit: string): Quantity {
  return { value: value ?? null, unit, basis: "", missing: [] };
}

/** An output row only matters for producers: non-producers report null with nothing missing. */
export function outputRelevant(...qs: (Quantity | undefined)[]): boolean {
  return qs.some((q) => !!q && (q.value !== null || q.missing.length > 0));
}
