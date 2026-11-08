import { describe, expect, it } from "vitest";
import { ICON_NAMES } from "../components/Icon";
import { COMING_NEXT, defaultOverlayState, OVERLAYS, pendingGroups, pendingSummary, rasterOverlays } from "./catalogue";
import { findElevationLayer, placeTitle } from "./MoonCellInspector";
import { asLayerList, type MoonCellContext, type MoonH3Layer } from "./api";

describe("LROC overlays", () => {
  it("shows feature names by default, on top", () => {
    const shown = rasterOverlays(defaultOverlayState());
    expect(shown.map((o) => o.key)).toEqual(["lroc:luna_nomenclature"]);
    expect(OVERLAYS[OVERLAYS.length - 1].id).toBe("names");
  });

  it("requests transparent Web Mercator WMS tiles", () => {
    const state = defaultOverlayState();
    state.psr.on = true;
    const [psr] = rasterOverlays(state);
    expect(psr.tiles[0]).toContain("LAYERS=luna_psr_81s");
    expect(psr.tiles[0]).toContain("{bbox-epsg-3857}");
    expect(psr.tiles[0]).toContain("TRANSPARENT=true");
  });

  it("can leave the WMS mare outlines out when the prepared ones are used", () => {
    const state = defaultOverlayState();
    state.mare_wms.on = true;
    expect(rasterOverlays(state, ["mare_wms"]).map((o) => o.key)).toEqual(["lroc:luna_nomenclature"]);
  });

  it("swaps the dense names layer for the overview labels when zoomed out", () => {
    const state = defaultOverlayState();
    expect(rasterOverlays(state, [], 1.8)[0].key).toBe("lroc:luna_wil_c_nom");
    expect(rasterOverlays(state, [], 3)[0].key).toBe("lroc:luna_nomenclature");
    state.psr.on = true;
    expect(rasterOverlays(state, [], 1)[0].key).toBe("lroc:luna_psr_81s");
  });

  it("does not offer the 88–90° polar illumination layer (beyond Web Mercator)", () => {
    expect(OVERLAYS.map((o) => o.layer)).not.toContain("luna_polar_illumination");
  });
});

describe("coming next", () => {
  it("lists P0 sunlight, temperature, ice and composition layers with MOON IDs and known icons", () => {
    const ids = COMING_NEXT.flatMap((g) => g.items.map((i) => i.id));
    for (const id of ["MOON-SUN-01", "MOON-THERM-01", "MOON-ICE-01", "MOON-COMP-02"]) expect(ids).toContain(id);
    for (const id of ids) expect(id).toMatch(/^MOON-[A-Z]+-\d{2}$/);
    for (const g of COMING_NEXT) expect(ICON_NAMES).toContain(g.icon);
  });

  it("drops items once an H3 layer cites their source, and empty groups with them", () => {
    const groups = pendingGroups(["MOON-TOPO-02", "MOON-TOPO-01"]);
    expect(groups.find((g) => g.id === "terrain")).toBeUndefined();
    expect(groups.length).toBe(COMING_NEXT.length - 1);
    expect(pendingGroups([]).length).toBe(COMING_NEXT.length);
  });

  it("summarises pending groups as a sentence", () => {
    expect(pendingSummary(COMING_NEXT.slice(0, 4))).toBe("Sunlight, temperature, water ice and composition");
    expect(pendingSummary(COMING_NEXT.slice(0, 1))).toBe("Sunlight");
  });
});

describe("inspector helpers", () => {
  const layer = (id: string, name: string, unit: string): MoonH3Layer => ({ id, name, unit, sourceId: "X", maxResolution: 5 });

  it("finds the elevation layer by id, then by unit and name", () => {
    expect(findElevationLayer(null)).toBeNull();
    expect(findElevationLayer([layer("tio2", "TiO2", "wt%"), layer("elevation", "Elevation (LOLA)", "m")])?.id).toBe("elevation");
    expect(findElevationLayer([layer("lola_height", "Height", "m")])?.id).toBe("lola_height");
    expect(findElevationLayer([layer("tio2", "TiO2", "wt%")])).toBeNull();
  });

  it("accepts the layer list or the whole layers.json object", () => {
    expect(asLayerList([layer("a", "A", "m")])).toHaveLength(1);
    expect(asLayerList({ layers: [layer("a", "A", "m")] })).toHaveLength(1);
    expect(asLayerList(null)).toEqual([]);
  });

  it("titles a location by the feature it lies in, its mare, or the nearest name", () => {
    const base: MoonCellContext = {
      h3Id: "x",
      body: "moon",
      centre: { latitude: 0, longitude: 0 },
      nearestPlaces: [
        { id: "m", name: "Moltke", type: "Crater, craters", diameterKm: 6.5, quad: null, latitude: 0, longitude: 0, distanceKm: 12, within: false },
      ],
      nearbySites: [],
      keepout: [],
      mare: null,
      quad: null,
    };
    expect(placeTitle(null)).toBeNull();
    expect(placeTitle(base)).toBe("Near Moltke");
    expect(placeTitle({ ...base, mare: { id: "t", name: "Mare Tranquillitatis" } })).toBe("Mare Tranquillitatis");
    expect(
      placeTitle({
        ...base,
        mare: { id: "t", name: "Mare Tranquillitatis" },
        nearestPlaces: [{ ...base.nearestPlaces[0], name: "Statio Tranquillitatis", within: true }],
      }),
    ).toBe("Statio Tranquillitatis · Mare Tranquillitatis");
  });
});
