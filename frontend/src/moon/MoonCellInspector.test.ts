import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MoonCellContext } from "./api";
import { keepoutHitsAt, UNKNOWN } from "./geo";
import MoonCellInspector, { absenceText, keepoutView, mareSummary, NOT_PREPARED } from "./MoonCellInspector";

describe("mareSummary", () => {
  const noMare = { mare: null };

  it("states 'not in a mapped mare' only when the mare layer is prepared", () => {
    expect(mareSummary(noMare, false, 8.5, true).text).toBe("Not in a mapped mare");
    // Missing regions/mare.geojson: the server leaves mare null, which measures nothing.
    expect(mareSummary(noMare, false, 8.5, false)).toEqual({ text: UNKNOWN, note: "Mare layer not prepared on this server" });
  });

  it("names the mare, and is Unknown beyond the map's latitudes or after a failure", () => {
    expect(mareSummary({ mare: { id: "m", name: "Mare Tranquillitatis" } }, false, 8.5, true).text).toBe("Mare Tranquillitatis");
    expect(mareSummary(noMare, false, -70, true).text).toBe(UNKNOWN);
    expect(mareSummary(null, true, 0, true).text).toBe(UNKNOWN);
    expect(mareSummary(null, false, 0, true).text).toBe("…");
  });
});

describe("absenceText", () => {
  it("never states an absence for a layer that isn't prepared", () => {
    expect(absenceText(true, "No named features found.")).toBe("No named features found.");
    expect(absenceText(false, "No named features found.")).toBe(NOT_PREPARED);
    expect(NOT_PREPARED).toBe("Unknown (layer not prepared)");
  });
});

describe("keepoutView", () => {
  const centreHit: MoonCellContext["keepout"][number] = {
    siteId: "Lunokhod1",
    siteName: "Lunokhod 1 Rover",
    rule: "heritage_landing",
    radiusM: 2000,
    distanceKm: 1.2,
  };
  const pointHit = { siteId: "Lunokhod1", siteName: "Lunokhod 1 Rover", rule: "heritage_landing", radiusM: 2000, distanceKm: 1.6 };

  it("alerts for the clicked point inside a ring even when the cell centre is outside it", () => {
    const v = keepoutView([pointHit], []);
    expect(v.at).toBe("point");
    expect(v.hits).toEqual([pointHit]);
    expect(v.centreOnly).toEqual([]);
  });

  it("does not alert for a point outside every ring, but notes a ring around the cell centre", () => {
    const v = keepoutView([], [centreHit]);
    expect(v.hits).toEqual([]);
    expect(v.centreOnly).toEqual([centreHit]);
    expect(keepoutView([pointHit], [centreHit]).centreOnly).toEqual([]);
  });

  it("falls back to the server's cell-centre result until the rings load", () => {
    expect(keepoutView(null, [centreHit])).toEqual({ at: "centre", hits: [centreHit], centreOnly: [] });
    expect(keepoutView(null, null).hits).toEqual([]);
  });

  it("agrees with keepoutHitsAt for no rings loaded", () => {
    expect(keepoutView(keepoutHitsAt(0, 0, null, null), []).at).toBe("centre");
  });
});

describe("MoonCellInspector keep-out alert", () => {
  const render = (pointKeepout: Parameters<typeof keepoutView>[0]) =>
    renderToStaticMarkup(
      createElement(MoonCellInspector, {
        selection: { h3Id: "863582b5fffffff", latitude: 38.36794, longitude: -35.00798 },
        pointKeepout,
        available: { mare: true, places: true, sites: true },
        h3Layers: [],
        activeLayer: null,
        pending: [],
        onSelectSimulationCell: () => {},
        onZoomToCell: () => {},
        onGoTo: () => {},
        onPickSite: () => {},
        onShowLayer: () => {},
        onShowComingNext: () => {},
      }),
    );

  it("labels the distance as from the selected point", () => {
    const html = render([{ siteId: "Lunokhod1", siteName: "Lunokhod 1 Rover", rule: "heritage_landing", radiusM: 2000, distanceKm: 1.6 }]);
    expect(html).toContain("Inside a heritage keep-out zone");
    expect(html).toContain("The selected point is 1.6 km from Lunokhod 1 Rover, a heritage landing site.");
  });

  it("shows no alert for a point outside every ring", () => {
    expect(render([])).not.toContain("keep-out zone");
  });
});
