/**
 * Prepared OSM infrastructure layers (datacenters, dams) — see scripts/prepare_infrastructure.py.
 * Ownership is copied from OSM tags; power values are tagged capacity ratings, never consumption.
 */
import type { Feature, FeatureCollection, Geometry } from "geojson";

export type InfraLayerId = "datacenters" | "dams";

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
  // Added by the backend from the boundary packs (null when outside every outline).
  country?: string | null;
  admin1?: string | null;
};

export type Facility = Feature<Geometry, FacilityProps> & { id: string };

export type InfraManifest = {
  id: string;
  provider: string;
  product: string;
  licence: string;
  attribution: string;
  evidenceType: string;
  spatialSupport: string;
  retrievedAt: string;
  observationPeriod: string | null;
  upstream: { repository: string; commit: string | null; notes: string[] };
  limitations: string[];
  layers: { id: InfraLayerId; file: string; stats: Record<string, number> }[];
};

export type Company = { key: string; label: string; count: number; colour: [number, number, number] };

export const LAYER_META: Record<InfraLayerId, { label: string; colour: [number, number, number] }> = {
  // Same accents as gods-eye-view: cyan datacenters, blue dams.
  datacenters: { label: "Datacenters", colour: [0, 229, 255] },
  dams: { label: "Dams & hydro", colour: [0, 136, 255] },
};

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

export async function loadInfrastructure(signal?: AbortSignal) {
  const get = async <T>(path: string) => {
    const r = await fetch(path, { signal, cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
    return (await r.json()) as T;
  };
  const [manifest, datacenters, dams] = await Promise.all([
    get<InfraManifest>("/api/infrastructure"),
    get<FeatureCollection<Geometry, FacilityProps>>("/api/infrastructure/datacenters"),
    get<FeatureCollection<Geometry, FacilityProps>>("/api/infrastructure/dams"),
  ]);
  return {
    manifest,
    facilities: [...datacenters.features, ...dams.features] as Facility[],
  };
}

/** Companies ranked by mapped facility count; the top ones get a distinct colour. */
export function rankCompanies(facilities: Facility[]): Company[] {
  const groups = new Map<string, { count: number; names: Map<string, number> }>();
  for (const f of facilities) {
    const { companyKey, operator } = f.properties;
    if (!companyKey || !operator) continue;
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
  return p.nameEn || p.name || p.operator || (p.layer === "dams" ? "Unnamed dam" : "Unnamed datacenter");
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
