/**
 * Count / filter / rank over records already loaded in the browser — the same idea as
 * gods-eye-view's analyst engine, reduced to explicit, user-selected criteria. Pure: no fetching.
 * A ranking describes the chosen criteria only; it is not a siting recommendation.
 */
import type { Earthquake, Fire, LandingPoint, PowerFeature } from "./context";
import { facilityMetric, facilityTitle, LAYER_META, type Facility, type InfraLayerId } from "./infrastructure";

export type Dataset = InfraLayerId | "earthquakes" | "fires" | "landing_points" | "power";

export const DATASET_LABEL: Record<Dataset, string> = {
  datacenters: "Datacenters",
  power_plants: "Power plants",
  dams: "Dams & hydro",
  substations: "Substations (Arizona, UK)",
  transmission_lines: "High-voltage lines (Arizona, UK)",
  airports: "Airports",
  ports: "Seaports",
  earthquakes: "Earthquakes",
  fires: "Fire detections",
  landing_points: "Cable landing points",
  power: "OSM power (loaded area)",
};

/** What the numeric column means for each dataset; null where there is none. */
export const METRIC: Record<Dataset, { label: string; unit: string } | null> = {
  datacenters: { label: "Tagged power rating", unit: "kW" },
  power_plants: { label: "Nameplate capacity", unit: "kW" },
  dams: { label: "Nameplate capacity", unit: "kW" },
  substations: { label: "Highest voltage", unit: "kV" },
  transmission_lines: { label: "Voltage", unit: "kV" },
  airports: null,
  ports: null,
  earthquakes: { label: "Magnitude", unit: "" },
  fires: { label: "Fire radiative power", unit: "MW" },
  landing_points: null,
  power: { label: "Nameplate output", unit: "kW" },
};

export type QueryRecord = {
  key: string;
  dataset: Dataset;
  title: string;
  lon: number;
  lat: number;
  country: string | null;
  admin1: string | null;
  operator: string | null;
  owner: string | null;
  metric: number | null;
  time: number | null;
  companyCount: number | null;
  ref: unknown;
};

export type Query = {
  dataset: Dataset;
  country?: string | null;
  admin1?: string | null;
  operator?: string | null;
  text?: string | null;
  sort: "metric" | "company" | "nearest" | "newest" | "name";
  near?: { lat: number; lon: number } | null;
  limit?: number;
};

export type QueryResult = {
  total: number;
  items: (QueryRecord & { distanceKm: number | null })[];
  metric: { withValue: number; sum: number | null; max: number | null };
  operators: { name: string; count: number }[];
};

export function haversineKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371.0088;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export const isFacilityDataset = (d: Dataset): d is InfraLayerId => d in LAYER_META;

export function fromFacilities(fs: Facility[]): QueryRecord[] {
  return fs.map((f) => {
    const p = f.properties;
    return {
      key: f.id,
      dataset: p.layer,
      title: facilityTitle(p),
      lon: p.lon,
      lat: p.lat,
      country: p.country ?? null,
      admin1: p.admin1 ?? null,
      operator: p.operator,
      owner: p.owner,
      metric: facilityMetric(p),
      time: null,
      companyCount: p.companyFacilityCount,
      ref: f,
    };
  });
}

export const fromEarthquakes = (qs: Earthquake[]): QueryRecord[] =>
  qs.map((q) => ({
    key: `quake:${q.id}`,
    dataset: "earthquakes",
    title: q.place ?? q.id,
    lon: q.lon,
    lat: q.lat,
    country: q.country,
    admin1: q.admin1,
    operator: null,
    owner: null,
    metric: q.magnitude,
    time: q.time,
    companyCount: null,
    ref: q,
  }));

export const fromFires = (fs: Fire[]): QueryRecord[] =>
  fs.map((f) => ({
    key: `fire:${f.id}`,
    dataset: "fires",
    title: `Detection ${f.acqDate} ${f.acqTime.padStart(4, "0")}Z`,
    lon: f.lon,
    lat: f.lat,
    country: f.country,
    admin1: f.admin1,
    operator: null,
    owner: null,
    metric: f.frpMw,
    time: Date.parse(`${f.acqDate}T${f.acqTime.padStart(4, "0").replace(/(\d\d)(\d\d)/, "$1:$2")}:00Z`) || null,
    companyCount: null,
    ref: f,
  }));

export const fromLanding = (ls: LandingPoint[]): QueryRecord[] =>
  ls.map((l) => ({
    key: l.id,
    dataset: "landing_points",
    title: l.properties.name,
    lon: l.properties.lon,
    lat: l.properties.lat,
    country: null,
    admin1: null,
    operator: null,
    owner: null,
    metric: null,
    time: null,
    companyCount: null,
    ref: l,
  }));

export function fromPower(ps: PowerFeature[]): QueryRecord[] {
  return ps
    .filter((p) => p.geometry.type === "Point")
    .map((p) => {
      const [lon, lat] = (p.geometry as unknown as { coordinates: [number, number] }).coordinates;
      const pr = p.properties;
      return {
        key: p.id,
        dataset: "power" as const,
        title: pr.name ?? `${pr.plantSource ? pr.plantSource + " " : ""}${pr.kind}`,
        lon,
        lat,
        country: null,
        admin1: null,
        operator: pr.operator,
        owner: pr.owner,
        metric: pr.outputKw,
        time: null,
        companyCount: null,
        ref: p,
      };
    });
}

export function runQuery(records: QueryRecord[], q: Query): QueryResult {
  const text = q.text?.trim().toLocaleLowerCase() || null;
  const op = q.operator?.trim().toLocaleLowerCase() || null;
  const matches = records.filter(
    (r) =>
      r.dataset === q.dataset &&
      (!q.country || r.country === q.country) &&
      (!q.admin1 || r.admin1 === q.admin1) &&
      (!op || [r.operator, r.owner].some((v) => v?.toLocaleLowerCase().includes(op))) &&
      (!text || r.title.toLocaleLowerCase().includes(text)),
  );

  const withDistance = matches.map((r) => ({ ...r, distanceKm: q.near ? haversineKm(q.near, r) : null }));
  // Unknown values sort last, never as zero.
  const desc = (a: number | null, b: number | null) => (b ?? -Infinity) - (a ?? -Infinity);
  const sorters: Record<Query["sort"], (a: (typeof withDistance)[0], b: (typeof withDistance)[0]) => number> = {
    metric: (a, b) => desc(a.metric, b.metric),
    company: (a, b) => desc(a.companyCount, b.companyCount),
    newest: (a, b) => desc(a.time, b.time),
    nearest: (a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity),
    name: (a, b) => a.title.localeCompare(b.title),
  };
  withDistance.sort((a, b) => sorters[q.sort](a, b) || a.title.localeCompare(b.title));

  const values = matches.map((r) => r.metric).filter((v): v is number => v !== null);
  const opCounts = new Map<string, number>();
  for (const r of matches) if (r.operator) opCounts.set(r.operator, (opCounts.get(r.operator) ?? 0) + 1);

  return {
    total: matches.length,
    items: withDistance.slice(0, q.limit ?? 25),
    metric: {
      withValue: values.length,
      sum: values.length && q.dataset !== "earthquakes" ? values.reduce((a, b) => a + b, 0) : null,
      max: values.length ? Math.max(...values) : null,
    },
    operators: [...opCounts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
      .slice(0, 5),
  };
}
