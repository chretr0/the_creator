/**
 * deck.gl layers for the Moon: landed objects, planned missions and Artemis regions, heritage keep-out
 * rings and mare outlines, plus the colour ramps for Moon H3 layers.
 *
 * deck.gl assumes Earth's radius for metres, so nothing here uses metre radii: markers are sized in
 * pixels and every circle on the ground (the keep-out rings) arrives as a lon/lat polygon computed on
 * the Moon sphere by the backend.
 */
import type { Layer } from "@deck.gl/core";
import { GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { MERCATOR_MAX_LAT } from "../lib/h3grid";
import { DIVERGING, SEQUENTIAL } from "../lib/datalayers";
import type { KeepoutFeature, MareFeature, MissionFeature, MoonSite, MoonSiteKind, MoonH3Layer } from "./api";
import { formatDistanceKm, formatMeasure, UNKNOWN } from "./geo";

export type RGB = [number, number, number];
export type RGBA = [number, number, number, number];

/** Layer ids handed to WorldMap's contextLayers (and back in its click/tooltip callbacks). */
export const MOON_LAYER_IDS = {
  sitesHalo: "moon-sites-halo",
  sites: "moon-sites",
  siteLabels: "moon-site-labels",
  missions: "moon-missions",
  regions: "moon-artemis-regions",
  keepout: "moon-keepout",
  mare: "moon-mare",
} as const;

/* ---------------- Landed objects ---------------- */

export const SITE_KINDS: MoonSiteKind[] = ["crewed_landing", "soft_landing", "rover", "impact", "retroreflector", "other"];

export const SITE_KIND_META: Record<MoonSiteKind, { label: string; plural: string; colour: RGB; radius: number }> = {
  crewed_landing: { label: "Crewed landing", plural: "Crewed landings", colour: [255, 200, 87], radius: 7 },
  soft_landing: { label: "Robotic landing", plural: "Robotic landings", colour: [96, 165, 250], radius: 5 },
  rover: { label: "Rover", plural: "Rovers", colour: [52, 211, 153], radius: 4.5 },
  impact: { label: "Impact site", plural: "Impact sites", colour: [251, 113, 133], radius: 3.5 },
  retroreflector: { label: "Retroreflector", plural: "Retroreflectors", colour: [196, 181, 253], radius: 4 },
  other: { label: "Other object", plural: "Other objects", colour: [180, 190, 205], radius: 3.5 },
};

export function siteKindMeta(kind: string | null | undefined) {
  return SITE_KIND_META[(kind ?? "other") as MoonSiteKind] ?? SITE_KIND_META.other;
}

export const rgb = (c: RGB | RGBA) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;

/** Count of sites per kind, in legend order. */
export function countByKind(sites: MoonSite[]): { kind: MoonSiteKind; count: number }[] {
  const m = new Map<MoonSiteKind, number>();
  for (const s of sites) {
    const k = (SITE_KIND_META[s.properties.kind] ? s.properties.kind : "other") as MoonSiteKind;
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return SITE_KINDS.filter((k) => m.has(k)).map((kind) => ({ kind, count: m.get(kind)! }));
}

/** Crewed first, then landings before impacts, then by date (unknown last) and name. */
export function sortSites(sites: MoonSite[]): MoonSite[] {
  const order = (k: string) => {
    const i = SITE_KINDS.indexOf(k as MoonSiteKind);
    return i < 0 ? SITE_KINDS.length : i;
  };
  return [...sites].sort(
    (a, b) =>
      order(a.properties.kind) - order(b.properties.kind) ||
      (a.properties.date ?? "9999").localeCompare(b.properties.date ?? "9999") ||
      a.properties.name.localeCompare(b.properties.name),
  );
}

export const siteLonLat = (s: MoonSite): [number, number] => [s.geometry.coordinates[0], s.geometry.coordinates[1]];

/* ---------------- Missions ---------------- */

export const MISSION_COLOUR: Record<"artemis_region" | "planned_mission", RGB> = {
  artemis_region: [56, 189, 248],
  planned_mission: [216, 160, 255],
};

export type MissionMarker = { id: string; lon: number; lat: number; feature: MissionFeature };

/** Mean of a polygon's outer-ring vertices (the closing vertex once): fine for ~15 km boxes. */
function ringCentre(ring: number[][]): [number, number] | null {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  if (!pts.length) return null;
  const lon = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const lat = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return [lon, lat];
}

/** Where a mission is drawn as a marker: its point, or the centre of its region box. Null geometry → none. */
export function missionPosition(f: MissionFeature): [number, number] | null {
  const g = f.geometry;
  if (!g) return null;
  if (g.type === "Point") return [g.coordinates[0], g.coordinates[1]];
  if (g.type === "Polygon") return ringCentre(g.coordinates[0] ?? []);
  if (g.type === "MultiPolygon") return ringCentre(g.coordinates[0]?.[0] ?? []);
  return null;
}

export function missionMarkers(missions: MissionFeature[]): MissionMarker[] {
  const out: MissionMarker[] = [];
  for (const f of missions) {
    const p = missionPosition(f);
    if (p) out.push({ id: f.properties.id, lon: p[0], lat: p[1], feature: f });
  }
  return out;
}

/** True when Web Mercator cannot draw the point (|lat| > 85.05°, e.g. most Artemis regions). */
export const beyondMapEdge = (lat: number) => Math.abs(lat) > MERCATOR_MAX_LAT;

/* ---------------- Tooltips ---------------- */

export function siteTooltip(s: MoonSite): string {
  const p = s.properties;
  const line2 = [siteKindMeta(p.kind).label, p.mission && p.mission !== p.name ? p.mission : null, p.date].filter(Boolean).join(" · ");
  return `${p.name}\n${line2}${p.heritage ? `\nHeritage keep-out: ${p.heritage === "landing" ? "2.0 km" : "0.5 km"}` : ""}`;
}

export function missionTooltip(f: MissionFeature): string {
  const p = f.properties;
  const kind = p.kind === "artemis_region" ? "Artemis candidate region" : "Planned mission";
  const when = p.date ? `${p.date} (as published${p.asOf ? `, as of ${p.asOf}` : ""})` : "Date unknown";
  return `${p.name}\n${kind}${p.target && p.kind !== "artemis_region" ? ` · ${p.target}` : ""}\n${when}${p.approximate ? "\nApproximate location" : ""}`;
}

export function keepoutTooltip(f: KeepoutFeature): string {
  const p = f.properties;
  return `Heritage keep-out · ${p.siteName}\nNo landing within ${formatDistanceKm(p.radiusM / 1000)} (NASA 2011 recommendation)`;
}

export const mareTooltip = (f: MareFeature) => `${f.properties.name || "Unnamed mare"}\nMare (LROC mare map)`;

/** WorldMap contextTooltip for the Moon layers; null for anything else (e.g. the grid). */
export function moonTooltip(layerId: string, object: unknown): string | null {
  switch (layerId) {
    case MOON_LAYER_IDS.sites:
      return siteTooltip(object as MoonSite);
    case MOON_LAYER_IDS.missions:
      return missionTooltip((object as MissionMarker).feature);
    case MOON_LAYER_IDS.regions:
      return missionTooltip(object as MissionFeature);
    case MOON_LAYER_IDS.keepout:
      return keepoutTooltip(object as KeepoutFeature);
    case MOON_LAYER_IDS.mare:
      return mareTooltip(object as MareFeature);
    default:
      return null;
  }
}

/* ---------------- Layer builders ---------------- */

export type MoonLayerInput = {
  sites: MoonSite[] | null;
  missions: MissionFeature[] | null;
  keepout: KeepoutFeature[] | null;
  mare: MareFeature[] | null;
  show: { sites: boolean; missions: boolean; keepout: boolean; mare: boolean };
  selectedId: string | null;
};

const LABEL_FONT = "Inter, system-ui, sans-serif";

export function buildMoonLayers(input: MoonLayerInput): Layer[] {
  const { show, selectedId } = input;
  const layers: Layer[] = [];

  if (show.mare && input.mare?.length) {
    layers.push(
      new GeoJsonLayer<MareFeature["properties"]>({
        id: MOON_LAYER_IDS.mare,
        data: input.mare as never,
        filled: false,
        stroked: true,
        getLineColor: [226, 232, 240, 120],
        lineWidthUnits: "pixels",
        getLineWidth: 1,
        pickable: true,
      }),
    );
  }

  if (show.keepout && input.keepout?.length) {
    layers.push(
      new GeoJsonLayer<KeepoutFeature["properties"]>({
        id: MOON_LAYER_IDS.keepout,
        data: input.keepout as never,
        filled: true,
        stroked: true,
        getFillColor: (f) => (f.properties.rule === "heritage_landing" ? [251, 113, 133, 46] : [251, 146, 60, 40]),
        getLineColor: (f) => (f.properties.rule === "heritage_landing" ? [251, 113, 133, 220] : [251, 146, 60, 200]),
        lineWidthUnits: "pixels",
        getLineWidth: 1.5,
        pickable: true,
      }),
    );
  }

  if (show.missions && input.missions?.length) {
    const regions = input.missions.filter((f) => f.properties.kind === "artemis_region" && f.geometry && f.geometry.type !== "Point");
    layers.push(
      new GeoJsonLayer<MissionFeature["properties"]>({
        id: MOON_LAYER_IDS.regions,
        data: regions as never,
        filled: true,
        stroked: true,
        getFillColor: (f) => [...MISSION_COLOUR.artemis_region, f.properties.id === selectedId ? 90 : 40] as RGBA,
        getLineColor: [...MISSION_COLOUR.artemis_region, 230] as RGBA,
        lineWidthUnits: "pixels",
        getLineWidth: (f) => (f.properties.id === selectedId ? 3 : 1.5),
        pickable: true,
        updateTriggers: { getFillColor: selectedId, getLineWidth: selectedId },
      }),
      new ScatterplotLayer<MissionMarker>({
        id: MOON_LAYER_IDS.missions,
        data: missionMarkers(input.missions),
        getPosition: (m) => [m.lon, m.lat],
        getFillColor: (m) => [...(MISSION_COLOUR[m.feature.properties.kind] ?? MISSION_COLOUR.planned_mission), 60] as RGBA,
        getLineColor: (m) => (m.id === selectedId ? [255, 255, 255, 255] : ([...(MISSION_COLOUR[m.feature.properties.kind] ?? MISSION_COLOUR.planned_mission), 255] as RGBA)),
        getRadius: (m) => (m.id === selectedId ? 9 : 6),
        radiusUnits: "pixels",
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: (m) => (m.id === selectedId ? 2.5 : 2),
        pickable: true,
        updateTriggers: { getLineColor: selectedId, getRadius: selectedId, getLineWidth: selectedId },
      }),
    );
  }

  if (show.sites && input.sites?.length) {
    const crewed = input.sites.filter((s) => s.properties.kind === "crewed_landing");
    layers.push(
      new ScatterplotLayer<MoonSite>({
        id: MOON_LAYER_IDS.sitesHalo,
        data: crewed,
        getPosition: siteLonLat,
        getFillColor: [...SITE_KIND_META.crewed_landing.colour, 55] as RGBA,
        getRadius: 13,
        radiusUnits: "pixels",
        stroked: false,
        pickable: false,
      }),
      new ScatterplotLayer<MoonSite>({
        id: MOON_LAYER_IDS.sites,
        data: input.sites,
        getPosition: siteLonLat,
        getFillColor: (s) => [...siteKindMeta(s.properties.kind).colour, 255] as RGBA,
        getLineColor: (s) =>
          s.properties.id === selectedId ? [255, 255, 255, 255] : s.properties.kind === "crewed_landing" ? [255, 255, 255, 230] : [0, 0, 0, 230],
        getRadius: (s) => (s.properties.id === selectedId ? 9 : siteKindMeta(s.properties.kind).radius),
        radiusUnits: "pixels",
        radiusMinPixels: 3,
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: (s) => (s.properties.id === selectedId ? 2.5 : 1.25),
        pickable: true,
        updateTriggers: { getLineColor: selectedId, getRadius: selectedId, getLineWidth: selectedId },
      }),
      new TextLayer<MoonSite>({
        id: MOON_LAYER_IDS.siteLabels,
        data: crewed,
        getPosition: siteLonLat,
        getText: (s) => s.properties.mission || s.properties.name,
        getColor: [255, 236, 190, 255],
        getSize: 12,
        fontWeight: 600,
        getPixelOffset: [0, -15],
        getTextAnchor: "middle",
        getAlignmentBaseline: "bottom",
        characterSet: "auto",
        fontFamily: LABEL_FONT,
        fontSettings: { sdf: true, fontSize: 64, buffer: 8 },
        outlineWidth: 2,
        outlineColor: [0, 0, 0, 235],
        pickable: false,
      }),
    );
  }
  return layers;
}

/* ---------------- H3 colour ramps ---------------- */

const hex = (h: string): RGB => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

/** Elevation: deep basins (indigo) → plains (teal) → highlands (amber) → peaks (near white). */
export const TERRAIN = ["#2d1b69", "#2c4fa8", "#1f8fb3", "#36b38a", "#b9cf5b", "#eca13b", "#d9573a", "#f5ede4"].map(hex);

export const PALETTES: Record<string, RGB[]> = { terrain: TERRAIN, sequential: SEQUENTIAL, diverging: DIVERGING };

export function paletteFor(name: string | null | undefined): RGB[] {
  return PALETTES[name ?? ""] ?? SEQUENTIAL;
}

/** Colour at position t (clamped to 0–1) along evenly spaced stops. */
export function rampColour(stops: RGB[], t: number): RGB {
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)) as RGB;
}

export type MoonScale = {
  domain: [number, number];
  stops: RGB[];
  /** Null for a missing or non-finite value: drawn as "No data", never as the low end. */
  colour: (v: number | null | undefined) => RGB | null;
};

/** A linear scale over the layer's published range (stable while panning), or `fallback` from the data. */
export function moonScale(layer: Pick<MoonH3Layer, "range" | "palette">, fallback: [number, number] | null = null): MoonScale | null {
  const r = layer.range && layer.range.length === 2 && layer.range.every(Number.isFinite) ? layer.range : fallback;
  if (!r) return null;
  const [lo, hi] = r;
  const stops = paletteFor(layer.palette);
  return {
    domain: [lo, hi],
    stops,
    colour: (v) => (v == null || !Number.isFinite(v) ? null : rampColour(stops, hi === lo ? 0.5 : (v - lo) / (hi - lo))),
  };
}

/** Min and max of the finite values, or null when there are none. */
export function valueRange(values: Iterable<number | null | undefined>): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v == null || !Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : null;
}

export const NO_DATA_FILL: RGBA = [148, 163, 184, 26];

/** Grid tooltip for an H3 layer value; `served` notes a coarser ancestor standing in for the cell. */
export function h3ValueTooltip(layer: Pick<MoonH3Layer, "name" | "unit">, value: number | null, cellRes: number, served: number | undefined): string {
  const v = value === null ? `${UNKNOWN} (no data)` : formatMeasure(value, layer.unit);
  const note = served !== undefined && served < cellRes ? `\nResolution-${served} average (the finest this layer has)` : "";
  return `${layer.name}: ${v}${note}`;
}
