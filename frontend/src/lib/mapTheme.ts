import type { LayerSpecification, Map as LibreMap } from "maplibre-gl";
import type { Theme } from "./theme";

type PaintName = Parameters<LibreMap["setPaintProperty"]>[1];
type PaintValue = Parameters<LibreMap["setPaintProperty"]>[2];

/** Palette overrides for the original basemap only. Data and satellite layers keep their colours. */
export function basemapPaint(layer: LayerSpecification, theme: Theme): Record<string, unknown> {
  const source = "source-layer" in layer ? layer["source-layer"] ?? "" : "";
  let night: Record<string, unknown> = {};
  switch (layer.type) {
    case "background":
      night = { "background-color": "#121f31" };
      break;
    case "fill": {
      const colour = source === "water" ? "#0a192b"
        : source === "building" ? "#26374d"
        : /park|wood|forest|grass/.test(layer.id) ? "#1b3035"
        : /sand|beach/.test(layer.id) ? "#2c303b" : "#18273a";
      night = { "fill-color": colour, "fill-outline-color": colour };
      break;
    }
    case "line":
      night = { "line-color": source === "waterway" ? "#20435d"
        : source === "boundary" ? "#52647c"
        : /casing|outline|tunnel/.test(layer.id) ? "#142034" : "#354a64" };
      break;
    case "symbol":
      // Road shields are light sprite images: their overlaid route numbers must stay dark.
      night = layer.id.includes("shield")
        ? { "text-color": layer.paint?.["text-color"] ?? "#18253b", "text-halo-color": layer.paint?.["text-halo-color"] ?? "#ffffff" }
        : { "text-color": "#c1cfe2", "text-halo-color": "#121f31" };
      break;
    case "fill-extrusion":
      night = { "fill-extrusion-color": "#2a3e57" };
      break;
    case "hillshade":
      night = { "hillshade-shadow-color": "#060d19", "hillshade-highlight-color": "#34465b", "hillshade-accent-color": "#1a2b40" };
      break;
    case "raster":
      // The basemap's Natural Earth relief, not the separately added satellite/data rasters.
      night = { "raster-brightness-max": 0.22, "raster-saturation": -0.7 };
      break;
  }
  if (theme === "dark") return night;

  // Restore expressions and unset properties too, so a round trip does not flatten the day style.
  const original = layer.paint as Record<string, unknown> | undefined;
  const day = Object.fromEntries(Object.keys(night).map((key) => [key, original?.[key] ?? null]));
  if (layer.type === "background") day["background-color"] = "#f4f6f5";
  if (layer.type === "fill" && source === "water") day["fill-color"] = "#c9e1ef";
  return day;
}

export function applyBasemapTheme(map: LibreMap, originalLayers: LayerSpecification[], theme: Theme) {
  for (const layer of originalLayers) {
    if (!map.getLayer(layer.id)) continue;
    for (const [property, value] of Object.entries(basemapPaint(layer, theme))) {
      map.setPaintProperty(layer.id, property as PaintName, value as PaintValue);
    }
  }
}
