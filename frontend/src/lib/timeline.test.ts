import { describe, expect, it } from "vitest";
import { concentrationAt, exposureAt, DEFAULT_DISPERSION, dailyEmission, impactCells, knownTotal, pollutantKey, timelineViewLabel,
  DEFAULT_ENVIRONMENT, TIMELINE_DAYS, FIRST_STEP, LAST_STEP, timeLabel, TIMELINE_HORIZON_DAYS, impactColour, impactUnit, soilConcentration, type TimelineData, type TimelineProject } from "./timeline";

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
  it("only releases elapsed emissions: the first hour cannot already contain the first day's distant plume", () => {
    // 3 m/s travels 10.8 km/hour: 50 km is far beyond the first-hour plume but inside the first day.
    expect(concentrationAt(50000, 0, 240, 1 / 24, DEFAULT_DISPERSION)).toBe(0);
    expect(concentrationAt(50000, 0, 240, 1, DEFAULT_DISPERSION)).toBeGreaterThan(0);
    expect(concentrationAt(500000, 0, 240, 1, DEFAULT_DISPERSION)).toBe(0);
    expect(concentrationAt(-50000, 0, 240, 1, DEFAULT_DISPERSION)).toBe(0);
    expect(knownTotal([240], 1).value).toBe(240);
  });
  it("preserves concentrations after local flow settles instead of changing them as time bins move", () => {
    for (const params of [DEFAULT_DISPERSION, { ...DEFAULT_DISPERSION, windSpeed: 30, diffusion: 10 }]) {
      for (const east of [0, 3000, 30000, 55000, 80000]) {
        const firstDay = concentrationAt(east, 0, 240, 1, params);
        for (const days of TIMELINE_DAYS) expect(concentrationAt(east, 0, 240, days, params)).toBe(firstDay);
      }
    }
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

describe("accumulated air exposure", () => {
  it("increases at every timeline step while instantaneous concentration can remain steady", () => {
    let previous = 0;
    for (const days of TIMELINE_DAYS) {
      const exposure = exposureAt(3000, 0, 240, days, DEFAULT_DISPERSION);
      expect(exposure).toBeGreaterThan(previous);
      expect(exposure).toBeLessThan(concentrationAt(3000, 0, 240, days, DEFAULT_DISPERSION) * days);
      previous = exposure;
    }
    expect(previous).toBeGreaterThan(exposureAt(3000, 0, 240, 1, DEFAULT_DISPERSION) * 1800);
  });
  it("integrates the history at the receptor instead of multiplying the final concentration by elapsed time", () => {
    // Independently integrate concentration snapshots over the first day at a distant receptor.
    const count = 192, dt = 1 / count;
    let integrated = 0;
    for (let i = 0; i <= count; i++) {
      const weight = i === 0 || i === count ? 1 : i % 2 ? 4 : 2;
      integrated += concentrationAt(50000, 0, 240, i * dt, DEFAULT_DISPERSION) * weight * dt / 3;
    }
    expect(exposureAt(50000, 0, 240, 1, DEFAULT_DISPERSION)).toBeCloseTo(integrated, 5);
    expect(exposureAt(50000, 0, 240, 1 / 24, DEFAULT_DISPERSION)).toBe(0);
    expect(exposureAt(50000, 0, 240, 0, DEFAULT_DISPERSION)).toBe(0);
    expect(exposureAt(50000, 0, 0, 1, DEFAULT_DISPERSION)).toBe(0);
  });
  it("uses concentration-day units and integrates the baseline without changing measured inputs", () => {
    const pm = { ...data, projects: [{ ...project, emissions: [{ pollutant: "PM2.5", kgPerDay: 24, missing: [] }] }] };
    const [cell] = impactCells(pm, "pm25", 2, DEFAULT_DISPERSION, "combined", "air", DEFAULT_ENVIRONMENT, "exposure");
    expect(cell.baseline).toBe(24);
    expect(cell.value).toBe(cell.added! + 24);
    expect(pm.cells[0].pm25).toBe(12);
    expect(impactCells(pm, "pm25", 2, DEFAULT_DISPERSION, "baseline")[0].value).toBe(12);
    expect(impactUnit("air", "exposure")).toBe("µg·day/m³");
    expect(impactUnit("air", "concentration")).toBe("µg/m³");
    expect(timelineViewLabel("air", "added", "exposure")).toBe("Accumulated exposure");
    expect(timelineViewLabel("air", "baseline", "exposure")).toBe("Historical reference exposure");
  });
  it("preserves unknown contributions and superposes matching sources", () => {
    const one = impactCells(data, "co2", 4, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "exposure")[0];
    const doubled = impactCells({ ...data, projects: [project, { ...project, id: "p2" }] }, "co2", 4, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "exposure")[0];
    expect(doubled.added).toBe(one.added! * 2);
    expect(one.baseline).toBeNull();
    expect(impactCells(data, "co2", 4, DEFAULT_DISPERSION, "combined", "air", DEFAULT_ENVIRONMENT, "exposure")[0].value).toBeNull();
    const unknown = { ...data, projects: [{ ...project, emissions: [{ pollutant: "CO2", kgPerDay: null, missing: ["rate"] }] }] };
    expect(impactCells(unknown, "co2", 4, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "exposure")[0].added).toBeNull();
  });
  it("keeps the air measure separate from soil, water and CO2e accounting", () => {
    for (const medium of ["soil", "freshwater", "marine", "climate"] as const) {
      const fixture: TimelineData = { ...data, projects: [{ ...project, displayCell: "test",
        emissions: [{ pollutant: medium === "climate" ? "CO2e" : "Lead", medium, kgPerDay: 240, missing: [] }],
        river: { cells: [{ h3Id: "test", distanceM: 0, flowM3PerSecond: 10 }], distanceKm: 0, note: "fixture" },
        marineRelease: { latitude: 0, longitude: 0, note: "fixture" },
      }], cells: [{ ...data.cells[0], surface: medium === "marine" ? "marine" : "land" }] };
      const pollutant = medium === "climate" ? "co2e" : "lead";
      const normal = impactCells(fixture, pollutant, 2, DEFAULT_DISPERSION, "added", medium);
      expect(impactCells(fixture, pollutant, 2, DEFAULT_DISPERSION, "added", medium, DEFAULT_ENVIRONMENT, "exposure")).toEqual(normal);
      expect(impactUnit(medium, "exposure")).toBe(impactUnit(medium));
    }
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

describe("exponential five-year horizon", () => {
  it("doubles from day one and caps the final step at exactly five model years", () => {
    expect(TIMELINE_DAYS).toEqual([1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 1826.25]);
    expect(TIMELINE_DAYS[FIRST_STEP]).toBe(1);
    expect(TIMELINE_DAYS[LAST_STEP]).toBe(TIMELINE_HORIZON_DAYS);
    for (let step = 1; step < LAST_STEP; step++) expect(TIMELINE_DAYS[step]).toBe(TIMELINE_DAYS[step - 1] * 2);
    for (const days of TIMELINE_DAYS) expect(knownTotal([240], days).value).toBe(240 * days);
    expect(timeLabel(1)).toBe("1 day");
    expect(timeLabel(2)).toBe("2 days");
    expect(timeLabel(1024)).toBe("1,024 days");
    expect(timeLabel(TIMELINE_HORIZON_DAYS)).toBe("5 years · 1,826.25 days");
  });
  it("keeps five-year totals cumulative, with unknown contributions still unknown", () => {
    expect(knownTotal([4800], TIMELINE_HORIZON_DAYS).value).toBe(8766000);
    expect(knownTotal([null], TIMELINE_HORIZON_DAYS).value).toBeNull();
    expect(knownTotal([0], TIMELINE_HORIZON_DAYS).value).toBe(0);
    const co2e = { ...data, projects: [{ ...project, displayCell: "test", emissions: [{ pollutant: "CO2e", kgPerDay: 4800, missing: [] }] }] };
    expect(impactCells(co2e, "co2e", TIMELINE_HORIZON_DAYS, DEFAULT_DISPERSION, "added")[0].added).toBe(8766000);
    expect(soilConcentration(0, 0, 240, TIMELINE_HORIZON_DAYS, DEFAULT_ENVIRONMENT)).toBeCloseTo(soilConcentration(0, 0, 240, 1, DEFAULT_ENVIRONMENT) * TIMELINE_HORIZON_DAYS);
  });
  it("preserves the historical baseline and produces finite nonnegative concentrations at every time step", () => {
    for (const days of TIMELINE_DAYS) {
      const [cell] = impactCells(data, "co2", days, DEFAULT_DISPERSION, "added");
      expect(Number.isFinite(cell.added)).toBe(true);
      expect(cell.added).toBeGreaterThanOrEqual(0);
      expect(impactCells(data, "pm25", days, DEFAULT_DISPERSION, "baseline")[0].value).toBe(12);
    }
  });
  it("stays within 1% of fine integration from the first hour to five years, beyond the local display edge", () => {
    // Independent composite Simpson quadrature in log(age+1), using the continuous Gaussian equation.
    function reference(east: number, speed: number, diffusion: number, days: number) {
      const n = 32768, du = Math.log1p(days * 86400) / n;
      let sum = 0;
      for (let i = 0; i <= n; i++) {
        const age = Math.expm1(i * du), variance = 750 ** 2 + 2 * diffusion * age;
        const f = Math.exp(i * du) * 240 * 1e9 / 86400 / (2 * Math.PI * variance * 500)
          * Math.exp(-((east - speed * age) ** 2) / (2 * variance));
        sum += f * (i === 0 || i === n ? 1 : i % 2 ? 4 : 2);
      }
      return sum * du / 3;
    }
    for (const days of [1 / 24, 1, 2, 1024, TIMELINE_HORIZON_DAYS])
      for (const [speed, diffusion] of [[0, 200], [3, 200], [30, 10]])
        for (const east of [0, 3000, 30000, 55000, 80000, 100000]) {
          const actual = concentrationAt(east, 0, 240, days, { ...DEFAULT_DISPERSION, windSpeed: speed, diffusion });
          const expected = reference(east, speed, diffusion, days);
          expect(Math.abs(actual - expected), `days=${days}, wind=${speed}, east=${east}`).toBeLessThan(Math.max(1e-12, expected * .01));
        }
  });
});

describe("timeline colour scale", () => {
  it("uses linear opacity so faint tails are not made to look ten times stronger", () => {
    expect(impactColour(0, 100)[3]).toBe(0);
    expect(impactColour(1, 100)[3]).toBe(2);
    expect(impactColour(10, 100)[3]).toBe(21);
    expect(impactColour(50, 100)[3]).toBe(103);
    expect(impactColour(100, 100)[3]).toBe(205);
    expect(impactColour(200, 100)).toEqual(impactColour(100, 100));
    expect(impactColour(null, 100)).toEqual([130, 145, 160, 55]);
  });
});

it("keeps river and sea outputs finite across all exponential steps without inventing baselines", () => {
  const water: TimelineData = { ...data, projects: [{ ...project, emissions: [
    { pollutant: "Lead", medium: "freshwater", kgPerDay: 240, missing: [] },
    { pollutant: "Lead", medium: "marine", kgPerDay: 240, missing: [] },
  ], river: { cells: [{ h3Id: "test", distanceM: 3000, flowM3PerSecond: 10 }], distanceKm: 0, note: "fixture" },
    marineRelease: { latitude: 0, longitude: 0, note: "fixture" } }], cells: [{ ...data.cells[0], surface: "marine" }] };
  for (const days of TIMELINE_DAYS) {
    for (const medium of ["freshwater", "marine"] as const) {
      const cell = impactCells(water, "lead", days, DEFAULT_DISPERSION, "added", medium)[0];
      expect(Number.isFinite(cell.added)).toBe(true);
      expect(cell.added).toBeGreaterThan(0);
      expect(cell.baseline).toBeNull();
      if (medium === "freshwater") expect(cell.added).toBeCloseTo(240 / 86400 / 10 * 1000);
    }
  }
});
