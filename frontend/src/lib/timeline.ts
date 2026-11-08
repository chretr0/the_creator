import { MEDIA, pollutantKey, releaseMedium, type ReleaseMedium } from "./pollutants";
/** Illustrative passive-tracer transport, NOT a weather/air-quality forecast.
 * Horizontal Gaussian puffs, uniformly mixed through a user-assumed layer height.
 * Equation reference: https://www.ready.noaa.gov/documents/AMS2018/html/conc_eqns.html
 * This is our simplified model, not NOAA HYSPLIT. No chemistry, deposition, terrain or plume rise.
 */
const HOUR = 1 / 24;
// Whole days: months and years are rounded from the backend's 365.25-day year.
const yearsToDays = (years: number) => Math.round(years * 365.25);
/** Timeline steps: day 0 (operation begins), then round calendar intervals that roughly double,
 * so every step advances further than the one before: hours apart at first, years apart at the end. */
export const TIMELINE_STEPS: readonly { days: number; label: string; short: string }[] = [
  { days: 0, label: "Day 0 · operation begins", short: "Start" },
  { days: HOUR, label: "1 hour", short: "1 h" },
  { days: 2 * HOUR, label: "2 hours", short: "2 h" },
  { days: 4 * HOUR, label: "4 hours", short: "4 h" },
  { days: 8 * HOUR, label: "8 hours", short: "8 h" },
  { days: 1, label: "1 day", short: "1 d" },
  { days: 2, label: "2 days", short: "2 d" },
  { days: 4, label: "4 days", short: "4 d" },
  { days: 7, label: "1 week · 7 days", short: "1 wk" },
  { days: 14, label: "2 weeks · 14 days", short: "2 wk" },
  { days: yearsToDays(1 / 12), label: "1 month · 30 days", short: "1 mo" },
  { days: yearsToDays(3 / 12), label: "3 months · 91 days", short: "3 mo" },
  { days: yearsToDays(6 / 12), label: "6 months · 183 days", short: "6 mo" },
  { days: yearsToDays(1), label: "1 year · 365 days", short: "1 y" },
  { days: yearsToDays(2), label: "2 years · 731 days", short: "2 y" },
  { days: yearsToDays(5), label: "5 years · 1,826 days", short: "5 y" },
];
export const TIMELINE_DAYS: readonly number[] = TIMELINE_STEPS.map((s) => s.days);
export const TIMELINE_HORIZON_DAYS = yearsToDays(5);
export const FIRST_STEP = 0;
export const LAST_STEP = TIMELINE_DAYS.length - 1;
export const PLAYBACK_INTERVAL_MS = 500;

export type TimelineProject = {
  id: string; name: string; type: string; latitude: number; longitude: number;
  displayCell?: string;
  /** Long-term climate wind at the building (NASA POWER MERRA-2, 10 m, annual mean); null when unavailable. */
  wind?: LocalWind | null;
  river?: { cells: { h3Id: string; distanceM: number; flowM3PerSecond: number | null }[]; distanceKm: number | null; note: string };
  marineRelease?: { latitude: number | null; longitude: number | null; note: string };
  emissions: { pollutant: string; medium?: ReleaseMedium; kgPerDay: number | null; missing: string[] }[];
  electricityKwhPerDay: number | null; waterM3PerDay: number | null;
  electricityOutputKwhPerDay: number | null; waterOutputM3PerDay: number | null;
};
export type TimelineCell = { h3Id: string; latitude: number; longitude: number; pm25: number | null; pm10: number | null; surface?: "land" | "marine" | "water" | "unknown" };
export type TimelineData = {
  projects: TimelineProject[]; cells: TimelineCell[];
  baseline: { label: string; period: string; resolution: string; sourceId: string; units: string };
};
/** (u, v) is the vector-mean wind: the net long-term drift. meanSpeed is the average of hourly speeds. */
export type LocalWind = { u: number; v: number; speed: number; fromDegrees: number | null; meanSpeed: number;
  gridLatitude: number; gridLongitude: number; source: string };
/** "local": each building's releases drift with the climate wind at its own location; "custom": one assumed wind. */
export type WindSource = "local" | "custom";
export type Dispersion = { windSpeed: number; windFrom: number; mixingHeight: number; diffusion: number };
// Prototype assumptions, explicitly shown and editable in the UI; never labelled measured weather.
export const DEFAULT_DISPERSION: Dispersion = { windSpeed: 3, windFrom: 270, mixingHeight: 500, diffusion: 200 };
export type TimelineMode = "baseline" | "added" | "combined";
export type TimelineMeasure = "concentration" | "exposure";
export const DEFAULT_AIR_MEASURE: TimelineMeasure = "exposure";
export type ImpactCell = TimelineCell & { baseline: number | null; added: number | null; value: number | null; relevant?: boolean };
/** "horizon" fixes colours to the five-year peak so playback is comparable; "step" fits the
 * colours to the frame shown, so early, still-small values remain visible. */
export type TimelineScale = "horizon" | "step";
export const defaultScale = (medium: ReleaseMedium, measure: TimelineMeasure): TimelineScale =>
  medium === "air" && measure === "exposure" ? "step" : "horizon";
export type TimelineOverlay = { cells: ImpactCell[]; pollutant: string; mode: TimelineMode; measure: TimelineMeasure; scale: TimelineScale; days: number; partial: boolean; max: number; medium: ReleaseMedium; unit: string };

export { pollutantKey, pollutantLabel } from "./pollutants";
export function isAtmosphericPollutant(key: string): boolean {
  return key !== "co2e" && !/scope2|scope12|scope1and2|scope1plus2/.test(key);
}
/** Pollutants the placed buildings actually release, per receiving environment, in catalogue
 * media order. Declared rows with an unknown rate are kept (their inputs are reported as missing);
 * rows declared at exactly zero are not, because nothing is released. */
export function releasedPollutants(projects: TimelineProject[]): Partial<Record<ReleaseMedium, string[]>> {
  const found = new Map<ReleaseMedium, Set<string>>();
  for (const project of projects) for (const e of project.emissions) {
    if (e.kgPerDay === 0) continue;
    const medium = releaseMedium(e.pollutant, e.medium);
    if (!found.has(medium)) found.set(medium, new Set());
    found.get(medium)!.add(pollutantKey(e.pollutant));
  }
  return Object.fromEntries((Object.keys(MEDIA) as ReleaseMedium[]).filter((m) => found.has(m)).map((m) => [m, [...found.get(m)!]]));
}
export function dailyEmission(project: TimelineProject, pollutant: string, medium: ReleaseMedium = releaseMedium(pollutant)): number | null {
  const rows = project.emissions.filter((e) => pollutantKey(e.pollutant) === pollutant && releaseMedium(e.pollutant, e.medium) === medium);
  if (!rows.length || rows.some((e) => e.kgPerDay === null || !Number.isFinite(e.kgPerDay) || e.kgPerDay! < 0)) return null;
  const total = rows.reduce((sum, e) => sum + e.kgPerDay!, 0);
  return Number.isFinite(total) ? total : null;
}
export const impactUnit = (medium: ReleaseMedium, measure: TimelineMeasure = "concentration") =>
  medium === "air" && measure === "exposure" ? "µg·day/m³" : ({ air: "µg/m³", soil: "mg/kg", freshwater: "mg/L", marine: "mg/L", climate: "kgCO₂e" })[medium];
export function timelineViewLabel(medium: ReleaseMedium, mode: TimelineMode, measure: TimelineMeasure): string {
  if (medium === "air" && measure === "exposure") return {
    baseline: "Historical reference exposure", added: "Accumulated exposure", combined: "Reference + added exposure",
  }[mode];
  return mode === "baseline" ? "Historical baseline" : mode === "combined" ? "Baseline + added impact"
    : medium === "climate" ? "Source contributions" : "Added concentration";
}
export const DEFAULT_ENVIRONMENT = { soilDepth: .2, soilDensity: 1300, soilSpread: 1000, riverSpeed: .3,
  currentSpeed: .1, currentFrom: 270, seaDepth: 10, seaDiffusion: 20 };
export type Environment = typeof DEFAULT_ENVIRONMENT;
export const ENVIRONMENT_FIELDS: Record<Exclude<ReleaseMedium, "air" | "climate">, [keyof Environment, string, string, number, number][]> = {
  soil: [["soilDepth", "Mixing depth", "m", .01, 5], ["soilDensity", "Soil bulk density", "kg/m³", 500, 2500], ["soilSpread", "Spread radius (σ)", "m", 100, 5000]],
  freshwater: [["riverSpeed", "Downstream speed", "m/s", .01, 5]],
  marine: [["currentSpeed", "Current speed", "m/s", 0, 3], ["currentFrom", "Current from", "° clockwise from north", 0, 360], ["seaDepth", "Mixing depth", "m", 1, 200], ["seaDiffusion", "Horizontal diffusion", "m²/s", 1, 1000]],
};
export function validEnvironment(p: Environment): boolean {
  return Object.values(ENVIRONMENT_FIELDS).flat().every(([k, , , min, max]) => Number.isFinite(p[k]) && p[k] >= min && p[k] <= max);
}
export function knownTotal(values: (number | null)[], days: number): { value: number | null; known: number; total: number } {
  const known = values.filter((x): x is number => x !== null && Number.isFinite(x));
  const value = known.reduce((a, b) => a + b, 0) * days;
  return { value: known.length && Number.isFinite(value) ? value : null, known: known.length, total: values.length };
}
export function baselineFor(cell: TimelineCell, pollutant: string, medium: ReleaseMedium = "air"): number | null {
  if (medium !== "air") return null;
  return pollutant === "pm25" ? cell.pm25 : pollutant === "pm10" ? cell.pm10 : null;
}
export function validDispersion(p: Dispersion): boolean {
  return Object.values(p).every(Number.isFinite) && p.windSpeed >= 0 && p.windSpeed <= 30
    && p.windFrom >= 0 && p.windFrom <= 360 && p.mixingHeight >= 50 && p.mixingHeight <= 3000
    && p.diffusion >= 10 && p.diffusion <= 2000;
}

const MAX_MODEL_DAYS = 3650;
const PUFF_INTERVALS = 2048;
// Fixed age intervals keep existing contributions identical as the horizon advances.
// Re-spacing a smaller number of bins for each frame made narrow plumes flicker and
// could overestimate concentrations near the edge of the actual ~50 km display domain.
const PUFF_AGE_EDGES = Array.from({ length: PUFF_INTERVALS }, (_, i) =>
  Math.expm1(Math.log1p(MAX_MODEL_DAYS * 86400) * (i + 1) / PUFF_INTERVALS));

/** Continuous emission integrated on a fixed log-spaced age grid. kg -> µg, seconds, metres.
 * All projects begin together at day 0; hourly rates are averaged by declared operating hours/day.
 * Older puffs leave the local display domain naturally; cumulative emissions are a separate total.
 */
// innerRadius/outerRadius bound each puff's exp(-40) footprint, √(80 × variance), around its
// centre at windSpeed × age, so each receptor only scans the puffs that can actually reach it.
type Puff = { x: number; y: number; inverseTwoVariance: number; factor: number; innerRadius: number; outerRadius: number };
function puffs(days: number, p: Dispersion, measure: TimelineMeasure = "concentration"): Puff[] {
  const seconds = days * 86400;
  const direction = (p.windFrom + 180) * Math.PI / 180;
  const vx = Math.sin(direction) * p.windSpeed, vy = Math.cos(direction) * p.windSpeed;
  let previous = 0;
  const result: Puff[] = [];
  for (const edge of PUFF_AGE_EDGES) {
    const end = Math.min(seconds, edge), age = (previous + end) / 2;
    const variance = 750 ** 2 + 2 * p.diffusion * age;
    // For continuous releases, integrating concentration from 0 to T gives
    // ∫₀ᵀ (T - age) × transportKernel(age) d(age). Convert the extra time factor
    // to days for µg·day/m³. This includes arrival delay; C(T) × T would not.
    const duration = measure === "exposure" ? Math.max(0, days - age / 86400) : 1;
    const footprint = Math.sqrt(80 * variance);
    result.push({ x: vx * age, y: vy * age, inverseTwoVariance: 1 / (2 * variance),
      innerRadius: p.windSpeed * age - footprint, outerRadius: p.windSpeed * age + footprint,
      factor: duration * (end - previous) * 1e9 / 86400 / (2 * Math.PI * variance * p.mixingHeight) });
    if (end >= seconds) break;
    previous = end;
  }
  return result;
}
function fromPuffs(east: number, north: number, ageBins: Puff[]): number {
  const radius = Math.hypot(east, north);
  // A puff whose footprint has not yet reached this radius contributes exactly nothing: the
  // receptor is more than √(80 × variance) from its centre. outerRadius only grows with age,
  // so binary-search the first puff that can reach this receptor (most young puffs cannot).
  let low = 0, high = ageBins.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (ageBins[mid].outerRadius < radius) low = mid + 1; else high = mid;
  }
  let total = 0;
  for (let i = low; i < ageBins.length; i++) {
    const puff = ageBins[i];
    // innerRadius is convex in age and starts negative, so once a puff's entire footprint has
    // passed this radius, all older puffs have too. Same exp(-40) cutoff as the full scan.
    if (puff.innerRadius > radius) break;
    const dx = east - puff.x, dy = north - puff.y;
    const exponent = (dx * dx + dy * dy) * puff.inverseTwoVariance;
    if (exponent < 40) total += puff.factor * Math.exp(-exponent);
  }
  return total;
}
function airImpactAt(east: number, north: number, kgPerDay: number, days: number, p: Dispersion, measure: TimelineMeasure): number {
  if (!Number.isFinite(kgPerDay) || kgPerDay < 0 || days < 0 || days > MAX_MODEL_DAYS || !Number.isFinite(days)) return NaN;
  // Nothing has been released yet, so the answer is zero whatever the transport assumptions.
  if (days === 0 || kgPerDay === 0) return 0;
  if (!validDispersion(p)) return NaN;
  return fromPuffs(east, north, puffs(days, p, measure)) * kgPerDay;
}
export function concentrationAt(east: number, north: number, kgPerDay: number, days: number, p: Dispersion): number {
  return airImpactAt(east, north, kgPerDay, days, p, "concentration");
}
/** Time-integrated added air concentration, in µg·day/m³ (not inhaled dose). */
export function exposureAt(east: number, north: number, kgPerDay: number, days: number, p: Dispersion): number {
  return airImpactAt(east, north, kgPerDay, days, p, "exposure");
}

function offsets(cell: TimelineCell, source: { longitude: number; latitude: number }) {
  const dlon = ((cell.longitude - source.longitude + 540) % 360) - 180;
  return [dlon * Math.PI / 180 * 6371008.8 * Math.cos(source.latitude * Math.PI / 180),
    (cell.latitude - source.latitude) * Math.PI / 180 * 6371008.8];
}
/** Added soil mass is uniformly mixed through the assumed soil layer; no decay or leaching. */
export function soilConcentration(east: number, north: number, rate: number, days: number, p: Environment): number {
  return rate * days * 1e6 / (2 * Math.PI * p.soilSpread ** 2 * p.soilDepth * p.soilDensity)
    * Math.exp(-(east ** 2 + north ** 2) / (2 * p.soilSpread ** 2));
}
/** Direction a wind blows FROM, in degrees clockwise from north, given its eastward/northward components. */
export const directionFrom = (u: number, v: number) => (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360;
/** Transport assumptions for one building: its own climate wind when chosen and known; mixing and
 * diffusion always come from the shared assumptions. Unknown local wind falls back to the assumed wind. */
export function projectDispersion(project: TimelineProject, p: Dispersion, wind: WindSource): Dispersion {
  if (wind !== "local" || !project.wind || !Number.isFinite(project.wind.u) || !Number.isFinite(project.wind.v)) return p;
  const speed = Math.hypot(project.wind.u, project.wind.v);
  return { ...p, windSpeed: Math.min(30, speed), windFrom: speed > 0 ? directionFrom(project.wind.u, project.wind.v) : 0 };
}
export function impactCells(data: TimelineData, pollutant: string, days: number, p: Dispersion, mode: TimelineMode,
  medium: ReleaseMedium = releaseMedium(pollutant), env: Environment = DEFAULT_ENVIRONMENT,
  measure: TimelineMeasure = "concentration", wind: WindSource = "custom"): ImpactCell[] {
  const valid = Number.isFinite(days) && days >= 0 && days <= MAX_MODEL_DAYS && validDispersion(p) && validEnvironment(env);
  const exposure = medium === "air" && measure === "exposure";
  const transported = valid && days > 0 && (medium === "air" || medium === "marine");
  // Puffs depend on the wind, so buildings sharing a wind (or the sea current) share one set.
  const binsByWind = new Map<string, Puff[]>();
  const binsFor = (params: Dispersion) => {
    if (!transported) return [];
    const key = `${params.windSpeed}|${params.windFrom}`;
    if (!binsByWind.has(key)) binsByWind.set(key, puffs(days, params, exposure ? "exposure" : "concentration"));
    return binsByWind.get(key)!;
  };
  const current = { windSpeed: env.currentSpeed, windFrom: env.currentFrom, mixingHeight: env.seaDepth, diffusion: env.seaDiffusion };
  const emitters = data.projects.map((project) => ({ project, rate: dailyEmission(project, pollutant, medium),
    river: new Map(project.river?.cells.map((c) => [c.h3Id, c])) })).filter((e) => e.rate !== null)
    .map((e) => ({ ...e, ageBins: binsFor(medium === "marine" ? current : projectDispersion(e.project, p, wind)) }));
  return data.cells.map((cell) => {
    let added: number | null = null;
    for (const { project, rate, river, ageBins } of emitters) {
      if (!valid) continue;
      let contribution: number | null = null;
      const [east, north] = offsets(cell, project);
      if (medium === "climate") {
        if (cell.h3Id === project.displayCell) contribution = rate! * days;
      } else if (medium === "air" && isAtmosphericPollutant(pollutant)) {
        contribution = fromPuffs(east, north, ageBins) * rate!;
      } else if (medium === "soil" && cell.surface === "land") {
        contribution = soilConcentration(east, north, rate!, days, env);
      } else if (medium === "freshwater") {
        const reach = river.get(cell.h3Id);
        if (reach && (rate === 0 || days === 0 || days * 86400 < reach.distanceM / env.riverSpeed)) contribution = 0;
        else if (reach?.flowM3PerSecond && reach.flowM3PerSecond > 0) contribution = rate! / 86400 / reach.flowM3PerSecond * 1000;
      } else if (medium === "marine" && cell.surface === "marine" && project.marineRelease?.latitude != null && project.marineRelease.longitude != null) {
        const [x, y] = offsets(cell, { latitude: project.marineRelease.latitude, longitude: project.marineRelease.longitude });
        contribution = fromPuffs(x, y, ageBins) * rate! * 1e-6; // µg/m³ -> mg/L
      }
      if (contribution !== null && Number.isFinite(contribution)) added = (added ?? 0) + contribution;
    }
    if (added !== null && !Number.isFinite(added)) added = null;
    const background = baselineFor(cell, pollutant, medium);
    // A reference exposure holds the historical mean constant, without modifying the measured input.
    const baseline = background === null ? null : exposure ? valid ? background * days : null : background;
    const value = mode === "baseline" ? baseline : mode === "added" ? added : baseline !== null && added !== null ? baseline + added : null;
    const relevant = medium === "air" || medium === "soil" && cell.surface === "land" || medium === "marine" && cell.surface === "marine"
      || medium === "climate" && data.projects.some((p) => p.displayCell === cell.h3Id)
      || medium === "freshwater" && emitters.some((e) => e.river.has(cell.h3Id));
    return { ...cell, baseline, added, value, relevant };
  });
}
export function timeLabel(days: number): string {
  const step = TIMELINE_STEPS.find((s) => s.days === days);
  if (step) return step.label;
  if (days < 1) { const hours = Math.round(days * 24); return `${hours} ${hours === 1 ? "hour" : "hours"}`; }
  const whole = Math.round(days);
  return `${whole.toLocaleString()} ${whole === 1 ? "day" : "days"}`;
}
/** Compact label for the step buttons under the slider. */
export const stepLabel = (days: number) => TIMELINE_STEPS.find((s) => s.days === days)?.short ?? timeLabel(days);
export function impactColour(value: number | null, max: number): [number, number, number, number] {
  if (value === null) return [130, 145, 160, 55];
  const t = Math.min(1, Math.max(0, value / Math.max(max, 1e-9)));
  // Linear opacity: do not visually amplify very small Gaussian tails into a broad plume.
  return [Math.round(70 + 175 * t), Math.round(145 - 65 * t), Math.round(235 - 175 * t), Math.round(205 * t)];
}
