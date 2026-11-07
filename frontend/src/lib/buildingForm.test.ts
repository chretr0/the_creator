import { describe, expect, it } from "vitest";
import {
  checkComparison,
  countErrors,
  editValue,
  fmtQuantity,
  mergeAssumptions,
  missingInputs,
  siteNeeds,
  isAirPollutant,
  newCriterion,
  newMaterial,
  parseBudgets,
  parseCriteria,
  parseNumber,
  parseSite,
  parseStats,
  parseStress,
  siteToDraft,
  statsToDraft,
  stressToDraft,
  toKg,
  newBudget,
} from "./buildingForm";
import { NEUTRAL_STRESS, type Criterion, type TemplateParam } from "./buildings";

describe("parseNumber", () => {
  it("treats blank as unknown, not zero", () => {
    expect(parseNumber("")).toEqual({ value: null, error: null });
    expect(parseNumber("   ")).toEqual({ value: null, error: null });
  });
  it("keeps an explicit zero", () => {
    expect(parseNumber("0")).toEqual({ value: 0, error: null });
  });
  it("rejects non-numbers, infinity and hex", () => {
    for (const s of ["abc", "1,000", "Infinity", "0x10", "1e400", "NaN", "--1"]) {
      expect(parseNumber(s).error).not.toBeNull();
    }
  });
  it("applies range rules", () => {
    expect(parseNumber("-1", "nonneg").error).toMatch(/0 or more/);
    expect(parseNumber("0", "positive").error).toMatch(/more than 0/);
    expect(parseNumber("1.2", "fraction").error).toMatch(/between 0 and 1/);
    expect(parseNumber("25", "hours").error).toMatch(/0 and 24/);
    expect(parseNumber("2.5", "int").error).toMatch(/whole/);
    expect(parseNumber("0.9", "pue").error).toMatch(/at least 1/);
    expect(parseNumber("-40", "finite").value).toBe(-40);
    expect(parseNumber("24", "hours").value).toBe(24);
    expect(parseNumber("1e3").value).toBe(1000);
  });
});

describe("toKg", () => {
  it("converts tonnes to kg exactly", () => {
    expect(toKg(1.1, "t")).toBe(1100);
    expect(toKg(0.3, "t")).toBe(300);
    expect(toKg(2.5, "kg")).toBe(2.5);
  });
});

const DC_PARAMS: TemplateParam[] = [
  { key: "itPowerKw", label: "IT power", unit: "kW", kind: "number" },
  { key: "loadFraction", label: "Load fraction", unit: "0–1", kind: "number" },
  { key: "pue", label: "PUE", unit: "ratio", kind: "number" },
  { key: "wueBasis", label: "WUE basis", unit: "", kind: "select", options: ["it_energy", "facility_energy"] },
];

describe("parseStats", () => {
  it("sends blanks as null, keeps zero, and reports invalid input", () => {
    let d = statsToDraft({});
    d = editValue(d, "power.averageDemandKw", "100");
    d = editValue(d, "water.inputM3PerHour", "0");
    d = editValue(d, "operatingHoursPerDay", "30");
    d = editValue(d, "workers.capacity", "3.5");
    d = editValue(d, "costs.currency", "usd");
    const { stats, errors } = parseStats(d, []);
    expect(stats.power?.averageDemandKw).toBe(100);
    expect(stats.power?.peakDemandKw).toBeNull();
    expect(stats.water?.inputM3PerHour).toBe(0);
    expect(stats.costs?.currency).toBe("USD");
    expect(errors["operatingHoursPerDay"]).toBeTruthy();
    expect(errors["workers.capacity"]).toBeTruthy();
    expect(errors["costs.currency"]).toBeUndefined();
  });

  it("rejects a bad currency code", () => {
    const d = editValue(statsToDraft({}), "costs.currency", "dollars");
    expect(parseStats(d, []).errors["costs.currency"]).toBeTruthy();
  });

  it("converts material tonnes to kg and only sends a period for operation", () => {
    const d = statsToDraft({});
    const steel = { ...newMaterial(), name: "Steel", quantity: "2.5", unit: "t" as const };
    const water = { ...newMaterial(), name: "Lime", phase: "operation" as const, quantity: "40", unit: "kg" as const, period: "month" as const };
    const { stats, errors } = parseStats({ ...d, materials: [steel, water] }, []);
    expect(errors).toEqual({});
    expect(stats.materials?.[0]).toMatchObject({ name: "Steel", quantityKg: 2500, period: null });
    expect(stats.materials?.[1]).toMatchObject({ name: "Lime", quantityKg: 40, period: "month" });
  });

  it("requires material and pollutant names", () => {
    const d = statsToDraft({});
    const { errors } = parseStats({ ...d, materials: [newMaterial()], emissions: [{ id: "e", pollutant: "", rate: "-1", provenance: { kind: "user_assumption" } }] }, []);
    expect(Object.keys(errors).sort()).toEqual(expect.arrayContaining(["emissions.e.pollutant", "emissions.e.rate"]));
    expect(Object.keys(errors).some((k) => k.endsWith(".name"))).toBe(true);
  });

  it("parses template parameters and keeps unknown legacy ones", () => {
    const d = statsToDraft({}, { itPowerKw: 500, legacyFlag: true, pue: 1.4 });
    d.params.loadFraction = "0.8";
    d.params.wueBasis = "it_energy";
    const { parameters, errors } = parseStats(d, DC_PARAMS);
    expect(errors).toEqual({});
    expect(parameters).toEqual({ itPowerKw: 500, loadFraction: 0.8, pue: 1.4, wueBasis: "it_energy", legacyFlag: true });
    d.params.pue = "0.5";
    expect(parseStats(d, DC_PARAMS).errors["params.pue"]).toBeTruthy();
  });

  it("round-trips stats and marks edited sections as user assumptions", () => {
    const stats = {
      footprintM2: 1200,
      power: { averageDemandKw: 100, provenance: { kind: "demo_assumption" as const, note: "demo" } },
      costs: { currency: "GBP", operating: { amount: 10, period: "month" as const, kind: "total" as const } },
    };
    const d = statsToDraft(stats);
    expect(d.provenance.power.kind).toBe("demo_assumption");
    const back = parseStats(d, []).stats;
    expect(back.footprintM2).toBe(1200);
    expect(back.costs?.operating).toEqual({ amount: 10, period: "month", kind: "total" });
    expect(editValue(d, "power.peakDemandKw", "5").provenance.power.kind).toBe("user_assumption");
  });
});

describe("siteNeeds", () => {
  it("lists what the site must provide from the specs, footprint always", () => {
    const n = siteNeeds(
      { footprintM2: 2000, operatingHoursPerDay: 24, water: { inputM3PerHour: 2 }, power: { peakDemandKw: 500 }, workers: { staffingRequired: 30 } },
      {},
      "custom",
    );
    expect(n.map((x) => [x.key, x.from])).toEqual([
      ["land", "2,000 m² footprint"],
      ["water", "48 m³/day (2 m³/h × 24 h)"],
      ["power", "500 kW peak"],
      ["workforce", "30 people"],
      ["air", null],
      ["light", null],
      ["materials", null],
    ]);
  });
  it("lists air, dark-sky and advisory raw-material needs", () => {
    const n = siteNeeds(
      {
        emissions: [
          { id: "a", pollutant: "CO2", rateKgPerHour: 10 },
          { id: "b", pollutant: "NOx", rateKgPerHour: 2 },
        ],
        light: { upwardLumens: 5000 },
        materials: [{ id: "m", name: "Steel", phase: "construction", quantityKg: 10 }],
      },
      {},
      "custom",
    );
    expect(n.find((x) => x.key === "air")!.from).toBe("emits NOx");
    expect(n.find((x) => x.key === "light")!.from).toBe("5,000 lm upward light");
    const m = n.find((x) => x.key === "materials")!;
    expect(m.advisory).toBe(true);
    expect(m.from).toContain("Steel");
  });
  it("round-trips the water intake source, fresh by default", () => {
    expect(parseStats(statsToDraft({ water: { source: "wastewater" } }), []).stats.water?.source).toBe("wastewater");
    expect(parseStats(statsToDraft({}), []).stats.water?.source).toBe("fresh");
  });
  it("recognises local air pollutants but not greenhouse gases", () => {
    expect(["NOx", "PM2.5", "SO₂", "CO", "VOCs"].map(isAirPollutant)).toEqual([true, true, true, true, true]);
    expect(["CO2", "CO2e (Scope 1)", "CH4"].map(isAirPollutant)).toEqual([false, false, false]);
  });
  it("marks undeclared needs as not checked, and a producer as exporting", () => {
    const n = siteNeeds({ power: { ratedOutputKw: 4000 } }, {}, "power_station");
    expect(n.find((x) => x.key === "land")!.from).toBeNull();
    expect(n.find((x) => x.key === "water")!.from).toBeNull();
    expect(n.find((x) => x.key === "power")!.from).toBe("exports 4 MW to the grid");
  });
});

describe("missingInputs", () => {
  const crit = (kind: Criterion["kind"], extra: Partial<Criterion> = {}): Criterion => ({ id: kind, kind, required: true, ...extra });

  it("asks for nothing when there are no extra limits: site checks are automatic", () => {
    expect(missingInputs({}, {}, { type: "water_plant" }, [])).toEqual([]);
  });
  it("lists nothing for map-layer requirements, which use map data only", () => {
    expect(missingInputs({}, {}, { type: "power_station" }, [crit("layer", { layerId: "slope", max: 5 })])).toEqual([]);
  });
  it("lists only the inputs each enabled requirement uses", () => {
    expect(missingInputs({}, {}, { type: "power_station" }, [crit("site_area")])).toEqual(["Footprint (m²)"]);
    expect(missingInputs({}, {}, { type: "power_station" }, [crit("energy_budget")])).toEqual([
      "Operating hours (h/day)",
      "Average power demand (kW)",
    ]);
    expect(missingInputs({ operatingHoursPerDay: 24 }, {}, { type: "water_plant" }, [crit("water_budget")])).toEqual(["Water input (m³/h)"]);
  });
  it("uses data-centre parameters for the derived basis", () => {
    const m = missingInputs({ demandBasis: "derived" }, { itPowerKw: 10 }, { type: "data_centre" }, [crit("energy_budget")]);
    expect(m).toContain("PUE");
    expect(m).not.toContain("IT power (kW)");
    expect(m).not.toContain("Average power demand (kW)");
  });
  it("adds criterion-specific needs", () => {
    const m = missingInputs({ emissions: [] }, {}, { type: "custom" }, [crit("emission_limit", { pollutant: "NOx" })]);
    expect(m).toContain("Emission rate for NOx (kg/h)");
  });
});

describe("demand basis", () => {
  it("is only sent as derived for a data centre", () => {
    const d = { ...statsToDraft({}), demandBasis: "derived" as const };
    expect(parseStats(d, [], "data_centre").stats.demandBasis).toBe("derived");
    expect(parseStats(d, [], "power_station").stats.demandBasis).toBe("direct");
    // a power station with the leftover choice still needs only its direct inputs
    const stats = parseStats(editValue(d, "power.averageDemandKw", "500"), [], "power_station").stats;
    const energy: Criterion = { id: "e", kind: "energy_budget", required: true };
    expect(missingInputs({ ...stats, operatingHoursPerDay: 24 }, {}, { type: "power_station" }, [energy])).toEqual([]);
  });
});

describe("section errors", () => {
  it("counts errors by path prefix", () => {
    const errors = { "power.averageDemandKw": "x", "power.peakDemandKw": "y", footprintM2: "z", "materials.m1.name": "n" };
    expect(countErrors(errors, ["power."])).toBe(2);
    expect(countErrors(errors, ["footprintM2", "operatingHoursPerDay"])).toBe(1);
    expect(countErrors(errors, ["materials."])).toBe(1);
    expect(countErrors(errors, ["costs."])).toBe(0);
  });
});

describe("checkComparison", () => {
  const base = { actual: 40, requiredValue: null, unit: "class" };
  it("never prints a raw class code or a single bound for map-layer checks", () => {
    expect(checkComparison({ ...base, kind: "layer" })).toBeNull();
  });
  it("shows building value and limit for other checks, unknown only when missing", () => {
    expect(checkComparison({ kind: "site_area", actual: 120, requiredValue: 500, unit: "m²" })).toBe("Building / site: 120 m² · Limit: 500 m²");
    expect(checkComparison({ kind: "site_area", actual: 120, requiredValue: null, unit: "m²" })).toMatch(/Limit: unknown$/);
  });
});

describe("criteria", () => {
  it("validates layer ranges and amounts", () => {
    const layer = { ...newCriterion("layer"), layerId: "slope", min: "5", max: "2" };
    const budget = { ...newCriterion("construction_budget"), amount: "-3" };
    const site = newCriterion("site_area");
    const { criteria, errors } = parseCriteria([layer, budget, site]);
    expect(errors[`${layer.id}.max`]).toBeTruthy();
    expect(errors[`${budget.id}.amount`]).toBeTruthy();
    expect(criteria[2]).toMatchObject({ kind: "site_area", required: true });
    expect(Object.keys(errors).some((k) => k.startsWith(site.id))).toBe(false);
  });
  it("accepts categorical classes", () => {
    const c = { ...newCriterion("layer"), layerId: "worldcover", classes: [10, 20] };
    expect(parseCriteria([c]).criteria[0].classes).toEqual([10, 20]);
    expect(parseCriteria([{ ...c, classes: [] }]).errors[`${c.id}.classes`]).toBeTruthy();
  });
});

describe("site, budgets, stress", () => {
  it("parses site assumptions with blank as unknown", () => {
    const d = { ...siteToDraft(null), usableAreaM2: "5000", waterAllocationM3PerDay: "0" };
    expect(parseSite(d).site).toMatchObject({ usableAreaM2: 5000, connectedCapacityKw: null, waterAllocationM3PerDay: 0 });
    expect(parseSite({ ...d, energyBudgetKwhPerDay: "x" }).errors.energyBudgetKwhPerDay).toBeTruthy();
  });
  it("validates budgets including radius scope", () => {
    const b = { ...newBudget(), label: "Grid", amount: "200", scopeKind: "radius" as const, latitude: "33", longitude: "-112", radiusKm: "0" };
    const { budgets, errors } = parseBudgets([b]);
    expect(budgets[0].amount).toBe(200);
    expect(errors[`${b.id}.radiusKm`]).toBeTruthy();
  });
  it("rejects one plant feeding two budgets of the same kind, like the server", () => {
    const a = { ...newBudget(), label: "Grid A", contributingProjectIds: ["p1", "p1"] };
    const b = { ...newBudget(), label: "Grid B", contributingProjectIds: ["p1"] };
    const water = { ...newBudget(), label: "Water", kind: "water_m3_per_day" as const, contributingProjectIds: ["p1"] };
    expect(parseBudgets([a, water]).errors).toEqual({});
    expect(parseBudgets([a, b]).errors[`${b.id}.contributors`]).toMatch(/Grid A/);
  });
  it("validates stress controls", () => {
    expect(parseStress(stressToDraft(NEUTRAL_STRESS))).toEqual({ stress: NEUTRAL_STRESS, errors: {} });
    const bad = parseStress({ ...stressToDraft(NEUTRAL_STRESS), waterAvailability: "1.5", operatingDemand: "-1" });
    expect(Object.keys(bad.errors).sort()).toEqual(["operatingDemand", "waterAvailability"]);
  });
  it("merges partial server assumptions with defaults", () => {
    const a = mergeAssumptions({ periodDays: 10, stress: { waterAvailability: 0.5 } });
    expect(a.periodDays).toBe(10);
    expect(a.stress).toEqual({ ...NEUTRAL_STRESS, waterAvailability: 0.5 });
    expect(a.budgets).toEqual([]);
    expect(mergeAssumptions(null).periodDays).toBe(30);
  });
  it("formats unknown quantities as unknown, never 0", () => {
    expect(fmtQuantity({ value: null, unit: "kWh", basis: "", missing: ["hours"] })).toBe("unknown");
    expect(fmtQuantity({ value: 0, unit: "kWh", basis: "", missing: [] })).toBe("0 kWh");
  });
});
