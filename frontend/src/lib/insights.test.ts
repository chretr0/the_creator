import { describe, expect, it } from "vitest";
import { cleanLayerName, groupByCategory, hasData, isMetaValue, visibleAttributes, type ProfileLayer } from "./insights";
import type { ProfileValue } from "./datalayers";

const value = (over: Partial<ProfileValue>): ProfileValue => ({
  slice: "mean", label: "Mean", group: null, value: 1, display: 1, units: "m", rawUnits: null, ...over,
});
const layer = (over: Partial<ProfileLayer>): ProfileLayer => ({
  layer: "x", name: "X", category: "Soil", categorical: false, categories: null, values: [value({})], ...over,
});

describe("cleanLayerName", () => {
  it("drops provider tags but keeps the year", () => {
    expect(cleanLayerName("Population (GHSL 2025)")).toBe("Population · 2025");
    expect(cleanLayerName("Air temperature (ERA5-Land 2024)")).toBe("Air temperature · 2024");
    expect(cleanLayerName("Elevation (Copernicus DEM)")).toBe("Elevation");
    expect(cleanLayerName("Baseline water stress (Aqueduct 4.0)")).toBe("Baseline water stress");
    expect(cleanLayerName("Aboveground biomass (GEDI L4B)")).toBe("Aboveground biomass");
    expect(cleanLayerName("NO₂ tropospheric column (Sentinel-5P)")).toBe("NO₂ tropospheric column");
    expect(cleanLayerName("Groundwater percentile (GRACE DA 2024)")).toBe("Groundwater percentile · 2024");
    expect(cleanLayerName("Aqueduct 4.0 baseline water risk")).toBe("Baseline water risk");
    expect(cleanLayerName("River basins, level 6 (HydroBASINS)")).toBe("River basins, level 6");
  });

  it("keeps descriptive brackets", () => {
    expect(cleanLayerName("Air temperature (2 m)")).toBe("Air temperature (2 m)");
    expect(cleanLayerName("Solar irradiation (clear sky)")).toBe("Solar irradiation (clear sky)");
    expect(cleanLayerName("Electricity price (average)")).toBe("Electricity price (average)");
  });
});

describe("profile filtering", () => {
  it("treats QA values as metadata", () => {
    expect(isMetaValue(value({ label: "Ground pixels used", units: "pixels" }))).toBe(true);
    expect(isMetaValue(value({ label: "Standard error", units: "Mg/ha" }))).toBe(true);
    expect(isMetaValue(value({ label: "Biomass density", units: "Mg/ha" }))).toBe(false);
  });

  it("finds layers with no usable value", () => {
    expect(hasData(layer({ values: [value({ display: null })] }))).toBe(false);
    expect(hasData(layer({ values: [value({ label: "Standard error", display: 2 })] }))).toBe(false);
    expect(hasData(layer({}))).toBe(true);
  });

  it("hides source notes from attributes", () => {
    const l = layer({
      attributes: [
        { key: "price_area_name", label: "Price area", value: "Canada · Ontario" },
        { key: "elec_household_basis", label: "Household basis", value: "CAD 0.18/kWh …" },
        { key: "aqueduct_unit", label: "Aqueduct unit", value: "1628" },
      ],
    });
    expect(visibleAttributes(l).map((a) => a.label)).toEqual(["Price area"]);
  });

  it("orders known categories first", () => {
    const groups = groupByCategory([layer({ category: "Soil" }), layer({ category: "Zebra" }), layer({ category: "Solar & climate" })]);
    expect(groups.map(([c]) => c)).toEqual(["Solar & climate", "Soil", "Zebra"]);
  });
});
