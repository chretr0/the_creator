import {
  GRADE_TIER,
  STATE_COLOUR,
  STATE_LABEL,
  TIER_COLOUR,
  TIER_LABEL,
  TIER_ORDER,
  type AreaAssessment,
  type AssessmentState,
  type CellState,
  type SuitabilityFactor,
  type SuitabilityProfile,
  type SuitabilityTier,
} from "./buildings";

type RGBA = [number, number, number, number];

/** What the screening overlay colours: the overall grade, or one factor of the profile (by key). */
export type ColourBy = "overall" | string;

/** The area screening result the map draws (the Build panel's latest one for the visible map). */
export type ScreenedArea = {
  cells: CellState[];
  counts: AreaAssessment["counts"];
  profile: SuitabilityProfile | null;
  /**
   * The result belongs to an earlier version of the building (another type, other specs) and can't be
   * refreshed right now (zoomed out too far, invalid fields, request failed): drawn greyed out.
   */
  stale?: boolean;
};

export function screenedArea(area: AreaAssessment, stale = false): ScreenedArea {
  return { cells: area.cells, counts: area.counts, profile: area.suitability ?? null, stale };
}

/** Out-of-date screening: every cell neutral, so an old building's grades aren't read as the new one's. */
export const STALE_FILL: RGBA = [150, 150, 160, 36];

const FILL = 150;
const FILL_UNSURE = 95; // some hard site checks can't be judged: the grade is shown paler
const NO_DATA: RGBA = [150, 150, 160, 42];

/** Index of a factor in the profile (its position in `CellState.grades`), or -1. */
export function factorIndex(profile: SuitabilityProfile | null, key: string): number {
  return profile ? profile.factors.findIndex((f) => f.key === key) : -1;
}

/** A colour-by choice that no longer exists in the profile falls back to the overall grade. */
export function effectiveColourBy(profile: SuitabilityProfile | null, colourBy: ColourBy): ColourBy {
  return colourBy !== "overall" && factorIndex(profile, colourBy) >= 0 ? colourBy : "overall";
}

export function gradeAt(cell: CellState, index: number): SuitabilityTier | null {
  const ch = cell.grades?.[index];
  return ch === undefined ? null : (GRADE_TIER[ch] ?? null);
}

/** Fill colour of one screened cell. */
export function cellColour(cell: CellState, profile: SuitabilityProfile | null, colourBy: ColourBy): RGBA {
  if (!profile) return [...STATE_COLOUR[cell.state], 110];
  const by = effectiveColourBy(profile, colourBy);
  if (by !== "overall") {
    const tier = gradeAt(cell, factorIndex(profile, by));
    return tier ? [...TIER_COLOUR[tier], FILL] : NO_DATA;
  }
  if (cell.state === "fails_criteria") return [...STATE_COLOUR.fails_criteria, 115];
  if (!cell.tier) return [...STATE_COLOUR.insufficient_data, 90];
  return [...TIER_COLOUR[cell.tier], cell.state === "meets_criteria" ? FILL : FILL_UNSURE];
}

export function cellLineColour(cell: CellState, profile: SuitabilityProfile | null, colourBy: ColourBy): RGBA {
  const [r, g, b, a] = cellColour(cell, profile, colourBy);
  return [r, g, b, Math.min(230, a + 90)];
}

const POINTS: Record<SuitabilityTier, number> = { ideal: 3, good: 2, marginal: 1, unsuitable: 0 };

/** The factors holding this cell back, worst first (then heaviest weight), from its grades string. */
export function weakestFactors(cell: CellState, profile: SuitabilityProfile, max = 3): { factor: SuitabilityFactor; tier: SuitabilityTier }[] {
  const graded = profile.factors
    .map((factor, i) => ({ factor, tier: gradeAt(cell, i) }))
    .filter((x): x is { factor: SuitabilityFactor; tier: SuitabilityTier } => !!x.tier && x.tier !== "ideal");
  graded.sort((a, b) => POINTS[a.tier] - POINTS[b.tier] || b.factor.weight - a.factor.weight);
  return graded.slice(0, max);
}

export function cellTooltip(cell: CellState, profile: SuitabilityProfile | null, colourBy: ColourBy): string {
  const state = STATE_LABEL[cell.state];
  if (!profile) return `${state}\nScreening result for this cell`;
  const by = effectiveColourBy(profile, colourBy);
  if (by !== "overall") {
    const i = factorIndex(profile, by);
    const f = profile.factors[i];
    const tier = gradeAt(cell, i);
    return `${f.label}: ${tier ? TIER_LABEL[tier] : "no data"}\n${f.bands}\nClick to see the value here`;
  }
  const lines = [cell.tier ? `${TIER_LABEL[cell.tier]} site for ${profile.label.toLowerCase()}` : "Not enough data to grade this site"];
  const weak = weakestFactors(cell, profile, 6);
  const named = (xs: typeof weak) => xs.slice(0, 3).map((w) => `${w.factor.label.toLowerCase()} (${TIER_LABEL[w.tier].toLowerCase()})`).join(", ");
  // Same notion as the server's limiting factors: graded marginal or unsuitable.
  const limiting = weak.filter((w) => w.tier === "marginal" || w.tier === "unsuitable");
  if (limiting.length) lines.push(`Limited by ${named(limiting)}`);
  else if (cell.tier && cell.tier !== "ideal" && weak.length) lines.push(`Not ideal: ${named(weak)}`);
  else if (cell.tier === "good") {
    // The server's no-data cap: a hard limit without data here means the site can't be confirmed ideal.
    const unknown = profile.factors.filter((f, i) => f.constraint && cell.grades?.[i] === "0").map((f) => f.label.toLowerCase());
    if (unknown.length) lines.push(`Can't be confirmed ideal: no data on ${unknown.slice(0, 3).join(", ")} here`);
  }
  lines.push(cell.state === "fails_criteria" ? `${state}: the site can't supply what the specs need` : state);
  return lines.join("\n");
}

type Counts = Partial<Record<SuitabilityTier | "unknown" | "fails", number>>;

/**
 * Cell counts per legend row, counted exactly as the map colours them: by one factor's grade, or (overall)
 * "fails" for cells that can't be built, otherwise the overall grade.
 */
export function colourCounts(cells: CellState[], profile: SuitabilityProfile, colourBy: ColourBy): Counts {
  const by = effectiveColourBy(profile, colourBy);
  const i = by === "overall" ? -1 : factorIndex(profile, by);
  const out: Counts = {};
  for (const c of cells) {
    const k = i >= 0 ? (gradeAt(c, i) ?? "unknown") : c.state === "fails_criteria" ? "fails" : (c.tier ?? "unknown");
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

export type LegendRow = { key: string; label: string; colour: [number, number, number]; count: number; faded?: boolean };

/** Legend rows for the current colouring, best first. */
export function legendRows(area: ScreenedArea, colourBy: ColourBy): LegendRow[] {
  const profile = area.profile;
  if (!profile) {
    const order: AssessmentState[] = ["meets_criteria", "insufficient_data", "fails_criteria"];
    return order.map((s) => ({ key: s, label: STATE_LABEL[s], colour: STATE_COLOUR[s], count: area.counts[s] ?? 0 }));
  }
  const overall = effectiveColourBy(profile, colourBy) === "overall";
  const counts = colourCounts(area.cells, profile, colourBy);
  const rows: LegendRow[] = TIER_ORDER.map((t) => ({ key: t, label: TIER_LABEL[t], colour: TIER_COLOUR[t], count: counts[t] ?? 0 }));
  if (overall) rows.push({ key: "fails", label: "Not buildable", colour: STATE_COLOUR.fails_criteria, count: counts.fails ?? 0 });
  rows.push({ key: "unknown", label: overall ? "Can't grade" : "No data", colour: STATE_COLOUR.insufficient_data, count: counts.unknown ?? 0, faded: true });
  return rows;
}

/** Factors grouped for the colour-by picker, in profile order within each group. */
export function factorGroups(profile: SuitabilityProfile): { group: string; factors: SuitabilityFactor[] }[] {
  const groups: { group: string; factors: SuitabilityFactor[] }[] = [];
  for (const f of profile.factors) {
    const g = groups.find((x) => x.group === f.group);
    if (g) g.factors.push(f);
    else groups.push({ group: f.group, factors: [f] });
  }
  return groups;
}
