import { describe, expect, it } from "vitest";
import { viewTouchesRegions } from "./datalayers";

const both = ["arizona", "uk"];

describe("viewTouchesRegions", () => {
  it("finds the region a view sits in", () => {
    expect(viewTouchesRegions({ west: -112.5, south: 33, east: -111.5, north: 34 }, both)).toBe(true);
    expect(viewTouchesRegions({ west: -1, south: 51, east: 0.5, north: 52 }, both)).toBe(true);
  });
  it("reports views outside both boxes", () => {
    expect(viewTouchesRegions({ west: 2.0, south: 48, east: 3, north: 49.5 }, both)).toBe(false); // Paris
    expect(viewTouchesRegions({ west: -100, south: 30, east: -95, north: 35 }, both)).toBe(false); // Texas
  });
  it("only counts the layer's own regions", () => {
    expect(viewTouchesRegions({ west: -1, south: 51, east: 0.5, north: 52 }, ["arizona"])).toBe(false);
  });
  it("handles longitudes wrapped past ±180", () => {
    expect(viewTouchesRegions({ west: 247, south: 33, east: 248, north: 34 }, both)).toBe(true);
  });
});
