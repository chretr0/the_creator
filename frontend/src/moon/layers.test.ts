import { describe, expect, it } from "vitest";
import type { KeepoutFeature, MissionFeature, MoonSite, MoonSiteProps } from "./api";
import {
  beyondMapEdge,
  buildMoonLayers,
  countByKind,
  h3ValueTooltip,
  missionMarkers,
  missionPosition,
  moonScale,
  moonTooltip,
  MOON_LAYER_IDS,
  rampColour,
  siteKindMeta,
  sortSites,
  TERRAIN,
  valueRange,
} from "./layers";

const site = (id: string, kind: MoonSiteProps["kind"], date: string | null, lon = 0, lat = 0): MoonSite => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lon, lat] },
  properties: {
    id,
    name: id,
    mission: id,
    kind,
    date,
    dateNote: null,
    elevationM: null,
    uncertainty: null,
    heritage: kind === "crewed_landing" ? "landing" : null,
    evidenceType: "reported_record",
    sourceId: "MOON-SITE-01",
  },
});

const mission = (id: string, kind: "artemis_region" | "planned_mission", geometry: MissionFeature["geometry"]): MissionFeature => ({
  type: "Feature",
  geometry,
  properties: {
    id,
    name: id,
    kind,
    mission: null,
    target: "Mons Mouton",
    date: "Q1 2027",
    asOf: "2026-11-08",
    evidenceType: "planned",
    approximate: true,
    note: null,
    sourceId: "MOON-SITE-02",
  },
});

const box = (lon: number, lat: number, d = 0.25): MissionFeature["geometry"] => ({
  type: "Polygon",
  coordinates: [
    [
      [lon - d, lat - d],
      [lon + d, lat - d],
      [lon + d, lat + d],
      [lon - d, lat + d],
      [lon - d, lat - d],
    ],
  ],
});

describe("sites", () => {
  const sites = [
    site("Luna 9", "soft_landing", "1966-01-31"),
    site("Ranger 7", "impact", "1964-07-31"),
    site("Apollo 12", "crewed_landing", "1969-11-19"),
    site("Apollo 11", "crewed_landing", "1969-07-20"),
    site("Mystery", "other", null),
  ];

  it("sorts crewed landings first, then by kind and date", () => {
    expect(sortSites(sites).map((s) => s.properties.id)).toEqual(["Apollo 11", "Apollo 12", "Luna 9", "Ranger 7", "Mystery"]);
  });

  it("counts by kind in legend order", () => {
    expect(countByKind(sites)).toEqual([
      { kind: "crewed_landing", count: 2 },
      { kind: "soft_landing", count: 1 },
      { kind: "impact", count: 1 },
      { kind: "other", count: 1 },
    ]);
  });

  it("emphasises crewed landings and falls back for unknown kinds", () => {
    expect(siteKindMeta("crewed_landing").radius).toBeGreaterThan(siteKindMeta("soft_landing").radius);
    expect(siteKindMeta("not-a-kind").label).toBe("Other object");
    expect(siteKindMeta(null).label).toBe("Other object");
  });

  it("tooltips name the object, kind and heritage rule", () => {
    const t = moonTooltip(MOON_LAYER_IDS.sites, sites[3]);
    expect(t).toContain("Apollo 11");
    expect(t).toContain("Crewed landing");
    expect(t).toContain("2.0 km");
    expect(moonTooltip("grid", "8a2a1072b59ffff")).toBeNull();
  });
});

describe("missions", () => {
  const planned = mission("Griffin-1", "planned_mission", { type: "Point", coordinates: [31, -84.6] });
  const region = mission("Haworth", "artemis_region", box(-5.17, -87.45));
  const unplaced = mission("Lanyue", "planned_mission", null);

  it("places points at their coordinate and regions at their box centre", () => {
    expect(missionPosition(planned)).toEqual([31, -84.6]);
    const [lon, lat] = missionPosition(region)!;
    expect(lon).toBeCloseTo(-5.17, 9);
    expect(lat).toBeCloseTo(-87.45, 9);
    expect(missionPosition(unplaced)).toBeNull();
  });

  it("skips missions without published coordinates", () => {
    expect(missionMarkers([planned, region, unplaced]).map((m) => m.id)).toEqual(["Griffin-1", "Haworth"]);
  });

  it("knows which positions the Web Mercator map cannot show", () => {
    expect(beyondMapEdge(-87.45)).toBe(true);
    expect(beyondMapEdge(-84.6)).toBe(false);
  });

  it("tooltips keep the as-published date and as-of note", () => {
    const t = moonTooltip(MOON_LAYER_IDS.regions, region)!;
    expect(t).toContain("Artemis candidate region");
    expect(t).toContain("Q1 2027");
    expect(t).toContain("as of 2026-11-08");
    expect(t).toContain("Approximate location");
  });
});

describe("buildMoonLayers", () => {
  const ring: KeepoutFeature = {
    type: "Feature",
    geometry: box(23.47, 0.67, 0.07) as KeepoutFeature["geometry"],
    properties: {
      id: "ko-a11",
      siteId: "a11",
      siteName: "Apollo 11",
      radiusM: 2000,
      rule: "heritage_landing",
      sourceId: "MOON-SITE-06",
      evidenceType: "rule",
    },
  };

  it("builds only the layers that are shown and have data", () => {
    const ids = buildMoonLayers({
      sites: [site("Apollo 11", "crewed_landing", "1969-07-20")],
      missions: [mission("Haworth", "artemis_region", box(-5.17, -87.45))],
      keepout: [ring],
      mare: null,
      show: { sites: true, missions: false, keepout: true, mare: true },
      selectedId: null,
    }).map((l) => l.id);
    expect(ids).toEqual([MOON_LAYER_IDS.keepout, MOON_LAYER_IDS.sitesHalo, MOON_LAYER_IDS.sites, MOON_LAYER_IDS.siteLabels]);
  });

  it("never sizes markers in metres (deck.gl metres are Earth metres)", () => {
    const layers = buildMoonLayers({
      sites: [site("Apollo 11", "crewed_landing", "1969-07-20")],
      missions: [mission("Griffin-1", "planned_mission", { type: "Point", coordinates: [31, -84.6] })],
      keepout: [ring],
      mare: null,
      show: { sites: true, missions: true, keepout: true, mare: false },
      selectedId: null,
    });
    for (const l of layers) {
      const units = (l.props as { radiusUnits?: string }).radiusUnits;
      if (units !== undefined) expect(units).toBe("pixels");
    }
  });

  it("describes keep-out rings in the Moon's own kilometres", () => {
    expect(moonTooltip(MOON_LAYER_IDS.keepout, ring)).toContain("2.0 km");
  });
});

describe("colour scales", () => {
  it("interpolates and clamps along the stops", () => {
    expect(rampColour(TERRAIN, 0)).toEqual(TERRAIN[0]);
    expect(rampColour(TERRAIN, 1)).toEqual(TERRAIN[TERRAIN.length - 1]);
    expect(rampColour(TERRAIN, -3)).toEqual(TERRAIN[0]);
    expect(rampColour(TERRAIN, 9)).toEqual(TERRAIN[TERRAIN.length - 1]);
  });

  it("maps missing values to null (No data), not to the low end", () => {
    const scale = moonScale({ range: [-5240, 6100], palette: "terrain" })!;
    expect(scale.colour(null)).toBeNull();
    expect(scale.colour(Number.NaN)).toBeNull();
    expect(scale.colour(-5240)).toEqual(TERRAIN[0]);
    expect(scale.colour(99999)).toEqual(TERRAIN[TERRAIN.length - 1]);
  });

  it("falls back to the on-screen range when a layer publishes none", () => {
    expect(moonScale({ range: null, palette: "terrain" })).toBeNull();
    expect(moonScale({ range: null, palette: "terrain" }, [0, 10])?.domain).toEqual([0, 10]);
    expect(valueRange([3, null, -1, Number.NaN, 7, undefined])).toEqual([-1, 7]);
    expect(valueRange([null, undefined])).toBeNull();
  });

  it("explains coarser served cells in the grid tooltip", () => {
    const layer = { name: "Elevation (LOLA)", unit: "m" };
    expect(h3ValueTooltip(layer, -1234, 6, 5)).toBe("Elevation (LOLA): -1,234 m\nResolution-5 average (the finest this layer has)");
    expect(h3ValueTooltip(layer, null, 4, 4)).toBe("Elevation (LOLA): Unknown (no data)");
  });
});
