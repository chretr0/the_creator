import { describe, expect, it } from "vitest";
import { concentrationAt, DEFAULT_DISPERSION, dailyEmission, impactCells, knownTotal, pollutantKey,
  DEFAULT_ENVIRONMENT, impactUnit, soilConcentration, type TimelineData, type TimelineProject } from "./timeline";

const project: TimelineProject = { id: "p", name: "Station", type: "power_station", latitude: 0, longitude: 0,
  emissions: [{ pollutant: "CO₂", kgPerDay: 240, missing: [] }], electricityKwhPerDay: 10, waterM3PerDay: null,
  electricityOutputKwhPerDay: null, waterOutputM3PerDay: null };
const data: TimelineData = { projects: [project], cells: [{ h3Id: "test", latitude: 0, longitude: .03, pm25: 12, pm10: null }],
  baseline: { label: "CAMS", period: "2024", resolution: "80 km", sourceId: "AIR-02", units: "µg/m³" } };

describe("timeline accounting", () => {
  it("normalises aliases without mixing CO2 with CO or CO2e", () => {
    expect(pollutantKey("carbon dioxide")).toBe(pollutantKey("CO₂"));
    expect(pollutantKey("CO2e")).not.toBe(pollutantKey("CO₂"));
    expect(pollutantKey("CO2 (direct, 2023)")).toBe("co2");
    expect(pollutantKey("CH₄")).toBe("ch4");
    expect(dailyEmission(project, "co2")).toBe(240);
    expect(dailyEmission(project, "co")).toBeNull();
  });
  it("preserves unknown rates, distinguishes explicit zero, and identifies partial totals", () => {
    expect(dailyEmission({ ...project, emissions: [{ pollutant: "CO2", kgPerDay: null, missing: [] }] }, "co2")).toBeNull();
    expect(knownTotal([0, null], 30)).toEqual({ value: 0, known: 1, total: 2 });
    expect(knownTotal([null], 30).value).toBeNull();
    expect(knownTotal([240, null], 2).value).toBe(480);
  });
  it("never invents a CO2 baseline or converts unrelated columns", () => {
    const [cell] = impactCells(data, "co2", 1, DEFAULT_DISPERSION, "combined");
    expect(cell.added).toBeGreaterThan(0);
    expect(cell.baseline).toBeNull();
    expect(cell.value).toBeNull();
  });
  it("maps existing CO2e aliases to source-cell totals with no invented air concentration", () => {
    for (const pollutant of ["CO2e (market-based Scope 1+2)", "PFCs (as CO2e)", "CO₂ equivalent"]) {
      const accounting = { ...data, projects: [{ ...project, displayCell: "test", emissions: [{ pollutant, kgPerDay: 4800, missing: [] }] }] };
      const key = pollutantKey(pollutant);
      expect(key).toBe("co2e");
      expect(dailyEmission(accounting.projects[0], key)).toBe(4800);
      const cell = impactCells(accounting, key, 30, DEFAULT_DISPERSION, "added")[0];
      expect(cell.added).toBe(144000);
      expect(cell.baseline).toBeNull();
      expect(impactUnit("climate")).toBe("kgCO₂e");
    }
  });
  it("does not disperse off-site Scope 2 CO2 locally", () => {
    const accounting = { ...data, projects: [{ ...project, emissions: [{ pollutant: "CO2 (Scope 2)", kgPerDay: 240, missing: [] }] }] };
    expect(impactCells(accounting, pollutantKey("CO2 (Scope 2)"), 1, DEFAULT_DISPERSION, "added")[0].added).toBeNull();
  });
  it("keeps the measured baseline unchanged and adds only the matching pollutant", () => {
    const pm = { ...data, projects: [{ ...project, emissions: [{ pollutant: "PM2.5", kgPerDay: 24, missing: [] }] }] };
    const [before] = impactCells(pm, "pm25", 0, DEFAULT_DISPERSION, "combined");
    const [after] = impactCells(pm, "pm25", 1, DEFAULT_DISPERSION, "combined");
    expect(before.value).toBe(12);
    expect(after.value).toBeGreaterThan(12);
    expect(after.baseline).toBe(12);
    expect(pm.cells[0].pm25).toBe(12);
  });
  it("superposes overlapping projects and wraps the date line", () => {
    const one = impactCells(data, "co2", 1, DEFAULT_DISPERSION, "added")[0].added!;
    expect(impactCells({ ...data, projects: [project, { ...project, id: "p2" }] }, "co2", 1, DEFAULT_DISPERSION, "added")[0].added).toBeCloseTo(one * 2);
    const across = { ...data, projects: [{ ...project, longitude: 179.99 }], cells: [{ ...data.cells[0], longitude: -179.98 }] };
    expect(impactCells(across, "co2", 1, DEFAULT_DISPERSION, "added")[0].added).toBeCloseTo(one, 5);
  });
});
describe("illustrative Gaussian transport", () => {
  it("has no impact before operation and scales linearly with emission rate", () => {
    expect(concentrationAt(0, 0, 240, 0, DEFAULT_DISPERSION)).toBe(0);
    const one = concentrationAt(3000, 0, 240, 1, DEFAULT_DISPERSION);
    expect(concentrationAt(3000, 0, 480, 1, DEFAULT_DISPERSION)).toBeCloseTo(one * 2);
  });
  it("a westerly wind carries pollution east and a deeper mixed layer dilutes it", () => {
    const east = concentrationAt(4000, 0, 240, 1, DEFAULT_DISPERSION);
    expect(east).toBeGreaterThan(concentrationAt(-4000, 0, 240, 1, DEFAULT_DISPERSION) * 10);
    expect(concentrationAt(4000, 0, 240, 1, { ...DEFAULT_DISPERSION, mixingHeight: 1000 })).toBeCloseTo(east / 2);
  });
  it("conserves emitted mass over a sufficiently large grid in calm conditions", () => {
    const params = { ...DEFAULT_DISPERSION, windSpeed: 0 };
    let kg = 0;
    for (let x = -10000; x <= 10000; x += 500) for (let y = -10000; y <= 10000; y += 500)
      kg += concentrationAt(x, y, 240, 1 / 24, params) * 500 ** 2 * params.mixingHeight / 1e9;
    expect(kg).toBeCloseTo(10, 2);
  });
  it("local concentrations level off under wind while total emitted mass continues to grow", () => {
    const day = concentrationAt(4000, 0, 240, 1, DEFAULT_DISPERSION);
    const month = concentrationAt(4000, 0, 240, 30, DEFAULT_DISPERSION);
    expect(month / day).toBeGreaterThan(.97);
    expect(month / day).toBeLessThan(1.03);
    expect(knownTotal([240], 30).value).toBe(7200);
  });
});

describe("separate receiving environments", () => {
  const mixed: TimelineData = { ...data, projects: [{ ...project, displayCell: "test", emissions: [
    { pollutant: "Lead", medium: "air", kgPerDay: 2, missing: [] },
    { pollutant: "Lead", medium: "soil", kgPerDay: 20, missing: [] },
    { pollutant: "Lead", medium: "freshwater", kgPerDay: 864, missing: [] },
    { pollutant: "Lead", medium: "marine", kgPerDay: 240, missing: [] },
  ], river: { cells: [{ h3Id: "test", distanceM: 3600, flowM3PerSecond: 10 }], distanceKm: 1, note: "fixture" },
    marineRelease: { latitude: 0, longitude: 0, note: "fixture" } }],
    cells: [{ ...data.cells[0], surface: "land" }, { ...data.cells[0], h3Id: "sea", surface: "marine" }] };
  it("never adds the same pollutant across different environments", () => {
    expect(dailyEmission(mixed.projects[0], "lead", "air")).toBe(2);
    expect(dailyEmission(mixed.projects[0], "lead", "soil")).toBe(20);
    expect(dailyEmission(mixed.projects[0], "lead", "freshwater")).toBe(864);
  });
  it("soil accumulates with time, dilutes with mixing mass, and excludes sea cells", () => {
    const one = soilConcentration(0, 0, 20, 1, DEFAULT_ENVIRONMENT);
    expect(soilConcentration(0, 0, 20, 30, DEFAULT_ENVIRONMENT)).toBeCloseTo(one * 30);
    expect(soilConcentration(0, 0, 20, 1, { ...DEFAULT_ENVIRONMENT, soilDepth: .4 })).toBeCloseTo(one / 2);
    const cells = impactCells(mixed, "lead", 1, DEFAULT_DISPERSION, "added", "soil");
    expect(cells[0].added).toBeGreaterThan(0);
    expect(cells[1].added).toBeNull();
    expect(cells[0].baseline).toBeNull();
  });
  it("river arrival follows travel time, concentration uses flow, and other cells stay unknown", () => {
    expect(impactCells(mixed, "lead", 1 / 24, DEFAULT_DISPERSION, "added", "freshwater")[0].added).toBe(0);
    const cells = impactCells(mixed, "lead", 1, DEFAULT_DISPERSION, "added", "freshwater");
    expect(cells[0].added).toBe(1);
    expect(cells[1].added).toBeNull();
    const noFlow = { ...mixed, projects: [{ ...mixed.projects[0], river: { cells: [{ h3Id: "test", distanceM: 3600, flowM3PerSecond: null }], distanceKm: 1, note: "" } }] };
    expect(impactCells(noFlow, "lead", 1, DEFAULT_DISPERSION, "added", "freshwater")[0].added).toBeNull();
    expect(dailyEmission(noFlow.projects[0], "lead", "freshwater")).toBe(864);
  });
  it("marine uses its own current and water depth and never colours land", () => {
    const cells = impactCells(mixed, "lead", 1, DEFAULT_DISPERSION, "added", "marine");
    expect(cells[0].added).toBeNull();
    expect(cells[1].added).toBeGreaterThan(0);
    const deeper = impactCells(mixed, "lead", 1, DEFAULT_DISPERSION, "added", "marine", { ...DEFAULT_ENVIRONMENT, seaDepth: 20 });
    expect(deeper[1].added).toBeCloseTo(cells[1].added! / 2, 10);
    const otherWind = impactCells(mixed, "lead", 1, { ...DEFAULT_DISPERSION, windFrom: 90 }, "added", "marine");
    expect(otherWind[1].added).toBe(cells[1].added);
    const noSea = { ...mixed, projects: [{ ...mixed.projects[0], marineRelease: { latitude: null, longitude: null, note: "inland" } }] };
    expect(impactCells(noSea, "lead", 1, DEFAULT_DISPERSION, "added", "marine")[1].added).toBeNull();
  });
  it("all media are zero before operation where inputs exist, unknown otherwise", () => {
    for (const medium of ["air", "soil", "freshwater", "marine"] as const) {
      const cells = impactCells(mixed, "lead", 0, DEFAULT_DISPERSION, "added", medium);
      expect(cells.some((c) => c.added === 0)).toBe(true);
      expect(cells.every((c) => c.added === 0 || c.added === null)).toBe(true);
    }
  });
});
