import { useEffect, useRef, useState, type DragEvent } from "react";
import { maplibregl } from "../lib/maplibre";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { GeoJsonLayer, LineLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { WebMercatorViewport, type Layer, type PickingInfo } from "@deck.gl/core";
import type { Project } from "../lib/api";
import { normaliseLongitude, viewportCells, type ViewportCells } from "../lib/h3grid";
import { typeColour, typeLabel } from "../lib/projectTypes";
import { PRESET_DRAG_TYPE, STATE_COLOUR, STATE_LABEL, type CellState } from "../lib/buildings";
import { facilityTitle, formatKw, type Facility } from "../lib/infrastructure";
import { applyBasemapTheme } from "../lib/mapTheme";
import type { Theme } from "../lib/theme";

type RGB = [number, number, number];

// Display-only marker height for facility "stems" in the tilted view (as in gods-eye-view). Not data.
// Capped to about STEM_MAX_PX on screen so the tips stay in view when zoomed in to street level.
const STEM_HEIGHT_M = 1500;
const STEM_MAX_PX = 70;

function stemHeightM(map: maplibregl.Map, tilted: boolean): number {
  if (!tilted) return 0;
  const metresPerPx = (40075016.686 * Math.cos((map.getCenter().lat * Math.PI) / 180)) / (512 * 2 ** map.getZoom());
  return Math.min(STEM_HEIGHT_M, STEM_MAX_PX * metresPerPx);
}
// Facility labels appear from this zoom and are thinned by a screen-space grid budget, the same
// approach as gods-eye-view (one label per grid cell, highest priority wins, capped total).
const LABEL_MIN_ZOOM = 5;
const LABEL_CELL_PX: [number, number] = [130, 30];
const LABEL_MAX = 400;

function pickLabels(map: maplibregl.Map, facilities: Facility[], selectedId: string | null, z: number): Facility[] {
  if (map.getZoom() < LABEL_MIN_ZOOM) return [];
  const { clientWidth: w, clientHeight: h } = map.getCanvas();
  // Project where deck.gl will actually draw the label (at the stem tip when tilted).
  const centre = map.getCenter();
  const viewport = new WebMercatorViewport({
    width: w,
    height: h,
    longitude: centre.lng,
    latitude: centre.lat,
    zoom: map.getZoom(),
    pitch: map.getPitch(),
    bearing: map.getBearing(),
  });
  const best = new Map<string, { f: Facility; score: number }>();
  for (const f of facilities) {
    const { lon, lat, name, operator, companyFacilityCount } = f.properties;
    if (!name && !operator && f.id !== selectedId) continue;
    const [x, y] = viewport.project([lon, lat, z]);
    if (!(x >= -20 && y >= -20 && x <= w + 20 && y <= h + 20)) continue;
    const score = f.id === selectedId ? Infinity : (name ? 1e6 : 0) + (companyFacilityCount ?? 0);
    const key = `${Math.floor(x / LABEL_CELL_PX[0])}:${Math.floor(y / LABEL_CELL_PX[1])}`;
    const cur = best.get(key);
    if (!cur || score > cur.score) best.set(key, { f, score });
  }
  return [...best.values()]
    .sort((a, b) => b.score - a.score)
    .slice(0, LABEL_MAX)
    .map((x) => x.f);
}

// OpenFreeMap basemap (OSM data).
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

export type MapFocus = {
  latitude: number;
  longitude: number;
  zoom?: number;
  /** [west, south, east, north]; when set the map fits it instead of flying to a zoom. */
  bbox?: [number, number, number, number];
  nonce: number;
};

export type Picked = { layerId: string; object: unknown };

export type MapView = {
  bounds: { west: number; south: number; east: number; north: number };
  zoom: number;
  centre: { lat: number; lon: number };
};

export type RasterImagery = {
  key: string;
  tiles: string[];
  maxzoom: number;
  opacity: number;
  attribution: string;
};

const IMAGERY_SOURCE = "context-imagery";
const SCENE_SOURCE = "scene-image";

export type SceneImage = { id: string; url: string; bounds: [number, number, number, number] };

type Props = {
  theme: Theme;
  /** Show hexagon borders; fills, markers and picking remain available when hidden. */
  showHexOutlines: boolean;
  projects: Project[];
  selectedProjectId: string | null;
  selectedCell: string | null;
  crosshair: boolean;
  focus: MapFocus | null;
  facilities: Facility[];
  facilityColour: (f: Facility) => RGB;
  selectedFacilityId: string | null;
  tilted: boolean;
  /** Context deck.gl layers (boundaries, cables, hazards, power), drawn above the grid. */
  contextLayers: Layer[];
  contextTooltip: (layerId: string, object: unknown) => string | null;
  imagery: RasterImagery | null;
  onViewChange: (view: MapView) => void;
  onMapClick: (latitude: number, longitude: number, picked: Picked | null) => void;
  onGridChange: (grid: { resolution: number; count: number; overview: boolean; cells: string[] }) => void;
  /** Choropleth fill for display cells (null = neutral "no layer" styling). */
  cellFill: ((h3: string) => [number, number, number, number]) | null;
  cellTooltip: (h3: string) => string | null;
  /** A prepared single-scene PNG (EPSG:4326) drawn at its bounds, under the labels. */
  scene: SceneImage | null;
  /** Building-assessment screening states for resolution-6 cells, drawn under project markers. */
  assessmentCells?: CellState[] | null;
  /** Ghost marker for a building placement preview (not its physical footprint). */
  preview?: { latitude: number; longitude: number; colour?: RGB } | null;
  /** A real example building dragged from the Build tab and dropped at this point. */
  onDropPreset?: (presetId: string, latitude: number, longitude: number) => void;
};

const isPresetDrag = (e: DragEvent) => Array.from(e.dataTransfer.types).includes(PRESET_DRAG_TYPE);

export default function WorldMap(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const basemapRef = useRef<maplibregl.LayerSpecification[]>([]);
  const [grid, setGrid] = useState<ViewportCells>({ resolution: 0, cells: [], overview: true });
  const [labelled, setLabelled] = useState<Facility[]>([]);
  const [stemM, setStemM] = useState(0);
  const [dropping, setDropping] = useState(false);

  // Keep latest callbacks without re-creating the map.
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current!,
      style: STYLE_URL,
      center: [10, 30],
      zoom: 1.6,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay);
    mapRef.current = map;
    overlayRef.current = overlay;

    // Debounced on moveend; a timer (not rAF) so it also runs in background tabs.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshGrid = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const b = map.getBounds();
        const next = viewportCells({
          west: b.getWest(),
          east: b.getEast(),
          south: b.getSouth(),
          north: b.getNorth(),
        });
        setGrid(next);
        const cur = propsRef.current;
        const stem = stemHeightM(map, cur.tilted);
        setStemM(stem);
        setLabelled(pickLabels(map, cur.facilities, cur.selectedFacilityId, stem));
        propsRef.current.onGridChange({
          resolution: next.resolution,
          count: next.cells.length,
          overview: next.overview,
          cells: next.cells,
        });
        const c = map.getCenter();
        propsRef.current.onViewChange({
          bounds: { west: b.getWest(), east: b.getEast(), south: b.getSouth(), north: b.getNorth() },
          zoom: map.getZoom(),
          centre: { lat: c.lat, lon: c.lng },
        });
      }, 60);
    };
    map.on("load", refreshGrid);
    map.on("load", () => {
      basemapRef.current = structuredClone(map.getStyle().layers);
      applyBasemapTheme(map, basemapRef.current, propsRef.current.theme);
    });
    map.on("moveend", refreshGrid);
    // The inspector and workspace panels resize the canvas without a window resize.
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(containerRef.current!);

    return () => {
      resize.disconnect();
      clearTimeout(timer);
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
      basemapRef.current = [];
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && basemapRef.current.length) applyBasemapTheme(map, basemapRef.current, props.theme);
  }, [props.theme]);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = props.crosshair ? "crosshair" : "";
  }, [props.crosshair]);

  // Tilted view: oblique camera with rotation. The basemap's own building-3d layer (OpenFreeMap,
// zoom >= 14) supplies building volumes; it is always on and only reads as 3D once tilted.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (props.tilted) {
      map.dragRotate.enable();
      map.touchZoomRotate.enableRotation();
      map.easeTo({ pitch: 55, duration: 800 });
    } else {
      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      map.easeTo({ pitch: 0, bearing: 0, duration: 800 });
    }
  }, [props.tilted]);

  // Re-pick labels when the facility set or selection changes (camera moves are handled on moveend).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const stem = stemHeightM(map, props.tilted);
    setStemM(stem);
    setLabelled(pickLabels(map, props.facilities, props.selectedFacilityId, stem));
  }, [props.facilities, props.selectedFacilityId, props.tilted]);

  useEffect(() => {
    const f = props.focus;
    if (!f || !mapRef.current) return;
    if (f.bbox) {
      const [w, s, e, n] = f.bbox;
      mapRef.current.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        { padding: 40, maxZoom: f.zoom ?? 12, speed: 1.6 },
      );
      return;
    }
    mapRef.current.flyTo({
      center: [f.longitude, f.latitude],
      zoom: Math.max(mapRef.current.getZoom(), f.zoom ?? 9),
      speed: 1.6,
    });
  }, [props.focus]);

  // Satellite imagery as a MapLibre raster source, beneath the basemap's labels and buildings.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const img = props.imagery;
    const apply = () => {
      if (map.getLayer(IMAGERY_SOURCE)) map.removeLayer(IMAGERY_SOURCE);
      if (map.getSource(IMAGERY_SOURCE)) map.removeSource(IMAGERY_SOURCE);
      if (!img) return;
      map.addSource(IMAGERY_SOURCE, {
        type: "raster",
        tiles: img.tiles,
        tileSize: 256,
        maxzoom: img.maxzoom,
        attribution: img.attribution,
      });
      const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol" || l.type === "fill-extrusion")?.id;
      map.addLayer(
        { id: IMAGERY_SOURCE, type: "raster", source: IMAGERY_SOURCE, paint: { "raster-opacity": img.opacity } },
        firstSymbol,
      );
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
    return () => {
      map.off("load", apply);
    };
    // Opacity changes are handled below without re-creating the source.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.imagery?.key]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const sc = props.scene;
    const apply = () => {
      if (map.getLayer(SCENE_SOURCE)) map.removeLayer(SCENE_SOURCE);
      if (map.getSource(SCENE_SOURCE)) map.removeSource(SCENE_SOURCE);
      if (!sc) return;
      const [w, s, e, n] = sc.bounds;
      map.addSource(SCENE_SOURCE, {
        type: "image",
        url: sc.url,
        coordinates: [
          [w, n],
          [e, n],
          [e, s],
          [w, s],
        ],
      });
      const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol" || l.type === "fill-extrusion")?.id;
      map.addLayer({ id: SCENE_SOURCE, type: "raster", source: SCENE_SOURCE, paint: { "raster-opacity": 1 } }, firstSymbol);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
    return () => {
      map.off("load", apply);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.scene?.id]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer(IMAGERY_SOURCE) && props.imagery) {
      map.setPaintProperty(IMAGERY_SOURCE, "raster-opacity", props.imagery.opacity);
    }
  }, [props.imagery?.opacity, props.imagery]);

  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    const { projects, selectedProjectId, selectedCell, facilities, facilityColour, selectedFacilityId, tilted } = props;
    const footprints = facilities.filter((f) => f.geometry.type !== "Point");
    const tip = tilted ? stemM : 0;
    const colourTrigger = [facilities, facilityColour];
    const dark = props.theme === "dark";
    const selectionLine: [number, number, number, number] = dark ? [150, 192, 255, 255] : [15, 23, 42, 255];

    const layers = [
      new H3HexagonLayer<string>({
        id: "grid",
        data: grid.cells,
        getHexagon: (d) => d,
        filled: true,
        stroked: props.showHexOutlines,
        extruded: false,
        highPrecision: true,
        // Neutral "no data" styling unless a baseline layer is active.
        getFillColor: props.cellFill ?? [89, 125, 175, 6],
        getLineColor: props.cellFill ? [51, 65, 85, 30] : dark ? [119, 151, 194, 25] : [86, 114, 151, 42],
        updateTriggers: { getFillColor: props.cellFill, getLineColor: [!!props.cellFill, dark] },
        lineWidthUnits: "pixels",
        getLineWidth: 1,
        pickable: true,
        autoHighlight: true,
        highlightColor: [59, 130, 246, 60],
      }),
      ...props.contextLayers,
      new H3HexagonLayer<CellState>({
        id: "assessment-cells",
        data: props.assessmentCells ?? [],
        getHexagon: (c) => c.h3Id,
        filled: true,
        stroked: props.showHexOutlines,
        extruded: false,
        highPrecision: true,
        getFillColor: (c) => [...STATE_COLOUR[c.state], 110],
        getLineColor: (c) => [...STATE_COLOUR[c.state], 200],
        lineWidthUnits: "pixels",
        getLineWidth: 1,
        pickable: true,
      }),
      new H3HexagonLayer<Project>({
        id: "project-cells",
        data: projects,
        getHexagon: (p) => p.h3Id,
        filled: true,
        stroked: props.showHexOutlines,
        extruded: false,
        highPrecision: true,
        getFillColor: (p) => [...typeColour(p.type), 60],
        getLineColor: (p) => [...typeColour(p.type), 220],
        lineWidthUnits: "pixels",
        getLineWidth: 2,
      }),
      new H3HexagonLayer<string>({
        id: "selected-cell",
        data: selectedCell ? [selectedCell] : [],
        getHexagon: (d) => d,
        filled: true,
        stroked: props.showHexOutlines,
        extruded: false,
        highPrecision: true,
        getFillColor: [37, 99, 235, 40],
        getLineColor: selectionLine,
        lineWidthUnits: "pixels",
        getLineWidth: 3,
      }),
      // Footprints as mapped in OSM. Extruded only by a tagged height; untagged stay flat.
      new GeoJsonLayer<Facility["properties"]>({
        id: "infra-footprints",
        data: footprints as never,
        filled: true,
        stroked: true,
        extruded: tilted,
        getElevation: (f) => f.properties.heightM ?? 0,
        getFillColor: (f) => [...facilityColour(f as Facility), f.id === selectedFacilityId ? 160 : 70],
        getLineColor: (f) => [...facilityColour(f as Facility), 255],
        lineWidthUnits: "pixels",
        getLineWidth: 1.5,
        pickable: true,
        updateTriggers: { getFillColor: [colourTrigger, selectedFacilityId], getLineColor: colourTrigger },
      }),
      new LineLayer<Facility>({
        id: "infra-stems",
        data: tilted ? facilities : [],
        getSourcePosition: (f) => [f.properties.lon, f.properties.lat, 0],
        getTargetPosition: (f) => [f.properties.lon, f.properties.lat, tip],
        getColor: (f) => [...facilityColour(f), 150],
        getWidth: 1.5,
        widthUnits: "pixels",
        updateTriggers: { getColor: colourTrigger, getTargetPosition: tip },
      }),
      new ScatterplotLayer<Facility>({
        id: "infra-points",
        data: facilities,
        getPosition: (f) => [f.properties.lon, f.properties.lat, tip],
        getFillColor: (f) => [...facilityColour(f), 255],
        getLineColor: (f) => (f.id === selectedFacilityId ? [255, 255, 255, 255] : [0, 0, 0, 255]),
        getRadius: (f) => (f.id === selectedFacilityId ? 8 : 4),
        radiusUnits: "pixels",
        radiusMinPixels: 3,
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: (f) => (f.id === selectedFacilityId ? 2.5 : 1.5),
        pickable: true,
        updateTriggers: {
          getPosition: tip,
          getFillColor: colourTrigger,
          getLineColor: selectedFacilityId,
          getRadius: selectedFacilityId,
          getLineWidth: selectedFacilityId,
        },
      }),
      new TextLayer<Facility>({
        id: "infra-labels",
        data: labelled,
        getPosition: (f) => [f.properties.lon, f.properties.lat, tip],
        getText: (f) => facilityTitle(f.properties),
        getColor: dark ? [216, 229, 247, 255] : [15, 23, 42, 255],
        getSize: 12,
        fontWeight: 600,
        getPixelOffset: [0, -12],
        getTextAnchor: "middle",
        getAlignmentBaseline: "bottom",
        characterSet: "auto",
        fontFamily: "Inter, system-ui, sans-serif",
        fontSettings: { sdf: true, fontSize: 64, buffer: 8 },
        outlineWidth: 2,
        outlineColor: dark ? [12, 24, 41, 245] : [255, 255, 255, 235],
        updateTriggers: { getPosition: tip },
      }),
      new ScatterplotLayer<Project>({
        id: "projects",
        data: projects,
        getPosition: (p) => [p.longitude, p.latitude],
        getFillColor: (p) => [...typeColour(p.type), 255],
        getLineColor: (p) => (p.id === selectedProjectId ? selectionLine : [255, 255, 255, 255]),
        getRadius: (p) => (p.id === selectedProjectId ? 9 : 6),
        radiusUnits: "pixels",
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: 2,
        pickable: true,
        updateTriggers: { getLineColor: [selectedProjectId, dark], getRadius: selectedProjectId },
      }),
      new ScatterplotLayer<{ latitude: number; longitude: number; colour?: RGB }>({
        id: "build-preview",
        data: props.preview ? [props.preview] : [],
        getPosition: (p) => [p.longitude, p.latitude],
        getFillColor: (p) => [...(p.colour ?? [37, 99, 235]), 90],
        getLineColor: selectionLine,
        getRadius: 11,
        radiusUnits: "pixels",
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: 2.5,
      }),
    ];

    overlay.setProps({
      layers,
      onClick: (info: PickingInfo) => {
        if (!info.coordinate) return;
        const [lng, lat] = info.coordinate;
        let layerId = info.layer?.id;
        let object = info.object;
        // The grid covers every pixel, so it always wins a radius pick. Re-pick without it so a
        // thin cable or power line a few pixels away still gets selected.
        // Assessment cells are a display overlay: clicks fall through to what lies beneath.
        const background = (id: string | undefined) => id === "grid" || id === "assessment-cells";
        if (background(layerId) || !object) {
          const alt = overlay.pickObject({
            x: info.x,
            y: info.y,
            radius: 6,
            layerIds: layers.map((l) => l.id).filter((id) => !background(id)),
          });
          if (alt?.object && alt.layer) {
            layerId = alt.layer.id;
            object = alt.object;
          }
        }
        const picked = layerId && !background(layerId) && object ? { layerId, object } : null;
        propsRef.current.onMapClick(lat, lng, picked);
      },
      getTooltip: ({ object, layer }: PickingInfo) => {
        if (!object || !layer) return null;
        if (layer.id === "projects") {
          const p = object as Project;
          return { text: `${p.name || typeLabel(p.type)}\n${typeLabel(p.type)}` };
        }
        if (layer.id === "assessment-cells") {
          return { text: `${STATE_LABEL[(object as CellState).state]}\nScreening result for this cell` };
        }
        if (layer.id === "infra-points" || layer.id === "infra-footprints") {
          const p = (object as Facility).properties;
          const company = p.operator ?? p.owner;
          const rating = p.powerRatings.find((r) => r.kw !== null);
          const lines = [facilityTitle(p), [p.layer === "datacenters" ? "Datacenter" : "Dam", company].filter(Boolean).join(" · ")];
          if (rating?.kw != null) lines.push(formatKw(rating.kw));
          return { text: lines.join("\n") };
        }
        const context = propsRef.current.contextTooltip(layer.id, object);
        if (context) return { text: context };
        if (layer.id === "grid") {
          const id = object as string;
          const value = propsRef.current.cellTooltip(id);
          return value ? { text: value } : null;
        }
        return null;
      },
    });
  }, [
    grid,
    labelled,
    stemM,
    props.projects,
    props.selectedProjectId,
    props.selectedCell,
    props.facilities,
    props.facilityColour,
    props.selectedFacilityId,
    props.tilted,
    props.contextLayers,
    props.cellFill,
    props.assessmentCells,
    props.preview,
    props.theme,
    props.showHexOutlines,
  ]);

  // Preset drag-and-drop. HTML5 drag events bubble from the MapLibre and deck.gl canvases to the
  // container; neither library handles them, so nothing is swallowed.
  const dropHandlers = props.onDropPreset
    ? {
        onDragEnter: (e: DragEvent) => {
          if (!isPresetDrag(e)) return;
          e.preventDefault();
          setDropping(true);
        },
        onDragOver: (e: DragEvent) => {
          if (!isPresetDrag(e)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          if (!dropping) setDropping(true);
        },
        onDragLeave: (e: DragEvent) => {
          // Moving between the map's own child elements also fires dragleave.
          const to = e.relatedTarget as Node | null;
          if (to && containerRef.current?.contains(to)) return;
          setDropping(false);
        },
        onDrop: (e: DragEvent) => {
          setDropping(false);
          if (!isPresetDrag(e)) return;
          e.preventDefault();
          const id = e.dataTransfer.getData(PRESET_DRAG_TYPE);
          const map = mapRef.current;
          const el = containerRef.current;
          if (!id || !map || !el) return;
          const rect = el.getBoundingClientRect();
          const { lng, lat } = map.unproject([e.clientX - rect.left, e.clientY - rect.top]);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          propsRef.current.onDropPreset?.(id, Math.max(-90, Math.min(90, lat)), normaliseLongitude(lng));
        },
      }
    : {};

  // A drag cancelled with Escape or dropped elsewhere never reaches the map: clear the highlight.
  useEffect(() => {
    if (!dropping) return;
    const clear = () => setDropping(false);
    window.addEventListener("dragend", clear);
    window.addEventListener("drop", clear);
    return () => {
      window.removeEventListener("dragend", clear);
      window.removeEventListener("drop", clear);
    };
  }, [dropping]);

  return (
    <>
      <div ref={containerRef} className="map" {...dropHandlers} />
      {dropping && (
        <div className="map-drop" aria-hidden="true">
          <span>Drop to preview here</span>
        </div>
      )}
    </>
  );
}
