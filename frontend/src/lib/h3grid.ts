/**
 * Viewport-bounded H3 cell generation (CLAUDE.mapping.md sections 3 and 5).
 *
 * Display resolution is chosen from an estimated on-screen cell count, never from zoom alone,
 * and is capped at the simulation resolution. Changing it never changes the simulation:
 * projects always reference their resolution-6 cell.
 */
import {
  POLYGON_TO_CELLS_FLAGS,
  cellToChildren,
  cellToParent,
  getHexagonAreaAvg,
  getResolution,
  getRes0Cells,
  latLngToCell,
  polygonToCellsExperimental,
  UNITS,
} from "h3-js";

export const SIMULATION_RESOLUTION = 6;
export const MAX_DISPLAY_RESOLUTION = SIMULATION_RESOLUTION;
/** Target visible cells; a performance heuristic to benchmark, not a guarantee. */
export const DEFAULT_CELL_BUDGET = 5000;
/** Resolutions at or below this are cheap enough to enumerate globally and cache. */
const OVERVIEW_MAX_RESOLUTION = 2;
/** Web Mercator cannot display beyond this latitude. */
export const MERCATOR_MAX_LAT = 85.0511;
/** Keep each polygonToCells query small so edges stay unambiguous. */
const MAX_CHUNK_DEGREES = 60;
const EARTH_RADIUS_KM = 6371.0088;

export type Bounds = {
  /** May be < -180 or > 180 when the map shows wrapped world copies. */
  west: number;
  south: number;
  east: number;
  north: number;
};

export type ViewportCells = {
  resolution: number;
  cells: string[];
  /** True when the whole-world overview set was returned. */
  overview: boolean;
};

const toRad = (deg: number) => (deg * Math.PI) / 180;

/** Normalise longitude to [-180, 180). In-range values are returned untouched (bit-exact). */
export function normaliseLongitude(lng: number): number {
  if (lng >= -180 && lng < 180) return lng;
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

export function simulationCell(latitude: number, longitude: number): string {
  if (!(latitude >= -90 && latitude <= 90)) throw new RangeError(`latitude ${latitude} out of range`);
  return latLngToCell(latitude, normaliseLongitude(longitude), SIMULATION_RESOLUTION);
}

/** The cell at `resolution` (0–6) containing a point: the hexagon drawn there at that display resolution. */
export function displayCell(latitude: number, longitude: number, resolution: number): string {
  if (!(latitude >= -90 && latitude <= 90)) throw new RangeError(`latitude ${latitude} out of range`);
  const res = Math.max(0, Math.min(SIMULATION_RESOLUTION, Math.round(resolution)));
  return latLngToCell(latitude, normaliseLongitude(longitude), res);
}

/** True when the resolution-6 cell `child` lies inside `cell` (or is it). */
export function cellContains(cell: string, child: string): boolean {
  const res = getResolution(cell);
  return res === getResolution(child) ? cell === child : cellToParent(child, res) === cell;
}

function clampBounds(b: Bounds): Bounds {
  const south = Math.max(-MERCATOR_MAX_LAT, Math.min(b.south, b.north));
  const north = Math.min(MERCATOR_MAX_LAT, Math.max(b.south, b.north));
  const width = Math.min(360, Math.max(0, b.east - b.west));
  return { west: b.west, east: b.west + width, south, north };
}

/** Area of a lat/lng rectangle on a sphere, in km². */
export function boundsAreaKm2(b: Bounds): number {
  const c = clampBounds(b);
  return (
    EARTH_RADIUS_KM ** 2 *
    toRad(c.east - c.west) *
    Math.abs(Math.sin(toRad(c.north)) - Math.sin(toRad(c.south)))
  );
}

export function chooseResolution(b: Bounds, budget = DEFAULT_CELL_BUDGET): number {
  const area = boundsAreaKm2(b);
  for (let res = MAX_DISPLAY_RESOLUTION; res > 0; res--) {
    // Overlapping containment adds a ring of edge cells; leave ~20 % headroom.
    if ((area / getHexagonAreaAvg(res, UNITS.km2)) * 1.2 <= budget) return res;
  }
  return 0;
}

const overviewCache = new Map<number, string[]>();

/** Every cell at a coarse resolution (res 2 = 5,882 cells). */
export function overviewCells(res: number): string[] {
  if (res > OVERVIEW_MAX_RESOLUTION) throw new RangeError("overview is limited to coarse resolutions");
  let cells = overviewCache.get(res);
  if (!cells) {
    cells = getRes0Cells().flatMap((c) => (res === 0 ? [c] : cellToChildren(c, res)));
    overviewCache.set(res, cells);
  }
  return cells;
}

/**
 * Split an (possibly wrapped) longitude span into pieces that each lie inside [-180, 180]
 * and are at most MAX_CHUNK_DEGREES wide. This is how date-line views are handled.
 */
export function splitLongitudeSpan(west: number, east: number): Array<[number, number]> {
  const pieces: Array<[number, number]> = [];
  let start = west;
  while (start < east) {
    const offset = Math.floor((start + 180) / 360) * 360; // shift into [-180, 180)
    const worldEnd = offset + 180; // next antimeridian crossing
    const end = Math.min(east, worldEnd, start + MAX_CHUNK_DEGREES);
    pieces.push([start - offset, end - offset]);
    start = end;
  }
  return pieces;
}

export function viewportCells(bounds: Bounds, budget = DEFAULT_CELL_BUDGET): ViewportCells {
  const b = clampBounds(bounds);
  const resolution = chooseResolution(b, budget);

  if (resolution <= OVERVIEW_MAX_RESOLUTION) {
    return { resolution, cells: overviewCells(resolution), overview: true };
  }

  const seen = new Set<string>();
  for (const [w, e] of splitLongitudeSpan(b.west, b.east)) {
    if (e - w <= 0) continue;
    const ring = [
      [b.south, w],
      [b.south, e],
      [b.north, e],
      [b.north, w],
      [b.south, w],
    ];
    const cells = polygonToCellsExperimental(
      ring,
      resolution,
      POLYGON_TO_CELLS_FLAGS.containmentOverlapping,
    );
    for (const c of cells) seen.add(c);
  }
  return { resolution, cells: [...seen], overview: false };
}
