import { describe, expect, it } from "vitest";
import { cellToLatLng, getResolution, gridDisk, getPentagons, latLngToCell } from "h3-js";
import {
  DEFAULT_CELL_BUDGET,
  SIMULATION_RESOLUTION,
  chooseResolution,
  normaliseLongitude,
  simulationCell,
  splitLongitudeSpan,
  viewportCells,
} from "./h3grid";

describe("coordinates", () => {
  it("normalises longitude to [-180, 180)", () => {
    expect(normaliseLongitude(180)).toBe(-180);
    expect(normaliseLongitude(190)).toBeCloseTo(-170);
    expect(normaliseLongitude(-190)).toBeCloseTo(170);
    expect(normaliseLongitude(541)).toBeCloseTo(-179);
    const exact = -2.23743987654321;
    expect(normaliseLongitude(exact)).toBe(exact);
  });

  it("matches the backend for known coordinates (same ID everywhere)", () => {
    // Values produced by the Python h3 4.x backend for the same inputs.
    expect(simulationCell(51.5074, -0.1278)).toBe("86195da4fffffff");
    expect(simulationCell(51.5, -0.12)).toBe("86194ad17ffffff");
  });

  it("wrapped longitudes resolve to the same cell", () => {
    expect(simulationCell(-16.5, 179.999 - 360)).toBe(simulationCell(-16.5, 179.999));
    expect(simulationCell(-16.5, 179.999)).not.toBe(simulationCell(-16.5, -179.999));
  });

  it("handles pentagons without assuming six neighbours", () => {
    const pentagon = getPentagons(SIMULATION_RESOLUTION)[0];
    expect(gridDisk(pentagon, 1).length - 1).toBe(5);
  });
});

describe("splitLongitudeSpan", () => {
  it("splits at the antimeridian", () => {
    const pieces = splitLongitudeSpan(170, 190);
    expect(pieces).toEqual([
      [170, 180],
      [-180, -170],
    ]);
  });

  it("keeps chunks narrow", () => {
    for (const [w, e] of splitLongitudeSpan(-180, 180)) {
      expect(e - w).toBeLessThanOrEqual(60);
      expect(w).toBeGreaterThanOrEqual(-180);
      expect(e).toBeLessThanOrEqual(180);
    }
  });
});

describe("viewportCells", () => {
  it("uses the coarse overview for the whole world", () => {
    const v = viewportCells({ west: -180, east: 180, south: -85, north: 85 });
    expect(v.overview).toBe(true);
    expect(v.resolution).toBeLessThanOrEqual(2);
  });

  it("never exceeds the simulation resolution and respects the budget", () => {
    const local = { west: -0.2, east: 0.0, south: 51.45, north: 51.55 };
    const v = viewportCells(local);
    expect(v.resolution).toBe(SIMULATION_RESOLUTION);
    const city = latLngToCell(51.5, -0.1, SIMULATION_RESOLUTION);
    expect(v.cells).toContain(city);

    const region = { west: -10, east: 5, south: 48, north: 60 };
    const r = viewportCells(region);
    expect(r.cells.length).toBeLessThanOrEqual(DEFAULT_CELL_BUDGET * 1.5);
    expect(r.cells.every((c) => getResolution(c) === r.resolution)).toBe(true);
  });

  it("covers both sides of the date line", () => {
    const fiji = { west: 177, east: 183, south: -19, north: -15 };
    const v = viewportCells(fiji);
    const lngs = v.cells.map((c) => cellToLatLng(c)[1]);
    expect(lngs.some((l) => l > 175)).toBe(true);
    expect(lngs.some((l) => l < -175)).toBe(true);
    expect(v.cells).toContain(latLngToCell(-17, 179.5, v.resolution));
    expect(v.cells).toContain(latLngToCell(-17, -179.5, v.resolution));
  });

  it("chooses coarser resolutions for larger views", () => {
    const small = chooseResolution({ west: 0, east: 1, south: 0, north: 1 });
    const large = chooseResolution({ west: 0, east: 40, south: 0, north: 40 });
    expect(large).toBeLessThan(small);
  });
});
