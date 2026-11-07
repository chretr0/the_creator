/**
 * Baseline data layers served by the backend:
 * - cell layers: H3 choropleths (climate, solar, soil, population, terrain, land cover, fires),
 * - feature layers: prepared points / lines / polygons / tables (MRDS, TRI, water quality, Aqueduct…).
 * Missing values are always `null` (unknown), never zero.
 */
import type { Feature, FeatureCollection, Geometry } from "geojson";

export type RGB = [number, number, number];
export type RGBA = [number, number, number, number];

export type LayerSlice = {
  id: string;
  label: string;
  group: string | null;
  units: string;
  rawUnits: string | null;
  aggregation: "mean" | "sum" | "mode";
  display: "value" | "density" | "percent";
  categorical: boolean;
  available: boolean;
  regions: string[];
};

export type LayerCategory = { value: number; label: string; colour: string };

export type Provenance = {
  provider?: string | null;
  product?: string | null;
  version?: string | null;
  licence?: string | null;
  licenceUrl?: string | null;
  attribution?: string | null;
  retrievedAt?: string | null;
  evidenceType?: string | null;
  documentationUrl?: string | null;
};

export type CellLayer = {
  id: string;
  name: string;
  category: string;
  sourceId: string;
  description: string;
  available: boolean;
  coverage: "global" | "regions";
  regions: string[];
  palette: "sequential" | "diverging" | "categorical";
  scaleType: "linear" | "log";
  domain: [number, number] | null;
  categories: LayerCategory[] | null;
  defaultSlice: string;
  slices: LayerSlice[];
  limitations: string[];
  nativeResolution: string | null;
  sampling: string | null;
  period?: string | null;
  provenance: Provenance;
};

export type CellValues = {
  layer: string;
  slice: string;
  resolution: number | null;
  units?: string;
  values: (number | null)[];
  domain: [number, number] | null;
  withData?: number;
};

export type FeatureField = { key: string; label: string; units: string | null };

export type FeatureLayerMeta = {
  id: string;
  name: string;
  sourceId: string;
  geometry: "point" | "line" | "polygon" | "table";
  file: string;
  regions: string[];
  count: number;
  bbox: [number, number, number, number] | null;
  nameField: string | null;
  categoryField: string | null;
  categories: string[] | null;
  valueField: string | null;
  valueUnits: string | null;
  fields: FeatureField[];
  provider?: string;
  product?: string;
  licence?: string;
  attribution?: string;
  evidenceType?: string;
  retrievedAt?: string;
  url?: string;
  limitations?: string[];
  available: boolean;
};

export type FeatureProps = Record<string, string | number | boolean | null>;
export type DataFeature = Feature<Geometry, FeatureProps>;
export type FeatureResult = FeatureCollection<Geometry, FeatureProps> & {
  layer: string;
  matched: number;
  truncated: boolean;
};

export type ProfileValue = {
  slice: string;
  label: string;
  group: string | null;
  value: number | null;
  display: number | null;
  units: string;
  rawUnits: string | null;
  /** For a zoomed-out hexagon: how many of its resolution-6 cells had data (null for a single cell). */
  cellsWithData?: number | null;
  /** The value is a class code (see the layer's categories), not a quantity. */
  categorical?: boolean;
};

/** What a profile value is and where it came from, for the cell inspector. */
export type CellSource = {
  sourceId: string;
  provider?: string | null;
  product?: string | null;
  period?: string | null;
  nativeResolution?: string | null;
  sampling?: string | null;
  evidenceType?: string | null;
  licence?: string | null;
  licenceUrl?: string | null;
  attribution?: string | null;
  retrievedAt?: string | null;
  documentationUrl?: string | null;
  limitations: string[];
};
export type CellProfile = {
  h3Id: string;
  resolution: number;
  areaKm2: number;
  /** Resolution-6 cells inside this cell (1 for a simulation cell). */
  simulationCells: number;
  /** Baseline region ("arizona" | "uk") containing the cell centre, or null outside both. */
  region?: string | null;
  layers: {
    layer: string;
    name: string;
    category: string;
    coverage?: "global" | "regions";
    categorical: boolean;
    categories: LayerCategory[] | null;
    values: ProfileValue[];
    attributes?: { key: string; label: string; value: string | number }[];
    source?: CellSource;
  }[];
};

export type CellFeatureContext = {
  h3Id: string;
  layers: {
    layer: string;
    name: string;
    geometry: "point" | "line" | "polygon";
    inCell?: number;
    count?: number;
    radiusKm?: number;
    nearest?: (FeatureProps & { lon: number; lat: number; distanceKm: number })[];
    features?: FeatureProps[];
  }[];
};

export type Scene = {
  id: string;
  name: string;
  url: string;
  bounds: [number, number, number, number];
  acquired: string;
  sourceId: string;
  attribution: string;
  licence: string;
  stretch?: string;
};

export type CarbonIntensity = {
  from: string;
  to: string;
  regions: {
    regionId: number;
    shortname: string;
    dnoregion?: string;
    forecast: number | null;
    index: string | null;
    generationMix: { fuel: string; perc: number }[];
  }[];
  national?: unknown;
};

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { cache: "no-cache", ...init });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      if (typeof b.detail === "string") detail = b.detail;
    } catch {
      /* non-JSON */
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

export const dataApi = {
  layers: (signal?: AbortSignal) => json<CellLayer[]>("/api/layers", { signal }),
  values: (layer: string, slice: string, cells: string[], signal?: AbortSignal) =>
    json<CellValues>(`/api/layers/${layer}/values`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slice, cells }),
      signal,
    }),
  profile: (h3Id: string, signal?: AbortSignal) => json<CellProfile>(`/api/cells/${h3Id}/profile`, { signal }),
  cellFeatures: (h3Id: string, signal?: AbortSignal) =>
    json<CellFeatureContext>(`/api/cells/${h3Id}/features`, { signal }),
  featureManifest: (signal?: AbortSignal) =>
    json<{ generatedAt: string | null; layers: FeatureLayerMeta[] }>("/api/features", { signal }),
  features: (
    layer: string,
    bounds: { west: number; south: number; east: number; north: number },
    opts: { categories?: string[]; q?: string; limit?: number } = {},
    signal?: AbortSignal,
  ) => {
    const p = new URLSearchParams({
      west: String(Math.max(-540, bounds.west)),
      south: String(Math.max(-90, bounds.south)),
      east: String(Math.min(540, bounds.east)),
      north: String(Math.min(90, bounds.north)),
      limit: String(opts.limit ?? 4000),
    });
    for (const c of opts.categories ?? []) p.append("category", c);
    if (opts.q) p.set("q", opts.q);
    return json<FeatureResult>(`/api/features/${layer}?${p}`, { signal });
  },
  scenes: (signal?: AbortSignal) => json<{ scenes: Scene[] }>("/api/imagery", { signal }),
  table: <T>(layer: string, signal?: AbortSignal) => json<T>(`/api/features/${layer}`, { signal }),
};

/* ---------------- Colour ---------------- */

const hex = (h: string): RGB => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

/** One-hue blue ramp, light → dark (magnitude). */
export const SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"].map(hex);
/** Blue ↔ neutral grey ↔ red (polarity, e.g. temperature). */
export const DIVERGING = ["#0d366b", "#256abf", "#86b6ef", "#f0efec", "#f2a99f", "#e34948", "#9b1c1c"].map(hex);
/** Second sequential context (feature choropleths such as water stress): one-hue orange. */
export const SEQUENTIAL_ORANGE = ["#fde3d6", "#f8bc9f", "#f29169", "#eb6834", "#c4501f", "#933b15", "#62270d"].map(hex);
/** Fixed categorical order for point categories; anything beyond folds into "Other". */
export const CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"].map(hex);
export const OTHER: RGB = [148, 163, 184];
export const NO_DATA: RGBA = [100, 116, 139, 14];

function lerp(stops: RGB[], t: number): RGB {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f].map(Math.round) as RGB;
}

export type ColourScale = {
  colour: (v: number | null) => RGB | null;
  /** Position 0–1 of a value on the legend bar. */
  position: (v: number) => number;
  domain: [number, number];
  log: boolean;
  stops: RGB[];
};

export function makeScale(
  domain: [number, number],
  opts: { log?: boolean; palette?: "sequential" | "diverging"; stops?: RGB[] } = {},
): ColourScale {
  const log = !!opts.log && domain[0] > 0;
  const stops = opts.stops ?? (opts.palette === "diverging" ? DIVERGING : SEQUENTIAL);
  const [lo, hi] = log ? [Math.log10(domain[0]), Math.log10(domain[1])] : domain;
  const position = (v: number) => {
    const x = log ? Math.log10(Math.max(v, domain[0])) : v;
    return hi === lo ? 0.5 : (x - lo) / (hi - lo);
  };
  return {
    colour: (v) => (v === null || !Number.isFinite(v) ? null : lerp(stops, position(v))),
    position,
    domain,
    log,
    stops,
  };
}

export function categoryColours(meta: FeatureLayerMeta): Map<string, RGB> {
  const m = new Map<string, RGB>();
  (meta.categories ?? []).slice(0, CATEGORICAL.length - 1).forEach((c, i) => m.set(c, CATEGORICAL[i]));
  return m;
}

export function landCoverColour(categories: LayerCategory[] | null): (v: number | null) => RGB | null {
  const m = new Map((categories ?? []).map((c) => [c.value, hex(c.colour)]));
  return (v) => (v === null ? null : (m.get(Math.round(v)) ?? OTHER));
}

/* ---------------- Formatting ---------------- */

export function formatValue(v: number | null | undefined, units?: string | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "no data";
  const a = Math.abs(v);
  const s =
    a >= 1e6
      ? `${(v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })} M`
      : a >= 1000
        ? Math.round(v).toLocaleString()
        : a >= 100
          ? v.toFixed(0)
          : a >= 10
            ? v.toFixed(1)
            : a >= 1
              ? v.toFixed(2)
              : a === 0
                ? "0"
                : v.toPrecision(2);
  return units ? `${s} ${units}` : s;
}

export const REGION_VIEWS: { id: string; label: string; bbox: [number, number, number, number] }[] = [
  { id: "arizona", label: "Arizona", bbox: [-113.5, 31.3, -109.0, 34.5] },
  { id: "uk", label: "United Kingdom", bbox: [-8.7, 49.8, 1.9, 60.9] },
];

/** Plain-language evidence types used in source records. */
export const EVIDENCE_LABEL: Record<string, string> = {
  reported_record: "reported record",
  reference_geometry: "reference geometry",
  reference_map: "reference map",
  in_situ_observation: "in-situ observation",
  satellite_retrieval: "satellite retrieval",
  satellite_imagery: "satellite imagery",
  model_output: "model output",
  modelled: "model output",
  reanalysis: "reanalysis (model + observations)",
  reference: "reference service",
};

type Bounds = { west: number; south: number; east: number; north: number };

/** Whether a map view overlaps any of the given baseline regions (longitudes compared modulo 360). */
export function viewTouchesRegions(bounds: Bounds, regionIds: string[]): boolean {
  if (bounds.east - bounds.west >= 360) return regionIds.length > 0;
  return REGION_VIEWS.filter((r) => regionIds.includes(r.id)).some(({ bbox: [w, s, e, n] }) => {
    if (bounds.north < s || bounds.south > n) return false;
    return [-360, 0, 360].some((k) => bounds.west + k <= e && bounds.east + k >= w);
  });
}
