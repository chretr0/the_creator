import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Position } from "geojson";
import type { MapView } from "../components/WorldMap";
import {
  categoryColours,
  dataApi,
  formatValue,
  landCoverColour,
  makeScale,
  NO_DATA,
  OTHER,
  SEQUENTIAL_ORANGE,
  viewTouchesRegions,
  type CellLayer,
  type ColourScale,
  type DataFeature,
  type FeatureLayerMeta,
  type FeatureResult,
  type RGB,
  type Scene,
  type RGBA,
} from "./datalayers";

export const FEATURE_LAYER_PREFIX = "feat-";
const FILL_ALPHA = 175;
const RIVER: RGB = [42, 120, 214];

export type ActiveCellLayer = { layerId: string; sliceId: string };
export type FeatureFilter = { categories: string[]; q: string };
export type PickedFeature = { meta: FeatureLayerMeta; feature: DataFeature };

type Status = { loading: boolean; error: string | null };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useDataLayers(view: MapView | null, gridCells: string[]) {
  const [catalogue, setCatalogue] = useState<CellLayer[]>([]);
  const [manifest, setManifest] = useState<FeatureLayerMeta[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [active, setActive] = useState<ActiveCellLayer | null>(null);
  const [opacity, setOpacity] = useState(0.7);
  const [values, setValues] = useState<{ key: string; map: Map<string, number | null>; domain: [number, number] | null; units: string; withData: number; total: number } | null>(null);
  const [cellStatus, setCellStatus] = useState<Status>({ loading: false, error: null });
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [filters, setFilters] = useState<Record<string, FeatureFilter>>({});
  const [featureData, setFeatureData] = useState<Record<string, FeatureResult>>({});
  const [featureStatus, setFeatureStatus] = useState<Record<string, Status>>({});
  const [picked, setPicked] = useState<PickedFeature | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    Promise.all([dataApi.layers(ctrl.signal), dataApi.featureManifest(ctrl.signal)])
      .then(([layers, fm]) => {
        setCatalogue(layers);
        setManifest(fm.layers);
      })
      .then(() => dataApi.scenes(ctrl.signal))
      .then((s) => setScenes(s.scenes))
      .catch((e) => {
        if (!ctrl.signal.aborted) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  const activeLayer = useMemo(
    () => (active ? (catalogue.find((l) => l.id === active.layerId) ?? null) : null),
    [active, catalogue],
  );
  const activeSlice = activeLayer?.slices.find((s) => s.id === active?.sliceId) ?? null;

  /* -------- cell values for the visible grid -------- */
  const cellsKey = gridCells.length ? `${gridCells.length}:${gridCells[0]}:${gridCells[gridCells.length - 1]}` : "";
  const debouncedCellsKey = useDebounced(cellsKey, 120);
  const cellsRef = useRef(gridCells);
  cellsRef.current = gridCells;

  useEffect(() => {
    if (!active) {
      setValues(null);
      setCellStatus({ loading: false, error: null });
      return;
    }
    const cells = cellsRef.current;
    if (!cells.length) return;
    const ctrl = new AbortController();
    setCellStatus({ loading: true, error: null });
    dataApi
      .values(active.layerId, active.sliceId, cells, ctrl.signal)
      .then((r) => {
        const map = new Map<string, number | null>();
        cells.forEach((c, i) => map.set(c, r.values[i] ?? null));
        setValues({
          key: `${active.layerId}/${active.sliceId}/${debouncedCellsKey}`,
          map,
          domain: r.domain,
          units: r.units ?? "",
          withData: r.withData ?? 0,
          total: cells.length,
        });
        setCellStatus({ loading: false, error: null });
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setCellStatus({ loading: false, error: e instanceof Error ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, [active, debouncedCellsKey]);

  const scale: ColourScale | null = useMemo(() => {
    if (!activeLayer || !values?.domain || activeSlice?.categorical) return null;
    const palette = activeLayer.palette === "diverging" ? "diverging" : "sequential";
    return makeScale(values.domain, { log: activeLayer.scaleType === "log", palette });
  }, [activeLayer, activeSlice, values?.domain]);

  const categorical = useMemo(
    () => (activeSlice?.categorical ? landCoverColour(activeLayer?.categories ?? null) : null),
    [activeSlice, activeLayer],
  );

  const cellFill = useMemo(() => {
    if (!values || (!scale && !categorical)) return null;
    const alpha = Math.round(FILL_ALPHA * opacity * 1.4);
    return (h3: string): RGBA => {
      const v = values.map.get(h3);
      const c = v === undefined || v === null ? null : categorical ? categorical(v) : scale!.colour(v);
      return c ? [c[0], c[1], c[2], Math.min(255, alpha)] : NO_DATA;
    };
  }, [values, scale, categorical, opacity]);

  const cellTooltip = useCallback(
    (h3: string): string | null => {
      if (!values || !activeLayer || !activeSlice) return null;
      const v = values.map.get(h3);
      if (v === undefined) return null;
      if (activeSlice.categorical) {
        const cat = activeLayer.categories?.find((c) => c.value === Math.round(v ?? -1));
        return `${activeLayer.name}: ${v === null ? "no data" : (cat?.label ?? v)}`;
      }
      return `${activeLayer.name} · ${activeSlice.label}: ${formatValue(v, values.units)}`;
    },
    [values, activeLayer, activeSlice],
  );

  /* -------- feature layers -------- */
  const debouncedView = useDebounced(view, 250);
  const enabledIds = useMemo(() => Object.keys(enabled).filter((k) => enabled[k]), [enabled]);

  useEffect(() => {
    if (!debouncedView) return;
    const ctrls: AbortController[] = [];
    for (const id of enabledIds) {
      const meta = manifest.find((m) => m.id === id);
      if (!meta || meta.geometry === "table") continue;
      const f = filters[id];
      const ctrl = new AbortController();
      ctrls.push(ctrl);
      setFeatureStatus((s) => ({ ...s, [id]: { loading: true, error: null } }));
      dataApi
        .features(id, debouncedView.bounds, { categories: f?.categories, q: f?.q || undefined }, ctrl.signal)
        .then((r) => {
          setFeatureData((d) => ({ ...d, [id]: r }));
          setFeatureStatus((s) => ({ ...s, [id]: { loading: false, error: null } }));
        })
        .catch((e) => {
          if (!ctrl.signal.aborted)
            setFeatureStatus((s) => ({ ...s, [id]: { loading: false, error: e instanceof Error ? e.message : String(e) } }));
        });
    }
    return () => ctrls.forEach((c) => c.abort());
  }, [debouncedView, enabledIds, filters, manifest]);

  const featureLayers = useMemo(() => {
    const out: Layer[] = [];
    // Polygons first (under), then lines, then points on top.
    const order = { polygon: 0, line: 1, point: 2, table: 3 } as const;
    const metas = enabledIds
      .map((id) => manifest.find((m) => m.id === id))
      .filter((m): m is FeatureLayerMeta => !!m && !!featureData[m.id])
      .sort((a, b) => order[a.geometry] - order[b.geometry]);
    for (const meta of metas) {
      const data = featureData[meta.id].features;
      const id = `${FEATURE_LAYER_PREFIX}${meta.id}`;
      if (meta.geometry === "point") {
        const cats = categoryColours(meta);
        const vf = meta.valueField;
        out.push(
          new ScatterplotLayer<DataFeature>({
            id,
            data,
            getPosition: (f) => (f.geometry as { coordinates: Position }).coordinates as [number, number],
            getFillColor: (f) => {
              const c = meta.categoryField ? cats.get(String(f.properties[meta.categoryField])) : cats.values().next().value;
              return [...(c ?? OTHER), 230];
            },
            getLineColor: (f) => (picked?.feature.id === f.id ? [255, 255, 255, 255] : [15, 23, 42, 220]),
            getRadius: (f) => {
              const v = vf ? Number(f.properties[vf]) : NaN;
              const base = Number.isFinite(v) && v > 0 ? 3 + Math.min(5, Math.log10(1 + v) * 0.7) : 4;
              return picked?.feature.id === f.id ? base + 3 : base;
            },
            radiusUnits: "pixels",
            stroked: true,
            lineWidthUnits: "pixels",
            getLineWidth: 1,
            pickable: true,
            updateTriggers: { getLineColor: picked?.feature.id, getRadius: picked?.feature.id },
          }),
        );
      } else if (meta.geometry === "line") {
        const vf = meta.valueField;
        const paths = data.flatMap((f) => {
          const g = f.geometry;
          const parts = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
          return parts.map((p) => ({ path: p as [number, number][], f }));
        });
        out.push(
          new PathLayer<{ path: [number, number][]; f: DataFeature }>({
            id,
            data: paths,
            getPath: (d) => d.path,
            getColor: [...RIVER, 210],
            getWidth: (d) => {
              const v = vf ? Number(d.f.properties[vf]) : NaN;
              return Number.isFinite(v) && v > 0 ? 1 + Math.min(5, Math.log10(1 + v) * 1.6) : 1;
            },
            widthUnits: "pixels",
            capRounded: true,
            jointRounded: true,
            pickable: true,
          }),
        );
      } else if (meta.geometry === "polygon") {
        const vf = meta.valueField;
        const sc = vf ? makeScale([0, 5], { stops: SEQUENTIAL_ORANGE }) : null;
        out.push(
          new GeoJsonLayer({
            id,
            data: { type: "FeatureCollection", features: data } as never,
            filled: !!vf,
            stroked: true,
            getFillColor: (f: DataFeature) => {
              const v = vf ? f.properties[vf] : null;
              const c = typeof v === "number" && sc ? sc.colour(v) : null;
              return c ? [...c, Math.round(150 * opacity + 30)] : [...OTHER, 50];
            },
            getLineColor: (f: DataFeature) => (picked?.feature.id === f.id ? [15, 23, 42, 255] : vf ? [255, 255, 255, 160] : [99, 102, 241, 200]),
            getLineWidth: (f: DataFeature) => (picked?.feature.id === f.id ? 3 : 1),
            lineWidthUnits: "pixels",
            pickable: true,
            updateTriggers: { getFillColor: opacity, getLineColor: picked?.feature.id, getLineWidth: picked?.feature.id },
          }),
        );
      }
    }
    return out;
  }, [enabledIds, featureData, manifest, picked, opacity]);

  const featureMetaForLayer = useCallback(
    (layerId: string) =>
      layerId.startsWith(FEATURE_LAYER_PREFIX)
        ? (manifest.find((m) => m.id === layerId.slice(FEATURE_LAYER_PREFIX.length)) ?? null)
        : null,
    [manifest],
  );

  /** Deck objects for lines are wrappers; normalise to the GeoJSON feature. */
  const asFeature = useCallback((object: unknown): DataFeature => {
    const o = object as { f?: DataFeature } & DataFeature;
    return o.f ?? o;
  }, []);

  const featureTooltip = useCallback(
    (layerId: string, object: unknown): string | null => {
      const meta = featureMetaForLayer(layerId);
      if (!meta) return null;
      const p = asFeature(object).properties;
      const lines = [`${(meta.nameField && p[meta.nameField]) || meta.name}`];
      if (meta.categoryField && p[meta.categoryField] != null) lines.push(String(p[meta.categoryField]));
      if (meta.valueField) {
        const f = meta.fields.find((x) => x.key === meta.valueField);
        lines.push(`${f?.label ?? meta.valueField}: ${formatValue(p[meta.valueField] as number | null, meta.valueUnits)}`);
      }
      lines.push(meta.name);
      return lines.join("\n");
    },
    [featureMetaForLayer, asFeature],
  );

  const scene = scenes.find((s) => s.id === sceneId) ?? null;

  /** A regional layer is active but the map shows neither of its regions: say so instead of a blank grid. */
  const outsideRegions =
    !!activeLayer && activeLayer.coverage === "regions" && !!view && !viewTouchesRegions(view.bounds, activeLayer.regions);

  const attributions = useMemo(() => {
    const a: string[] = [];
    if (scene) a.push(`${scene.name}: ${scene.attribution}`);
    if (activeLayer) {
      // The full attribution text is in the cell inspector and the sources panel; the map names the
      // provider and licence so the line stays readable.
      const p = activeLayer.provenance;
      const who = p.attribution && p.attribution.length <= 90 ? p.attribution : (p.provider ?? p.attribution?.slice(0, 90));
      if (who) a.push(`${activeLayer.name}: ${who}${p.licence ? ` (${p.licence})` : ""}`);
    }
    for (const id of enabledIds) {
      const m = manifest.find((x) => x.id === id);
      if (m?.attribution) a.push(m.attribution.length > 120 ? (m.provider ?? m.attribution.slice(0, 120)) : m.attribution);
    }
    return a;
  }, [activeLayer, enabledIds, manifest, scene]);

  return {
    catalogue,
    manifest,
    loadError,
    active,
    setActive,
    activeLayer,
    activeSlice,
    opacity,
    setOpacity,
    values,
    outsideRegions,
    cellStatus,
    scale,
    cellFill,
    cellTooltip,
    enabled,
    setEnabled,
    filters,
    setFilters,
    featureData,
    featureStatus,
    featureLayers,
    featureMetaForLayer,
    asFeature,
    featureTooltip,
    picked,
    setPicked,
    attributions,
    scenes,
    scene,
    setSceneId,
  };
}

export type DataLayersState = ReturnType<typeof useDataLayers>;
