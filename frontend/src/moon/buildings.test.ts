import { describe, expect, it } from "vitest";
import { ICON_NAMES } from "../components/Icon";
import {
  baseBalance,
  defaultValues,
  formatUsd,
  isMoonBuildingType,
  LIFE_SUPPORT,
  LUNAR_NIGHT_HOURS,
  MOON_BUILDINGS,
  MOON_BUILDING_BY_TYPE,
  paramProblem,
  POLAR_RIDGE_NIGHT_HOURS,
  powerDemandKw,
  siteCheck,
  siteFacts,
  TAG_LABELS,
  toParameters,
  TRANSPORT_CASES,
  valuesFromParameters,
  type MoonBuildingType,
  type PlacedMoonBuilding,
  type SiteContext,
} from "./buildings";

const ctx = (latitude: number, longitude: number, extra: Partial<SiteContext> = {}): SiteContext => ({
  latitude, longitude, elevationM: -1200, mare: null, heritage: [], ...extra,
});
let n = 0;
const placed = (type: MoonBuildingType, latitude = 0, longitude = 0, values: Record<string, number | null> = {}): PlacedMoonBuilding => ({
  id: `b${n++}`, type, name: "", latitude, longitude, values: { ...defaultValues(type), ...values },
});
const status = (items: { id: string; status: string }[], id: string) => items.find((i) => i.id === id)?.status;

describe("catalogue", () => {
  it("defines every type once, with known icons, tags and defaults inside their bounds", () => {
    expect(new Set(MOON_BUILDINGS.map((b) => b.type)).size).toBe(MOON_BUILDINGS.length);
    expect(MOON_BUILDINGS).toHaveLength(8);
    for (const b of MOON_BUILDINGS) {
      expect(ICON_NAMES).toContain(b.icon);
      expect(b.params.some((p) => p.key === "landedMassT")).toBe(true);
      for (const p of b.params) {
        expect(TAG_LABELS[p.tag], `${b.type}.${p.key}`).toBeTruthy();
        expect(p.min).toBeLessThanOrEqual(p.max);
        if (p.default !== null) expect(paramProblem(p, String(p.default)), `${b.type}.${p.key}`).toBeNull();
      }
    }
    expect(isMoonBuildingType("moon_habitat")).toBe(true);
    expect(isMoonBuildingType("data_centre")).toBe(false);
  });
  it("keeps unknown values unknown when saving and loading", () => {
    const values = defaultValues("moon_storage");
    expect(values.landedMassT).toBeNull();
    const params = toParameters(values);
    expect(params).not.toHaveProperty("landedMassT");
    expect(valuesFromParameters("moon_storage", { ...params, landedMassT: "x", extra: 3 })).toEqual(values);
  });
  it("explains invalid typed values", () => {
    const crew = MOON_BUILDING_BY_TYPE.moon_habitat.params.find((p) => p.key === "crew")!;
    expect(paramProblem(crew, "")).toBeNull();
    expect(paramProblem(crew, "abc")).toBe("Enter a number");
    expect(paramProblem(crew, "2.5")).toBe("Whole number");
    expect(paramProblem(crew, "500")).toMatch(/^Between/);
  });
});

describe("site facts", () => {
  it("models sunlight and night away from the poles, and leaves polar terrain unknown", () => {
    const equator = siteFacts(ctx(0, 0));
    expect(equator.sunlitFraction).toBe(0.5);
    expect(equator.longestNightHours).toBeCloseTo(354.4, 1);
    const pole = siteFacts(ctx(-89.5, 0));
    expect(pole.polar).toBe(true);
    expect(pole.sunlitFraction).toBeNull();
    expect(pole.longestNightHours).toBeNull();
  });
  it("tells the near side, the limb and the far side apart", () => {
    expect(siteFacts(ctx(0, 0)).earthVisibility).toBe("always");
    expect(siteFacts(ctx(0, 90)).earthVisibility).toBe("sometimes");
    expect(siteFacts(ctx(0, 180)).earthVisibility).toBe("never");
    expect(siteFacts(ctx(-89, 0)).earthVisibility).toBe("sometimes");
  });
  it("expects ice only near the poles and separates mare from highlands", () => {
    expect(siteFacts(ctx(-88, 0)).icePotential).toBe("likely");
    expect(siteFacts(ctx(82, 0)).icePotential).toBe("possible");
    expect(siteFacts(ctx(20, 0)).icePotential).toBe("unlikely");
    expect(siteFacts(ctx(0, 0, { mare: "Mare Tranquillitatis" })).terrain).toBe("mare");
    expect(siteFacts(ctx(0, 0, { mare: null })).terrain).toBe("highlands");
    expect(siteFacts(ctx(0, 0, { mare: undefined })).terrain).toBeNull();
  });
});

describe("site check", () => {
  it("vetoes heritage sites for every building type", () => {
    const heritage = [{ siteName: "Apollo 11", rule: "heritage_landing", radiusM: 2000, distanceKm: 0.5 }];
    for (const b of MOON_BUILDINGS) {
      const r = siteCheck(b.type, defaultValues(b.type), siteFacts(ctx(0.67, 23.47)), heritage, []);
      expect(r.verdict).toBe("unsuitable");
      expect(status(r.items, "heritage")).toBe("fail");
    }
  });
  it("keeps crew outside a reactor's radiation keep-out, both ways round", () => {
    const reactor = placed("moon_fission", 0, 0);
    const close = siteCheck("moon_habitat", defaultValues("moon_habitat"), siteFacts(ctx(0, 0.02)), [], [reactor]); // ~0.6 km
    expect(status(close.items, "radiation")).toBe("fail");
    const far = siteCheck("moon_habitat", defaultValues("moon_habitat"), siteFacts(ctx(0, 0.05)), [], [reactor]); // ~1.5 km
    expect(status(far.items, "radiation")).toBe("pass");
    const habitat = placed("moon_habitat", 0, 0);
    expect(status(siteCheck("moon_fission", defaultValues("moon_fission"), siteFacts(ctx(0, 0.02)), [], [habitat]).items, "radiation")).toBe("fail");
  });
  it("warns about landing plumes and distant buildings", () => {
    const pad = placed("moon_landing_pad", 0, 0);
    const r = siteCheck("moon_solar_tower", defaultValues("moon_solar_tower"), siteFacts(ctx(0, 0.03)), [], [pad]);
    expect(status(r.items, "plume")).toBe("warn");
    const padCheck = siteCheck("moon_landing_pad", defaultValues("moon_landing_pad"), siteFacts(ctx(0, 0)), [], [placed("moon_habitat", 0, 0.03)]);
    expect(status(padCheck.items, "plume")).toBe("warn");
    const lonely = siteCheck("moon_habitat", defaultValues("moon_habitat"), siteFacts(ctx(0, 1)), [], [placed("moon_storage", 0, 0)]); // ~30 km
    expect(status(lonely.items, "network")).toBe("warn");
    expect(status(siteCheck("moon_habitat", defaultValues("moon_habitat"), siteFacts(ctx(0, 0)), [], []).items, "network")).toBe("info");
  });
  it("checks each type against what it needs from the site", () => {
    const solar = (lat: number, values = {}) => status(siteCheck("moon_solar_tower", { ...defaultValues("moon_solar_tower"), ...values }, siteFacts(ctx(lat, 0)), [], []).items, "sunlight");
    expect(solar(0)).toBe("warn");
    expect(solar(-89)).toBe("unknown");
    expect(solar(-89, { sunlitFraction: 0.85 })).toBe("pass");
    expect(solar(-89, { sunlitFraction: 0.1 })).toBe("fail");
    expect(status(siteCheck("moon_ice_mine", defaultValues("moon_ice_mine"), siteFacts(ctx(10, 0)), [], []).items, "ice")).toBe("fail");
    expect(status(siteCheck("moon_ice_mine", defaultValues("moon_ice_mine"), siteFacts(ctx(-88, 0)), [], []).items, "ice")).toBe("pass");
    const mare = siteFacts(ctx(8, 30, { mare: "Mare Tranquillitatis" }));
    expect(status(siteCheck("moon_oxygen_plant", defaultValues("moon_oxygen_plant"), mare, [], []).items, "ilmenite")).toBe("pass");
    expect(status(siteCheck("moon_oxygen_plant", defaultValues("moon_oxygen_plant"), siteFacts(ctx(-30, 0)), [], []).items, "ilmenite")).toBe("warn");
    expect(status(siteCheck("moon_habitat", defaultValues("moon_habitat"), siteFacts(ctx(0, 175)), [], []).items, "earth")).toBe("fail");
  });
});

describe("base balance", () => {
  it("adds up crew needs using the NASA per-person rates and recycling", () => {
    const b = baseBalance([placed("moon_habitat", 0, 0, { crew: 4, oxygenRecoveryPct: 50, waterRecoveryPct: 90 })]);
    expect(b.crew).toBe(4);
    expect(b.oxygen.needed).toBeCloseTo(4 * LIFE_SUPPORT.oxygenKgPerCrewDay * 0.5);
    expect(b.water.needed).toBeCloseTo(4 * LIFE_SUPPORT.waterKgPerCrewDay * 0.1);
    expect(b.food.needed).toBeCloseTo(4 * LIFE_SUPPORT.foodKgPerCrewDay);
    expect(b.oxygen.shortfall).toBeCloseTo(b.oxygen.needed);
    expect(b.cost.resupplyKgPerYear).toBeCloseTo((b.oxygen.needed + b.water.needed + b.food.needed) * 365.25);
  });
  it("needs night power: solar alone fails the two-week night, fission or storage carries it", () => {
    const habitat = placed("moon_habitat", 0, 0, { powerKw: 15 });
    const solar = [placed("moon_solar_tower", 0, 0.01), placed("moon_solar_tower", 0, 0.02)];
    const daytimeOnly = baseBalance([habitat, ...solar]);
    expect(daytimeOnly.power.dayOk).toBe(true);
    expect(daytimeOnly.power.nightOk).toBe(false);
    expect(daytimeOnly.power.nightHours).toBeCloseTo(LUNAR_NIGHT_HOURS);
    expect(daytimeOnly.headline.status).toBe("fail");
    const withReactor = baseBalance([habitat, placed("moon_fission", 0, 0.1)]);
    expect(withReactor.power.nightOk).toBe(true);
    expect(withReactor.power.rechargeOk).toBe(true);
    // 15 kW for 354 h needs ~5.3 MWh: one 3 MWh fuel cell gives 8.5 kW all night; two give 16.9 kW.
    const storage = (k: number) => Array.from({ length: k }, () => placed("moon_storage", 0, 0.03, { capacityKwh: 3000, maxOutputKw: 10 }));
    expect(baseBalance([habitat, ...solar, ...storage(1)]).power.nightOk).toBe(false);
    expect(baseBalance([habitat, ...solar, ...storage(2)]).power.nightOk).toBe(true);
  });
  it("uses a short ridge night for an all-polar base and honours a set night length", () => {
    const polar = baseBalance([placed("moon_habitat", -89.5, 0), placed("moon_solar_tower", -89.5, 10, { sunlitFraction: 0.85 })]);
    expect(polar.power.nightHours).toBe(POLAR_RIDGE_NIGHT_HOURS);
    expect(polar.power.solarAverageKw).toBeCloseTo(8.5);
    expect(baseBalance([placed("moon_habitat")], { transportCase: "central", nightHours: 48 }).power.nightHours).toBe(48);
    expect(baseBalance([placed("moon_solar_tower", -89, 0)]).power.solarAverageKw).toBeNull();
  });
  it("counts local oxygen, water and food production against the crew's needs", () => {
    const b = baseBalance([
      placed("moon_habitat", 0, 0, { crew: 2 }),
      placed("moon_oxygen_plant", 0, 0.05, { oxygenKgPerDay: 5 }),
      placed("moon_ice_mine", 0, 0.05, { waterKgPerDay: 10 }),
      placed("moon_greenhouse", 0, 0.05, { areaM2: 200, foodKgPerM2Day: 0.02 }),
    ]);
    expect(b.oxygen.produced).toBeCloseTo(5 + 200 * 0.02);
    expect(b.oxygen.shortfall).toBe(0);
    expect(b.water.shortfall).toBe(0);
    expect(b.food.produced).toBeCloseTo(4);
    expect(b.food.shortfall).toBe(0);
    expect(b.cost.resupplyKgPerYear).toBe(0);
    expect(powerDemandKw("moon_oxygen_plant", { oxygenKgPerDay: 5, energyKwhPerKg: 24 })).toBe(5);
    expect(powerDemandKw("moon_ice_mine", { waterKgPerDay: 24, energyKwhPerKg: null })).toBeNull();
  });
  it("prices known landed mass with the chosen transport case and lists unknown masses", () => {
    const b = baseBalance([placed("moon_habitat"), placed("moon_storage")], { transportCase: "spacex_list", nightHours: null });
    expect(b.mass.knownT).toBe(12);
    expect(b.mass.unknown).toEqual(["Night power storage"]);
    expect(b.cost.deliveryUsd).toBe(12 * 1000 * 100000);
    expect(TRANSPORT_CASES.map((c) => c.id)).toContain(b.cost.case.id);
    expect(formatUsd(1.2e9)).toBe("$1.2B");
    expect(formatUsd(14000)).toBe("$14k");
  });
  it("reports a base that sustains its crew on its own", () => {
    const b = baseBalance([
      placed("moon_habitat", 0, 0, { crew: 1, powerKw: 5, oxygenRecoveryPct: 0, waterRecoveryPct: 0 }),
      placed("moon_fission", 0, 0.1, { outputKw: 40 }),
      placed("moon_oxygen_plant", 0, 0.05, { oxygenKgPerDay: 1 }),
      placed("moon_ice_mine", 0, 0.05, { waterKgPerDay: 3 }),
      placed("moon_greenhouse", 0, 0.05, { areaM2: 100, foodKgPerM2Day: 0.02, powerKwPerM2: 0.1 }),
    ]);
    expect(b.headline.status).toBe("pass");
    expect(b.headline.text).toMatch(/keeps 1 crew alive on its own/);
  });
});
