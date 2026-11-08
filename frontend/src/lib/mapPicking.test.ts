import { describe, expect, it } from "vitest";
import { isBackgroundLayer } from "./mapPicking";

describe("isBackgroundLayer", () => {
  it("treats the grid, screening cells and timeline overlay as background", () => {
    expect(isBackgroundLayer("grid")).toBe(true);
    expect(isBackgroundLayer("assessment-cells")).toBe(true);
    expect(isBackgroundLayer("timeline-impact")).toBe(true);
  });

  it("keeps records and nothing-picked out of the background", () => {
    expect(isBackgroundLayer("projects")).toBe(false);
    expect(isBackgroundLayer("infra-points")).toBe(false);
    expect(isBackgroundLayer("grid-proximity")).toBe(false);
    expect(isBackgroundLayer(undefined)).toBe(false);
    expect(isBackgroundLayer(undefined, ["moon-keepout"])).toBe(false);
  });

  it("adds a map's extra background layers without changing the defaults", () => {
    const extra = ["moon-keepout", "moon-mare"];
    expect(isBackgroundLayer("moon-keepout")).toBe(false);
    expect(isBackgroundLayer("moon-keepout", extra)).toBe(true);
    expect(isBackgroundLayer("moon-mare", extra)).toBe(true);
    expect(isBackgroundLayer("grid", extra)).toBe(true);
    expect(isBackgroundLayer("moon-sites", extra)).toBe(false);
  });
});
