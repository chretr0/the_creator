import { pollutantKey, releaseMedium, type ReleaseMedium } from "./pollutants";
/** Illustrative passive-tracer transport, NOT a weather/air-quality forecast.
 * Horizontal Gaussian puffs, uniformly mixed through a user-assumed layer height.
 * Equation reference: https://www.ready.noaa.gov/documents/AMS2018/html/conc_eqns.html
 * This is our simplified model, not NOAA HYSPLIT. No chemistry, deposition, terrain or plume rise.
 */
export type TimelineProject = {
  id: string; name: string; type: string; latitude: number; longitude: number;
  displayCell?: string;
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
export type Dispersion = { windSpeed: number; windFrom: number; mixingHeight: number; diffusion: number };
// Prototype assumptions, explicitly shown and editable in the UI; never labelled measured weather.
export const DEFAULT_DISPERSION: Dispersion = { windSpeed: 3, windFrom: 270, mixingHeight: 500, diffusion: 200 };
export type TimelineMode = "baseline" | "added" | "combined";
export type ImpactCell = TimelineCell & { baseline: number | null; added: number | null; value: number | null; relevant?: boolean };
export type TimelineOverlay = { cells: ImpactCell[]; pollutant: string; mode: TimelineMode; days: number; partial: boolean; max: number; medium: ReleaseMedium; unit: string };

export { pollutantKey, pollutantLabel } from "./pollutants";
export function isAtmosphericPollutant(key: string): boolean {
  return key !== "co2e" && !/scope2|scope12|scope1and2|scope1plus2/.test(key);
}
export function dailyEmission(project: TimelineProject, pollutant: string, medium: ReleaseMedium = releaseMedium(pollutant)): number | null {
  const rows = project.emissions.filter((e) => pollutantKey(e.pollutant) === pollutant && releaseMedium(e.pollutant, e.medium) === medium);
  if (!rows.length || rows.some((e) => e.kgPerDay === null || !Number.isFinite(e.kgPerDay) || e.kgPerDay! < 0)) return null;
  const total = rows.reduce((sum, e) => sum + e.kgPerDay!, 0);
  return Number.isFinite(total) ? total : null;
}
export const impactUnit = (medium: ReleaseMedium) => ({ air: "µg/m³", soil: "mg/kg", freshwater: "mg/L", marine: "mg/L", climate: "kgCO₂e" })[medium];
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

/** Continuous emission integrated using 160 log-spaced age bins. kg -> µg, seconds, metres.
 * All projects begin together at day 0; hourly rates are averaged by declared operating hours/day.
 * Older puffs leave the local display domain naturally; cumulative emissions are a separate total.
 */
type Puff = { x: number; y: number; variance: number; factor: number };
function puffs(days: number, p: Dispersion): Puff[] {
  const seconds = days * 86400;
  const direction = (p.windFrom + 180) * Math.PI / 180;
  const vx = Math.sin(direction) * p.windSpeed, vy = Math.cos(direction) * p.windSpeed;
  const scale = Math.log1p(seconds);
  let previous = 0;
  const result: Puff[] = [];
  for (let i = 1; i <= 160; i++) {
    const end = Math.expm1(scale * i / 160), age = (previous + end) / 2;
    const variance = 750 ** 2 + 2 * p.diffusion * age;
    result.push({ x: vx * age, y: vy * age, variance,
      factor: (end - previous) * 1e9 / 86400 / (2 * Math.PI * variance * p.mixingHeight) });
    previous = end;
  }
  return result;
}
function fromPuffs(east: number, north: number, ageBins: Puff[]): number {
  let total = 0;
  for (const puff of ageBins) {
    const exponent = ((east - puff.x) ** 2 + (north - puff.y) ** 2) / (2 * puff.variance);
    if (exponent < 40) total += puff.factor * Math.exp(-exponent);
  }
  return total;
}
export function concentrationAt(east: number, north: number, kgPerDay: number, days: number, p: Dispersion): number {
  if (days <= 0 || kgPerDay === 0) return 0;
  if (!validDispersion(p) || !Number.isFinite(kgPerDay) || kgPerDay < 0 || days > 3650 || !Number.isFinite(days)) return NaN;
  return fromPuffs(east, north, puffs(days, p)) * kgPerDay;
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
export function impactCells(data: TimelineData, pollutant: string, days: number, p: Dispersion, mode: TimelineMode,
  medium: ReleaseMedium = releaseMedium(pollutant), env: Environment = DEFAULT_ENVIRONMENT): ImpactCell[] {
  const valid = Number.isFinite(days) && days >= 0 && days <= 3650 && validDispersion(p) && validEnvironment(env);
  const emitters = data.projects.map((project) => ({ project, rate: dailyEmission(project, pollutant, medium),
    river: new Map(project.river?.cells.map((c) => [c.h3Id, c])) })).filter((e) => e.rate !== null);
  const params = medium === "marine" ? { windSpeed: env.currentSpeed, windFrom: env.currentFrom, mixingHeight: env.seaDepth, diffusion: env.seaDiffusion } : p;
  const ageBins = valid && days > 0 && (medium === "air" || medium === "marine") ? puffs(days, params) : [];
  return data.cells.map((cell) => {
    let added: number | null = null;
    for (const { project, rate, river } of emitters) {
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
    const baseline = baselineFor(cell, pollutant, medium);
    const value = mode === "baseline" ? baseline : mode === "added" ? added : baseline !== null && added !== null ? baseline + added : null;
    const relevant = medium === "air" || medium === "soil" && cell.surface === "land" || medium === "marine" && cell.surface === "marine"
      || medium === "climate" && data.projects.some((p) => p.displayCell === cell.h3Id)
      || medium === "freshwater" && emitters.some((e) => e.river.has(cell.h3Id));
    return { ...cell, baseline, added, value, relevant };
  });
}
export function timeLabel(days: number): string {
  if (days === 0) return "Before building";
  if (days < 1) { const hours = Number((days * 24).toFixed(1)); return `${hours} ${hours === 1 ? "hour" : "hours"} later`; }
  const rounded = Number(days.toFixed(1));
  return `${rounded} ${rounded === 1 ? "day" : "days"} later`;
}
export function impactColour(value: number | null, max: number): [number, number, number, number] {
  if (value === null) return [130, 145, 160, 55];
  const t = Math.min(1, Math.max(0, value / Math.max(max, 1e-9)));
  return [Math.round(70 + 175 * t), Math.round(145 - 65 * t), Math.round(235 - 175 * t), Math.round(205 * Math.sqrt(t))];
}
