/**
 * Pure Moon helpers: gazetteer search, coordinate parsing, crater-sized map boxes and formatting.
 * Every length here is on the Moon sphere (R = 1737.4 km); nothing uses Earth metres.
 */
import { MOON_RADIUS_KM } from "../bodies/moon";
import { distanceKm } from "../lib/bodyGeometry";
import { MERCATOR_MAX_LAT, normaliseLongitude } from "../lib/h3grid";
import type { GazetteerPlace, KeepoutFeature, MoonSite } from "./api";

const DEG = 180 / Math.PI;

export type MoonPlaceHit = {
  key: string;
  label: string;
  detail: string;
  lat: number;
  lon: number;
  /** [west, south, east, north] to fit; absent → fly to a fixed zoom. */
  bbox?: [number, number, number, number];
  /** The point lies beyond Web Mercator's ±85.05° edge, so the map can only show the nearest latitude. */
  beyondMap: boolean;
  source: "coordinates" | "gazetteer";
};

/* ---------------- Formatting ---------------- */

export const UNKNOWN = "Unknown";

/** "0.6742° N, 23.4731° E" (longitude positive east). */
export function formatLatLon(lat: number | null | undefined, lon: number | null | undefined, digits = 4): string {
  if (lat == null || lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return UNKNOWN;
  return `${Math.abs(lat).toFixed(digits)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(digits)}° ${lon >= 0 ? "E" : "W"}`;
}

/** A distance on the surface: metres below 1 km, one decimal below 10 km, whole km above. */
export function formatDistanceKm(km: number | null | undefined): string {
  if (km == null || !Number.isFinite(km)) return UNKNOWN;
  if (km < 1) return `${Math.round(km * 1000).toLocaleString()} m`;
  if (km < 10) return `${km.toFixed(1)} km`;
  return `${Math.round(km).toLocaleString()} km`;
}

/** Areas from 0.01 km² up to whole basins. */
export function formatAreaKm2(km2: number | null | undefined): string {
  if (km2 == null || !Number.isFinite(km2)) return UNKNOWN;
  if (km2 < 1) return `${km2.toFixed(3)} km²`;
  if (km2 < 10) return `${km2.toFixed(2)} km²`;
  if (km2 < 100) return `${km2.toFixed(1)} km²`;
  return `${Math.round(km2).toLocaleString()} km²`;
}

/** A value with its unit, or "Unknown" — never 0 for a missing value. */
export function formatMeasure(v: number | null | undefined, unit?: string | null, maxDigits = 4): string {
  if (v == null || !Number.isFinite(v)) return UNKNOWN;
  const a = Math.abs(v);
  const s =
    a >= 1000
      ? Math.round(v).toLocaleString()
      : a >= 100
        ? v.toFixed(0)
        : a >= 10
          ? v.toFixed(1)
          : a === 0
            ? "0"
            : v.toPrecision(Math.min(maxDigits, 3));
  return unit ? `${s} ${unit}` : s;
}

/** IAU feature types read "Crater, craters"; the singular is enough for a label. */
export function featureTypeLabel(type: string | null | undefined): string {
  if (!type) return "Named feature";
  return type.split(",")[0].trim() || "Named feature";
}

/** "Crater · 21 km · LAC-144" for a gazetteer row. */
export function placeDetail(p: Pick<GazetteerPlace, "type" | "diameterKm" | "quad">): string {
  const parts = [featureTypeLabel(p.type)];
  if (p.diameterKm != null && Number.isFinite(p.diameterKm)) parts.push(formatDistanceKm(p.diameterKm));
  if (p.quad) parts.push(p.quad);
  return parts.join(" · ");
}

/* ---------------- Map boxes ---------------- */

/** Clamp a latitude to what Web Mercator can show. */
export const clampToMap = (lat: number) => Math.max(-MERCATOR_MAX_LAT, Math.min(MERCATOR_MAX_LAT, lat));

/**
 * A [west, south, east, north] box roughly the size of a feature of `diameterKm` on the Moon, with a
 * margin, so fitting it frames the whole crater. Kilometres → degrees with R = 1737.4 km. Longitudes
 * are left unwrapped (may pass ±180) so a box across the antimeridian stays one box; latitudes are
 * clamped to the map's ±85.05° edge.
 */
export function placeBBox(
  lat: number,
  lon: number,
  diameterKm: number,
  radiusKm = MOON_RADIUS_KM,
  margin = 1.25,
  minHalfKm = 4,
): [number, number, number, number] {
  const halfKm = Math.max(minHalfKm, (diameterKm / 2) * margin);
  const dLat = (halfKm / radiusKm) * DEG;
  const cos = Math.max(0.02, Math.cos(clampToMap(lat) / DEG));
  const dLon = Math.min(180, dLat / cos);
  return [lon - dLon, clampToMap(lat - dLat), lon + dLon, clampToMap(lat + dLat)];
}

/* ---------------- Search ---------------- */

/** Lower case without accents, so "schrodinger" finds "Schrödinger". */
export function foldName(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase().trim();
}

const COORD_RE = /^\s*(-?\d+(?:\.\d+)?)\s*°?\s*([NS])?\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*°?\s*([EW])?\s*$/i;

/**
 * "lat, lon" in degrees (latitude first). Accepts N/S/E/W suffixes and 0–360 east longitudes
 * (the PDS convention), which are normalised to ±180.
 */
export function parseMoonCoordinates(q: string): MoonPlaceHit | null {
  const m = COORD_RE.exec(q);
  if (!m) return null;
  let lat = Number(m[1]);
  let lon = Number(m[3]);
  if (m[2]) lat = Math.abs(lat) * (m[2].toUpperCase() === "S" ? -1 : 1);
  if (m[4]) lon = Math.abs(lon) * (m[4].toUpperCase() === "W" ? -1 : 1);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || lon < -180 || lon > 360) return null;
  lon = normaliseLongitude(lon);
  return {
    key: `coord:${lat},${lon}`,
    label: formatLatLon(lat, lon, 3),
    detail: "Coordinates (lat, lon east)",
    lat,
    lon,
    beyondMap: Math.abs(lat) > MERCATOR_MAX_LAT,
    source: "coordinates",
  };
}

export type IndexedPlace = { place: GazetteerPlace; folded: string };

/** Pre-fold names once; the gazetteer has ~9,000 rows. */
export function indexPlaces(places: GazetteerPlace[]): IndexedPlace[] {
  return places
    .filter((p) => p && typeof p.name === "string" && Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .map((place) => ({ place, folded: foldName(place.name) }));
}

/** 0 exact, 1 prefix, 2 a word starts with it, 3 contains, -1 no match. */
function matchScore(name: string, needle: string): number {
  if (name === needle) return 0;
  if (name.startsWith(needle)) return 1;
  if (name.includes(` ${needle}`) || name.includes(`-${needle}`)) return 2;
  return name.includes(needle) ? 3 : -1;
}

export function placeToHit(p: GazetteerPlace): MoonPlaceHit {
  const lon = normaliseLongitude(p.lon);
  return {
    key: `place:${p.id ?? p.name}`,
    label: p.name,
    detail: placeDetail(p),
    lat: p.lat,
    lon,
    bbox: p.diameterKm != null && p.diameterKm > 0 ? placeBBox(p.lat, lon, p.diameterKm) : undefined,
    beyondMap: Math.abs(p.lat) > MERCATOR_MAX_LAT,
    source: "gazetteer",
  };
}

/**
 * Local gazetteer search: exact > prefix > word-prefix > contains, then bigger features first, then
 * alphabetical. Needs at least two characters.
 */
export function searchGazetteer(index: IndexedPlace[], q: string, limit = 8): MoonPlaceHit[] {
  const needle = foldName(q);
  if (needle.length < 2) return [];
  const scored: { p: GazetteerPlace; score: number; folded: string }[] = [];
  for (const { place, folded } of index) {
    const score = matchScore(folded, needle);
    if (score >= 0) scored.push({ p: place, score, folded });
  }
  scored.sort(
    (a, b) =>
      a.score - b.score ||
      (b.p.diameterKm ?? -1) - (a.p.diameterKm ?? -1) ||
      a.folded.localeCompare(b.folded),
  );
  return scored.slice(0, limit).map(({ p }) => placeToHit(p));
}

/** Hits for a query: coordinates win; otherwise the gazetteer (empty until it has loaded). */
export function moonSearch(index: IndexedPlace[] | null, q: string, limit = 8): MoonPlaceHit[] {
  const coord = parseMoonCoordinates(q);
  if (coord) return [coord];
  return index ? searchGazetteer(index, q, limit) : [];
}

/* ---------------- Cells ---------------- */

/** [west, south, east, north] of a polygon ring of [lat, lon] pairs (h3 order), unwrapped across ±180. */
export function ringBBox(ring: [number, number][]): [number, number, number, number] {
  const lats = ring.map((p) => p[0]);
  let lons = ring.map((p) => p[1]);
  if (Math.max(...lons) - Math.min(...lons) > 180) lons = lons.map((l) => (l < 0 ? l + 360 : l));
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

/** "No landing within 2.0 km of a heritage landing site" style labels for keep-out rules. */
export function keepoutRuleLabel(rule: string | null | undefined): string {
  if (rule === "heritage_landing") return "heritage landing site";
  if (rule === "heritage_impact") return "heritage impact site";
  return "heritage site";
}

/* ---------------- Keep-out ---------------- */

/** A keep-out ring that contains a point, with the point's distance from the protected site. */
export type KeepoutHit = { siteId: string; siteName: string; rule: string; radiusM: number; distanceKm: number };

/**
 * [lon, lat] of the centre of a geodesic circle drawn as a ring: the normalised mean of its vertices
 * (exact for evenly spaced vertices; the repeated closing vertex is skipped). Null for an empty ring.
 */
export function ringCentre(ring: [number, number][] | null | undefined): [number, number] | null {
  if (!ring?.length) return null;
  const n = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.length - 1 : ring.length;
  let x = 0;
  let y = 0;
  let z = 0;
  for (let i = 0; i < n; i++) {
    const lon = ring[i][0] / DEG;
    const lat = ring[i][1] / DEG;
    x += Math.cos(lat) * Math.cos(lon);
    y += Math.cos(lat) * Math.sin(lon);
    z += Math.sin(lat);
  }
  if (!Number.isFinite(x + y + z) || Math.hypot(x, y, z) === 0) return null;
  return [normaliseLongitude(Math.atan2(y, x) * DEG), Math.atan2(z, Math.hypot(x, y)) * DEG];
}

/**
 * The keep-out rings that contain the point (lat, lon), nearest site first: a great-circle test on the
 * Moon sphere against each ring's site (from `sites`, else the ring's own centre) and radius. This is
 * the point itself, not the centre of its H3 cell. Null until the rings have loaded.
 */
export function keepoutHitsAt(
  lat: number,
  lon: number,
  rings: KeepoutFeature[] | null,
  sites: MoonSite[] | null,
  radiusKm = MOON_RADIUS_KM,
): KeepoutHit[] | null {
  if (!rings) return null;
  const siteAt = new Map<string, number[]>();
  for (const s of sites ?? []) if (s.properties?.id && s.geometry?.coordinates) siteAt.set(s.properties.id, s.geometry.coordinates);
  const hits: KeepoutHit[] = [];
  for (const f of rings) {
    const p = f.properties;
    if (!p || !Number.isFinite(p.radiusM)) continue;
    const centre = siteAt.get(p.siteId) ?? ringCentre(f.geometry?.coordinates?.[0] as [number, number][] | undefined);
    if (!centre) continue;
    const d = distanceKm(lat, lon, centre[1], centre[0], radiusKm);
    if (d * 1000 <= p.radiusM) hits.push({ siteId: p.siteId, siteName: p.siteName, rule: p.rule, radiusM: p.radiusM, distanceKm: d });
  }
  return hits.sort((a, b) => a.distanceKm - b.distanceKm);
}
