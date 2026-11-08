import { expect, it } from "vitest";
import { siteMargin } from "./siteMargin";
import type { SiteResource } from "./buildings";
const resource: SiteResource = { key: "power", label: "Grid", unit: "kW", available: 100, needed: 70, reach: "cell", parts: [], note: null };
it("shows spare capacity, shortfalls and exact allocation without clamping", () => {
  expect(siteMargin(resource)).toBe(30);
  expect(siteMargin({ ...resource, needed: 130 })).toBe(-30);
  expect(siteMargin({ ...resource, needed: 100 })).toBe(0);
  expect(siteMargin({ ...resource, available: 0, needed: 70 })).toBe(-70);
});
it("keeps unknowns and incomparable air/light indicators out of arithmetic", () => {
  expect(siteMargin({ ...resource, available: null })).toBeNull();
  expect(siteMargin({ ...resource, needed: null })).toBeNull();
  expect(siteMargin({ ...resource, key: "air", status: "pass" })).toBeNull();
});
