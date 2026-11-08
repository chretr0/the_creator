import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getResolution } from "h3-js";
import { isNotPrepared, MoonApiError, moonApi, type MoonH3Layer } from "./api";
import { cellSetKey, EMPTY_CACHE as EMPTY, IDLE_STATUS, mergeCellValues, planValuesRequest, type CellCache, type ValuesStatus } from "./h3Cache";
import { h3ValueTooltip, moonScale, NO_DATA_FILL, valueRange, type RGBA } from "./layers";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Display cells are coloured up to this alpha (× opacity); the basemap stays readable underneath. */
const FILL_ALPHA = 235;

/**
 * Moon H3 layers (GET /api/moon/h3) and the values of the active one for the cells on screen
 * (POST /api/moon/h3/{id}). Values are cached per layer, so panning back is instant; a pan or zoom
 * debounces the request and aborts the previous one.
 */
export function useMoonH3(gridCells: string[]) {
  const [layers, setLayers] = useState<MoonH3Layer[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  /** The server has no Moon H3 layers yet: 503 = not prepared, 404 = this backend doesn't serve them. */
  const [listMissing, setListMissing] = useState<"not_prepared" | "not_served" | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [opacity, setOpacity] = useState(0.7);
  const [stored, setStored] = useState<CellCache>(EMPTY);
  const [status, setStatus] = useState<ValuesStatus>(IDLE_STATUS);

  useEffect(() => {
    const ctrl = new AbortController();
    moonApi
      .h3Layers(ctrl.signal)
      .then((list) => setLayers(list.filter((l) => l && typeof l.id === "string")))
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setLayers([]);
        if (isNotPrepared(e)) setListMissing("not_prepared");
        else if (e instanceof MoonApiError && e.status === 404) setListMissing("not_served");
        else setListError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  const active = useMemo(() => layers?.find((l) => l.id === activeId) ?? null, [layers, activeId]);
  // Values of another (previous) layer never colour this one.
  const cache = active && stored.layerId === active.id ? stored : EMPTY;

  // Every cell id counts: a pan can keep the count, first and last cell yet bring new cells on screen.
  const cellsKey = useMemo(() => cellSetKey(gridCells), [gridCells]);
  const debouncedKey = useDebounced(cellsKey, 150);
  const cellsRef = useRef(gridCells);
  cellsRef.current = gridCells;
  const storedRef = useRef(stored);
  storedRef.current = stored;

  useEffect(() => {
    const layerId = active?.id ?? null;
    const { missing, status: next } = planValuesRequest(layerId, cellsRef.current, storedRef.current);
    // Also when nothing is requested: a "Loading…" or error from an aborted request must not stick.
    setStatus(next);
    if (!layerId || !missing.length) return;
    const ctrl = new AbortController();
    moonApi
      .h3Values(layerId, missing, ctrl.signal)
      .then((r) => {
        // The cache starts afresh after long sessions of panning, keeping what is on screen now.
        const onScreen = cellsRef.current;
        setStored((cur) => mergeCellValues(cur, layerId, missing, r, onScreen));
        setStatus(IDLE_STATUS);
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setStatus({ loading: false, error: e instanceof Error ? e.message : String(e), notPrepared: isNotPrepared(e) });
      });
    return () => ctrl.abort();
  }, [active, debouncedKey]);

  // The published range keeps colours stable while panning; the on-screen range is only a fallback.
  const fallbackRange = useMemo(
    () => (active && !active.range ? valueRange(gridCells.map((c) => cache.values.get(c))) : null),
    [active, gridCells, cache],
  );
  const fallbackKey = fallbackRange ? fallbackRange.join(":") : "";
  const scale = useMemo(
    () => (active ? moonScale(active, fallbackRange) : null),
    // fallbackKey identifies fallbackRange.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active, fallbackKey],
  );

  const cellFill = useMemo(() => {
    if (!active || !scale) return null;
    const alpha = Math.min(255, Math.round(FILL_ALPHA * opacity));
    const values = cache.values;
    return (h3: string): RGBA => {
      const c = scale.colour(values.get(h3));
      return c ? [c[0], c[1], c[2], alpha] : NO_DATA_FILL;
    };
  }, [active, scale, cache, opacity]);

  const cellTooltip = useCallback(
    (h3: string): string | null => {
      if (!active || !cache.values.has(h3)) return null;
      return h3ValueTooltip(active, cache.values.get(h3) ?? null, getResolution(h3), cache.served.get(h3));
    },
    [active, cache],
  );

  /** How many of the cells on screen have loaded, and how many of those have a value. */
  const coverage = useMemo(() => {
    if (!active || !gridCells.length) return null;
    let known = 0;
    let withData = 0;
    for (const c of gridCells) {
      if (!cache.values.has(c)) continue;
      known++;
      if (cache.values.get(c) !== null) withData++;
    }
    return known ? { known, withData } : null;
  }, [active, gridCells, cache]);

  /** The resolution the values on screen come from (the layer's finest, when cells are finer). */
  const servedResolution = useMemo(() => {
    for (const c of gridCells) {
      const s = cache.served.get(c);
      if (s !== undefined) return s;
    }
    return null;
  }, [gridCells, cache]);

  return {
    layers,
    listError,
    listMissing,
    active,
    setActive: setActiveId,
    opacity,
    setOpacity,
    scale,
    cellFill,
    cellTooltip,
    status,
    coverage,
    servedResolution,
  };
}

export type MoonH3State = ReturnType<typeof useMoonH3>;
