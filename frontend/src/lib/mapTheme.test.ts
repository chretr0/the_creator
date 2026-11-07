import { describe, expect, it, vi } from "vitest";
import type { LayerSpecification, Map as LibreMap } from "maplibre-gl";
import { applyBasemapTheme, basemapPaint } from "./mapTheme";

describe("basemap theme changes", () => {
  it("restores day expressions and properties that were originally unset", () => {
    const layer: LayerSpecification = {
      id: "landcover", type: "fill", source: "openmaptiles", "source-layer": "landcover",
      paint: { "fill-color": ["match", ["get", "class"], "wood", "#aacbaa", "#eee"], "fill-opacity": 0.7 },
    };
    const before = structuredClone(layer);
    expect(basemapPaint(layer, "dark")["fill-color"]).not.toEqual(layer.paint?.["fill-color"]);
    expect(basemapPaint(layer, "light")).toEqual({ "fill-color": layer.paint?.["fill-color"], "fill-outline-color": null });
    expect(layer).toEqual(before);
  });

  it("keeps the existing blue water palette in day mode", () => {
    expect(basemapPaint({ id: "water", type: "fill", source: "osm", "source-layer": "water" }, "light")["fill-color"]).toBe("#c9e1ef");
  });

  it("keeps route numbers legible on the basemap's light road-shield sprites", () => {
    const layer: LayerSpecification = { id: "highway-shield-non-us", type: "symbol", source: "osm" };
    expect(basemapPaint(layer, "dark")["text-color"]).toBe("#18253b");
    expect(basemapPaint(layer, "light")["text-color"]).toBeNull();
  });

  it("only updates captured basemap layers, leaving scientific rasters and camera untouched", () => {
    const setPaintProperty = vi.fn();
    const map = { getLayer: vi.fn(() => ({})), setPaintProperty, setStyle: vi.fn(), flyTo: vi.fn() };
    const original: LayerSpecification[] = [
      { id: "background", type: "background" },
      { id: "natural_earth", type: "raster", source: "relief", paint: { "raster-opacity": 0.6 } },
    ];
    applyBasemapTheme(map as unknown as LibreMap, original, "dark");
    expect(setPaintProperty.mock.calls.every(([id]) => ["background", "natural_earth"].includes(id))).toBe(true);
    expect(setPaintProperty).toHaveBeenCalledWith("natural_earth", "raster-brightness-max", 0.22);
    expect(map.setStyle).not.toHaveBeenCalled();
    expect(map.flyTo).not.toHaveBeenCalled();
    expect(basemapPaint(original[1], "light")).toEqual({ "raster-brightness-max": null, "raster-saturation": null });
  });
});
