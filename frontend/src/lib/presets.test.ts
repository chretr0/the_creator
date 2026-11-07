import { describe, expect, it } from "vitest";
import type { BuildingPreset } from "./buildings";
import { editEmission, editMaterial, editOperating, editValue, parseStats, statsToDraft } from "./buildingForm";
import { presetPlace, presetToForm, sourceCount, splitPresetsByType } from "./presets";

const cited = (note: string) => ({ kind: "cited" as const, note });

const PRESET: BuildingPreset = {
  id: "example-plant",
  name: "Example Plant",
  type: "power_station",
  description: "A real gas plant.",
  headline: "1,000 MW combined cycle",
  referenceSite: { name: "Example Plant", latitude: 51.5, longitude: -0.1, country: "United Kingdom" },
  stats: {
    footprintM2: 120000,
    operatingHoursPerDay: 24,
    power: { ratedOutputKw: 1_000_000, capacityFactor: 0.55, technology: "CCGT", provenance: cited("S1: nameplate") },
    water: { inputM3PerHour: 50, provenance: cited("S2: abstraction licence") },
    workers: { staffingRequired: 60, provenance: cited("S1: staff") },
    costs: {
      currency: "GBP",
      constructionTotal: 500_000_000,
      operating: { amount: null, period: "year", kind: "fixed" },
      provenance: cited("S3: capex"),
    },
    materials: [
      { id: "m1", name: "Steel", phase: "construction", quantityKg: 9_000_000, provenance: cited("S1: steel") },
      { id: "m2", name: "Concrete", phase: "construction", quantityKg: 40_000_000, provenance: cited("S1: concrete") },
    ],
    emissions: [{ id: "e1", pollutant: "NOx", rateKgPerHour: 30, provenance: cited("S4: permit") }],
    footprintProvenance: cited("S1: site plan"),
  },
  parameters: { fuel: "gas" },
  sources: [
    { id: "S1", title: "Plant fact sheet", publisher: "Operator", url: "https://example.org/s1" },
    { id: "S2", title: "Licence", publisher: "Regulator", url: "https://example.org/s2", year: "2020" },
  ],
  notes: ["Capacity factor is the 2022 average."],
};

describe("presetToForm", () => {
  it("copies type, name, description, values and parameters", () => {
    const f = presetToForm(PRESET);
    expect(f.type).toBe("power_station");
    expect(f.name).toBe("Example Plant");
    expect(f.description).toBe("A real gas plant.");
    expect(f.stats.values["power.ratedOutputKw"]).toBe("1000000");
    expect(f.stats.values["costs.currency"]).toBe("GBP");
    expect(f.stats.values["power.averageDemandKw"]).toBe(""); // unknown stays blank, never 0
    expect(f.stats.params).toEqual({ fuel: "gas" });
    expect(f.stats.basedOn).toBe("Example Plant");
  });

  it("keeps cited provenance for every section and item", () => {
    const { stats } = presetToForm(PRESET);
    expect(stats.provenance.power).toEqual(cited("S1: nameplate"));
    expect(stats.provenance.water).toEqual(cited("S2: abstraction licence"));
    expect(stats.provenance.footprint).toEqual(cited("S1: site plan"));
    expect(stats.provenance.costs.kind).toBe("cited");
    expect(stats.materials.map((m) => m.provenance.kind)).toEqual(["cited", "cited"]);
    expect(stats.emissions[0].provenance).toEqual(cited("S4: permit"));
  });

  it("does not mutate the preset", () => {
    const before = JSON.stringify(PRESET);
    const { stats } = presetToForm(PRESET);
    editValue(stats, "power.ratedOutputKw", "1");
    expect(JSON.stringify(PRESET)).toBe(before);
  });
});

describe("editing a preset-based draft", () => {
  const edited = { kind: "user_assumption", note: "edited from Example Plant" };

  it("flips only the edited section to a user assumption", () => {
    const d = editValue(presetToForm(PRESET).stats, "water.inputM3PerHour", "60");
    expect(d.provenance.water).toEqual(edited);
    expect(d.provenance.power.kind).toBe("cited");
    expect(d.provenance.costs.kind).toBe("cited");
    expect(d.provenance.footprint.kind).toBe("cited");
  });

  it("flips only the edited material or emission row", () => {
    let d = presetToForm(PRESET).stats;
    d = editMaterial(d, { ...d.materials[1], quantity: "1" });
    expect(d.materials[0].provenance.kind).toBe("cited");
    expect(d.materials[1].provenance).toEqual(edited);
    d = editEmission(d, { ...d.emissions[0], rate: "25" });
    expect(d.emissions[0].provenance).toEqual(edited);
    expect(d.provenance.power.kind).toBe("cited");
  });

  it("flips costs when the operating period or kind changes", () => {
    const d = editOperating(presetToForm(PRESET).stats, { operatingKind: "total" });
    expect(d.operatingKind).toBe("total");
    expect(d.provenance.costs).toEqual(edited);
    expect(d.provenance.water.kind).toBe("cited");
  });

  it("operating hours (no section) leave every provenance alone", () => {
    const d = editValue(presetToForm(PRESET).stats, "operatingHoursPerDay", "20");
    expect(d.provenance).toEqual(presetToForm(PRESET).stats.provenance);
  });

  it("edits outside a preset are plain user assumptions", () => {
    const d = editValue(statsToDraft({ water: { inputM3PerHour: 1, provenance: cited("x") } }), "water.inputM3PerHour", "2");
    expect(d.provenance.water).toEqual({ kind: "user_assumption" });
  });
});

describe("serialising a preset-based draft", () => {
  it("keeps cited provenance for untouched sections and items", () => {
    let d = presetToForm(PRESET).stats;
    d = editValue(d, "power.capacityFactor", "0.6");
    d = editMaterial(d, { ...d.materials[0], quantity: "8000000" });
    const { stats, parameters, errors } = parseStats(d, [{ key: "fuel", label: "Fuel", unit: "", kind: "select", options: ["gas"] }], "power_station");
    expect(errors).toEqual({});
    expect(stats.power?.capacityFactor).toBe(0.6);
    expect(stats.power?.provenance).toEqual({ kind: "user_assumption", note: "edited from Example Plant" });
    expect(stats.water?.provenance).toEqual(cited("S2: abstraction licence"));
    expect(stats.workers?.provenance).toEqual(cited("S1: staff"));
    expect(stats.costs?.provenance).toEqual(cited("S3: capex"));
    expect(stats.footprintProvenance).toEqual(cited("S1: site plan"));
    expect(stats.materials?.[0].provenance?.kind).toBe("user_assumption");
    expect(stats.materials?.[1].provenance).toEqual(cited("S1: concrete"));
    expect(stats.emissions?.[0].provenance).toEqual(cited("S4: permit"));
    expect(stats.water?.inputM3PerHour).toBe(50);
    expect(parameters).toEqual({ fuel: "gas" });
  });

  it("round-trips: saved stats reload with the same provenance", () => {
    const { stats } = parseStats(presetToForm(PRESET).stats, [], "power_station");
    const again = statsToDraft(stats, {});
    expect(again.provenance).toEqual(presetToForm(PRESET).stats.provenance);
    expect(again.basedOn).toBeUndefined();
  });
});

describe("labels", () => {
  it("formats the place and source count", () => {
    expect(presetPlace(PRESET)).toBe("Example Plant, United Kingdom");
    expect(sourceCount(1)).toBe("1 source");
    expect(sourceCount(3)).toBe("3 sources");
  });
});

describe("splitPresetsByType", () => {
  it("puts the selected type's presets first and keeps the rest in order", () => {
    const ps = [{ type: "mine" }, { type: "office" }, { type: "mine" }, { type: "farm" }] as const;
    const { matching, others } = splitPresetsByType([...ps], "mine");
    expect(matching).toEqual([ps[0], ps[2]]);
    expect(others).toEqual([ps[1], ps[3]]);
  });
});
