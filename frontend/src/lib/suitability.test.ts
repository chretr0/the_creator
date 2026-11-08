import { describe, expect, it } from "vitest";
import { STATE_COLOUR, TIER_COLOUR, type CellState, type SuitabilityFactor, type SuitabilityProfile } from "./buildings";
import { cellColour, cellTooltip, colourCounts, effectiveColourBy, factorGroups, legendRows, weakestFactors } from "./suitability";

const factor = (key: string, group: string, weight = 1): SuitabilityFactor => ({
  key,
  label: key.replace("_", " "),
  group,
  unit: "",
  weight,
  constraint: false,
  bands: `${key} bands`,
  layerId: null,
  sliceId: null,
  source: "test",
  why: "test",
});

const profile: SuitabilityProfile = {
  id: "farm:rainfed",
  label: "Crop farm",
  method: "weighted mean",
  factors: [factor("soil_ph", "Soil", 1.5), factor("slope", "Terrain", 1), factor("soil_nitrogen", "Soil", 2)],
};

const cell = (state: CellState["state"], tier: CellState["tier"], grades: string): CellState => ({ h3Id: "x", state, tier, grades });

describe("suitability colouring", () => {
  it("keeps the hard-state colours when the type has no profile", () => {
    expect(cellColour(cell("meets_criteria", null, ""), null, "overall").slice(0, 3)).toEqual(STATE_COLOUR.meets_criteria);
  });

  it("colours by grade, keeps not-buildable red and fades unsure cells", () => {
    const sure = cellColour(cell("meets_criteria", "good", "121"), profile, "overall");
    const unsure = cellColour(cell("insufficient_data", "good", "121"), profile, "overall");
    expect(sure.slice(0, 3)).toEqual(TIER_COLOUR.good);
    expect(unsure.slice(0, 3)).toEqual(TIER_COLOUR.good);
    expect(unsure[3]).toBeLessThan(sure[3]);
    expect(cellColour(cell("fails_criteria", "ideal", "111"), profile, "overall").slice(0, 3)).toEqual(STATE_COLOUR.fails_criteria);
  });

  it("colours one factor by its grade character, ignoring the hard state", () => {
    expect(cellColour(cell("fails_criteria", "good", "143"), profile, "slope").slice(0, 3)).toEqual(TIER_COLOUR.unsuitable);
    expect(cellColour(cell("meets_criteria", "good", "103"), profile, "slope")[3]).toBeLessThan(60); // no data
  });

  it("falls back to the overall grade for a factor the profile doesn't have", () => {
    expect(effectiveColourBy(profile, "wind_resource")).toBe("overall");
    expect(effectiveColourBy(null, "slope")).toBe("overall");
    expect(effectiveColourBy(profile, "slope")).toBe("slope");
  });
});

describe("weakest factors and tooltips", () => {
  it("lists the worst grades first, then the heavier weight", () => {
    const weak = weakestFactors(cell("meets_criteria", "marginal", "323"), profile);
    expect(weak.map((w) => w.factor.key)).toEqual(["soil_nitrogen", "soil_ph", "slope"]);
    expect(weakestFactors(cell("meets_criteria", "ideal", "111"), profile)).toEqual([]);
  });

  it("explains the grade, the factor holding it back and the hard state", () => {
    const text = cellTooltip(cell("fails_criteria", "good", "131"), profile, "overall");
    expect(text).toContain("Good site for crop farm");
    expect(text).toContain("slope (marginal)");
    expect(text).toContain("Not buildable");
    expect(cellTooltip(cell("meets_criteria", "good", "131"), profile, "soil_ph")).toContain("soil ph: Ideal");
  });

  it("only says 'limited by' for marginal or unsuitable factors, like the server", () => {
    const ideal = cellTooltip(cell("meets_criteria", "ideal", "121"), profile, "overall");
    expect(ideal).not.toContain("Limited by");
    expect(ideal).not.toContain("Not ideal");
    const good = cellTooltip(cell("meets_criteria", "good", "121"), profile, "overall");
    expect(good).toContain("Not ideal: slope (good)");
  });

  it("explains a good grade held by a hard limit without data", () => {
    const withLimit: SuitabilityProfile = { ...profile, factors: profile.factors.map((f) => (f.key === "slope" ? { ...f, constraint: true } : f)) };
    expect(cellTooltip(cell("insufficient_data", "good", "101"), withLimit, "overall")).toContain("Can't be confirmed ideal: no data on slope here");
  });
});

describe("legend counts", () => {
  const cells = [
    cell("meets_criteria", "ideal", "111"),
    cell("insufficient_data", "good", "121"),
    cell("fails_criteria", "ideal", "111"),
    cell("meets_criteria", null, "000"),
  ];

  it("counts cells exactly as they are coloured", () => {
    expect(colourCounts(cells, profile, "overall")).toEqual({ ideal: 1, good: 1, fails: 1, unknown: 1 });
    expect(colourCounts(cells, profile, "slope")).toEqual({ ideal: 2, good: 1, unknown: 1 });
  });

  it("adds a not-buildable row only for the overall grade", () => {
    const area = { cells, counts: {}, profile };
    expect(legendRows(area, "overall").map((r) => r.key)).toEqual(["ideal", "good", "marginal", "unsuitable", "fails", "unknown"]);
    expect(legendRows(area, "slope").map((r) => r.key)).toEqual(["ideal", "good", "marginal", "unsuitable", "unknown"]);
    expect(legendRows({ cells, counts: { meets_criteria: 2 }, profile: null }, "overall")[0]).toMatchObject({ key: "meets_criteria", count: 2 });
  });

  it("groups factors in profile order", () => {
    expect(factorGroups(profile).map((g) => [g.group, g.factors.map((f) => f.key)])).toEqual([
      ["Soil", ["soil_ph", "soil_nitrogen"]],
      ["Terrain", ["slope"]],
    ]);
  });
});
