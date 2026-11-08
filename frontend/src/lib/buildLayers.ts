/**
 * Map layers the Build workspace switches on for the building being defined.
 *
 * `layerNeeds` says which existing map layers are about a resource the building needs (a data
 * centre that draws electricity -> the high-voltage grid). It mirrors the need detection in
 * `siteNeeds` (buildingForm.ts) and the backend's `demand_of`, but keeps draw and export apart.
 *
 * The ownership functions (`reconcileLayers`, `toggleLayers`) decide which layers to switch on or
 * off; `useBuildLayers` applies their decisions to React state. They are pure so they can be tested
 * without React. Per layer the build flow remembers who it belongs to:
 * - "auto": the build flow switched it on; it is switched off again when no longer needed,
 * - "user": it was already on when it became needed; the build flow never touches it,
 * - "declined": the user switched it off while it was needed; it stays off until the need goes
 *   away and comes back.
 */
import type { IconName } from "../components/Icon";
import { isAirPollutant } from "./buildingForm";
import type { BuildingStats, BuildingType, ParamValue } from "./buildings";
import { formatKw, LAYER_META, type InfraLayerId } from "./infrastructure";

export type LayerRef = { kind: "infra"; id: InfraLayerId } | { kind: "feature"; id: string };

export type LayerNeed = {
  /** Stable per resource (e.g. "power" whether the building draws, exports or both). */
  key: string;
  label: string;
  icon: IconName;
  /** Why these layers are shown, e.g. "Draws ~12 MW of electricity at peak". */
  reason: string;
  layers: LayerRef[];
};

export type LayerNeedsInput = {
  type: BuildingType;
  stats: BuildingStats;
  parameters: Record<string, ParamValue>;
  producesPower: boolean;
  producesWater: boolean;
  /** Optional: drop unavailable layers here (the hook filters again, so this can be left out). */
  isAvailable?: (ref: LayerRef) => boolean;
};

// --------------------------------------------------------------------------------------------
// Layer references

const infra = (id: InfraLayerId): LayerRef => ({ kind: "infra", id });
const feature = (id: string): LayerRef => ({ kind: "feature", id });

/** "infra:ports" / "feature:mrds": one string per layer, for maps and effect keys. */
export const refKey = (ref: LayerRef): string => `${ref.kind}:${ref.id}`;

export function parseRefKey(key: string): LayerRef | null {
  const i = key.indexOf(":");
  if (i < 0) return null;
  const kind = key.slice(0, i);
  const id = key.slice(i + 1);
  if (kind === "infra" && Object.hasOwn(LAYER_META, id)) return { kind, id: id as InfraLayerId };
  if (kind === "feature" && id) return { kind, id };
  return null;
}

/** Names of the feature layers this module can switch on (the manifest name wins when known). */
const FEATURE_LABELS: Record<string, string> = {
  hydrorivers: "Rivers",
  wqp_sites: "Water-quality monitoring sites",
  mrds: "Mineral sites (USGS)",
  tri_facilities: "Toxics Release Inventory facilities",
};

export function layerLabel(ref: LayerRef): string {
  return ref.kind === "infra" ? LAYER_META[ref.id].label : (FEATURE_LABELS[ref.id] ?? ref.id);
}

/**
 * Availability predicate from the two manifests. Polygon and table feature layers are never
 * switched on automatically (polygons would cover the screening colours; tables are not drawn).
 */
export function layerAvailability(
  infraLayers: readonly { id: string; available?: boolean }[] | null | undefined,
  featureLayers: readonly { id: string; available: boolean; geometry: string }[] | null | undefined,
): (ref: LayerRef) => boolean {
  const infraOk = new Set((infraLayers ?? []).filter((l) => l.available !== false).map((l) => l.id));
  const featureOk = new Set(
    (featureLayers ?? []).filter((l) => l.available && (l.geometry === "point" || l.geometry === "line")).map((l) => l.id),
  );
  return (ref) => (ref.kind === "infra" ? infraOk.has(ref.id) : featureOk.has(ref.id));
}

/** Keep only available layers; drop needs left with none. */
export function availableNeeds(needs: readonly LayerNeed[], isAvailable: (ref: LayerRef) => boolean): LayerNeed[] {
  const out: LayerNeed[] = [];
  for (const need of needs) {
    const layers = need.layers.filter(isAvailable);
    if (!layers.length) continue;
    out.push(layers.length === need.layers.length ? need : { ...need, layers });
  }
  return out;
}

// --------------------------------------------------------------------------------------------
// What the building needs -> layers

const GRID_DRAW: LayerRef[] = [infra("transmission_lines"), infra("substations"), infra("power_plants")];
const GRID_EXPORT: LayerRef[] = [infra("transmission_lines"), infra("substations")];
const WATER: LayerRef[] = [feature("hydrorivers"), infra("dams")];

/** Farming types whose water use makes nearby nitrate / arsenic / salinity readings relevant. */
const AGRICULTURE: ReadonlySet<BuildingType> = new Set<BuildingType>(["farm", "livestock_farm", "greenhouse", "aquaculture"]);

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
/** A declared amount above zero (blank = unknown and "0" = explicitly none both mean "no need"). */
const pos = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && n > 0 ? n : null;
};
const fmt = (v: number) =>
  v >= 1 ? v.toLocaleString(undefined, { maximumFractionDigits: v >= 100 ? 0 : 1 }) : v.toLocaleString(undefined, { maximumSignificantDigits: 2 });
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "a", "a and b", "a, b and c", "a, b, c and 2 more". */
function listNames(names: string[], max = 3): string {
  if (names.length <= 1) return names.join("");
  if (names.length <= max) return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `${names.slice(0, max).join(", ")} and ${names.length - max} more`;
}

function uniqueNames(names: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of names) {
    const name = raw.trim();
    const k = name.toLowerCase();
    if (!name || seen.has(k)) continue;
    seen.add(k);
    out.push(name);
  }
  return out;
}

/** Electricity drawn from the grid, as a phrase ("draws ~12 MW of electricity at peak"), or null. */
function drawPhrase(type: BuildingType, stats: BuildingStats, p: Record<string, ParamValue>): string | null {
  const peak = pos(stats.power?.peakDemandKw);
  const avg = pos(stats.power?.averageDemandKw);
  if (peak !== null) return `draws ~${formatKw(peak)} of electricity at peak`;
  if (type === "data_centre" && stats.demandBasis === "derived") {
    // Same as the backend: peak = IT power × PUE when no peak is declared.
    const it = pos(p.itPowerKw);
    const pue = pos(p.pue);
    if (it !== null && pue !== null) return `draws ~${formatKw(it * Math.max(1, pue))} of electricity (IT load × PUE)`;
    if (it !== null) return `draws at least ~${formatKw(it)} of electricity (IT load, before cooling)`;
  }
  if (avg !== null) return `draws ~${formatKw(avg)} of electricity on average`;
  return null;
}

/** Electricity exported to the grid, as a phrase, or null. */
function exportPhrase(type: BuildingType, stats: BuildingStats, p: Record<string, ParamValue>, producesPower: boolean): string | null {
  const rated = num(stats.power?.ratedOutputKw);
  const avgOut = num(stats.power?.averageOutputKw);
  if (rated !== null && rated > 0) return `exports up to ~${formatKw(rated)} to the grid`;
  if (avgOut !== null && avgOut > 0) return `exports ~${formatKw(avgOut)} to the grid on average`;
  const kwp = type === "solar" ? pos(p.capacityKwp) : null;
  if (kwp !== null) return `exports up to ~${formatKw(kwp)} peak (kWp) to the grid`;
  // A generator whose output isn't entered yet still needs a grid connection; an explicit 0 doesn't.
  if (producesPower && rated === null && avgOut === null) return "generates electricity for the grid (output not entered yet)";
  return null;
}

/**
 * Water drawn: an amount (m³/day when operating hours are known, else m³/h), "" when the building
 * draws water but the amount can't be worked out yet, or null when no intake is declared.
 */
function intakeAmount(type: BuildingType, stats: BuildingStats, p: Record<string, ParamValue>): string | null {
  const hours = num(stats.operatingHoursPerDay);
  if (type === "data_centre" && stats.demandBasis === "derived") {
    const wue = pos(p.wueLPerKwh);
    if (wue === null) return null;
    // Same as the backend: WUE (L/kWh) × IT or facility energy ÷ 1000.
    const it = num(p.itPowerKw);
    const load = num(p.loadFraction);
    const pue = num(p.pue);
    const itKwhDay = it !== null && load !== null && hours !== null ? it * load * hours : null;
    const energy = itKwhDay === null ? null : p.wueBasis === "it_energy" ? itKwhDay : pue !== null ? itKwhDay * pue : null;
    return energy !== null && energy > 0 ? `~${fmt((wue * energy) / 1000)} m³/day` : "";
  }
  const perHour = pos(stats.water?.inputM3PerHour);
  if (perHour === null) return null;
  if (hours === null) return `~${fmt(perHour)} m³/h`;
  if (hours === 0) return null;
  return `~${fmt(perHour * hours)} m³/day`;
}

function outputAmount(stats: BuildingStats): string | null {
  const perHour = pos(stats.water?.outputM3PerHour);
  if (perHour === null) return null;
  const hours = num(stats.operatingHoursPerDay);
  if (hours === null) return `~${fmt(perHour)} m³/h`;
  if (hours === 0) return null;
  return `~${fmt(perHour * hours)} m³/day`;
}

/**
 * The map layers about each resource the building needs, in a fixed order:
 * power, water, water quality, coast, raw materials, air emissions, then type-driven context.
 */
export function layerNeeds(input: LayerNeedsInput): LayerNeed[] {
  const { type, stats, parameters, producesPower, producesWater } = input;
  const out: LayerNeed[] = [];

  // Electricity: drawing needs the whole grid; exporting needs lines and substations.
  const draw = drawPhrase(type, stats, parameters);
  const exp = exportPhrase(type, stats, parameters, producesPower);
  if (draw || exp) {
    out.push({
      key: "power",
      label: draw ? "Power grid" : "Grid connection",
      icon: "bolt",
      reason: cap([exp, draw].filter(Boolean).join("; ")),
      layers: draw ? GRID_DRAW : GRID_EXPORT,
    });
  }

  // Water: fresh intake and usable output both relate to rivers and reservoirs.
  const source = stats.water?.source ?? "fresh";
  const intake = intakeAmount(type, stats, parameters);
  const output = outputAmount(stats) ?? (producesWater && stats.water?.outputM3PerHour == null ? "water (output not entered yet)" : null);
  const draws = intake !== null;
  const of = (what: string) => (intake ? `${intake} of ${what}` : what); // "" = amount not known yet
  const water: string[] = [];
  if (draws && source === "fresh") water.push(`draws ${of("fresh water")}`);
  if (output) water.push(`supplies ${output}`);
  if (water.length) out.push({ key: "water", label: "Water", icon: "water", reason: cap(water.join("; ")), layers: WATER });

  // Farming water (not seawater): nitrate, arsenic and salinity readings nearby.
  if (draws && source !== "seawater" && AGRICULTURE.has(type)) {
    out.push({
      key: "water_quality",
      label: "Water quality (nitrate)",
      icon: "flask",
      reason: `Uses ${of("water")} for farming: nearby nitrate, arsenic and salinity readings`,
      layers: [feature("wqp_sites")],
    });
  }

  if (draws && source === "seawater") {
    out.push({ key: "coast", label: "Coast & ports", icon: "anchor", reason: `Takes ${of("seawater")}: needs a coastal site`, layers: [infra("ports")] });
  }

  const materials = uniqueNames((stats.materials ?? []).map((m) => m.name ?? ""));
  if (materials.length) {
    out.push({
      key: "materials",
      label: "Mineral sites",
      icon: "pickaxe",
      reason: `Uses ${listNames(materials)}: known mineral sites (materials can also be shipped)`,
      layers: [feature("mrds")],
    });
  }

  // Same notion of an air pollutant as siteNeeds (CO₂ and other greenhouse gases are not).
  const air = uniqueNames((stats.emissions ?? []).filter((e) => isAirPollutant(e.pollutant ?? "") && e.rateKgPerHour !== 0).map((e) => e.pollutant));
  if (air.length) {
    out.push({
      key: "emissions",
      label: "Other emitters",
      icon: "factory",
      reason: `Emits ${listNames(air)}: where industry already reports emissions`,
      layers: [feature("tri_facilities")],
    });
  }

  // Type-driven context: what is already built of the same kind.
  if (type === "data_centre") {
    out.push({ key: "datacentres", label: "Existing datacentres", icon: "server", reason: "Where datacentres are already built", layers: [infra("datacenters")] });
  } else if (type === "airport") {
    out.push({ key: "airports", label: "Airports", icon: "plane", reason: "Where airports already are", layers: [infra("airports")] });
  } else if (type === "seaport") {
    out.push({ key: "seaports", label: "Seaports", icon: "anchor", reason: "Existing seaports along the coast", layers: [infra("ports")] });
  } else if (type === "warehouse") {
    out.push({ key: "logistics", label: "Logistics", icon: "warehouse", reason: "Seaports and airports for freight", layers: [infra("ports"), infra("airports")] });
  }

  const merged = mergeSameLayers(out);
  return input.isAvailable ? availableNeeds(merged, input.isAvailable) : merged;
}

/** Two needs about exactly the same layers (a seaport taking seawater) become one chip. */
function mergeSameLayers(needs: LayerNeed[]): LayerNeed[] {
  const out: LayerNeed[] = [];
  const sig = (n: LayerNeed) => n.layers.map(refKey).sort().join("|");
  for (const need of needs) {
    const i = out.findIndex((o) => sig(o) === sig(need));
    if (i < 0) out.push(need);
    else out[i] = { ...out[i], reason: `${out[i].reason}; ${need.reason.charAt(0).toLowerCase()}${need.reason.slice(1)}` };
  }
  return out;
}

// --------------------------------------------------------------------------------------------
// Ownership: which layers the build flow switched on (pure decisions, applied by useBuildLayers)

export type LayerOwner = "auto" | "user" | "declined";

export type OwnershipState = {
  /** Per layer key; only layers that are needed, or that the build flow still has to switch off. */
  owners: Readonly<Record<string, LayerOwner>>;
  /**
   * Visibility the build flow asked for and has not seen applied yet. While a request is pending
   * the requested value counts as the layer's state, so a re-run before React applies it (StrictMode,
   * a stale effect) neither mistakes "not on yet" for "the user switched it off" nor drops the request.
   */
  expect: Readonly<Record<string, boolean>>;
  /**
   * Who owned a "declined" layer before it was hidden, so showing it again gives it back: a layer the
   * user already had on stays theirs (never switched off on leaving), one the build flow added stays "auto".
   */
  declinedFrom?: Readonly<Record<string, "auto" | "user">>;
};

export const EMPTY_OWNERSHIP: OwnershipState = { owners: {}, expect: {}, declinedFrom: {} };

/** The owner to remember when `key` becomes "declined" (its owner until now). */
function priorOwner(prev: OwnershipState, key: string): "auto" | "user" {
  const owner = prev.owners[key];
  if (owner === "auto" || owner === "user") return owner;
  return prev.declinedFrom?.[key] ?? "auto";
}

/** New state plus the visibility changes to apply (layer key -> on). */
export type OwnershipResult = { state: OwnershipState; changes: Record<string, boolean> };

/** A layer's state counting a pending request as applied. */
export function effectiveOn(state: OwnershipState, key: string, isOn: (key: string) => boolean): boolean {
  return key in state.expect ? state.expect[key] : isOn(key);
}

/**
 * Bring layers in line with what is needed now (`needed`: available layer keys; empty when the
 * Build workspace is closed):
 * - a needed layer that is off and unclaimed is switched on and becomes "auto";
 * - a needed layer that is already on and unclaimed becomes "user" (never touched);
 * - an "auto" or "user" layer seen off while still needed becomes "declined" (stays off);
 * - a "declined" layer seen on again was switched on by the user: it becomes "user";
 * - a layer no longer needed is forgotten; if it was "auto" and is on, it is switched off.
 */
export function reconcileLayers(prev: OwnershipState, needed: readonly string[], isOn: (key: string) => boolean): OwnershipResult {
  const want = new Set(needed);
  const owners: Record<string, LayerOwner> = {};
  const expect: Record<string, boolean> = {};
  const declinedFrom: Record<string, "auto" | "user"> = {};
  const changes: Record<string, boolean> = {};
  const keys = new Set([...needed, ...Object.keys(prev.owners), ...Object.keys(prev.expect)]);
  for (const key of keys) {
    const actual = isOn(key);
    const requested = key in prev.expect ? prev.expect[key] : undefined;
    const pending = requested !== undefined && requested !== actual;
    const on = pending ? requested : actual;
    const owner = prev.owners[key];
    let set: boolean | undefined;
    if (want.has(key)) {
      if (owner === undefined) {
        owners[key] = on ? "user" : "auto";
        if (!on) set = true;
      } else if (owner === "declined") {
        owners[key] = on ? "user" : "declined";
      } else {
        owners[key] = on ? owner : "declined";
      }
      if (owners[key] === "declined") declinedFrom[key] = priorOwner(prev, key);
    } else if (owner === "auto" && on) {
      set = false;
    }
    if (set === undefined && pending) set = requested; // not applied yet: ask again (idempotent)
    if (set !== undefined) {
      changes[key] = set;
      expect[key] = set;
    }
  }
  return { state: { owners, expect, declinedFrom }, changes };
}

/**
 * The user toggled a chip: switch all of its layers on (those switched on here become "auto", a
 * hidden layer gets back the owner it had before it was hidden, layers already on keep their owner)
 * or off (all become "declined", remembering their owner).
 */
export function toggleLayers(prev: OwnershipState, keys: readonly string[], on: boolean, isOn: (key: string) => boolean): OwnershipResult {
  const owners: Record<string, LayerOwner> = { ...prev.owners };
  const expect: Record<string, boolean> = { ...prev.expect };
  const declinedFrom: Record<string, "auto" | "user"> = { ...prev.declinedFrom };
  const changes: Record<string, boolean> = {};
  for (const key of keys) {
    const cur = effectiveOn(prev, key, isOn);
    const owner = prev.owners[key];
    if (on) {
      owners[key] = cur ? (owner === "auto" ? "auto" : "user") : owner === "declined" ? priorOwner(prev, key) : "auto";
      delete declinedFrom[key];
    } else {
      declinedFrom[key] = priorOwner(prev, key);
      owners[key] = "declined";
    }
    if (cur !== on) {
      changes[key] = on;
      expect[key] = on;
    }
  }
  return { state: { owners, expect, declinedFrom }, changes };
}

// --------------------------------------------------------------------------------------------
// Chips

export type BuildLayerEntry = {
  need: LayerNeed;
  /** Every layer of the need is on. */
  on: boolean;
  /** Some (not all) of its layers are on. */
  partial: boolean;
  /** At least one of its visible layers was switched on by the build flow. */
  auto: boolean;
};

/** One chip per need (needs already filtered to available layers). */
export function layerEntries(needs: readonly LayerNeed[], owners: Readonly<Record<string, LayerOwner>>, isOn: (key: string) => boolean): BuildLayerEntry[] {
  return needs.map((need) => {
    const keys = need.layers.map(refKey);
    const shown = keys.filter(isOn);
    return {
      need,
      on: keys.length > 0 && shown.length === keys.length,
      partial: shown.length > 0 && shown.length < keys.length,
      auto: shown.some((k) => owners[k] === "auto"),
    };
  });
}

/** Loading predicate by need key, from a per-layer loading status (e.g. App's infraStatus). */
export function loadingByNeed(entries: readonly { need: LayerNeed }[], layerLoading: (ref: LayerRef) => boolean): (key: string) => boolean {
  return (key) => !!entries.find((e) => e.need.key === key)?.need.layers.some(layerLoading);
}
