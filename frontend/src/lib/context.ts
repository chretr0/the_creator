/**
 * Context layers ported from gods-eye-view: boundaries, submarine cables, hazards, OSM power
 * infrastructure, satellite imagery, point weather, place search and the data-credits registry.
 * Everything here is context for a cell or scenario; none of it feeds the resource model.
 */
import type { Feature, FeatureCollection, Geometry, LineString, MultiLineString, Point } from "geojson";

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  // Our own /api files can change when the prepare scripts re-run, so always revalidate them.
  const r = await fetch(url, { signal, cache: url.startsWith("/api/") ? "no-cache" : "default" });
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

/* ---------------- Regions / boundaries ---------------- */

export type RegionLevel = "country" | "admin1" | "us_county";
export type RegionProps = {
  id: string;
  name: string;
  country: string;
  level: RegionLevel;
  iso?: string;
  iso2?: string;
  state?: string;
  bbox: [number, number, number, number];
};
export type BoundaryLayerId = "countries" | "admin1" | "us_counties";
export type RegionRef = { id: string; name: string; country: string; level: RegionLevel };
export type RegionLocate = { country: RegionRef | null; admin1: RegionRef | null; county?: RegionRef | null; note: string };
export type SearchEntry = {
  id: string;
  name: string;
  level: RegionLevel;
  country: string | null;
  state: string | null;
  bbox: [number, number, number, number];
  label: [number, number];
};

export const loadBoundaries = (id: BoundaryLayerId, signal?: AbortSignal) =>
  getJson<FeatureCollection<Geometry, RegionProps>>(`/api/boundaries/${id}`, signal);
export const locateRegion = (lat: number, lon: number, signal?: AbortSignal) =>
  getJson<RegionLocate>(`/api/regions/locate?latitude=${lat}&longitude=${lon}`, signal);
export const loadSearchIndex = (signal?: AbortSignal) => getJson<SearchEntry[]>("/api/regions/search-index", signal);

/* ---------------- Submarine cables ---------------- */

export type CableProps = { id: string; featureId: string; name: string; colour: string | null; url: string };
export type LandingProps = { id: string; name: string; isTbd: boolean; lon: number; lat: number; url: string };
export type CablePath = { id: string; path: [number, number][]; cable: CableProps };
export type LandingPoint = Feature<Point, LandingProps> & { id: string };

export async function loadCables(signal?: AbortSignal) {
  const [cables, landing] = await Promise.all([
    getJson<FeatureCollection<MultiLineString | LineString, CableProps>>("/api/cables/cables", signal),
    getJson<FeatureCollection<Point, LandingProps>>("/api/cables/landing_points", signal),
  ]);
  const paths: CablePath[] = [];
  for (const f of cables.features) {
    const lines = f.geometry.type === "MultiLineString" ? f.geometry.coordinates : [f.geometry.coordinates];
    lines.forEach((line, i) =>
      paths.push({ id: `${f.properties.featureId}:${i}`, path: line as [number, number][], cable: f.properties }),
    );
  }
  return { paths, landing: landing.features as LandingPoint[] };
}

export function hexToRgb(hex: string | null | undefined, fallback: [number, number, number]): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex ?? "");
  if (!m) return fallback;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/* ---------------- Hazards ---------------- */

export type RegionTags = { country: string | null; countryId: string | null; admin1: string | null; admin1Id: string | null };
export type HazardSource = {
  provider: string;
  product?: string;
  attribution?: string;
  licence?: string;
  evidenceType?: string;
  retrievedAt?: string;
  stale?: boolean;
  notes?: string;
  available?: boolean;
  reason?: string;
};
export type Earthquake = RegionTags & {
  id: string;
  lon: number;
  lat: number;
  depthKm: number | null;
  magnitude: number | null;
  magType: string | null;
  place: string | null;
  time: number;
  status: string | null;
  tsunami: boolean;
  url: string | null;
};
export type Fire = RegionTags & {
  id: string;
  lon: number;
  lat: number;
  acqDate: string;
  acqTime: string;
  confidence: string | null;
  frpMw: number | null;
  dayNight: string | null;
  satellite: string | null;
};
export type Hazard<T> = { source: HazardSource; records: T[] };

export const loadEarthquakes = (signal?: AbortSignal) => getJson<Hazard<Earthquake>>("/api/hazards/earthquakes", signal);
export const loadFires = (b: Bounds, signal?: AbortSignal) =>
  getJson<Hazard<Fire>>(
    `/api/hazards/fires?west=${b.west.toFixed(2)}&south=${b.south.toFixed(2)}&east=${b.east.toFixed(2)}&north=${b.north.toFixed(2)}`,
    signal,
  );

/* ---------------- OSM power ---------------- */

export type PowerProps = {
  kind: "plant" | "substation" | "line" | "cable";
  name: string | null;
  operator: string | null;
  owner: string | null;
  voltageKv: number[];
  voltageRaw: string | null;
  plantSource: string | null;
  outputRaw: string | null;
  outputKw: number | null;
  osmUrl: string;
};
export type PowerFeature = Feature<Point | LineString, PowerProps> & { id: string };
export type PowerResult = {
  features: PowerFeature[];
  bbox: [number, number, number, number];
  source: HazardSource;
  centre: { lat: number; lon: number };
  radiusKm: number;
};
export async function loadPower(lat: number, lon: number, radiusKm = 10, signal?: AbortSignal): Promise<PowerResult> {
  const r = await getJson<Omit<PowerResult, "centre" | "radiusKm">>(
    `/api/osm/power?latitude=${lat}&longitude=${lon}&radiusKm=${radiusKm}`,
    signal,
  );
  return { ...r, centre: { lat, lon }, radiusKm };
}

/** Colour lines by highest voltage class (display convention, similar to OpenInfraMap). */
export function voltageColour(kv: number[]): [number, number, number] {
  const v = Math.max(0, ...kv);
  if (v >= 330) return [220, 38, 38];
  if (v >= 220) return [234, 88, 12];
  if (v >= 110) return [202, 138, 4];
  if (v >= 50) return [101, 163, 13];
  if (v > 0) return [37, 99, 235];
  return [100, 116, 139];
}

/* ---------------- Imagery (NASA GIBS + CMR) ---------------- */

export type ImageryProductId = "VIIRS" | "S30" | "L30";
export const IMAGERY_PRODUCTS: Record<
  ImageryProductId,
  { label: string; sensor: string; gibsLayer: string; maxLevel: number; format: "jpg" | "png"; resolution: string; cmr?: string }
> = {
  VIIRS: {
    label: "VIIRS daily true colour",
    sensor: "VIIRS NOAA-21",
    gibsLayer: "VIIRS_NOAA21_CorrectedReflectance_TrueColor",
    maxLevel: 9,
    format: "jpg",
    resolution: "250 m",
  },
  S30: {
    label: "HLS Sentinel-2 (S30)",
    sensor: "Sentinel-2 via HLS",
    gibsLayer: "HLS_S30_Nadir_BRDF_Adjusted_Reflectance",
    maxLevel: 12,
    format: "png",
    resolution: "30 m",
    cmr: "C2021957295-LPCLOUD",
  },
  L30: {
    label: "HLS Landsat 8/9 (L30)",
    sensor: "Landsat 8/9 via HLS",
    gibsLayer: "HLS_L30_Nadir_BRDF_Adjusted_Reflectance",
    maxLevel: 12,
    format: "png",
    resolution: "30 m",
    cmr: "C2021957657-LPCLOUD",
  },
};
export type ImageryState = { product: ImageryProductId; date: string; opacity: number };

export function gibsTiles(product: ImageryProductId, date: string): string[] {
  const p = IMAGERY_PRODUCTS[product];
  return ["a", "b", "c"].map(
    (s) =>
      `https://gibs-${s}.earthdata.nasa.gov/wmts/epsg3857/best/${p.gibsLayer}/default/${date}/GoogleMapsCompatible_Level${p.maxLevel}/{z}/{y}/{x}.${p.format}`,
  );
}

export type ImageryDay = { date: string; granules: number; cloudMin: number | null; cloudMax: number | null };

/** HLS acquisition days over a box in the last `days` days, newest first (CMR granule search). */
export async function searchImageryDays(product: "S30" | "L30", b: Bounds, days = 30, signal?: AbortSignal) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400e3);
  const url =
    `https://cmr.earthdata.nasa.gov/search/granules.umm_json?collection_concept_id=${IMAGERY_PRODUCTS[product].cmr}` +
    `&bounding_box=${b.west.toFixed(3)},${b.south.toFixed(3)},${b.east.toFixed(3)},${b.north.toFixed(3)}` +
    `&temporal=${start.toISOString()},${end.toISOString()}&sort_key=-start_date&page_size=200`;
  type Umm = {
    items?: {
      umm?: {
        TemporalExtent?: { RangeDateTime?: { BeginningDateTime?: string } };
        AdditionalAttributes?: { Name: string; Values: string[] }[];
      };
    }[];
  };
  const body = await getJson<Umm>(url, signal);
  const byDay = new Map<string, ImageryDay>();
  for (const item of body.items ?? []) {
    const begin = item.umm?.TemporalExtent?.RangeDateTime?.BeginningDateTime;
    if (!begin) continue;
    const date = begin.slice(0, 10);
    const cloudRaw = item.umm?.AdditionalAttributes?.find((a) => a.Name === "CLOUD_COVERAGE")?.Values?.[0];
    const cloud = cloudRaw !== undefined && Number.isFinite(Number(cloudRaw)) ? Number(cloudRaw) : null;
    const d = byDay.get(date) ?? { date, granules: 0, cloudMin: null, cloudMax: null };
    d.granules += 1;
    if (cloud !== null) {
      d.cloudMin = d.cloudMin === null ? cloud : Math.min(d.cloudMin, cloud);
      d.cloudMax = d.cloudMax === null ? cloud : Math.max(d.cloudMax, cloud);
    }
    byDay.set(date, d);
  }
  return [...byDay.values()].sort((a, b) => b.date.localeCompare(a.date));
}

export const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/* ---------------- Point weather (Open-Meteo) ---------------- */

export type ForecastHour = { time: string; tempC: number | null; precipProb: number | null; wind100m: number | null };
export type ForecastDay = { date: string; code: number | null; maxC: number | null; minC: number | null; precipMm: number | null };
export type PointForecast = {
  /** Local time at the location, ISO without offset. */
  time: string;
  timezone: string;
  current: {
    tempC: number | null;
    feelsLikeC: number | null;
    humidity: number | null;
    code: number | null;
    isDay: boolean;
    windSpeed: number | null;
    windDirection: number | null;
  };
  hours: ForecastHour[];
  days: ForecastDay[];
};

/** Current conditions, the next 24 hours and a three-day outlook at a point (Open-Meteo best-match model). */
export async function loadForecast(lat: number, lon: number, signal?: AbortSignal): Promise<PointForecast> {
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}` +
    `&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m,wind_direction_10m` +
    `&hourly=temperature_2m,precipitation_probability,wind_speed_100m&forecast_hours=24` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum&forecast_days=3` +
    `&wind_speed_unit=ms&timezone=auto`;
  type Arr = (number | null)[] | undefined;
  type R = {
    timezone?: string;
    current?: {
      time: string;
      temperature_2m?: number;
      apparent_temperature?: number;
      relative_humidity_2m?: number;
      weather_code?: number;
      is_day?: number;
      wind_speed_10m?: number;
      wind_direction_10m?: number;
    };
    hourly?: { time?: string[]; temperature_2m?: Arr; precipitation_probability?: Arr; wind_speed_100m?: Arr };
    daily?: { time?: string[]; weather_code?: Arr; temperature_2m_max?: Arr; temperature_2m_min?: Arr; precipitation_sum?: Arr };
  };
  const r = await getJson<R>(url, signal);
  const at = (a: Arr, i: number) => (typeof a?.[i] === "number" ? (a[i] as number) : null);
  const c = r.current;
  return {
    time: c?.time ?? "",
    timezone: r.timezone ?? "UTC",
    current: {
      tempC: c?.temperature_2m ?? null,
      feelsLikeC: c?.apparent_temperature ?? null,
      humidity: c?.relative_humidity_2m ?? null,
      code: c?.weather_code ?? null,
      isDay: c?.is_day !== 0,
      windSpeed: c?.wind_speed_10m ?? null,
      windDirection: c?.wind_direction_10m ?? null,
    },
    hours: (r.hourly?.time ?? []).map((time, i) => ({
      time,
      tempC: at(r.hourly?.temperature_2m, i),
      precipProb: at(r.hourly?.precipitation_probability, i),
      wind100m: at(r.hourly?.wind_speed_100m, i),
    })),
    days: (r.daily?.time ?? []).map((date, i) => ({
      date,
      code: at(r.daily?.weather_code, i),
      maxC: at(r.daily?.temperature_2m_max, i),
      minC: at(r.daily?.temperature_2m_min, i),
      precipMm: at(r.daily?.precipitation_sum, i),
    })),
  };
}

export type WeatherKind = "clear" | "partly" | "cloudy" | "fog" | "drizzle" | "rain" | "snow" | "storm";
/** WMO weather interpretation code → a short label and an icon family. */
export function describeWeather(code: number | null): { label: string; kind: WeatherKind } {
  if (code === null) return { label: "Unknown", kind: "cloudy" };
  if (code === 0) return { label: "Clear", kind: "clear" };
  if (code === 1) return { label: "Mostly clear", kind: "partly" };
  if (code === 2) return { label: "Partly cloudy", kind: "partly" };
  if (code === 3) return { label: "Overcast", kind: "cloudy" };
  if (code === 45 || code === 48) return { label: "Fog", kind: "fog" };
  if (code >= 51 && code <= 57) return { label: "Drizzle", kind: "drizzle" };
  if (code >= 61 && code <= 67) return { label: code >= 65 ? "Heavy rain" : "Rain", kind: "rain" };
  if (code >= 71 && code <= 77) return { label: "Snow", kind: "snow" };
  if (code >= 80 && code <= 82) return { label: "Showers", kind: "rain" };
  if (code === 85 || code === 86) return { label: "Snow showers", kind: "snow" };
  if (code >= 95) return { label: "Thunderstorm", kind: "storm" };
  return { label: "Cloudy", kind: "cloudy" };
}

/** 0–360° → the nearest of eight compass points. */
export const compass = (deg: number) => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round((((deg % 360) + 360) % 360) / 45) % 8];

/* ---------------- Place search ---------------- */

export type Bounds = { west: number; south: number; east: number; north: number };
export type PlaceHit = {
  key: string;
  label: string;
  detail: string;
  lat: number;
  lon: number;
  bbox?: [number, number, number, number];
  source: "coordinates" | "local" | "photon";
};

/** "48.85, 2.35" or "48.85 2.35" (latitude first). */
export function parseCoordinates(q: string): PlaceHit | null {
  const m = /^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(q);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { key: `coord:${lat},${lon}`, label: `${lat}, ${lon}`, detail: "Coordinates (lat, lon)", lat, lon, source: "coordinates" };
}

const LEVEL_LABEL: Record<RegionLevel, string> = { country: "Country", admin1: "Region", us_county: "County" };

/** Keyless search over bundled region names (no network). Prefix matches rank first, then larger units. */
export function searchLocal(index: SearchEntry[], q: string, limit = 6): PlaceHit[] {
  const needle = q.trim().toLocaleLowerCase();
  if (needle.length < 2) return [];
  const rank = { country: 0, admin1: 1, us_county: 2 } as const;
  return index
    .map((e) => {
      const name = e.name.toLocaleLowerCase();
      const score = name === needle ? 0 : name.startsWith(needle) ? 1 : name.includes(needle) ? 2 : -1;
      return { e, score };
    })
    .filter((x) => x.score >= 0)
    .sort((a, b) => a.score - b.score || rank[a.e.level] - rank[b.e.level] || a.e.name.localeCompare(b.e.name))
    .slice(0, limit)
    .map(({ e }) => ({
      key: e.id,
      label: e.name,
      detail: [LEVEL_LABEL[e.level], e.state, e.level !== "country" ? e.country : null].filter(Boolean).join(" · "),
      lat: e.label[1],
      lon: e.label[0],
      bbox: e.bbox,
      source: "local" as const,
    }));
}

/** Photon (komoot) fallback for other place names. Fair-use public service: call on submit only. */
export async function searchPhoton(q: string, signal?: AbortSignal): Promise<PlaceHit[]> {
  type P = {
    features: {
      geometry: { coordinates: [number, number] };
      properties: { osm_id: number; osm_type: string; name?: string; city?: string; state?: string; country?: string; type?: string; extent?: [number, number, number, number] };
    }[];
  };
  const r = await getJson<P>(`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=5&lang=en`, signal);
  return r.features.map((f) => {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    // Photon extent is [minLon, maxLat, maxLon, minLat].
    const bbox = p.extent ? ([p.extent[0], p.extent[3], p.extent[2], p.extent[1]] as [number, number, number, number]) : undefined;
    return {
      key: `photon:${p.osm_type}${p.osm_id}`,
      label: p.name ?? q,
      detail: [p.type, p.city, p.state, p.country].filter(Boolean).join(" · "),
      lat,
      lon,
      bbox,
      source: "photon" as const,
    };
  });
}

/* ---------------- Data credits ---------------- */

export type SourceCredit = {
  id: string;
  name: string;
  provider?: string;
  licence: string;
  attribution: string;
  evidenceType: string;
  retrievedAt?: string | null;
  url?: string | null;
  layers: string[];
  limitations?: string[];
  notes?: string;
  commercialUse?: boolean;
};
export const loadSources = (signal?: AbortSignal) => getJson<SourceCredit[]>("/api/sources", signal);
