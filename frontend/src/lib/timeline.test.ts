import { describe, expect, it } from "vitest";
import { concentrationAt, exposureAt, DEFAULT_DISPERSION, dailyEmission, impactCells, knownTotal, pollutantKey, timelineViewLabel,
  DEFAULT_ENVIRONMENT, TIMELINE_DAYS, FIRST_STEP, LAST_STEP, timeLabel, TIMELINE_HORIZON_DAYS, impactColour, impactUnit, soilConcentration, stepLabel, projectDispersion, directionFrom, type LocalWind, releasedPollutants, defaultScale, type TimelineData, type TimelineProject } from "./timeline";

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
        for (const days of TIMELINE_DAYS.filter((d) => d >= 1)) expect(concentrationAt(east, 0, 240, days, params)).toBe(firstDay);
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
    expect(exposureAt(3000, 0, 240, TIMELINE_DAYS[FIRST_STEP], DEFAULT_DISPERSION)).toBe(0);
    for (const days of TIMELINE_DAYS.slice(1)) {
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
  it("starts at day 0 and uses round calendar steps that grow, ending at five years", () => {
    expect(TIMELINE_DAYS).toEqual([0, 1 / 24, 2 / 24, 4 / 24, 8 / 24, 1, 2, 4, 7, 14, 30, 91, 183, 365, 731, 1826]);
    expect(TIMELINE_DAYS[FIRST_STEP]).toBe(0);
    expect(TIMELINE_DAYS[LAST_STEP]).toBe(TIMELINE_HORIZON_DAYS);
    // Sub-day steps are whole hours; every later step is a whole number of days.
    for (const days of TIMELINE_DAYS) expect(Number.isInteger(days < 1 ? Math.round(days * 24 * 1e9) / 1e9 : days)).toBe(true);
    // Each step advances further than the last: slow at first, then faster and faster.
    for (let step = 3; step <= LAST_STEP; step++)
      expect(TIMELINE_DAYS[step] - TIMELINE_DAYS[step - 1]).toBeGreaterThan(TIMELINE_DAYS[step - 1] - TIMELINE_DAYS[step - 2]);
    for (const days of TIMELINE_DAYS) expect(knownTotal([240], days).value).toBe(240 * days);
    expect(TIMELINE_DAYS.map(timeLabel)).toEqual(["Day 0 · operation begins", "1 hour", "2 hours", "4 hours", "8 hours",
      "1 day", "2 days", "4 days", "1 week · 7 days", "2 weeks · 14 days", "1 month · 30 days", "3 months · 91 days",
      "6 months · 183 days", "1 year · 365 days", "2 years · 731 days", "5 years · 1,826 days"]);
    expect(TIMELINE_DAYS.map(stepLabel)).toEqual(["Start", "1 h", "2 h", "4 h", "8 h", "1 d", "2 d", "4 d", "1 wk", "2 wk",
      "1 mo", "3 mo", "6 mo", "1 y", "2 y", "5 y"]);
    expect(timeLabel(2.6)).toBe("3 days");
    expect(timeLabel(.3)).toBe("7 hours");
  });
  it("shows nothing released at day 0 in every environment", () => {
    for (const medium of ["air", "soil", "freshwater", "marine", "climate"] as const)
      for (const cell of impactCells(data, "co2", 0, DEFAULT_DISPERSION, "added", medium)) expect(cell.added ?? 0).toBe(0);
    expect(knownTotal([240], 0).value).toBe(0);
  });
  it("keeps five-year totals cumulative, with unknown contributions still unknown", () => {
    expect(knownTotal([4800], TIMELINE_HORIZON_DAYS).value).toBe(4800 * 1826);
    expect(knownTotal([null], TIMELINE_HORIZON_DAYS).value).toBeNull();
    expect(knownTotal([0], TIMELINE_HORIZON_DAYS).value).toBe(0);
    const co2e = { ...data, projects: [{ ...project, displayCell: "test", emissions: [{ pollutant: "CO2e", kgPerDay: 4800, missing: [] }] }] };
    expect(impactCells(co2e, "co2e", TIMELINE_HORIZON_DAYS, DEFAULT_DISPERSION, "added")[0].added).toBe(4800 * 1826);
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
  // River outfall is 3 km away at 0.3 m/s (2.8 hours), so check from day 1 onwards.
  for (const days of TIMELINE_DAYS.filter((d) => d >= 1)) {
    for (const medium of ["freshwater", "marine"] as const) {
      const cell = impactCells(water, "lead", days, DEFAULT_DISPERSION, "added", medium)[0];
      expect(Number.isFinite(cell.added)).toBe(true);
      expect(cell.added).toBeGreaterThan(0);
      expect(cell.baseline).toBeNull();
      if (medium === "freshwater") expect(cell.added).toBeCloseTo(240 / 86400 / 10 * 1000);
    }
  }
});

describe("pollutants offered by the timeline", () => {
  const building = (emissions: TimelineProject["emissions"]): TimelineProject => ({ ...project, emissions });
  it("lists only what the placed buildings release, per receiving environment", () => {
    const released = releasedPollutants([
      building([{ pollutant: "CO₂", kgPerDay: 240, missing: [] }, { pollutant: "PM2.5", kgPerDay: null, missing: ["rate"] }]),
      building([{ pollutant: "CO2", kgPerDay: 5, missing: [] }, { pollutant: "CO2e", kgPerDay: 9, missing: [] }]),
    ]);
    expect(released).toEqual({ air: ["co2", "pm25"], climate: ["co2e"] });
    expect(released.soil).toBeUndefined();
  });
  it("drops releases declared at exactly zero and returns nothing for buildings without releases", () => {
    expect(releasedPollutants([building([{ pollutant: "Ammonia", medium: "soil", kgPerDay: 0, missing: [] }])])).toEqual({});
    expect(releasedPollutants([building([])])).toEqual({});
    expect(releasedPollutants([])).toEqual({});
  });
  it("orders environments as in the catalogue, whatever order buildings declare them", () => {
    const released = releasedPollutants([building([
      { pollutant: "Nitrate", medium: "freshwater", kgPerDay: 1, missing: [] },
      { pollutant: "Ammonia", medium: "soil", kgPerDay: 1, missing: [] },
      { pollutant: "NOx", kgPerDay: 1, missing: [] },
    ])]);
    expect(Object.keys(released)).toEqual(["air", "soil", "freshwater"]);
  });
});

describe("colour scale default", () => {
  it("fits accumulated air exposure to the step so the first steps are visible, and keeps a fixed scale otherwise", () => {
    expect(defaultScale("air", "exposure")).toBe("step");
    expect(defaultScale("air", "concentration")).toBe("horizon");
    expect(defaultScale("soil", "concentration")).toBe("horizon");
    expect(defaultScale("climate", "concentration")).toBe("horizon");
  });
});

describe("air input validation", () => {
  const invalid = { ...DEFAULT_DISPERSION, mixingHeight: 0 };
  it("returns zero before anything is released, whatever the transport settings", () => {
    expect(concentrationAt(1000, 0, 240, 0, invalid)).toBe(0);
    expect(exposureAt(1000, 0, 240, 0, invalid)).toBe(0);
    expect(concentrationAt(1000, 0, 0, 5, invalid)).toBe(0);
  });
  it("rejects invalid settings and times once releases have begun", () => {
    expect(concentrationAt(1000, 0, 240, 1, invalid)).toBeNaN();
    expect(concentrationAt(1000, 0, 240, -1, DEFAULT_DISPERSION)).toBeNaN();
    expect(concentrationAt(1000, 0, 240, 4000, DEFAULT_DISPERSION)).toBeNaN();
    expect(concentrationAt(1000, 0, -1, 1, DEFAULT_DISPERSION)).toBeNaN();
  });
});

describe("puff search", () => {
  // Brute-force reference over the same fixed age grid, scanning every puff with no skipping.
  const bruteForce = (east: number, north: number, kgPerDay: number, days: number, p = DEFAULT_DISPERSION, exposure = false) => {
    const scale = Math.log1p(3650 * 86400), seconds = days * 86400, dir = (p.windFrom + 180) * Math.PI / 180;
    let previous = 0, total = 0;
    for (let i = 1; i <= 2048; i++) {
      const end = Math.min(seconds, Math.expm1(scale * i / 2048)), age = (previous + end) / 2;
      const variance = 750 ** 2 + 2 * p.diffusion * age;
      const exponent = ((east - Math.sin(dir) * p.windSpeed * age) ** 2 + (north - Math.cos(dir) * p.windSpeed * age) ** 2) / (2 * variance);
      const duration = exposure ? Math.max(0, days - age / 86400) : 1;
      if (exponent < 40) total += duration * (end - previous) * 1e9 / 86400 / (2 * Math.PI * variance * p.mixingHeight) * Math.exp(-exponent);
      if (end >= seconds) break;
      previous = end;
    }
    return total * kgPerDay;
  };
  const winds = [DEFAULT_DISPERSION, { ...DEFAULT_DISPERSION, windSpeed: 0 }, { ...DEFAULT_DISPERSION, windSpeed: .5, windFrom: 45 }];
  const receptors = [[0, 0], [600, 0], [5000, 0], [20000, 3000], [-15000, -15000], [48000, 1000], [0, 50000]];
  it("skips only puffs that cannot reach a receptor, matching a full scan", () => {
    for (const wind of winds) for (const [east, north] of receptors) for (const days of [1, 64, TIMELINE_HORIZON_DAYS]) {
      expect(concentrationAt(east, north, 240, days, wind)).toBeCloseTo(bruteForce(east, north, 240, days, wind), 9);
      expect(exposureAt(east, north, 240, days, wind)).toBeCloseTo(bruteForce(east, north, 240, days, wind, true), 6);
    }
  });
});

describe("local climate wind", () => {
  const wind = (u: number, v: number): LocalWind => ({ u, v, speed: Math.hypot(u, v), fromDegrees: directionFrom(u, v), meanSpeed: 6,
    gridLatitude: 0, gridLongitude: 0, source: "fixture" });
  it("converts eastward/northward components to the direction the wind blows from", () => {
    expect(directionFrom(3, 0)).toBeCloseTo(270);
    expect(directionFrom(-3, 0)).toBeCloseTo(90);
    expect(directionFrom(0, 3)).toBeCloseTo(180);
    expect(directionFrom(0, -3)).toBeCloseTo(0);
  });
  it("uses each building's own wind, keeping the shared mixing assumptions", () => {
    const p = { ...DEFAULT_DISPERSION, mixingHeight: 800, diffusion: 300 };
    const local = projectDispersion({ ...project, wind: wind(0, -4) }, p, "local");
    expect(local).toEqual({ windSpeed: 4, windFrom: 0, mixingHeight: 800, diffusion: 300 });
    expect(projectDispersion({ ...project, wind: wind(0, -4) }, p, "custom")).toBe(p);
    expect(projectDispersion({ ...project, wind: null }, p, "local")).toBe(p); // unknown local wind: assumed wind
    expect(projectDispersion({ ...project, wind: wind(0, 0) }, p, "local").windSpeed).toBe(0);
    expect(projectDispersion({ ...project, wind: wind(40, 0) }, p, "local").windSpeed).toBe(30); // model limit
  });
  it("moves each building's plume downwind of its own location", () => {
    // Two receptor cells 10 km east and west of a source; a westerly carries releases east, an easterly west.
    const cells = [{ h3Id: "east", latitude: 0, longitude: .09, pm25: null, pm10: null }, { h3Id: "west", latitude: 0, longitude: -.09, pm25: null, pm10: null }];
    const at = (u: number) => {
      const world: TimelineData = { ...data, cells, projects: [{ ...project, wind: wind(u, 0) }] };
      const [east, west] = impactCells(world, "co2", 1, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "concentration", "local");
      return { east: east.added!, west: west.added! };
    };
    expect(at(5).east).toBeGreaterThan(0);
    expect(at(5).west).toBe(0);
    expect(at(-5).west).toBeGreaterThan(0);
    expect(at(-5).east).toBe(0);
  });
  it("superposes buildings with different winds and matches each one computed alone", () => {
    const cells = [{ h3Id: "east", latitude: 0, longitude: .09, pm25: null, pm10: null }, { h3Id: "north", latitude: .09, longitude: 0, pm25: null, pm10: null }];
    const westerly = { ...project, id: "a", wind: wind(5, 0) }, southerly = { ...project, id: "b", wind: wind(0, 5) };
    const run = (projects: TimelineProject[]) => impactCells({ ...data, cells, projects }, "co2", 2, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "exposure", "local").map((c) => c.added!);
    const both = run([westerly, southerly]), a = run([westerly]), b = run([southerly]);
    expect(both[0]).toBeCloseTo(a[0] + b[0], 9);
    expect(both[1]).toBeCloseTo(a[1] + b[1], 9);
    expect(a[0]).toBeGreaterThan(0); expect(a[1]).toBe(0);
    expect(b[1]).toBeGreaterThan(0); expect(b[0]).toBe(0);
  });
  it("leaves the custom-wind result unchanged by any local wind data", () => {
    const withWind = { ...data, projects: [{ ...project, wind: wind(-7, 2) }] };
    expect(impactCells(withWind, "co2", 4, DEFAULT_DISPERSION, "added", "air", DEFAULT_ENVIRONMENT, "concentration", "custom"))
      .toEqual(impactCells(data, "co2", 4, DEFAULT_DISPERSION, "added", "air"));
  });
});
