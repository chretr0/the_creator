/**
 * What the Moon workspace can switch on: LROC WMS overlays (MOON-MAP-01), map views, and the P0
 * catalogue layers (CLAUDE-Moon-Data-Sources.md) that are not ingested yet.
 */
import type { RasterImagery } from "../components/WorldMap";
import { LROC_WAC_MAXZOOM, lrocWmsTiles } from "../bodies/moon";
import type { IconName } from "../components/Icon";

/* ---------------- LROC WMS overlays ---------------- */

export type OverlayId = "names" | "hillshade" | "relief" | "psr" | "mare_wms";

export type OverlayDef = {
  id: OverlayId;
  /** Lunaserv layer name. */
  layer: string;
  label: string;
  detail: string;
  /** An opaque image blended over the mosaic (gets an opacity slider), rather than labels or outlines. */
  blend: boolean;
  defaultOn: boolean;
  defaultOpacity: number;
  maxzoom: number;
};

/**
 * Checked with a GetMap tile each (2026-11-08). `luna_polar_illumination` is left out: it covers
 * 88–90° only, beyond Web Mercator's ±85.05° edge, so every tile comes back empty.
 * `mare_wms` is the fallback when the prepared (named, hoverable) mare outlines are unavailable.
 */
export const OVERLAYS: OverlayDef[] = [
  {
    id: "hillshade",
    layer: "luna_wac_dtm_hillshade",
    label: "Hillshade",
    detail: "Relief shading from the WAC GLD100 terrain model",
    blend: true,
    defaultOn: false,
    defaultOpacity: 0.45,
    maxzoom: LROC_WAC_MAXZOOM,
  },
  {
    id: "relief",
    layer: "luna_wac_dtm",
    label: "Colour shaded relief",
    detail: "GLD100 heights as colour: low basins blue, high terrain red",
    blend: true,
    defaultOn: false,
    defaultOpacity: 0.6,
    maxzoom: LROC_WAC_MAXZOOM,
  },
  {
    id: "psr",
    layer: "luna_psr_81s",
    label: "Permanently shadowed regions",
    detail: "LOLA outlines, 81–90° S (visible to 85° S)",
    blend: false,
    defaultOn: false,
    defaultOpacity: 1,
    maxzoom: 12,
  },
  {
    id: "mare_wms",
    layer: "luna_mare",
    label: "Mare outlines",
    detail: "LROC mare boundaries, 65° S–65° N",
    blend: false,
    defaultOn: false,
    defaultOpacity: 0.9,
    maxzoom: 12,
  },
  {
    id: "names",
    layer: "luna_nomenclature",
    label: "Feature names",
    detail: "IAU names drawn by LROC: major regions from afar, every feature closer in",
    blend: false,
    defaultOn: true,
    defaultOpacity: 1,
    // Labels are rendered for the requested scale, so keep fetching them as you zoom in.
    maxzoom: 12,
  },
];

export type OverlayState = Record<OverlayId, { on: boolean; opacity: number }>;

export function defaultOverlayState(): OverlayState {
  return Object.fromEntries(OVERLAYS.map((o) => [o.id, { on: o.defaultOn, opacity: o.defaultOpacity }])) as OverlayState;
}

export const LROC_OVERLAY_ATTRIBUTION = "LROC overlays: NASA/GSFC/Arizona State University";

/**
 * `luna_nomenclature` fills every 256-px tile with a dozen labels whatever the scale, which buries the
 * whole-Moon view. Below this map zoom the names overlay uses LROC's overview label set instead
 * (`luna_wil_c_nom`: the major maria and basins only).
 */
export const NAMES_DETAIL_ZOOM = 3;
const NAMES_OVERVIEW_LAYER = "luna_wil_c_nom";

/** The Lunaserv layer drawn for an overlay at a map zoom. */
export function overlayLayer(o: OverlayDef, zoom: number | null): string {
  return o.id === "names" && zoom !== null && zoom < NAMES_DETAIL_ZOOM ? NAMES_OVERVIEW_LAYER : o.layer;
}

/** The overlays to draw, bottom to top (OVERLAYS order), as WorldMap raster imagery. */
export function rasterOverlays(state: OverlayState, exclude: OverlayId[] = [], zoom: number | null = null): RasterImagery[] {
  return OVERLAYS.filter((o) => state[o.id]?.on && !exclude.includes(o.id)).map((o) => {
    const layer = overlayLayer(o, zoom);
    return {
      key: `lroc:${layer}`,
      tiles: lrocWmsTiles(layer, true),
      maxzoom: o.maxzoom,
      opacity: state[o.id].opacity,
      attribution: LROC_OVERLAY_ATTRIBUTION,
    };
  });
}

/* ---------------- Map views ---------------- */

export type MoonView = { id: string; label: string; bbox: [number, number, number, number]; maxZoom?: number };

/** Quick views. The south pole view stops at 85° S, the edge of a Web Mercator map. */
export const MOON_VIEWS: MoonView[] = [
  { id: "near", label: "Near side", bbox: [-90, -60, 90, 60] },
  { id: "far", label: "Far side", bbox: [90, -60, 270, 60] },
  { id: "south", label: "South pole", bbox: [-60, -85.05, 60, -76], maxZoom: 6 },
  { id: "tranquillitatis", label: "Apollo region", bbox: [-10, -10, 40, 30], maxZoom: 6 },
];

/* ---------------- Coming next ---------------- */

export type ComingItem = { id: string; name: string; coverage: string };
export type ComingGroup = { id: string; label: string; icon: IconName; why: string; items: ComingItem[] };

/** P0 layers from the Moon catalogue that the app does not serve yet (§5–§7, §4.2). */
export const COMING_NEXT: ComingGroup[] = [
  {
    id: "sunlight",
    label: "Sunlight",
    icon: "sun",
    why: "Solar power, night length and line of sight to Earth",
    items: [
      { id: "MOON-SUN-01", name: "Average solar illumination", coverage: "LOLA · 65–90°" },
      { id: "MOON-SUN-02", name: "Permanently shadowed regions", coverage: "LOLA polygons · poles" },
      { id: "MOON-SUN-03", name: "Earth visibility", coverage: "LOLA · 65–90°" },
      { id: "MOON-SUN-04", name: "Sunlight & longest night", coverage: "Computed · global" },
    ],
  },
  {
    id: "temperature",
    label: "Temperature",
    icon: "thermometer",
    why: "Day–night swing and the cold traps that hold ice",
    items: [
      { id: "MOON-THERM-01", name: "Surface temperature by local time", coverage: "Diviner · global" },
      { id: "MOON-THERM-02", name: "Seasonal polar temperatures", coverage: "Diviner · 80–90°" },
      { id: "MOON-THERM-03", name: "Rock abundance", coverage: "Diviner · ±80°" },
    ],
  },
  {
    id: "ice",
    label: "Water ice",
    icon: "water",
    why: "Where ice is stable and how deep",
    items: [
      { id: "MOON-ICE-01", name: "Ice stability depth", coverage: "Diviner PRP · poles" },
      { id: "MOON-ICE-02", name: "Hydrogen", coverage: "Lunar Prospector · global" },
      { id: "MOON-ICE-03", name: "South-polar PSR volatiles", coverage: "Per shadowed region" },
    ],
  },
  {
    id: "composition",
    label: "Composition",
    icon: "pickaxe",
    why: "Oxygen, metals and rare-earth feedstock in the regolith",
    items: [
      { id: "MOON-COMP-01", name: "Thorium, FeO and other elements", coverage: "Lunar Prospector · global" },
      { id: "MOON-COMP-02", name: "Titanium dioxide (TiO₂)", coverage: "LROC WAC · ±70°" },
      { id: "MOON-COMP-03", name: "Mineralogy", coverage: "Diviner · ±70°" },
    ],
  },
  {
    id: "terrain",
    label: "Terrain detail",
    icon: "mountain",
    why: "Slope at landing-site scale",
    items: [{ id: "MOON-TOPO-01", name: "Slope (SLDEM2015)", coverage: "LOLA + Kaguya · ±60°" }],
  },
];

/** Groups with the items whose source is not served yet (an H3 layer citing it counts as served). */
export function pendingGroups(servedSourceIds: Iterable<string>, groups: ComingGroup[] = COMING_NEXT): ComingGroup[] {
  const served = new Set(servedSourceIds);
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => !served.has(i.id)) }))
    .filter((g) => g.items.length > 0);
}

/** The short "Not measured yet" line for the inspector, e.g. "Sunlight, temperature, water ice and composition". */
export function pendingSummary(groups: ComingGroup[]): string {
  const names = groups.map((g, i) => (i === 0 ? g.label : g.label.toLocaleLowerCase()));
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
