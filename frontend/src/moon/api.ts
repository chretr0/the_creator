/**
 * Typed client for the Moon endpoints (/api/moon/*). Every value the server leaves out stays null here:
 * the UI shows "Unknown", never 0.
 */
import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";
import type { SourceCredit } from "../lib/context";

/** An HTTP error that keeps its status, so a 503 ("not prepared") can be told apart from a failure. */
export class MoonApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "MoonApiError";
  }
}

/** The prepare scripts named in "not prepared" hints. */
export const PREPARE_REFERENCE_SCRIPT = "scripts/moon/prepare_moon_reference.py";
export const PREPARE_ELEVATION_SCRIPT = "scripts/moon/prepare_moon_elevation.py";

export const isNotPrepared = (e: unknown): boolean => e instanceof MoonApiError && e.status === 503;

async function readError(r: Response): Promise<MoonApiError> {
  let detail = `${r.status} ${r.statusText}`.trim();
  try {
    const b = await r.json();
    if (typeof b?.detail === "string") detail = b.detail;
  } catch {
    /* not JSON */
  }
  return new MoonApiError(detail, r.status);
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  // Prepared files change whenever the prepare scripts re-run: always revalidate.
  const r = await fetch(url, { signal, cache: "no-cache" });
  if (!r.ok) throw await readError(r);
  return (await r.json()) as T;
}

async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) throw await readError(r);
  return (await r.json()) as T;
}

/* ---------------- Manifest & sources ---------------- */

export type MoonSourceRecord = {
  id: string;
  name: string;
  provider?: string;
  licence?: string;
  attribution?: string;
  evidenceType?: string;
  url?: string | null;
  retrievedAt?: string | null;
  limitations?: string[];
  commercialUse?: boolean;
};

export type MoonManifestLayer = { id: string; file: string; source: string; count: number | null; available?: boolean };

export type MoonManifest = {
  body: "moon";
  generatedAt?: string;
  sources: Record<string, MoonSourceRecord>;
  layers: MoonManifestLayer[];
};

/* ---------------- Records ---------------- */

export type MoonSiteKind = "crewed_landing" | "soft_landing" | "rover" | "impact" | "retroreflector" | "other";

export type MoonSiteProps = {
  id: string;
  name: string;
  mission: string | null;
  kind: MoonSiteKind;
  date: string | null;
  dateNote: string | null;
  elevationM: number | null;
  uncertainty: string | null;
  heritage: "landing" | "impact" | null;
  evidenceType: string;
  sourceId: string;
  note?: string | null;
};
export type MoonSite = Feature<Point, MoonSiteProps>;

export type MissionKind = "artemis_region" | "planned_mission";
export type MissionProps = {
  id: string;
  name: string;
  kind: MissionKind;
  mission: string | null;
  target: string;
  date: string | null;
  asOf: string | null;
  evidenceType: string;
  approximate: boolean;
  note: string | null;
  sourceId: string;
};
export type MissionFeature = Feature<Point | Polygon | MultiPolygon | null, MissionProps>;

export type GazetteerPlace = {
  id: string;
  name: string;
  type: string;
  diameterKm: number | null;
  lat: number;
  lon: number;
  quad: string | null;
  approved: string | null;
  origin: string | null;
  link: string | null;
};

export type MareProps = { id: string; name: string };
export type MareFeature = Feature<Polygon | MultiPolygon, MareProps>;

export type KeepoutProps = {
  id: string;
  siteId: string;
  siteName: string;
  radiusM: number;
  rule: "heritage_landing" | "heritage_impact";
  sourceId: string;
  evidenceType: string;
};
export type KeepoutFeature = Feature<Polygon, KeepoutProps>;

/* ---------------- Cell context ---------------- */

export type MoonCellContext = {
  h3Id: string;
  body: "moon";
  centre: { latitude: number; longitude: number };
  nearestPlaces: {
    id: string;
    name: string;
    type: string | null;
    diameterKm: number | null;
    quad: string | null;
    latitude: number;
    longitude: number;
    distanceKm: number;
    within: boolean;
  }[];
  nearbySites: {
    id: string;
    name: string;
    mission: string | null;
    kind: MoonSiteKind | null;
    date: string | null;
    heritage?: "landing" | "impact" | null;
    latitude?: number;
    longitude?: number;
    distanceKm: number;
  }[];
  keepout: { siteId: string; siteName: string; rule: string; radiusM: number; distanceKm: number; sourceId?: string }[];
  mare: { id: string; name: string } | null;
  quad: string | null;
};

/* ---------------- H3 layers ---------------- */

export type MoonH3Layer = {
  id: string;
  name: string;
  unit: string;
  description?: string;
  sourceId: string;
  evidenceType?: string;
  maxResolution: number;
  nativeResolutionKm?: number | null;
  aggregation?: string;
  range?: [number, number] | null;
  palette?: string;
  limitations?: string[];
  /** How `range` was chosen, e.g. "p1-p99" (so the legend ends read ≤ / ≥). */
  rangeMethod?: string;
  /** True minimum and maximum of the data, when published. */
  extent?: [number, number] | null;
  available?: boolean;
};

export type MoonH3Values = {
  layerId: string;
  unit: string;
  values: Record<string, number | null>;
  servedResolution: Record<string, number>;
};

/** The backend caps one values request at this many cells. */
export const MAX_H3_CELLS = 20000;

/* ---------------- Client ---------------- */

export const moonApi = {
  manifest: (signal?: AbortSignal) => getJson<MoonManifest>("/api/moon", signal),
  sources: (signal?: AbortSignal) => getJson<SourceCredit[]>("/api/moon/sources", signal),
  places: (signal?: AbortSignal) => getJson<GazetteerPlace[]>("/api/moon/layers/moon_places", signal),
  sites: (signal?: AbortSignal) => getJson<FeatureCollection<Point, MoonSiteProps>>("/api/moon/layers/moon_sites", signal),
  missions: (signal?: AbortSignal) =>
    getJson<FeatureCollection<Point | Polygon | MultiPolygon | null, MissionProps>>("/api/moon/layers/moon_missions", signal),
  mare: (signal?: AbortSignal) => getJson<FeatureCollection<Polygon | MultiPolygon, MareProps>>("/api/moon/layers/moon_mare", signal),
  keepout: (signal?: AbortSignal) => getJson<FeatureCollection<Polygon, KeepoutProps>>("/api/moon/keepout", signal),
  cellContext: (h3: string, signal?: AbortSignal) =>
    getJson<MoonCellContext>(`/api/moon/cells/${encodeURIComponent(h3)}/context`, signal),
  h3Layers: (signal?: AbortSignal) => getJson<MoonH3Layer[] | { layers: MoonH3Layer[] }>("/api/moon/h3", signal).then(asLayerList),
  h3Values: (layerId: string, cells: string[], signal?: AbortSignal) =>
    postJson<MoonH3Values>(`/api/moon/h3/${encodeURIComponent(layerId)}`, { cells: cells.slice(0, MAX_H3_CELLS) }, signal),
};

/** GET /api/moon/h3 returns the layers list; accept the whole layers.json object too. */
export function asLayerList(x: MoonH3Layer[] | { layers: MoonH3Layer[] } | null | undefined): MoonH3Layer[] {
  if (Array.isArray(x)) return x;
  return Array.isArray(x?.layers) ? x.layers : [];
}
