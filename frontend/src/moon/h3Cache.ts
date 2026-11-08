/**
 * Pure parts of useMoonH3: the key that identifies the cells on screen, which cells a view still
 * needs, and the per-layer value cache. Missing values stay null, never 0.
 */
import type { MoonH3Values } from "./api";

export type CellCache = { layerId: string | null; values: Map<string, number | null>; served: Map<string, number> };
export const EMPTY_CACHE: CellCache = { layerId: null, values: new Map(), served: new Map() };

/** Past this many cached cells the cache starts afresh, keeping the cells on screen. */
export const MAX_CACHED_CELLS = 80000;

export type ValuesStatus = { loading: boolean; error: string | null; notPrepared: boolean };
// Shared objects, so setting the same status again doesn't re-render.
export const IDLE_STATUS: ValuesStatus = { loading: false, error: null, notPrepared: false };
export const LOADING_STATUS: ValuesStatus = { loading: true, error: null, notPrepared: false };

/**
 * A key for a list of cells that depends on every id in it (the count and two 32-bit FNV-1a style
 * hashes), so a pan that keeps the count, the first and the last cell but changes cells in between
 * still gets a new key.
 */
export function cellSetKey(cells: readonly string[]): string {
  if (!cells.length) return "";
  let a = 0x811c9dc5;
  let b = 0x9e3779b9;
  for (const c of cells) {
    for (let i = 0; i < c.length; i++) {
      const ch = c.charCodeAt(i);
      a = Math.imul(a ^ ch, 0x01000193);
      b = Math.imul(b ^ ch, 0x5bd1e995);
    }
    // Separator, so ["ab", "c"] and ["a", "bc"] differ.
    a = Math.imul(a ^ 0x2c, 0x01000193);
    b = Math.imul(b ^ 0x2c, 0x5bd1e995);
  }
  return `${cells.length}:${(a >>> 0).toString(36)}:${(b >>> 0).toString(36)}`;
}

/**
 * What the values request for a view should do: the cells not cached yet for `layerId`, and the
 * status to show. A view that needs no request (or no active layer) is idle, so an earlier
 * "Loading…" or error never outlives the request it belonged to.
 */
export function planValuesRequest(
  layerId: string | null,
  cells: readonly string[],
  cache: CellCache,
): { missing: string[]; status: ValuesStatus } {
  if (!layerId) return { missing: [], status: IDLE_STATUS };
  const known = cache.layerId === layerId ? cache.values : null;
  const missing = known ? cells.filter((c) => !known.has(c)) : [...cells];
  return { missing, status: missing.length ? LOADING_STATUS : IDLE_STATUS };
}

/**
 * The cache after a values response for `requested`. Values of another layer are dropped. Past
 * `maxCells` the cache starts afresh, but the cells on screen keep their values: dropping them
 * would paint cells that have data as "no data" until the next pan.
 */
export function mergeCellValues(
  cur: CellCache,
  layerId: string,
  requested: readonly string[],
  response: Pick<MoonH3Values, "values" | "servedResolution">,
  onScreen: readonly string[],
  maxCells = MAX_CACHED_CELLS,
): CellCache {
  const same = cur.layerId === layerId;
  let values: Map<string, number | null>;
  let served: Map<string, number>;
  if (same && cur.values.size < maxCells) {
    values = new Map(cur.values);
    served = new Map(cur.served);
  } else {
    values = new Map();
    served = new Map();
    if (same) {
      for (const c of onScreen) {
        if (!cur.values.has(c)) continue;
        values.set(c, cur.values.get(c) ?? null);
        const s = cur.served.get(c);
        if (s !== undefined) served.set(c, s);
      }
    }
  }
  for (const c of requested) {
    const v = response.values?.[c];
    values.set(c, typeof v === "number" && Number.isFinite(v) ? v : null);
    const s = response.servedResolution?.[c];
    if (typeof s === "number") served.set(c, s);
  }
  return { layerId, values, served };
}
