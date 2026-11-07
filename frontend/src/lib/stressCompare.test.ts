import { describe, expect, it } from "vitest";
import type { BuildingEvaluation, CheckResult, Quantity } from "./buildings";
import { keepIfShown, type Scenario } from "./api";
import { checkQuantity, outputRelevant, shortfall, supplyPairs } from "./stressCompare";

const check = (over: Partial<CheckResult>): CheckResult => ({
  criterionId: "c1",
  kind: "water_budget",
  label: "Water budget ≥ water demand",
  required: true,
  status: "pass",
  actual: 10,
  requiredValue: 20,
  unit: "m³",
  period: "30 days",
  source: "",
  explanation: "",
  ...over,
});

const evaluation = (checks: CheckResult[]): BuildingEvaluation =>
  ({ projectId: "p", name: "DC", type: "data_centre", result: {} as never, assessment: { state: "meets_criteria", checks, summary: "" } }) as BuildingEvaluation;

describe("shortfall", () => {
  it("is max(0, demand − supply)", () => {
    expect(shortfall(check({ actual: 10, requiredValue: 20 }))).toBe(0);
    expect(shortfall(check({ status: "fail", actual: 80, requiredValue: 20 }))).toBe(60);
  });
  it("is unknown (never 0) when demand or supply is unknown", () => {
    expect(shortfall(undefined)).toBeNull();
    expect(shortfall(check({ actual: null }))).toBeNull();
    expect(shortfall(check({ requiredValue: null, status: "unknown" }))).toBeNull();
  });
  it("is unknown when part of the supply is unknown and known supply falls short", () => {
    expect(shortfall(check({ status: "unknown", actual: 80, requiredValue: 20 }))).toBeNull();
    expect(shortfall(check({ status: "unknown", actual: 10, requiredValue: 20 }))).toBe(0);
  });
  it("renders unknown values as null quantities", () => {
    expect(checkQuantity(null, "kW").value).toBeNull();
    expect(checkQuantity(undefined, "kW").value).toBeNull();
    expect(checkQuantity(0, "kW").value).toBe(0);
  });
});

describe("supplyPairs", () => {
  it("pairs only supply checks between unstressed and stressed, in a fixed order", () => {
    const a = evaluation([
      check({ criterionId: "p", kind: "power_capacity", unit: "kW", period: null }),
      check({ criterionId: "w", kind: "water_budget" }),
      check({ criterionId: "x", kind: "site_area" }),
    ]);
    const b = evaluation([check({ criterionId: "w", kind: "water_budget", status: "fail", actual: 10, requiredValue: 5 })]);
    const pairs = supplyPairs(a, b);
    expect(pairs.map((p) => [p.label, !!p.a, !!p.b])).toEqual([
      ["Water allocation", true, true],
      ["Power capacity", true, false],
    ]);
    expect(shortfall(pairs[0].b)).toBe(5);
  });
});

describe("outputRelevant", () => {
  const q = (value: number | null, missing: string[] = []): Quantity => ({ value, unit: "kWh", basis: "", missing });
  it("hides outputs for buildings that produce nothing", () => {
    expect(outputRelevant(q(null), q(null))).toBe(false);
    expect(outputRelevant(q(null, ["average output"]))).toBe(true);
    expect(outputRelevant(q(null), q(12))).toBe(true);
  });
});

describe("keepIfShown", () => {
  const sc = (id: string, name = id) => ({ id, name }) as Scenario;
  it("applies a save result only to the scenario it was made for", () => {
    const b = sc("B");
    expect(keepIfShown(b, sc("A", "A saved"))).toBe(b);
    expect(keepIfShown(sc("A"), sc("A", "A saved"))?.name).toBe("A saved");
    expect(keepIfShown(null, sc("A"))).toBeNull();
  });
});
