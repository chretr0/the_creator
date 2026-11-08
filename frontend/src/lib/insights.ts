/**
 * Turns a cell profile into the plain, source-free location insights shown in the inspector:
 * dataset names without provider tags, no QA/provenance values, layers without data set aside.
 */
import type { CellProfile, ProfileValue } from "./datalayers";

export type ProfileLayer = CellProfile["layers"][number];

/** Provider, product and mission names that only say where a number came from. */
const SOURCE_WORDS =
  /\b(GHSL|WorldPop|VIIRS|Copernicus|DEM|ESA|WorldCover|ERA5(-Land)?|CAMS|Sentinel(-\dP?)?|GRACE|mascons|DA|SWOT|GEDI|L\d[A-B]?|MODIS|ECOSTRESS|EMIT|Aqueduct|\d\.\d|USGS|MRDS|HydroRIVERS|HydroBASINS|NASA|NOAA|SoilGrids|WRI)\b/i;

/**
 * "Population (GHSL 2025)" → "Population · 2025", "Elevation (Copernicus DEM)" → "Elevation",
 * "Air temperature (2 m)" stays as it is. A year is kept so 2024 data reads apart from long-term means.
 */
export function cleanLayerName(name: string): string {
  const cleaned = name
    .replace(/\s*\(([^)]*)\)/g, (whole, inner: string) => {
      if (!SOURCE_WORDS.test(inner)) return whole;
      const year = inner.match(/\b(19|20)\d{2}\b/);
      return year ? ` · ${year[0]}` : "";
    })
    // A leading product name: "Aqueduct 4.0 baseline water risk" → "Baseline water risk".
    .replace(/^(Aqueduct(\s+\d\.\d)?|USGS|NASA|NOAA)\s+/i, "")
    .trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/** Quality and provenance values (pixel counts, standard errors) rather than facts about the place. */
export function isMetaValue(v: ProfileValue): boolean {
  return v.units === "pixels" || /standard error|pixels used/i.test(v.label);
}

/** Attributes worth showing: drops the long price "basis" notes and unit/source bookkeeping. */
export function visibleAttributes(layer: ProfileLayer) {
  return (layer.attributes ?? []).filter(
    (a) => !/basis|unit|source|licen[cs]e/i.test(`${a.key} ${a.label}`) && !SOURCE_WORDS.test(a.label),
  );
}

export const isMonthly = (v: ProfileValue) => /-\d{2}$/.test(v.slice);

export function hasData(layer: ProfileLayer): boolean {
  return layer.values.some((v) => !isMetaValue(v) && v.display !== null && v.display !== undefined);
}

/** Sections in reading order; anything new from the API lands after these, alphabetically. */
export const CATEGORY_ORDER = [
  "Solar & climate",
  "Prices",
  "Water",
  "Terrain & land cover",
  "People & settlement",
  "Air quality",
  "Vegetation",
  "Soil",
  "Hazards",
  "Geology",
];

export function groupByCategory(layers: ProfileLayer[]): [string, ProfileLayer[]][] {
  const m = new Map<string, ProfileLayer[]>();
  for (const l of layers) m.set(l.category, [...(m.get(l.category) ?? []), l]);
  const rank = (c: string) => {
    const i = CATEGORY_ORDER.indexOf(c);
    return i === -1 ? CATEGORY_ORDER.length : i;
  };
  return [...m.entries()].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** The few numbers that describe a site at a glance, in display order, when the profile has them. */
export const GLANCE = [
  { layer: "solar_ghi", label: "Sunshine", slice: "clim-ann" },
  { layer: "air_temperature", label: "Avg temperature", slice: "clim-ann" },
  { layer: "precipitation", label: "Rainfall", slice: "clim-ann" },
  { layer: "electricity_price", label: "Power price", slice: "business" },
  { layer: "water_stress", label: "Water stress", slice: "category" },
  { layer: "elevation", label: "Elevation", slice: "mean" },
  { layer: "population_ghsl", label: "Population", slice: "2025" },
] as const;
