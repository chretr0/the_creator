/**
 * Building on the Moon: a hypothetical lunar base, to show what the app can do once the right data exists.
 *
 * The building catalogue (types, parameters, defaults and their source tags) is shared with the backend
 * in shared/moon_buildings.json. This module turns a location into site facts, checks a building type
 * against them, and adds up a base: power by day and through the night, oxygen, water, food, landed
 * mass and delivery cost. Unknown values stay unknown (null), never zero.
 */
import catalogue from "../../../shared/moon_buildings.json";
import type { IconName } from "../components/Icon";
import { distanceKm } from "../lib/bodyGeometry";
import { MOON_RADIUS_KM } from "../bodies/moon";

export type MoonTag = "K" | "C" | "M" | "E" | "D" | "ASSUMP";
export type MoonRole = "habitat" | "solar" | "fission" | "storage" | "ice_mine" | "oxygen_plant" | "greenhouse" | "landing_pad";
export type MoonBuildingType =
  | "moon_habitat"
  | "moon_solar_tower"
  | "moon_fission"
  | "moon_storage"
  | "moon_ice_mine"
  | "moon_oxygen_plant"
  | "moon_greenhouse"
  | "moon_landing_pad";

export type MoonParam = {
  key: string;
  label: string;
  unit: string;
  default: number | null;
  min: number;
  max: number;
  integer?: boolean;
  tag: MoonTag;
  note: string;
};

export type MoonBuildingDef = {
  type: MoonBuildingType;
  label: string;
  role: MoonRole;
  icon: IconName;
  colour: [number, number, number];
  example: string;
  description: string;
  params: MoonParam[];
};

export type TransportCase = { id: string; label: string; usdPerKg: number; tag: MoonTag; note: string };

export const MOON_BUILDINGS = catalogue.buildings as MoonBuildingDef[];
export const MOON_BUILDING_BY_TYPE = Object.fromEntries(MOON_BUILDINGS.map((b) => [b.type, b])) as Record<MoonBuildingType, MoonBuildingDef>;
export const TAG_LABELS = catalogue.tags as Record<MoonTag, string>;
export const LIFE_SUPPORT = catalogue.lifeSupport;
export const TRANSPORT_CASES = catalogue.transportCases as TransportCase[];
export const DEFAULT_TRANSPORT_CASE = catalogue.defaultTransportCase;

export const isMoonBuildingType = (type: string): type is MoonBuildingType => type in MOON_BUILDING_BY_TYPE;

/* ---------------- Values ---------------- */

/** A building's parameter values by key; null = unknown. */
export type MoonValues = Record<string, number | null>;

export const defaultValues = (type: MoonBuildingType): MoonValues =>
  Object.fromEntries(MOON_BUILDING_BY_TYPE[type].params.map((p) => [p.key, p.default]));

/** Stored parameters back to values: anything that is not a finite number is unknown. */
export function valuesFromParameters(type: MoonBuildingType, parameters: Record<string, unknown>): MoonValues {
  return Object.fromEntries(
    MOON_BUILDING_BY_TYPE[type].params.map((p) => {
      const v = parameters[p.key];
      return [p.key, typeof v === "number" && Number.isFinite(v) ? v : null];
    }),
  );
}

/** Values to send: unknown values are left out rather than sent as zero. */
export const toParameters = (values: MoonValues): Record<string, number> =>
  Object.fromEntries(Object.entries(values).filter((e): e is [string, number] => e[1] !== null && Number.isFinite(e[1])));

/** A problem with a typed value, or null when it is acceptable (blank = unknown). */
export function paramProblem(param: MoonParam, raw: string): string | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return "Enter a number";
  if (n < param.min || n > param.max) return `Between ${param.min.toLocaleString()} and ${param.max.toLocaleString()}`;
  if (param.integer && !Number.isInteger(n)) return "Whole number";
  return null;
}

const value = (values: MoonValues, key: string): number | null => {
  const v = values[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};

/* ---------------- Site facts ---------------- */

/** Half a synodic month (29.53 days): how long the night lasts away from the poles. */
export const LUNAR_NIGHT_HOURS = (29.530589 * 24) / 2;
/** Best polar ridges stay dark 3–5 days (Gläser 2014): the default night for a polar base. */
export const POLAR_RIDGE_NIGHT_HOURS = 120;
/** Beyond this latitude sunlight and night length depend on local terrain, not latitude. */
export const POLAR_LATITUDE = 80;
/** Buildings this far apart are assumed to share one power and life-support network. */
export const NETWORK_REACH_KM = 5;

export type EarthVisibility = "always" | "sometimes" | "never";

/** What the app knows about a location, gathered from the prepared Moon data. */
export type SiteContext = {
  latitude: number;
  longitude: number;
  /** LOLA mean height (m) relative to the 1,737.4 km sphere; null when unknown. */
  elevationM: number | null;
  /** Mare name, null in the highlands, undefined when the mare data has not loaded. */
  mare: string | null | undefined;
  /** Heritage keep-out rings containing the point; null while they load. */
  heritage: { siteName: string; rule: string; radiusM: number; distanceKm: number }[] | null;
};

export type SiteFacts = {
  latitude: number;
  longitude: number;
  polar: boolean;
  /** Fraction of the time the Sun is up; null when it depends on terrain we have no data for. */
  sunlitFraction: number | null;
  sunlitBasis: string;
  longestNightHours: number | null;
  nightBasis: string;
  /** Angle from the sub-Earth point (0°, 0°). */
  earthAngleDeg: number;
  earthVisibility: EarthVisibility;
  icePotential: "likely" | "possible" | "unlikely";
  terrain: "mare" | "highlands" | null;
  mareName: string | null;
  elevationM: number | null;
};

export function siteFacts(ctx: SiteContext): SiteFacts {
  const polar = Math.abs(ctx.latitude) >= POLAR_LATITUDE;
  const rad = Math.PI / 180;
  const cosAngle = Math.cos(ctx.latitude * rad) * Math.cos(ctx.longitude * rad);
  const earthAngleDeg = Math.acos(Math.max(-1, Math.min(1, cosAngle))) / rad;
  // The Moon's libration (about ±8°) brings the band near the limb in and out of Earth's view.
  const earthVisibility: EarthVisibility = earthAngleDeg <= 82 ? "always" : earthAngleDeg <= 98 ? "sometimes" : "never";
  const absLat = Math.abs(ctx.latitude);
  return {
    latitude: ctx.latitude,
    longitude: ctx.longitude,
    polar,
    sunlitFraction: polar ? null : 0.5,
    sunlitBasis: polar
      ? "Near the poles sunlight depends on terrain: ridges are lit 70–90% of the time, crater floors never. Illumination maps are not prepared yet."
      : "Flat ground: the Sun is up for half of each 29.5-day lunar day.",
    longestNightHours: polar ? null : LUNAR_NIGHT_HOURS,
    nightBasis: polar
      ? "Depends on terrain: 3–5 days on the best ridges, months on crater floors."
      : "Half of the 29.5-day lunar day: about 14.8 Earth days of darkness.",
    earthAngleDeg,
    earthVisibility,
    icePotential: absLat >= 85 ? "likely" : polar ? "possible" : "unlikely",
    terrain: ctx.mare === undefined ? null : ctx.mare ? "mare" : "highlands",
    mareName: ctx.mare ?? null,
    elevationM: ctx.elevationM,
  };
}

/* ---------------- Site check ---------------- */

export type CheckStatus = "pass" | "warn" | "fail" | "unknown" | "info";
export type SiteCheckItem = { id: string; label: string; status: CheckStatus; detail: string };
export type Verdict = "suitable" | "warnings" | "unsuitable";

/** A building already in the base. */
export type PlacedMoonBuilding = {
  id: string;
  type: MoonBuildingType;
  name: string;
  latitude: number;
  longitude: number;
  values: MoonValues;
};

const CREWED: MoonRole[] = ["habitat", "greenhouse"];
const nameOf = (b: PlacedMoonBuilding) => b.name || MOON_BUILDING_BY_TYPE[b.type].label;
const km = (d: number) => `${d < 10 ? d.toFixed(2) : d.toFixed(1)} km`;
const pct = (f: number) => `${Math.round(f * 100)}%`;

export function siteCheck(
  type: MoonBuildingType,
  values: MoonValues,
  facts: SiteFacts,
  heritage: SiteContext["heritage"],
  others: PlacedMoonBuilding[],
): { items: SiteCheckItem[]; verdict: Verdict } {
  const role = MOON_BUILDING_BY_TYPE[type].role;
  const items: SiteCheckItem[] = [];
  const near = others
    .map((b) => ({ b, d: distanceKm(facts.latitude, facts.longitude, b.latitude, b.longitude, MOON_RADIUS_KM) }))
    .sort((a, b) => a.d - b.d);

  // Heritage: the 2011 NASA recommendations keep visitors away from historic landing sites.
  if (heritage === null) items.push({ id: "heritage", label: "Heritage keep-out", status: "unknown", detail: "Keep-out rings are still loading." });
  else if (heritage.length)
    items.push({
      id: "heritage",
      label: "Heritage keep-out",
      status: "fail",
      detail: `Inside the ${heritage[0].radiusM.toLocaleString()} m keep-out around ${heritage[0].siteName}. Historic sites are protected.`,
    });
  else items.push({ id: "heritage", label: "Heritage keep-out", status: "pass", detail: "Outside every historic site's keep-out ring." });

  // Landing plumes blast regolith outwards for kilometres.
  if (role === "landing_pad") {
    const reach = value(values, "keepoutKm") ?? 0;
    const inside = near.filter(({ b, d }) => d < reach && MOON_BUILDING_BY_TYPE[b.type].role !== "landing_pad");
    items.push(
      inside.length
        ? { id: "plume", label: "Plume keep-out", status: "warn", detail: `${inside.map(({ b, d }) => `${nameOf(b)} (${km(d)})`).join(", ")} would be inside its ${km(reach)} plume keep-out.` }
        : { id: "plume", label: "Plume keep-out", status: "pass", detail: `No other building within its ${km(reach)} plume keep-out.` },
    );
  } else {
    const pads = near.filter(({ b, d }) => MOON_BUILDING_BY_TYPE[b.type].role === "landing_pad" && d < (value(b.values, "keepoutKm") ?? 0));
    items.push(
      pads.length
        ? { id: "plume", label: "Landing plumes", status: "warn", detail: `Within the plume keep-out of ${nameOf(pads[0].b)} (${km(pads[0].d)} away): landings would spray it with regolith.` }
        : { id: "plume", label: "Landing plumes", status: "pass", detail: "Outside every landing pad's plume keep-out." },
    );
  }

  // Reactor radiation: crewed buildings stay outside the fission keep-out.
  if (CREWED.includes(role)) {
    const reactors = near.filter(({ b, d }) => MOON_BUILDING_BY_TYPE[b.type].role === "fission" && d < (value(b.values, "keepoutKm") ?? 0));
    items.push(
      reactors.length
        ? { id: "radiation", label: "Reactor radiation", status: "fail", detail: `${km(reactors[0].d)} from ${nameOf(reactors[0].b)}, inside its radiation keep-out. Crew need to live farther away.` }
        : { id: "radiation", label: "Reactor radiation", status: "pass", detail: "Outside every reactor's radiation keep-out." },
    );
  }
  if (role === "fission") {
    const reach = value(values, "keepoutKm") ?? 0;
    const crewed = near.filter(({ b, d }) => CREWED.includes(MOON_BUILDING_BY_TYPE[b.type].role) && d < reach);
    items.push(
      crewed.length
        ? { id: "radiation", label: "Reactor radiation", status: "fail", detail: `${crewed.map(({ b, d }) => `${nameOf(b)} (${km(d)})`).join(", ")} would be inside its ${km(reach)} radiation keep-out.` }
        : { id: "radiation", label: "Reactor radiation", status: "pass", detail: `No crewed building within ${km(reach)}.` },
    );
  }

  // The base shares power and life support over short cables and pipes.
  if (!near.length) items.push({ id: "network", label: "Base network", status: "info", detail: "The first building of this base." });
  else if (near[0].d <= NETWORK_REACH_KM)
    items.push({ id: "network", label: "Base network", status: "pass", detail: `${km(near[0].d)} from ${nameOf(near[0].b)}: close enough to share power and supplies.` });
  else
    items.push({
      id: "network",
      label: "Base network",
      status: "warn",
      detail: `${km(near[0].d)} from the nearest building (${nameOf(near[0].b)}). Beyond ${NETWORK_REACH_KM} km a cable or rover link is assumed.`,
    });

  if (role === "habitat") {
    const vis = facts.earthVisibility;
    items.push({
      id: "earth",
      label: "Earth in view",
      status: vis === "always" ? "pass" : vis === "sometimes" ? "warn" : "fail",
      detail:
        vis === "always"
          ? "Earth is always above the horizon: direct radio contact."
          : vis === "sometimes"
            ? "Near the limb: Earth rises and sets as the Moon librates. Contact is intermittent without a relay."
            : "Far side: Earth never rises. Crew would need a relay satellite.",
    });
    const night = facts.longestNightHours;
    items.push(
      night === null
        ? { id: "night", label: "Longest night", status: "unknown", detail: facts.nightBasis }
        : {
            id: "night",
            label: "Longest night",
            status: night <= 120 ? "pass" : "warn",
            detail: `${(night / 24).toFixed(1)} days of darkness. Life support needs fission power or storage to last it.`,
          },
    );
  }
  if (role === "solar") {
    const surveyed = value(values, "sunlitFraction");
    const f = surveyed ?? facts.sunlitFraction;
    items.push(
      f === null
        ? { id: "sunlight", label: "Sunlight", status: "unknown", detail: `${facts.sunlitBasis} Enter a surveyed sunlit fraction.` }
        : {
            id: "sunlight",
            label: "Sunlight",
            status: f >= 0.6 ? "pass" : f >= 0.45 ? "warn" : "fail",
            detail: `Lit ${pct(f)} of the time${surveyed !== null ? " (surveyed value)" : ""}. ${
              f >= 0.8 ? "An excellent polar site." : f >= 0.6 ? "Good." : f >= 0.45 ? "Typical away from the poles: two-week nights need storage." : "Too dark for solar power."
            }`,
          },
    );
  }
  if (role === "ice_mine")
    items.push({
      id: "ice",
      label: "Water ice",
      status: facts.icePotential === "likely" ? "pass" : facts.icePotential === "possible" ? "warn" : "fail",
      detail:
        facts.icePotential === "likely"
          ? "Close to the pole: permanently shadowed craters nearby can hold ice. Ice maps are not prepared yet, so confirm the crater."
          : facts.icePotential === "possible"
            ? "Polar latitude: some shadowed craters may hold ice. Confirm with ice-stability data."
            : "Away from the poles surface ice is not stable. There is nothing to mine here.",
    });
  if (role === "oxygen_plant")
    items.push(
      facts.terrain === null
        ? { id: "ilmenite", label: "Feedstock", status: "unknown", detail: "Mare outlines are still loading." }
        : facts.terrain === "mare"
          ? { id: "ilmenite", label: "Feedstock", status: "pass", detail: `${facts.mareName}: mare basalt, rich in ilmenite (FeTiO₃), the easiest ore to take oxygen from.` }
          : { id: "ilmenite", label: "Feedstock", status: "warn", detail: "Highlands: little ilmenite. Expect more energy per kg (e.g. molten regolith electrolysis)." },
    );
  if (role === "landing_pad")
    items.push(
      facts.terrain === null
        ? { id: "terrain", label: "Ground", status: "unknown", detail: "Mare outlines are still loading." }
        : facts.terrain === "mare"
          ? { id: "terrain", label: "Ground", status: "pass", detail: `${facts.mareName}: smooth mare plains suit landings.` }
          : { id: "terrain", label: "Ground", status: "warn", detail: "Highlands: rougher and more cratered. Check slopes before landing." },
    );

  items.push({
    id: "elevation",
    label: "Elevation",
    status: "info",
    detail:
      facts.elevationM === null
        ? "Unknown here (LOLA elevation not prepared). Slopes are not checked."
        : `${Math.round(facts.elevationM).toLocaleString()} m relative to the 1,737.4 km lunar sphere (LOLA). Slopes are not checked: the prepared grid is too coarse.`,
  });

  const verdict: Verdict = items.some((i) => i.status === "fail")
    ? "unsuitable"
    : items.some((i) => i.status === "warn" || i.status === "unknown")
      ? "warnings"
      : "suitable";
  return { items, verdict };
}

/* ---------------- Base balance ---------------- */

export type BaseSettings = {
  transportCase: string;
  /** Longest night the base must survive, in hours; null = derived from where the base is. */
  nightHours: number | null;
};

export const DEFAULT_BASE_SETTINGS: BaseSettings = { transportCase: DEFAULT_TRANSPORT_CASE, nightHours: null };

/** A per-day resource: kg/day produced on site and needed by the crew. */
export type Supply = { produced: number; needed: number; shortfall: number; unknown: string[] };

export type BaseBalance = {
  crew: number;
  power: {
    demandKw: number;
    unknownDemand: string[];
    fissionKw: number;
    solarRatedKw: number;
    /** Solar output averaged over day and night (null if a tower's sunlight is unknown). */
    solarAverageKw: number | null;
    storageKwh: number;
    storageKw: number;
    nightHours: number;
    nightBasis: string;
    daySupplyKw: number;
    nightSupplyKw: number;
    /** Energy the base must draw from storage through one night. */
    nightDeficitKwh: number;
    dayOk: boolean;
    nightOk: boolean;
    /** Daytime surplus refills what the night used (assuming days as long as nights). */
    rechargeOk: boolean;
  };
  oxygen: Supply;
  water: Supply;
  food: Supply;
  reserveDays: number | null;
  mass: { knownT: number; unknown: string[] };
  cost: {
    case: TransportCase;
    deliveryUsd: number;
    /** Oxygen, water and food shipped from Earth each year to cover shortfalls. */
    resupplyKgPerYear: number;
    resupplyUsdPerYear: number;
  };
  lines: { id: string; status: CheckStatus; text: string }[];
  headline: { status: CheckStatus; text: string };
};

const supply = (): Supply => ({ produced: 0, needed: 0, shortfall: 0, unknown: [] });

/** Electrical load of a building while it runs (kW); null if a needed value is unknown. */
export function powerDemandKw(type: MoonBuildingType, values: MoonValues): number | null {
  const v = (k: string) => value(values, k);
  switch (MOON_BUILDING_BY_TYPE[type].role) {
    case "habitat":
      return v("powerKw");
    case "ice_mine": {
      const water = v("waterKgPerDay"), e = v("energyKwhPerKg");
      return water === null || e === null ? null : (water * e) / 24;
    }
    case "oxygen_plant": {
      const o2 = v("oxygenKgPerDay"), e = v("energyKwhPerKg");
      return o2 === null || e === null ? null : (o2 * e) / 24;
    }
    case "greenhouse": {
      const area = v("areaM2"), perM2 = v("powerKwPerM2");
      return area === null || perM2 === null ? null : area * perM2;
    }
    default:
      return 0;
  }
}

function nightFor(buildings: PlacedMoonBuilding[], settings: BaseSettings): { hours: number; basis: string } {
  if (settings.nightHours !== null && Number.isFinite(settings.nightHours) && settings.nightHours > 0)
    return { hours: settings.nightHours, basis: "Set for this base." };
  const polar = buildings.length > 0 && buildings.every((b) => Math.abs(b.latitude) >= POLAR_LATITUDE);
  return polar
    ? { hours: POLAR_RIDGE_NIGHT_HOURS, basis: "Polar base: assumes a well-lit ridge, dark 3–5 days at a time (Gläser 2014). Crater sites are far darker." }
    : { hours: LUNAR_NIGHT_HOURS, basis: "Away from the poles every night lasts about 14.8 Earth days." };
}

export function baseBalance(buildings: PlacedMoonBuilding[], settings: BaseSettings = DEFAULT_BASE_SETTINGS): BaseBalance {
  const night = nightFor(buildings, settings);
  const transport = TRANSPORT_CASES.find((c) => c.id === settings.transportCase) ?? TRANSPORT_CASES.find((c) => c.id === DEFAULT_TRANSPORT_CASE)!;
  let crew = 0, demandKw = 0, fissionKw = 0, solarRatedKw = 0, storageKwh = 0, storageKw = 0, knownT = 0;
  let solarAverageKw: number | null = 0;
  let reserveDays: number | null = null;
  const unknownDemand: string[] = [], unknownMass: string[] = [];
  const oxygen = supply(), water = supply(), food = supply();
  const ls = LIFE_SUPPORT;

  for (const b of buildings) {
    const def = MOON_BUILDING_BY_TYPE[b.type];
    const v = (k: string) => value(b.values, k);
    const name = nameOf(b);
    const load = powerDemandKw(b.type, b.values);
    if (load === null) unknownDemand.push(name);
    else demandKw += load;
    const mass = v("landedMassT");
    if (mass === null) unknownMass.push(name);
    else knownT += mass;

    switch (def.role) {
      case "habitat": {
        const n = v("crew") ?? 0;
        crew += n;
        const oxRec = (v("oxygenRecoveryPct") ?? 0) / 100, waterRec = (v("waterRecoveryPct") ?? 0) / 100;
        oxygen.needed += n * ls.oxygenKgPerCrewDay * (1 - oxRec);
        water.needed += n * ls.waterKgPerCrewDay * (1 - waterRec);
        food.needed += n * ls.foodKgPerCrewDay;
        const days = v("reserveDays");
        if (days !== null) reserveDays = reserveDays === null ? days : Math.min(reserveDays, days);
        break;
      }
      case "solar": {
        const rated = v("ratedKw") ?? 0;
        solarRatedKw += rated;
        const f = v("sunlitFraction") ?? (Math.abs(b.latitude) >= POLAR_LATITUDE ? null : 0.5);
        solarAverageKw = solarAverageKw === null || f === null ? null : solarAverageKw + rated * f;
        break;
      }
      case "fission":
        fissionKw += v("outputKw") ?? 0;
        break;
      case "storage":
        storageKwh += v("capacityKwh") ?? 0;
        storageKw += v("maxOutputKw") ?? 0;
        break;
      case "ice_mine": {
        const w = v("waterKgPerDay");
        if (w === null) water.unknown.push(name);
        else water.produced += w;
        break;
      }
      case "oxygen_plant": {
        const o = v("oxygenKgPerDay");
        if (o === null) oxygen.unknown.push(name);
        else oxygen.produced += o;
        break;
      }
      case "greenhouse": {
        const area = v("areaM2");
        const f = v("foodKgPerM2Day"), o = v("oxygenKgPerM2Day");
        if (area === null || f === null) food.unknown.push(name);
        else food.produced += area * f;
        if (area === null || o === null) oxygen.unknown.push(name);
        else oxygen.produced += area * o;
        break;
      }
      default:
        break;
    }
  }
  for (const s of [oxygen, water, food]) s.shortfall = Math.max(0, s.needed - s.produced);

  const daySupplyKw = fissionKw + solarRatedKw;
  const fromStorageKw = Math.min(storageKw, storageKwh / night.hours);
  const nightSupplyKw = fissionKw + fromStorageKw;
  const nightDeficitKwh = Math.max(0, demandKw - fissionKw) * night.hours;
  const dayOk = daySupplyKw >= demandKw;
  const nightOk = nightSupplyKw >= demandKw;
  const rechargeOk = (daySupplyKw - demandKw) * night.hours >= Math.min(nightDeficitKwh, storageKwh);

  const resupplyKgPerYear = (oxygen.shortfall + water.shortfall + food.shortfall) * 365.25;
  const lines: BaseBalance["lines"] = [];
  const kw = (n: number) => `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })} kW`;
  const kg = (n: number) => `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg/day`;

  lines.push(
    crew > 0
      ? { id: "crew", status: "pass", text: `Houses ${crew} crew.` }
      : { id: "crew", status: "fail", text: "No crew habitat: nobody can live here yet." },
  );
  lines.push(
    dayOk
      ? { id: "day", status: "pass", text: `Daytime power: ${kw(daySupplyKw)} available for ${kw(demandKw)} of demand.` }
      : { id: "day", status: "fail", text: `Daytime power short: ${kw(daySupplyKw)} available for ${kw(demandKw)} of demand.` },
  );
  lines.push(
    nightOk
      ? { id: "night", status: rechargeOk ? "pass" : "warn", text: rechargeOk ? `Night power: ${kw(nightSupplyKw)} through a ${(night.hours / 24).toFixed(1)}-day night.` : `Night power holds, but daytime surplus cannot refill storage between nights.` }
      : { id: "night", status: "fail", text: `Night power short: ${kw(nightSupplyKw)} for ${kw(demandKw)} through a ${(night.hours / 24).toFixed(1)}-day night. Add fission power or storage.` },
  );
  if (unknownDemand.length)
    lines.push({ id: "unknown-power", status: "unknown", text: `Power demand unknown for ${unknownDemand.join(", ")}: not counted.` });
  for (const [id, label, s] of [["oxygen", "Oxygen", oxygen], ["water", "Water", water], ["food", "Food", food]] as const) {
    if (s.needed === 0 && s.produced === 0) continue;
    lines.push(
      s.shortfall === 0
        ? { id, status: "pass", text: `${label}: ${kg(s.produced)} made on site covers ${kg(s.needed)} needed.` }
        : { id, status: "warn", text: `${label}: ${kg(s.produced)} made on site, ${kg(s.needed)} needed. ${kg(s.shortfall)} shipped from Earth.` },
    );
  }

  const alive = crew > 0 && dayOk && nightOk;
  const selfSufficient = alive && resupplyKgPerYear === 0;
  const headline: BaseBalance["headline"] = !buildings.length
    ? { status: "info", text: "Place buildings to see whether the base can keep a crew alive." }
    : selfSufficient
      ? { status: "pass", text: `This base keeps ${crew} crew alive on its own power, oxygen, water and food.` }
      : alive
        ? { status: "warn", text: `This base keeps ${crew} crew alive with regular deliveries from Earth.` }
        : { status: "fail", text: crew > 0 ? "This base cannot keep its crew alive yet." : "No crew can live here yet." };

  return {
    crew,
    power: {
      demandKw,
      unknownDemand,
      fissionKw,
      solarRatedKw,
      solarAverageKw,
      storageKwh,
      storageKw,
      nightHours: night.hours,
      nightBasis: night.basis,
      daySupplyKw,
      nightSupplyKw,
      nightDeficitKwh,
      dayOk,
      nightOk,
      rechargeOk,
    },
    oxygen,
    water,
    food,
    reserveDays,
    mass: { knownT, unknown: unknownMass },
    cost: {
      case: transport,
      deliveryUsd: knownT * 1000 * transport.usdPerKg,
      resupplyKgPerYear,
      resupplyUsdPerYear: resupplyKgPerYear * transport.usdPerKg,
    },
    lines,
    headline,
  };
}

/** US dollars in short form: $14k, $3.2M, $1.4B. */
export function formatUsd(usd: number): string {
  const abs = Math.abs(usd);
  const [div, suffix] = abs >= 1e9 ? [1e9, "B"] : abs >= 1e6 ? [1e6, "M"] : abs >= 1e3 ? [1e3, "k"] : [1, ""];
  return `$${(usd / div).toLocaleString(undefined, { maximumFractionDigits: usd / div < 10 ? 1 : 0 })}${suffix}`;
}
