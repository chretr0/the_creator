import { describe, expect, it } from "vitest";
import type { BuildingCategory, BuildingTemplate, BuildingType } from "./buildings";
import { BUILDING_TYPES_ORDER } from "./buildingForm";
import { ICON_NAMES } from "../components/Icon";
import {
  BUILDING_CATEGORIES,
  PROJECT_TYPES,
  POWER_PRODUCER_TYPES,
  WATER_PRODUCER_TYPES,
  fallbackTemplate,
  groupTemplates,
  templateMatches,
  typeColour,
  typeIcon,
  typeLabel,
} from "./projectTypes";

/** Compile-time exhaustive list: adding or removing a BuildingType without updating this fails tsc. */
const ALL_TYPES: Record<BuildingType, true> = {
  power_station: true, solar: true, wind_farm: true, hydro_plant: true, geothermal_plant: true, battery_storage: true,
  hydrogen_plant: true, water_plant: true, wastewater_plant: true, mine: true, quarry: true, oil_gas_field: true,
  factory: true, steel_mill: true, aluminium_smelter: true, cement_plant: true, chemical_plant: true, oil_refinery: true,
  semiconductor_fab: true, farm: true, livestock_farm: true, greenhouse: true, vertical_farm: true, aquaculture: true,
  food_processing: true, data_centre: true, office: true, retail: true, hotel: true, research_lab: true, housing: true,
  hospital: true, school: true, university: true, stadium: true, airport: true, seaport: true, warehouse: true,
  landfill: true, recycling_facility: true, waste_to_energy: true, custom: true,
};
const TYPES = Object.keys(ALL_TYPES) as BuildingType[];

/** "Redmean" colour distance: a cheap approximation of perceived difference. */
function distance(a: number[], b: number[]) {
  const r = (a[0] + b[0]) / 2;
  const [dr, dg, db] = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  return Math.sqrt((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db);
}

describe("PROJECT_TYPES", () => {
  it("covers every building type exactly once, in picker order", () => {
    expect(TYPES).toHaveLength(42);
    expect(PROJECT_TYPES.map((d) => d.type)).toEqual(BUILDING_TYPES_ORDER);
    expect(new Set(BUILDING_TYPES_ORDER).size).toBe(BUILDING_TYPES_ORDER.length);
    expect([...BUILDING_TYPES_ORDER].sort()).toEqual([...TYPES].sort());
  });

  it("gives every type a label, a known category, an existing icon and a valid colour", () => {
    const categories = new Set<BuildingCategory>(BUILDING_CATEGORIES.map((c) => c.category));
    for (const d of PROJECT_TYPES) {
      expect(d.label.trim(), d.type).not.toBe("");
      expect(categories.has(d.category), d.type).toBe(true);
      expect(ICON_NAMES, d.type).toContain(d.icon);
      expect(d.colour.every((c) => Number.isInteger(c) && c >= 0 && c <= 255), d.type).toBe(true);
    }
    for (const c of BUILDING_CATEGORIES) expect(ICON_NAMES, c.category).toContain(c.icon);
  });

  it("keeps types in contiguous category runs, in category order", () => {
    const runs = PROJECT_TYPES.map((d) => d.category).filter((c, i, all) => c !== all[i - 1]);
    expect(runs).toEqual(BUILDING_CATEGORIES.map((c) => c.category));
  });

  it("uses distinguishable map colours and keeps the original six", () => {
    const labels = PROJECT_TYPES.map((d) => d.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (let i = 0; i < PROJECT_TYPES.length; i++) {
      for (let j = i + 1; j < PROJECT_TYPES.length; j++) {
        const [a, b] = [PROJECT_TYPES[i], PROJECT_TYPES[j]];
        expect(distance(a.colour, b.colour), `${a.type} vs ${b.type}`).toBeGreaterThan(60);
      }
    }
    expect(typeColour("data_centre")).toEqual([124, 92, 255]);
    expect(typeColour("solar")).toEqual([245, 176, 33]);
    expect(typeColour("greenhouse")).toEqual([46, 184, 114]);
    expect(typeColour("power_station")).toEqual([214, 69, 160]);
    expect(typeColour("water_plant")).toEqual([30, 136, 229]);
    expect(typeColour("custom")).toEqual([96, 108, 128]);
  });

  it("falls back gracefully for an unknown type", () => {
    expect(typeLabel("teleporter")).toBe("teleporter");
    expect(typeColour("teleporter")).toEqual([96, 108, 128]);
    expect(typeIcon("teleporter")).toBe("building");
  });
});

describe("fallbackTemplate", () => {
  it("works for every type and flags the backend's power and water producers", () => {
    for (const type of TYPES) {
      const t = fallbackTemplate(type);
      expect(t.type).toBe(type);
      expect(t.label).toBe(typeLabel(type));
      expect(t.description.trim()).not.toBe("");
    }
    expect(TYPES.filter((t) => fallbackTemplate(t).producesPower).sort()).toEqual(
      ["battery_storage", "geothermal_plant", "hydro_plant", "power_station", "solar", "waste_to_energy", "wind_farm"],
    );
    expect(TYPES.filter((t) => fallbackTemplate(t).producesWater).sort()).toEqual(["wastewater_plant", "water_plant"]);
    expect([...POWER_PRODUCER_TYPES].every((t) => !WATER_PRODUCER_TYPES.has(t))).toBe(true);
    expect(fallbackTemplate("data_centre").parameters.map((p) => p.key)).toContain("itPowerKw");
    expect(fallbackTemplate("wind_farm").category).toBe("energy");
  });
});

describe("groupTemplates", () => {
  const templates: BuildingTemplate[] = TYPES.map(fallbackTemplate);

  it("groups every template under its category, in category order", () => {
    const groups = groupTemplates(templates);
    expect(groups.map((g) => g.category)).toEqual(BUILDING_CATEGORIES.map((c) => c.category));
    expect(groups.flatMap((g) => g.templates).map((t) => t.type)).toEqual(BUILDING_TYPES_ORDER);
    expect(groups.find((g) => g.category === "transport")!.templates.map((t) => t.type)).toEqual(["airport", "seaport", "warehouse"]);
  });

  it("filters by label, type id, description and category, all words required", () => {
    const types = (q: string) => groupTemplates(templates, q).flatMap((g) => g.templates.map((t) => t.type));
    expect(types("wind")).toEqual(["wind_farm"]);
    expect(types("STEEL")).toEqual(["steel_mill"]);
    expect(types("oil gas")).toEqual(["oil_gas_field"]);
    expect(types("waste to energy")).toContain("waste_to_energy");
    expect(types("recycling")).toEqual(expect.arrayContaining(["landfill", "recycling_facility", "waste_to_energy"]));
    expect(types("  ")).toHaveLength(42);
    expect(types("zzz-no-match")).toEqual([]);
  });

  it("always keeps the selected template visible", () => {
    const groups = groupTemplates(templates, "wind", "hospital");
    expect(groups.map((g) => g.category)).toEqual(["energy", "community"]);
    expect(groups[1].templates.map((t) => t.type)).toEqual(["hospital"]);
  });

  it("uses the type's category when a template lacks a known one", () => {
    const odd = { ...fallbackTemplate("mine"), category: "mystery" as BuildingCategory };
    expect(groupTemplates([odd])[0].category).toBe("extraction");
    expect(templateMatches(odd, "mining")).toBe(true);
  });
});
