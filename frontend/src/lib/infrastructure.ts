/**
 * Prepared infrastructure layers — see scripts/prepare_infrastructure.py. Datacenters, dams and the
 * high-voltage grid come from OSM; power plants from WRI's Global Power Plant Database; airports from
 * OurAirports; ports from Natural Earth. Ownership is copied from the source; power values are
 * capacity ratings, never consumption; voltages are tags, not spare capacity.
 */
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { voltageColour } from "./context";

export type InfraLayerId =
  | "datacenters"
  | "power_plants"
  | "dams"
  | "substations"
  | "transmission_lines"
  | "airports"
  | "ports";

export type PowerRating = { tag: string; meaning: string; raw: string; kw: number | null };

export type FacilityProps = {
  layer: InfraLayerId;
  name: string | null;
  nameEn: string | null;
  operator: string | null;
  operatorShort: string | null;
  operatorWikidata: string | null;
  owner: string | null;
  ownerWikidata: string | null;
  lon: number;
  lat: number;
  h3Id: string;
  osmId: number | null;
  osmType: string | null;
  osmUrl: string | null;
  startDate: string | null;
  website: string | null;
  heightM: number | null;
  levels: number | null;
  electricityConsumptionKwhPerYear: null;
  waterConsumptionM3PerYear: null;
  powerRatings: PowerRating[];
  companyKey: string | null;
  companyFacilityCount: number | null;
  river?: string | null;
  plantSource?: string | null;
  // Layer-specific details (absent when the source does not report them).
  kind?: string | null;
  capacityMw?: number | null;
  otherFuels?: string[] | null;
  generation?: { gwh: number; year: number; estimated: boolean } | null;
  voltageKv?: number[] | null;
  circuits?: number | null;
  lengthKm?: number | null;
  region?: string | null;
  iata?: string | null;
  icao?: string | null;
  municipality?: string | null;
  scheduledService?: boolean | null;
  elevationM?: number | null;
  rank?: number | null;
  recordId?: string | null;
  recordSource?: string | null;
  recordUrl?: string | null;
  // Added by the backend from the boundary packs (null when outside every outline).
  country?: string | null;
  admin1?: string | null;
};

export type Facility = Feature<Geometry, FacilityProps> & { id: string };

export type InfraSource = {
  id: string;
  name: string;
  provider: string;
  product: string;
  licence: string;
  attribution: string;
  evidenceType: string;
  retrievedAt: string;
  observationPeriod: string | null;
  url?: string;
  limitations: string[];
};

export type InfraLayerEntry = {
  id: InfraLayerId;
  file: string;
  source: string;
  scope: "global" | "regions";
  regions?: string[];
  minVoltageKv?: number;
  kinds?: Record<string, number>;
  available?: boolean;
  stats: Record<string, number>;
};

export type InfraManifest = {
  id: string;
  sources: Record<string, InfraSource>;
  layers: InfraLayerEntry[];
};

export type Company = { key: string; label: string; count: number; colour: [number, number, number] };

export type InfraGroup = "Energy" | "Digital" | "Transport";

export const LAYER_META: Record<
  InfraLayerId,
  { label: string; singular: string; group: InfraGroup; colour: [number, number, number]; line?: boolean }
> = {
  // Same accents as gods-eye-view: cyan datacenters, blue dams.
  power_plants: { label: "Power plants", singular: "Power plant", group: "Energy", colour: [217, 119, 6] },
  dams: { label: "Dams & hydro", singular: "Dam", group: "Energy", colour: [0, 136, 255] },
  substations: { label: "Substations", singular: "Substation", group: "Energy", colour: [202, 138, 4] },
  transmission_lines: { label: "High-voltage lines", singular: "Power line", group: "Energy", colour: [220, 38, 38], line: true },
  datacenters: { label: "Datacenters", singular: "Datacenter", group: "Digital", colour: [0, 229, 255] },
  airports: { label: "Airports", singular: "Airport", group: "Transport", colour: [124, 58, 237] },
  ports: { label: "Seaports", singular: "Port", group: "Transport", colour: [13, 148, 136] },
};

export const INFRA_LAYER_IDS = Object.keys(LAYER_META) as InfraLayerId[];
export const isInfraLayer = (id: string): id is InfraLayerId => id in LAYER_META;

/** Fuel colours, shared with the per-location OSM power layer. Keys are lower-case. */
export const FUEL_COLOURS: Record<string, [number, number, number]> = {
  solar: [234, 179, 8],
  wind: [20, 184, 166],
  hydro: [37, 99, 235],
  gas: [100, 116, 139],
  coal: [41, 37, 36],
  nuclear: [168, 85, 247],
  oil: [120, 53, 15],
  biomass: [101, 163, 13],
  geothermal: [225, 29, 72],
  waste: [161, 98, 7],
  storage: [14, 165, 233],
};
export const OTHER_FUEL: [number, number, number] = [148, 163, 184];
export const fuelColour = (fuel: string | null | undefined) => FUEL_COLOURS[(fuel ?? "").toLowerCase()] ?? OTHER_FUEL;

/** Colour by what the layer is about: fuel for plants, voltage for the grid, the layer accent otherwise.
 *  (Datacenters are coloured by operator in App, which knows the company ranking.) */
export function layerColour(p: FacilityProps): [number, number, number] {
  if (p.layer === "power_plants") return fuelColour(p.kind);
  if ((p.layer === "substations" || p.layer === "transmission_lines") && p.voltageKv?.length) return voltageColour(p.voltageKv);
  return LAYER_META[p.layer].colour;
}

export const UNKNOWN_OWNER: [number, number, number] = [148, 163, 184];

// Distinct, dark-background-friendly colours for the most-mapped companies.
const COMPANY_PALETTE: [number, number, number][] = [
  [255, 153, 0],
  [236, 72, 153],
  [34, 197, 94],
  [168, 85, 247],
  [250, 204, 21],
  [239, 68, 68],
  [45, 212, 191],
  [129, 140, 248],
];

async function getJson<T>(path: string, signal?: AbortSignal) {
  const r = await fetch(path, { signal, cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export const loadInfraManifest = (signal?: AbortSignal) => getJson<InfraManifest>("/api/infrastructure", signal);

const DEFAULTS: Partial<FacilityProps> = {
  name: null,
  nameEn: null,
  operator: null,
  operatorShort: null,
  operatorWikidata: null,
  owner: null,
  ownerWikidata: null,
  osmId: null,
  osmType: null,
  osmUrl: null,
  startDate: null,
  website: null,
  heightM: null,
  levels: null,
  electricityConsumptionKwhPerYear: null,
  waterConsumptionM3PerYear: null,
  companyKey: null,
  companyFacilityCount: null,
};

/** The larger layers are written compactly (null fields dropped); restore the full record shape. */
export function normaliseFacility(f: Feature<Geometry, Partial<FacilityProps>>): Facility {
  const p = { ...DEFAULTS, ...f.properties } as FacilityProps;
  if (!p.powerRatings) {
    p.powerRatings = p.capacityMw
      ? [{ tag: "capacity_mw", meaning: "Nameplate generation capacity", raw: `${p.capacityMw} MW`, kw: p.capacityMw * 1000 }]
      : [];
  }
  return { ...f, id: String(f.id), properties: p } as Facility;
}

export async function loadInfraLayer(id: InfraLayerId, signal?: AbortSignal): Promise<Facility[]> {
  const fc = await getJson<FeatureCollection<Geometry, Partial<FacilityProps>>>(`/api/infrastructure/${id}`, signal);
  return fc.features.map(normaliseFacility);
}

/** Companies ranked by mapped facility count; the top ones get a distinct colour. */
export function rankCompanies(facilities: Facility[]): Company[] {
  const groups = new Map<string, { count: number; names: Map<string, number> }>();
  for (const f of facilities) {
    const { companyKey, operator, layer } = f.properties;
    // The operator filter and colours are about datacenter operators.
    if (layer !== "datacenters" || !companyKey || !operator) continue;
    const g = groups.get(companyKey) ?? { count: 0, names: new Map() };
    g.count += 1;
    g.names.set(operator, (g.names.get(operator) ?? 0) + 1);
    groups.set(companyKey, g);
  }
  return [...groups.entries()]
    .map(([key, g]) => ({
      key,
      // Most common spelling of the operator name within the group.
      label: [...g.names.entries()].sort((a, b) => b[1] - a[1])[0][0],
      count: g.count,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .map((c, i) => ({ ...c, colour: COMPANY_PALETTE[i] ?? [0, 229, 255] }));
}

export const COLOURED_COMPANIES = COMPANY_PALETTE.length;

export function facilityTitle(p: FacilityProps): string {
  if (p.nameEn || p.name) return (p.nameEn || p.name)!;
  if (p.layer === "transmission_lines" && p.voltageKv?.length) return `${formatKv(p.voltageKv)} ${p.kind === "Overhead line" ? "line" : "cable"}`;
  if (p.layer === "substations" && p.voltageKv?.length) return `${formatKv(p.voltageKv)} substation`;
  return p.operator || p.owner || `Unnamed ${LAYER_META[p.layer].singular.toLowerCase()}`;
}

/** [400, 132] -> "400/132 kV". */
export function formatKv(kv: number[]): string {
  return `${kv.map((v) => v.toLocaleString(undefined, { maximumFractionDigits: 1 })).join("/")} kV`;
}

/** The headline number of a record: highest voltage for the grid, else the first parsed power rating (kW). */
export function facilityMetric(p: FacilityProps): number | null {
  if (p.layer === "substations" || p.layer === "transmission_lines") return p.voltageKv?.[0] ?? null;
  return p.powerRatings.find((r) => r.kw !== null)?.kw ?? null;
}

export function formatKw(kw: number): string {
  if (kw >= 1e6) return `${(kw / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })} GW`;
  if (kw >= 1e3) return `${(kw / 1e3).toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`;
  return `${kw.toLocaleString(undefined, { maximumFractionDigits: 1 })} kW`;
}

/** The rated IT load, if (and only if) the source tagged one explicitly. */
export function ratedItLoadKw(p: FacilityProps): number | null {
  return p.powerRatings.find((r) => r.tag === "capacity:it_load" && r.kw !== null)?.kw ?? null;
}
