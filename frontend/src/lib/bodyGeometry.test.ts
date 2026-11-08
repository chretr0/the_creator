import { describe, expect, it } from "vitest";
import { cellArea, getHexagonEdgeLengthAvg, greatCircleDistance, latLngToCell, UNITS } from "h3-js";
import { cellAreaKm2, distanceKm, edgeLengthKm, geodesicCircle, metresPerPixel, scaleBar } from "./bodyGeometry";
import { BODIES } from "../bodies";

const EARTH_R = BODIES.earth.radiusKm;
const MOON_R = BODIES.moon.radiusKm;
/** MapLibre's hard-coded Earth radius (metres), used by ScaleControl and LngLat.distanceTo. */
const MAPLIBRE_EARTH_RADIUS_M = 6371008.8;

const relative = (a: number, b: number) => Math.abs(a - b) / Math.abs(b);

describe("body radii", () => {
  it("uses h3's Earth radius and the IAU mean lunar radius", () => {
    expect(EARTH_R).toBe(6371.007180918475);
    expect(MOON_R).toBe(1737.4);
  });
});

describe("cellAreaKm2", () => {
  const cells = [latLngToCell(51.5074, -0.1278, 6), latLngToCell(-89.5, 0, 6), latLngToCell(0, 179.99, 3), "8001fffffffffff"];

  it("equals h3's own km² on Earth", () => {
    for (const h of cells) expect(relative(cellAreaKm2(h, EARTH_R), cellArea(h, UNITS.km2))).toBeLessThan(1e-12);
  });

  it("scales by (R_moon / R_earth)² on the Moon", () => {
    const ratio = (1737.4 / 6371.007180918475) ** 2;
    for (const h of cells) expect(cellAreaKm2(h, MOON_R) / cellAreaKm2(h, EARTH_R)).toBeCloseTo(ratio, 12);
    expect(ratio).toBeCloseTo(0.07437, 5);
  });

  it("gives the catalogue's ~2.7 km² for a Moon res-6 cell", () => {
    const area = cellAreaKm2(latLngToCell(0.674, 23.473, 6), MOON_R); // Apollo 11
    expect(area).toBeGreaterThan(2.2);
    expect(area).toBeLessThan(3.2);
  });
});

describe("edgeLengthKm", () => {
  it("equals h3's average edge on Earth", () => {
    for (let r = 0; r <= 15; r++) expect(relative(edgeLengthKm(r, EARTH_R), getHexagonEdgeLengthAvg(r, UNITS.km))).toBeLessThan(1e-12);
  });

  it("is ~1.0 km at res 6 on the Moon (× 0.2727)", () => {
    expect(edgeLengthKm(6, MOON_R)).toBeCloseTo(1.016, 2);
    expect(edgeLengthKm(6, MOON_R) / edgeLengthKm(6, EARTH_R)).toBeCloseTo(0.2727, 4);
  });
});

describe("distanceKm", () => {
  it("matches h3's great-circle distance on Earth", () => {
    const pairs: [number, number, number, number][] = [
      [51.5074, -0.1278, 40.7128, -74.006],
      [-33.86, 151.21, 35.68, 139.69],
      [0, 179.5, 0, -179.5],
    ];
    for (const [a, b, c, d] of pairs) {
      expect(relative(distanceKm(a, b, c, d, EARTH_R), greatCircleDistance([a, b], [c, d], UNITS.km))).toBeLessThan(1e-9);
    }
  });

  it("is a quarter circumference from the equator to a pole", () => {
    expect(distanceKm(0, 0, 90, 0, MOON_R)).toBeCloseTo((Math.PI * MOON_R) / 2, 9);
    expect(distanceKm(-89.9, 0, -89.9, 180, MOON_R)).toBeCloseTo((0.2 * Math.PI * MOON_R) / 180, 9);
    expect(distanceKm(10, 20, 10, 20, MOON_R)).toBe(0);
  });
});

describe("geodesicCircle", () => {
  const cases: [string, number, number, number][] = [
    ["near side", 0.674, 23.473, 2],
    ["south pole (Shackleton rim)", -89.45, -137.31, 2],
    ["antimeridian", 10, 179.9, 15],
    ["impact keep-out", 45, -60, 0.5],
  ];

  it.each(cases)("puts every vertex at the radius on the Moon sphere: %s", (_name, lat, lon, r) => {
    const ring = geodesicCircle(lat, lon, r, MOON_R, 64);
    expect(ring).toHaveLength(65);
    expect(ring[64]).toEqual(ring[0]);
    for (const [vLon, vLat] of ring) expect(relative(distanceKm(lat, lon, vLat, vLon, MOON_R), r)).toBeLessThan(1e-9);
  });

  it("starts due north and winds counter-clockwise", () => {
    const ring = geodesicCircle(0, 0, 10, MOON_R, 4);
    expect(ring[0][0]).toBeCloseTo(0, 12);
    expect(ring[0][1]).toBeGreaterThan(0);
    // Second vertex is due west.
    expect(ring[1][0]).toBeLessThan(0);
    expect(ring[1][1]).toBeCloseTo(0, 12);
    let signedArea = 0;
    for (let i = 0; i < ring.length - 1; i++) signedArea += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    expect(signedArea).toBeGreaterThan(0);
  });

  it("keeps longitudes continuous across the antimeridian", () => {
    const ring = geodesicCircle(0, 179.9, 15, MOON_R);
    const lons = ring.map(([x]) => x);
    expect(Math.max(...lons)).toBeGreaterThan(180);
    expect(Math.max(...lons) - Math.min(...lons)).toBeLessThan(2);
  });

  it("uses the body radius: the same km span a wider angle on the Moon", () => {
    const moon = geodesicCircle(0, 0, 100, MOON_R, 4);
    const earth = geodesicCircle(0, 0, 100, EARTH_R, 4);
    expect(moon[0][1] / earth[0][1]).toBeCloseTo(EARTH_R / MOON_R, 6);
  });
});

describe("metresPerPixel", () => {
  // MapLibre: a world 512·2^z px wide, and mercatorZfromAltitude's circumferenceAtLatitude
  // (2π · 6371008.8 m · cos lat) metres around each parallel.
  const maplibreFormula = (latitude: number, zoom: number) =>
    (2 * Math.PI * MAPLIBRE_EARTH_RADIUS_M * Math.cos((latitude * Math.PI) / 180)) / (512 * 2 ** zoom);
  // What MapLibre's ScaleControl measures: unproject points either side of the centre and take
  // LngLat.distanceTo (haversine). 1 px apart, so it is the local scale.
  function scaleControlMetresPerPixel(latitude: number, zoom: number) {
    const dLon = 360 / (512 * 2 ** zoom);
    return distanceKm(latitude, -dLon / 2, latitude, dLon / 2, MAPLIBRE_EARTH_RADIUS_M / 1000) * 1000;
  }

  it.each([
    [0, 0],
    [30, 1.6],
    [51.5, 9],
    [-70, 14],
    [85, 18],
  ])("matches MapLibre's formula on Earth at lat %d, zoom %d", (lat, zoom) => {
    expect(relative(metresPerPixel(lat, zoom, MAPLIBRE_EARTH_RADIUS_M / 1000), maplibreFormula(lat, zoom))).toBeLessThan(1e-12);
    expect(relative(metresPerPixel(lat, zoom, MAPLIBRE_EARTH_RADIUS_M / 1000), scaleControlMetresPerPixel(lat, zoom))).toBeLessThan(1e-5);
    // h3's Earth radius differs from MapLibre's by ~0.3 ppm.
    expect(relative(metresPerPixel(lat, zoom, EARTH_R), maplibreFormula(lat, zoom))).toBeLessThan(1e-6);
  });

  it("is 3.67× smaller on the Moon at the same zoom", () => {
    expect(metresPerPixel(0, 5, EARTH_R) / metresPerPixel(0, 5, MOON_R)).toBeCloseTo(3.667, 3);
  });

  it("halves with each zoom level", () => {
    expect(metresPerPixel(20, 7, MOON_R) / metresPerPixel(20, 8, MOON_R)).toBeCloseTo(2, 12);
  });
});

describe("scaleBar", () => {
  it.each([
    [12.34, "1\u00a0km", 1 / 1.234],
    [4.5, "300\u00a0m", 300 / 450],
    [70, "5\u00a0km", 5 / 7],
    [0.0042, "0.4\u00a0m", 0.4 / 0.42],
  ])("rounds like MapLibre's ScaleControl (%d m/px)", (mpp, label, ratio) => {
    const bar = scaleBar(mpp);
    expect(bar.label).toBe(label);
    expect(bar.widthPx).toBeCloseTo(100 * ratio, 9);
  });

  it("stays between half and the full maximum width at map scales", () => {
    for (const mpp of [0.37, 1, 9.99, 123, 4567, 98765]) {
      const { widthPx } = scaleBar(mpp, 80);
      expect(widthPx).toBeLessThanOrEqual(80 + 1e-9);
      expect(widthPx).toBeGreaterThanOrEqual(40);
    }
  });
});
