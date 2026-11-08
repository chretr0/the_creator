import { describe, expect, it } from "vitest";
import { distanceKm, geodesicCircle } from "../lib/bodyGeometry";
import { MOON_RADIUS_KM } from "../bodies/moon";
import type { GazetteerPlace, KeepoutFeature, MoonSite } from "./api";
import {
  featureTypeLabel,
  foldName,
  formatAreaKm2,
  formatDistanceKm,
  formatLatLon,
  formatMeasure,
  indexPlaces,
  keepoutHitsAt,
  moonSearch,
  parseMoonCoordinates,
  placeBBox,
  placeDetail,
  ringBBox,
  ringCentre,
  searchGazetteer,
} from "./geo";

const place = (name: string, diameterKm: number | null, extra: Partial<GazetteerPlace> = {}): GazetteerPlace => ({
  id: name.toLowerCase().replace(/\W+/g, "-"),
  name,
  type: "Crater, craters",
  diameterKm,
  lat: 0,
  lon: 0,
  quad: "LAC-78",
  approved: null,
  origin: null,
  link: null,
  ...extra,
});

const GAZ = indexPlaces([
  place("Tycho", 85.29, { lat: -43.3, lon: -11.36, quad: "LAC-112" }),
  place("Tycho A", 29.6),
  place("Tycho B", 13),
  place("Shackleton", 21.0, { lat: -89.67, lon: 129.78, quad: "LAC-144" }),
  place("de Gerlache", 31.9),
  place("Schrödinger", 316.4, { lat: -75, lon: 132.4 }),
  place("Mare Tranquillitatis", 873.0, { type: "Mare, maria" }),
  place("Statio Tranquillitatis", null, { type: "Landing site name" }),
  place("Rimae Tycho", 10),
]);

describe("searchGazetteer", () => {
  it("ranks exact over prefix over contains, bigger features first", () => {
    const names = searchGazetteer(GAZ, "tycho").map((h) => h.label);
    expect(names[0]).toBe("Tycho");
    expect(names.slice(1, 3)).toEqual(["Tycho A", "Tycho B"]);
    expect(names).toContain("Rimae Tycho");
    expect(names.indexOf("Rimae Tycho")).toBeGreaterThan(names.indexOf("Tycho B"));
  });

  it("orders prefix matches by diameter (unknown diameters last)", () => {
    const names = searchGazetteer(GAZ, "tranq").map((h) => h.label);
    expect(names).toEqual(["Mare Tranquillitatis", "Statio Tranquillitatis"]);
  });

  it("ignores case and accents", () => {
    expect(searchGazetteer(GAZ, "SCHRODINGER")[0].label).toBe("Schrödinger");
    expect(foldName("Schrödinger")).toBe("schrodinger");
  });

  it("needs two characters and respects the limit", () => {
    expect(searchGazetteer(GAZ, "t")).toEqual([]);
    expect(searchGazetteer(GAZ, "ty", 2)).toHaveLength(2);
  });

  it("describes a hit as type · diameter · LAC quad", () => {
    expect(searchGazetteer(GAZ, "Tycho")[0].detail).toBe("Crater · 85 km · LAC-112");
    expect(placeDetail({ type: "Landing site name", diameterKm: null, quad: null })).toBe("Landing site name");
    expect(featureTypeLabel(null)).toBe("Named feature");
  });

  it("flags features beyond the Web Mercator edge", () => {
    const shackleton = searchGazetteer(GAZ, "shackleton")[0];
    expect(shackleton.beyondMap).toBe(true);
    expect(searchGazetteer(GAZ, "tycho")[0].beyondMap).toBe(false);
  });
});

describe("placeBBox", () => {
  it("spans roughly the crater's diameter on the Moon sphere", () => {
    const [w, s, e, n] = placeBBox(-43.3, -11.36, 85.29, MOON_RADIUS_KM, 1);
    const northSouthKm = distanceKm(s, -11.36, n, -11.36, MOON_RADIUS_KM);
    const eastWestKm = distanceKm(-43.3, w, -43.3, e, MOON_RADIUS_KM);
    expect(northSouthKm).toBeCloseTo(85.29, 0);
    // East-west at the centre latitude is the same ground distance (within the small-circle error).
    expect(eastWestKm / 85.29).toBeGreaterThan(0.97);
    expect(eastWestKm / 85.29).toBeLessThan(1.03);
  });

  it("uses the Moon radius, not Earth's (3.67× more degrees per km)", () => {
    const moon = placeBBox(0, 0, 100, MOON_RADIUS_KM, 1);
    const earth = placeBBox(0, 0, 100, 6371.0, 1);
    expect((moon[3] - moon[1]) / (earth[3] - earth[1])).toBeCloseTo(6371.0 / MOON_RADIUS_KM, 2);
  });

  it("keeps a minimum size and clamps to the map edge", () => {
    const tiny = placeBBox(10, 10, 0.2);
    expect(tiny[3] - tiny[1]).toBeGreaterThan(0.2);
    const polar = placeBBox(-84.9, 30, 50);
    expect(polar[1]).toBeGreaterThanOrEqual(-85.0511);
    expect(polar[2] - polar[0]).toBeLessThanOrEqual(360);
  });
});

describe("parseMoonCoordinates", () => {
  it("reads lat, lon and hemisphere letters", () => {
    expect(parseMoonCoordinates("0.674, 23.47")).toMatchObject({ lat: 0.674, lon: 23.47, source: "coordinates" });
    expect(parseMoonCoordinates("43.3S 11.36W")).toMatchObject({ lat: -43.3, lon: -11.36 });
    expect(parseMoonCoordinates("-8.97 15.5")).toMatchObject({ lat: -8.97, lon: 15.5 });
  });

  it("normalises 0–360 east longitudes to ±180", () => {
    expect(parseMoonCoordinates("10, 350")?.lon).toBeCloseTo(-10, 9);
    expect(parseMoonCoordinates("10, 180")?.lon).toBe(-180);
  });

  it("rejects names and out-of-range values", () => {
    expect(parseMoonCoordinates("Apollo 11")).toBeNull();
    expect(parseMoonCoordinates("91, 0")).toBeNull();
    expect(parseMoonCoordinates("0, 361")).toBeNull();
  });

  it("marks polar coordinates as beyond the map", () => {
    expect(parseMoonCoordinates("-89.9, 0")?.beyondMap).toBe(true);
  });

  it("wins over the gazetteer in moonSearch", () => {
    expect(moonSearch(GAZ, "12, 34")).toHaveLength(1);
    expect(moonSearch(null, "tycho")).toEqual([]);
    expect(moonSearch(GAZ, "tycho")[0].label).toBe("Tycho");
  });
});

describe("formatting", () => {
  it("shows Unknown for missing values, never 0", () => {
    expect(formatMeasure(null, "m")).toBe("Unknown");
    expect(formatMeasure(Number.NaN, "m")).toBe("Unknown");
    expect(formatDistanceKm(undefined)).toBe("Unknown");
    expect(formatAreaKm2(null)).toBe("Unknown");
    expect(formatLatLon(null, 3)).toBe("Unknown");
    expect(formatMeasure(0, "m")).toBe("0 m");
  });

  it("formats distances, areas and positions", () => {
    expect(formatDistanceKm(0.5)).toBe("500 m");
    expect(formatDistanceKm(2.04)).toBe("2.0 km");
    expect(formatDistanceKm(150)).toBe("150 km");
    expect(formatAreaKm2(2.69)).toBe("2.69 km²");
    expect(formatLatLon(0.6742, 23.4731)).toBe("0.6742° N, 23.4731° E");
    expect(formatLatLon(-3.0128, -23.4219, 2)).toBe("3.01° S, 23.42° W");
    expect(formatMeasure(-2345.6, "m")).toBe("-2,346 m");
  });
});

describe("ringBBox", () => {
  it("unwraps rings across the antimeridian", () => {
    const bbox = ringBBox([
      [1, 179],
      [1, -179],
      [-1, -179],
      [-1, 179],
    ]);
    expect(bbox).toEqual([179, -1, 181, 1]);
  });
});

describe("keepoutHitsAt", () => {
  // Lunokhod 1 and its 2 km heritage ring, as the server serves them.
  const LUNOKHOD: [number, number] = [-35.0079815, 38.3151705];
  const ring = (siteId: string, siteName: string, [lon, lat]: [number, number], radiusM: number): KeepoutFeature => ({
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [geodesicCircle(lat, lon, radiusM / 1000, MOON_RADIUS_KM)] },
    properties: { id: `keepout-${siteId}`, siteId, siteName, radiusM, rule: "heritage_landing", sourceId: "MOON-SITE-06", evidenceType: "rule" },
  });
  const site = (id: string, [lon, lat]: [number, number]): MoonSite =>
    ({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: { id, name: id } }) as MoonSite;
  const rings = [ring("Lunokhod1", "Lunokhod 1 Rover", LUNOKHOD, 2000)];
  const sites = [site("Lunokhod1", LUNOKHOD)];

  it("flags a clicked point inside the ring although its res-6 cell centre is outside", () => {
    // Click 1.6 km north of Lunokhod 1; its res-6 cell (863582b5fffffff) is centred 2.48 km away.
    const hits = keepoutHitsAt(38.36794, -35.00798, rings, sites);
    expect(hits).toHaveLength(1);
    expect(hits![0].siteName).toBe("Lunokhod 1 Rover");
    expect(hits![0].distanceKm).toBeCloseTo(1.6, 1);
    expect(keepoutHitsAt(38.3954, -34.9872, rings, sites)).toEqual([]);
  });

  it("uses the ring's own centre when the site isn't loaded", () => {
    expect(keepoutHitsAt(38.36794, -35.00798, rings, null)).toHaveLength(1);
    expect(keepoutHitsAt(38.3954, -34.9872, rings, null)).toEqual([]);
  });

  it("is null until the rings have loaded, and sorts the nearest site first", () => {
    expect(keepoutHitsAt(0, 0, null, sites)).toBeNull();
    const two = [ring("far", "Far", [0.04, 0], 2000), ring("near", "Near", [0.01, 0], 2000)];
    expect(keepoutHitsAt(0, 0, two, null)!.map((h) => h.siteId)).toEqual(["near", "far"]);
  });
});

describe("ringCentre", () => {
  it("recovers the centre of a geodesic circle, across the antimeridian too", () => {
    const [lon, lat] = ringCentre(geodesicCircle(-43.3, 179.99, 5, MOON_RADIUS_KM))!;
    expect(lat).toBeCloseTo(-43.3, 6);
    expect(lon).toBeCloseTo(179.99, 6);
    expect(ringCentre([])).toBeNull();
  });
});
