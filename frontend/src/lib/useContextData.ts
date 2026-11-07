import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { FeatureCollection, Geometry } from "geojson";
import type { MapView, RasterImagery } from "../components/WorldMap";
import {
  gibsTiles,
  hexToRgb,
  IMAGERY_PRODUCTS,
  isoDay,
  loadBoundaries,
  loadCables,
  loadEarthquakes,
  loadFires,
  loadPower,
  loadSearchIndex,
  loadSources,
  voltageColour,
  type BoundaryLayerId,
  type CablePath,
  type Earthquake,
  type Fire,
  type Hazard,
  type ImageryState,
  type LandingPoint,
  type PowerFeature,
  type PowerResult,
  type RegionProps,
  type SearchEntry,
  type SourceCredit,
} from "./context";

export type ContextToggles = {
  boundaries: Record<BoundaryLayerId, boolean>;
  cables: boolean;
  earthquakes: boolean;
  fires: boolean;
};

export type ContextSelection = { layerId: string; object: unknown } | null;

type Status = { loading: boolean; error: string | null };
const idle: Status = { loading: false, error: null };

const FIRE_MAX_SPAN_DEG = 40;

/** Minimum zoom at which each boundary level draws (they stay loaded). */
const BOUNDARY_MIN_ZOOM: Record<BoundaryLayerId, number> = { countries: 0, admin1: 3, us_counties: 5 };

export const CONTEXT_LAYER_IDS = {
  cables: "ctx-cables",
  landing: "ctx-landing",
  quakes: "ctx-quakes",
  fires: "ctx-fires",
  powerLines: "ctx-power-lines",
  powerPoints: "ctx-power-points",
} as const;

const PLANT_COLOURS: Record<string, [number, number, number]> = {
  solar: [234, 179, 8],
  wind: [20, 184, 166],
  hydro: [37, 99, 235],
  gas: [100, 116, 139],
  coal: [41, 37, 36],
  nuclear: [168, 85, 247],
  oil: [120, 53, 15],
  biomass: [101, 163, 13],
};

export function quakeColour(depthKm: number | null): [number, number, number] {
  if (depthKm === null) return [148, 163, 184];
  if (depthKm < 70) return [239, 68, 68];
  if (depthKm < 300) return [249, 115, 22];
  return [168, 85, 247];
}

export function positionOf(layerId: string, object: unknown): [number, number] | null {
  switch (layerId) {
    case CONTEXT_LAYER_IDS.landing: {
      const l = object as LandingPoint;
      return [l.properties.lon, l.properties.lat];
    }
    case CONTEXT_LAYER_IDS.quakes:
    case CONTEXT_LAYER_IDS.fires: {
      const r = object as { lon: number; lat: number };
      return [r.lon, r.lat];
    }
    case CONTEXT_LAYER_IDS.powerPoints:
      return (object as PowerFeature).geometry.coordinates as [number, number];
    default:
      return null;
  }
}

export function useContextData(view: MapView | null, regionHighlight: { country?: string | null; admin1?: string | null }) {
  const [toggles, setToggles] = useState<ContextToggles>({
    boundaries: { countries: false, admin1: false, us_counties: false },
    cables: false,
    earthquakes: false,
    fires: false,
  });
  const [boundaries, setBoundaries] = useState<Partial<Record<BoundaryLayerId, FeatureCollection<Geometry, RegionProps>>>>({});
  const [cables, setCables] = useState<{ paths: CablePath[]; landing: LandingPoint[] } | null>(null);
  const [quakes, setQuakes] = useState<Hazard<Earthquake> | null>(null);
  const [fires, setFires] = useState<Hazard<Fire> | null>(null);
  const [fireHint, setFireHint] = useState<string | null>(null);
  const [power, setPower] = useState<PowerResult | null>(null);
  const [imagery, setImagery] = useState<ImageryState | null>(null);
  const [sources, setSources] = useState<SourceCredit[]>([]);
  const [searchIndex, setSearchIndex] = useState<SearchEntry[] | null>(null);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [selection, setSelection] = useState<ContextSelection>(null);
  const loading = useRef(new Set<string>());

  const track = useCallback(async (key: string, work: () => Promise<void>) => {
    if (loading.current.has(key)) return;
    loading.current.add(key);
    setStatus((s) => ({ ...s, [key]: { loading: true, error: null } }));
    try {
      await work();
      setStatus((s) => ({ ...s, [key]: idle }));
    } catch (e) {
      setStatus((s) => ({ ...s, [key]: { loading: false, error: e instanceof Error ? e.message : String(e) } }));
    } finally {
      loading.current.delete(key);
    }
  }, []);

  useEffect(() => {
    loadSources().then(setSources).catch(() => setSources([]));
  }, []);

  // Lazy-load each dataset the first time it is switched on (or needed for a region highlight).
  useEffect(() => {
    const needed = (Object.keys(toggles.boundaries) as BoundaryLayerId[]).filter(
      (id) =>
        (toggles.boundaries[id] || (id === "countries" && regionHighlight.country) || (id === "admin1" && regionHighlight.admin1)) &&
        !boundaries[id],
    );
    for (const id of needed) {
      track(`boundaries:${id}`, async () => {
        const fc = await loadBoundaries(id);
        setBoundaries((b) => ({ ...b, [id]: fc }));
      });
    }
  }, [toggles.boundaries, regionHighlight.country, regionHighlight.admin1, boundaries, track]);

  useEffect(() => {
    if (toggles.cables && !cables) track("cables", async () => setCables(await loadCables()));
  }, [toggles.cables, cables, track]);

  const reloadQuakes = useCallback(() => track("earthquakes", async () => setQuakes(await loadEarthquakes())), [track]);
  useEffect(() => {
    if (toggles.earthquakes && !quakes) reloadQuakes();
  }, [toggles.earthquakes, quakes, reloadQuakes]);

  // Fires are fetched per view (bounded box) because a world-wide day of VIIRS detections is large.
  const viewKey = view
    ? [view.bounds.west, view.bounds.south, view.bounds.east, view.bounds.north].map((v) => v.toFixed(1)).join(",")
    : "";
  useEffect(() => {
    if (!toggles.fires || !view) return;
    const b = view.bounds;
    if (b.east - b.west > FIRE_MAX_SPAN_DEG || b.north - b.south > FIRE_MAX_SPAN_DEG) {
      setFireHint(`Zoom in to load fire detections (view must be under ${FIRE_MAX_SPAN_DEG}° across).`);
      return;
    }
    if (b.west < -180 || b.east > 180) {
      setFireHint("Fire detections are not loaded across the date line; pan away from ±180°.");
      return;
    }
    setFireHint(null);
    track("fires", async () => setFires(await loadFires(b)));
    // viewKey captures the bounds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toggles.fires, viewKey, track]);

  const requestPower = useCallback(
    (lat: number, lon: number, radiusKm = 10) => track("power", async () => setPower(await loadPower(lat, lon, radiusKm))),
    [track],
  );

  const ensureSearchIndex = useCallback(() => {
    if (!searchIndex) track("searchIndex", async () => setSearchIndex(await loadSearchIndex()));
  }, [searchIndex, track]);

  const zoom = view?.zoom ?? 0;
  const selectedObject = selection?.object ?? null;

  const layers = useMemo(() => {
    const out: Layer[] = [];

    // Region highlight (from the search panel's country / admin-1 filter).
    const hl =
      regionHighlight.admin1 && boundaries.admin1
        ? boundaries.admin1.features.filter(
            (f) => f.properties.name === regionHighlight.admin1 && (!regionHighlight.country || f.properties.country === regionHighlight.country),
          )
        : regionHighlight.country && boundaries.countries
          ? boundaries.countries.features.filter((f) => f.properties.name === regionHighlight.country)
          : [];
    if (hl.length) {
      out.push(
        new GeoJsonLayer({
          id: "ctx-region-highlight",
          data: hl as never,
          filled: true,
          stroked: true,
          getFillColor: [59, 130, 246, 28],
          getLineColor: [37, 99, 235, 230],
          lineWidthUnits: "pixels",
          getLineWidth: 2.5,
        }),
      );
    }

    const boundaryStyle: Record<BoundaryLayerId, { colour: [number, number, number, number]; width: number }> = {
      countries: { colour: [30, 41, 59, 210], width: 1.4 },
      admin1: { colour: [71, 85, 105, 170], width: 0.9 },
      us_counties: { colour: [100, 116, 139, 150], width: 0.6 },
    };
    for (const id of ["us_counties", "admin1", "countries"] as BoundaryLayerId[]) {
      const fc = boundaries[id];
      if (!toggles.boundaries[id] || !fc || zoom < BOUNDARY_MIN_ZOOM[id]) continue;
      out.push(
        new GeoJsonLayer({
          id: `ctx-boundaries-${id}`,
          data: fc as never,
          filled: false,
          stroked: true,
          getLineColor: boundaryStyle[id].colour,
          lineWidthUnits: "pixels",
          getLineWidth: boundaryStyle[id].width,
        }),
      );
    }

    if (toggles.cables && cables) {
      out.push(
        new PathLayer<CablePath>({
          id: CONTEXT_LAYER_IDS.cables,
          data: cables.paths,
          getPath: (d) => d.path,
          getColor: (d) => [...hexToRgb(d.cable.colour, [14, 165, 233]), selectedObject === d ? 255 : 200],
          getWidth: (d) => (selectedObject === d ? 4 : 1.6),
          widthUnits: "pixels",
          pickable: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 180],
          updateTriggers: { getColor: selectedObject, getWidth: selectedObject },
        }),
        new ScatterplotLayer<LandingPoint>({
          id: CONTEXT_LAYER_IDS.landing,
          data: zoom >= 2 ? cables.landing : [],
          getPosition: (d) => [d.properties.lon, d.properties.lat],
          getFillColor: [255, 255, 255, 255],
          getLineColor: [15, 23, 42, 255],
          getRadius: 3,
          radiusUnits: "pixels",
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 1,
          pickable: true,
        }),
      );
    }

    if (toggles.earthquakes && quakes) {
      out.push(
        new ScatterplotLayer<Earthquake>({
          id: CONTEXT_LAYER_IDS.quakes,
          data: quakes.records,
          getPosition: (d) => [d.lon, d.lat],
          getFillColor: (d) => [...quakeColour(d.depthKm), 160],
          getLineColor: [255, 255, 255, 220],
          getRadius: (d) => Math.max(2.5, ((d.magnitude ?? 2.5) - 1.5) * 3),
          radiusUnits: "pixels",
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 1,
          pickable: true,
        }),
      );
    }

    if (toggles.fires && fires) {
      out.push(
        new ScatterplotLayer<Fire>({
          id: CONTEXT_LAYER_IDS.fires,
          data: fires.records,
          getPosition: (d) => [d.lon, d.lat],
          getFillColor: [249, 115, 22, 210],
          getLineColor: [124, 45, 18, 255],
          getRadius: 3,
          radiusUnits: "pixels",
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 0.5,
          pickable: true,
        }),
      );
    }

    if (power) {
      const [w, s, e, n] = power.bbox;
      out.push(
        new PathLayer({
          id: "ctx-power-area",
          data: [{ path: [[w, s], [e, s], [e, n], [w, n], [w, s]] }],
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: [217, 119, 6, 200],
          getWidth: 1.5,
          widthUnits: "pixels",
        }),
        new PathLayer<PowerFeature>({
          id: CONTEXT_LAYER_IDS.powerLines,
          data: power.features.filter((f) => f.geometry.type === "LineString"),
          getPath: (f) => f.geometry.coordinates as [number, number][],
          getColor: (f) => [...voltageColour(f.properties.voltageKv), f.properties.kind === "cable" ? 140 : 230],
          getWidth: (f) => (selectedObject === f ? 5 : Math.max(1.2, Math.min(4, Math.max(0, ...f.properties.voltageKv) / 100))),
          widthUnits: "pixels",
          pickable: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 160],
          updateTriggers: { getWidth: selectedObject },
        }),
        new ScatterplotLayer<PowerFeature>({
          id: CONTEXT_LAYER_IDS.powerPoints,
          data: power.features.filter((f) => f.geometry.type === "Point"),
          getPosition: (f) => f.geometry.coordinates as [number, number],
          getFillColor: (f) =>
            f.properties.kind === "plant" ? [...(PLANT_COLOURS[f.properties.plantSource ?? ""] ?? [217, 119, 6]), 255] : [71, 85, 105, 230],
          getLineColor: [255, 255, 255, 255],
          getRadius: (f) => (f.properties.kind === "plant" ? 7 : 4),
          radiusUnits: "pixels",
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 1.5,
          pickable: true,
        }),
      );
    }

    // Ring around the selected point-like context object.
    const pos = selection ? positionOf(selection.layerId, selection.object) : null;
    if (pos) {
      out.push(
        new ScatterplotLayer({
          id: "ctx-selected",
          data: [pos],
          getPosition: (d: [number, number]) => d,
          filled: false,
          stroked: true,
          getLineColor: [15, 23, 42, 255],
          getRadius: 11,
          radiusUnits: "pixels",
          lineWidthUnits: "pixels",
          getLineWidth: 2.5,
        }),
      );
    }
    return out;
  }, [toggles, boundaries, cables, quakes, fires, power, zoom, selection, selectedObject, regionHighlight.country, regionHighlight.admin1]);

  const rasterImagery: RasterImagery | null = useMemo(() => {
    if (!imagery) return null;
    const p = IMAGERY_PRODUCTS[imagery.product];
    return {
      key: `${imagery.product}:${imagery.date}`,
      tiles: gibsTiles(imagery.product, imagery.date),
      maxzoom: p.maxLevel,
      opacity: imagery.opacity,
      attribution: `Imagery: NASA GIBS · ${p.sensor} ${imagery.date}`,
    };
  }, [imagery]);

  /** Attributions of active non-basemap sources, kept visible on the map. */
  const attributions = useMemo(() => {
    const a: string[] = [];
    if (Object.values(toggles.boundaries).some(Boolean)) a.push("Boundaries: Natural Earth · US Census Bureau");
    if (toggles.cables) a.push("Cables © TeleGeography — submarinecablemap.com (CC BY-NC-SA 3.0, non-commercial)");
    if (toggles.earthquakes) a.push("Earthquakes: USGS");
    if (toggles.fires) a.push("Fires: NASA LANCE FIRMS");
    if (power) a.push("Power: © OpenStreetMap contributors via Overpass");
    return a;
  }, [toggles, power]);

  return {
    toggles,
    setToggles,
    boundaries,
    cables,
    quakes,
    reloadQuakes,
    fires,
    fireHint,
    power,
    setPower,
    requestPower,
    imagery,
    setImagery,
    rasterImagery,
    sources,
    searchIndex,
    ensureSearchIndex,
    status,
    selection,
    setSelection,
    layers,
    attributions,
    defaultImageryDate: isoDay(new Date(Date.now() - 86400e3)),
  };
}
