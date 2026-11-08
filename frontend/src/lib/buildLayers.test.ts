import { describe, expect, it } from "vitest";
import {
  availableNeeds,
  EMPTY_OWNERSHIP,
  layerAvailability,
  layerEntries,
  layerNeeds,
  loadingByNeed,
  parseRefKey,
  reconcileLayers,
  refKey,
  toggleLayers,
  type LayerNeed,
  type LayerNeedsInput,
  type LayerRef,
  type OwnershipState,
} from "./buildLayers";

const needs = (input: Partial<LayerNeedsInput> & Pick<LayerNeedsInput, "type">) =>
  layerNeeds({ stats: {}, parameters: {}, producesPower: false, producesWater: false, ...input });
const keys = (ns: LayerNeed[]) => ns.map((n) => n.key);
const layerKeys = (n: LayerNeed | undefined) => (n?.layers ?? []).map(refKey);
const byKey = (ns: LayerNeed[], key: string) => ns.find((n) => n.key === key);

const GRID = ["infra:transmission_lines", "infra:substations", "infra:power_plants"];

describe("layerNeeds", () => {
  it("does not enable air-emission layers for soil, water or climate releases", () => {
    for (const medium of ["soil", "freshwater", "marine", "climate"] as const) {
      const pollutant = medium === "climate" ? "CO2e (Scope 1+2)" : "Lead";
      expect(keys(needs({ type: "factory", stats: { emissions: [{ id: "e", pollutant, medium, rateKgPerHour: 10 }] } }))).not.toContain("emissions");
    }
    expect(keys(needs({ type: "factory", stats: { emissions: [{ id: "e", pollutant: "Lead", medium: "air", rateKgPerHour: 10 }] } }))).toContain("emissions");
  });
  it("data centre with direct demand: power grid and existing datacentres", () => {
    const ns = needs({ type: "data_centre", stats: { power: { peakDemandKw: 12000, averageDemandKw: 9000 } } });
    expect(keys(ns)).toEqual(["power", "datacentres"]);
    const power = byKey(ns, "power")!;
    expect(power.label).toBe("Power grid");
    expect(power.icon).toBe("bolt");
    expect(layerKeys(power)).toEqual(GRID);
    expect(power.reason).toContain("~12 MW of electricity");
    expect(layerKeys(byKey(ns, "datacentres"))).toEqual(["infra:datacenters"]);
  });

  it("data centre with derived demand: IT load × PUE and WUE-derived water", () => {
    const ns = needs({
      type: "data_centre",
      stats: { demandBasis: "derived", operatingHoursPerDay: 24, power: { averageDemandKw: 1 } },
      parameters: { itPowerKw: 10000, loadFraction: 0.5, pue: 1.2, wueLPerKwh: 1.8, wueBasis: "it_energy" },
    });
    expect(keys(ns)).toEqual(["power", "water", "datacentres"]);
    expect(byKey(ns, "power")!.reason).toBe("Draws ~12 MW of electricity (IT load × PUE)");
    // 1.8 L/kWh × (10 000 kW × 0.5 × 24 h) ÷ 1000 = 216 m³/day
    const water = byKey(ns, "water")!;
    expect(water.reason).toBe("Draws ~216 m³/day of fresh water");
    expect(layerKeys(water)).toEqual(["feature:hydrorivers", "infra:dams"]);
  });

  it("derived data centre with partial inputs still flags power and water", () => {
    const ns = needs({ type: "data_centre", stats: { demandBasis: "derived" }, parameters: { itPowerKw: 10000, wueLPerKwh: 1.8 } });
    expect(byKey(ns, "power")!.reason).toContain("at least ~10 MW");
    expect(byKey(ns, "water")!.reason).toBe("Draws fresh water");
  });

  it("power station: output and own use merge into one power entry", () => {
    const ns = needs({ type: "power_station", producesPower: true, stats: { power: { ratedOutputKw: 50000, averageDemandKw: 2000 } } });
    expect(keys(ns)).toEqual(["power"]);
    const power = ns[0];
    expect(power.label).toBe("Power grid");
    expect(layerKeys(power)).toEqual(GRID);
    expect(power.reason).toContain("Exports up to ~50 MW to the grid");
    expect(power.reason).toContain("draws ~2 MW");
  });

  it("output only needs a grid connection (lines and substations)", () => {
    const solar = needs({ type: "solar", producesPower: true, stats: { power: { averageOutputKw: 5000 } } });
    expect(solar[0].key).toBe("power");
    expect(solar[0].label).toBe("Grid connection");
    expect(layerKeys(solar[0])).toEqual(["infra:transmission_lines", "infra:substations"]);
    expect(needs({ type: "solar", producesPower: true, parameters: { capacityKwp: 3000 } })[0].reason).toContain("~3 MW peak (kWp)");
  });

  it("a generator without output entered still needs the grid; an explicit 0 does not", () => {
    expect(needs({ type: "wind_farm", producesPower: true })[0].reason).toContain("output not entered yet");
    expect(needs({ type: "wind_farm", producesPower: true, stats: { power: { ratedOutputKw: 0, averageOutputKw: 0 } } })).toEqual([]);
    expect(needs({ type: "office", stats: { power: { peakDemandKw: 0, averageDemandKw: 0 } } })).toEqual([]);
  });

  it("water plant on seawater: water output and the coast", () => {
    const ns = needs({
      type: "water_plant",
      producesWater: true,
      stats: { operatingHoursPerDay: 24, water: { inputM3PerHour: 12, outputM3PerHour: 10, source: "seawater" } },
    });
    expect(keys(ns)).toEqual(["water", "coast"]);
    expect(byKey(ns, "water")!.reason).toBe("Supplies ~240 m³/day");
    const coast = byKey(ns, "coast")!;
    expect(coast.label).toBe("Coast & ports");
    expect(layerKeys(coast)).toEqual(["infra:ports"]);
    expect(coast.reason).toContain("~288 m³/day of seawater");
  });

  it("water plant with output not entered yet still shows the water layers", () => {
    const ns = needs({ type: "water_plant", producesWater: true });
    expect(keys(ns)).toEqual(["water"]);
  });

  it("seawater intake without operating hours is given per hour; no fresh-water entry", () => {
    const ns = needs({ type: "factory", stats: { water: { inputM3PerHour: 5, source: "seawater" } } });
    expect(keys(ns)).toEqual(["coast"]);
    expect(ns[0].reason).toContain("~5 m³/h of seawater");
  });

  it("treated wastewater intake does not draw on rivers", () => {
    expect(needs({ type: "factory", stats: { water: { inputM3PerHour: 5, source: "wastewater" } } })).toEqual([]);
  });

  it("farm with irrigation: water and water quality (nitrate)", () => {
    const ns = needs({ type: "farm", stats: { operatingHoursPerDay: 10, water: { inputM3PerHour: 50 } } });
    expect(keys(ns)).toEqual(["water", "water_quality"]);
    const quality = byKey(ns, "water_quality")!;
    expect(quality.label).toBe("Water quality (nitrate)");
    expect(layerKeys(quality)).toEqual(["feature:wqp_sites"]);
    expect(quality.reason).toContain("~500 m³/day");
    // Water quality only for farming types, and not for seawater.
    expect(keys(needs({ type: "factory", stats: { water: { inputM3PerHour: 50 } } }))).toEqual(["water"]);
    expect(keys(needs({ type: "aquaculture", stats: { water: { inputM3PerHour: 50, source: "seawater" } } }))).toEqual(["coast"]);
    expect(keys(needs({ type: "livestock_farm", stats: { water: { inputM3PerHour: 1 } } }))).toContain("water_quality");
  });

  it("named raw materials: mineral sites, up to three names", () => {
    const ns = needs({
      type: "factory",
      stats: {
        materials: [
          { id: "1", name: "Steel", phase: "construction" },
          { id: "2", name: "copper", phase: "operation" },
          { id: "3", name: "steel ", phase: "operation" },
          { id: "4", name: "Lithium", phase: "operation" },
          { id: "5", name: "Cobalt", phase: "operation" },
          { id: "6", name: "  ", phase: "operation" },
        ],
      },
    });
    expect(keys(ns)).toEqual(["materials"]);
    expect(layerKeys(ns[0])).toEqual(["feature:mrds"]);
    expect(ns[0].reason).toContain("Uses Steel, copper, Lithium and 1 more");
    const two = needs({ type: "factory", stats: { materials: [{ id: "1", name: "Sand", phase: "construction" }, { id: "2", name: "Gravel", phase: "construction" }] } });
    expect(two[0].reason).toContain("Uses Sand and Gravel");
  });

  it("air pollutants (not greenhouse gases): other emitters", () => {
    const ns = needs({
      type: "factory",
      stats: {
        emissions: [
          { id: "1", pollutant: "NOx", rateKgPerHour: 2 },
          { id: "2", pollutant: "CO2", rateKgPerHour: 100 },
          { id: "3", pollutant: "PM2.5", rateKgPerHour: 0 },
          { id: "4", pollutant: "SO2" },
        ],
      },
    });
    expect(keys(ns)).toEqual(["emissions"]);
    expect(layerKeys(ns[0])).toEqual(["feature:tri_facilities"]);
    expect(ns[0].reason).toContain("Emits NOx and SO2");
    expect(needs({ type: "factory", stats: { emissions: [{ id: "1", pollutant: "CO₂", rateKgPerHour: 5 }] } })).toEqual([]);
  });

  it("type-driven layers", () => {
    expect(layerKeys(byKey(needs({ type: "airport" }), "airports"))).toEqual(["infra:airports"]);
    expect(layerKeys(byKey(needs({ type: "seaport" }), "seaports"))).toEqual(["infra:ports"]);
    const logistics = byKey(needs({ type: "warehouse" }), "logistics")!;
    expect(logistics.label).toBe("Logistics");
    expect(layerKeys(logistics)).toEqual(["infra:ports", "infra:airports"]);
    expect(keys(needs({ type: "data_centre" }))).toEqual(["datacentres"]);
    expect(needs({ type: "office" })).toEqual([]);
  });

  it("a seaport taking seawater gets one ports chip", () => {
    const ns = needs({ type: "seaport", stats: { water: { inputM3PerHour: 2, source: "seawater" } } });
    expect(keys(ns)).toEqual(["coast"]);
    expect(ns[0].reason).toContain("seawater");
    expect(ns[0].reason).toContain("existing seaports");
  });

  it("drops unavailable layers, and needs left with none", () => {
    const unavailable = new Set(["infra:power_plants", "infra:datacenters"]);
    const isAvailable = (r: LayerRef) => !unavailable.has(refKey(r));
    const ns = layerNeeds({
      type: "data_centre",
      stats: { power: { peakDemandKw: 12000 } },
      parameters: {},
      producesPower: false,
      producesWater: false,
      isAvailable,
    });
    expect(keys(ns)).toEqual(["power"]);
    expect(layerKeys(ns[0])).toEqual(["infra:transmission_lines", "infra:substations"]);
    // Same through the hook's filter.
    const all = needs({ type: "data_centre", stats: { power: { peakDemandKw: 12000 } } });
    expect(availableNeeds(all, isAvailable)).toEqual(ns);
    expect(availableNeeds(all, () => false)).toEqual([]);
  });

  it("is deterministic and keeps keys stable as numbers change", () => {
    const a = needs({ type: "data_centre", stats: { power: { peakDemandKw: 12000 } } });
    expect(needs({ type: "data_centre", stats: { power: { peakDemandKw: 12000 } } })).toEqual(a);
    const b = needs({ type: "data_centre", stats: { power: { peakDemandKw: 12000, ratedOutputKw: 500 } } });
    expect(keys(b)).toEqual(keys(a));
  });
});

describe("layer refs and availability", () => {
  it("round-trips keys", () => {
    expect(parseRefKey("infra:ports")).toEqual({ kind: "infra", id: "ports" });
    expect(parseRefKey("feature:mrds")).toEqual({ kind: "feature", id: "mrds" });
    expect(parseRefKey("infra:toString")).toBeNull();
    expect(parseRefKey("nonsense")).toBeNull();
  });

  it("never auto-enables polygon or table feature layers, nor unavailable ones", () => {
    const ok = layerAvailability(
      [{ id: "ports" }, { id: "airports", available: false }],
      [
        { id: "mrds", available: true, geometry: "point" },
        { id: "hydrorivers", available: true, geometry: "line" },
        { id: "aqueduct_baseline", available: true, geometry: "polygon" },
        { id: "neso_carbon_intensity", available: true, geometry: "table" },
        { id: "wqp_sites", available: false, geometry: "point" },
      ],
    );
    expect(ok({ kind: "infra", id: "ports" })).toBe(true);
    expect(ok({ kind: "infra", id: "airports" })).toBe(false);
    expect(ok({ kind: "infra", id: "dams" })).toBe(false);
    expect(ok({ kind: "feature", id: "mrds" })).toBe(true);
    expect(ok({ kind: "feature", id: "hydrorivers" })).toBe(true);
    expect(ok({ kind: "feature", id: "aqueduct_baseline" })).toBe(false);
    expect(ok({ kind: "feature", id: "neso_carbon_intensity" })).toBe(false);
    expect(ok({ kind: "feature", id: "wqp_sites" })).toBe(false);
    expect(layerAvailability(null, undefined)({ kind: "infra", id: "ports" })).toBe(false);
  });
});

/**
 * A tiny map driven the way React drives the hook: an effect run reconciles and applies its changes;
 * a visibility change re-renders and runs the effect again, until nothing changes.
 */
function world(initial: Record<string, boolean> = {}) {
  const vis: Record<string, boolean> = { ...initial };
  let state: OwnershipState = EMPTY_OWNERSHIP;
  let needed: string[] = [];
  const isOn = (k: string) => !!vis[k];
  /** Apply changes; returns those that actually changed visibility (the setter bails out otherwise). */
  const apply = (changes: Record<string, boolean>) => {
    const changed = Object.fromEntries(Object.entries(changes).filter(([k, on]) => !!vis[k] !== on));
    Object.assign(vis, changes);
    return changed;
  };
  const settle = () => {
    const applied: Record<string, boolean> = {};
    for (let i = 0; i < 5; i++) {
      const r = reconcileLayers(state, needed, isOn);
      state = r.state;
      const changed = apply(r.changes);
      if (!Object.keys(changed).length) return applied;
      Object.assign(applied, changed);
    }
    throw new Error("did not settle");
  };
  return {
    vis,
    get state() {
      return state;
    },
    /** What is needed now (empty = Build workspace closed); returns the visibility changes made. */
    sync(next: string[]) {
      needed = next;
      return settle();
    },
    /** The user switches a layer elsewhere (layer panel). */
    user(key: string, on: boolean) {
      vis[key] = on;
      return settle();
    },
    /** The user clicks a chip. */
    toggle(keys: string[], on: boolean) {
      const r = toggleLayers(state, keys, on, isOn);
      state = r.state;
      return { ...apply(r.changes), ...settle() };
    },
    /** An effect run whose update React has not applied yet (StrictMode re-run, cleanup). */
    pending(next: string[]) {
      needed = next;
      const r = reconcileLayers(state, needed, isOn);
      state = r.state;
      return r.changes;
    },
    apply,
  };
}

const SUB = "infra:substations";
const LINES = "infra:transmission_lines";
const RIVERS = "feature:hydrorivers";

describe("ownership (reconcileLayers / toggleLayers)", () => {
  it("switches needed layers on and marks them as the build flow's", () => {
    const w = world();
    expect(w.sync([SUB, RIVERS])).toEqual({ [SUB]: true, [RIVERS]: true });
    expect(w.state.owners).toEqual({ [SUB]: "auto", [RIVERS]: "auto" });
    expect(w.state.expect).toEqual({});
    expect(w.sync([SUB, RIVERS])).toEqual({});
  });

  it("does not switch back on a layer the user turned off while it is needed", () => {
    const w = world();
    w.sync([SUB]);
    expect(w.user(SUB, false)).toEqual({});
    expect(w.state.owners[SUB]).toBe("declined");
    expect(w.sync([SUB])).toEqual({});
    expect(w.vis[SUB]).toBe(false);
  });

  it("a chip toggled off stays off while needed", () => {
    const w = world();
    w.sync([SUB, LINES]);
    expect(w.toggle([SUB, LINES], false)).toEqual({ [SUB]: false, [LINES]: false });
    expect(w.sync([SUB, LINES])).toEqual({});
    expect(w.vis).toEqual({ [SUB]: false, [LINES]: false });
    expect(w.state.owners).toEqual({ [SUB]: "declined", [LINES]: "declined" });
  });

  it("a chip toggled back on is the build flow's again", () => {
    const w = world();
    w.sync([SUB]);
    w.toggle([SUB], false);
    expect(w.toggle([SUB], true)).toEqual({ [SUB]: true });
    expect(w.state.owners[SUB]).toBe("auto");
    expect(w.sync([])).toEqual({ [SUB]: false });
  });

  it("a user's layer hidden and shown again with its chip stays the user's", () => {
    const w = world({ [SUB]: true });
    w.sync([SUB, LINES]);
    w.toggle([SUB, LINES], false);
    w.sync([SUB, LINES]);
    expect(w.toggle([SUB, LINES], true)).toEqual({ [SUB]: true, [LINES]: true });
    expect(w.state.owners).toEqual({ [SUB]: "user", [LINES]: "auto" });
    expect(w.sync([])).toEqual({ [LINES]: false }); // leaving Build keeps the user's own layer on
    expect(w.vis[SUB]).toBe(true);
  });

  it("switches its layers off again when the workspace closes", () => {
    const w = world();
    w.sync([SUB, RIVERS]);
    expect(w.sync([])).toEqual({ [SUB]: false, [RIVERS]: false });
    expect(w.state).toEqual(EMPTY_OWNERSHIP);
    expect(w.sync([])).toEqual({});
  });

  it("never touches layers the user already had on", () => {
    const w = world({ [SUB]: true });
    expect(w.sync([SUB, LINES])).toEqual({ [LINES]: true });
    expect(w.state.owners).toEqual({ [SUB]: "user", [LINES]: "auto" });
    expect(w.sync([])).toEqual({ [LINES]: false });
    expect(w.vis[SUB]).toBe(true);
  });

  it("a user's layer switched off while needed is declined, and left alone after", () => {
    const w = world({ [SUB]: true });
    w.sync([SUB]);
    w.user(SUB, false);
    expect(w.state.owners[SUB]).toBe("declined");
    expect(w.sync([])).toEqual({});
    expect(w.vis[SUB]).toBe(false);
  });

  it("restores a layer when its need goes away, keeping the others", () => {
    const w = world();
    w.sync([SUB, RIVERS]);
    expect(w.sync([SUB])).toEqual({ [RIVERS]: false });
    expect(w.vis).toEqual({ [SUB]: true, [RIVERS]: false });
    expect(w.state.owners).toEqual({ [SUB]: "auto" });
  });

  it("a declined layer comes back on when the need disappears and returns", () => {
    const w = world();
    w.sync([SUB]);
    w.toggle([SUB], false);
    w.sync([SUB]);
    expect(w.vis[SUB]).toBe(false);
    expect(w.sync([])).toEqual({}); // need removed: forgotten, nothing to restore
    expect(w.state.owners).toEqual({});
    expect(w.sync([SUB])).toEqual({ [SUB]: true });
    expect(w.state.owners[SUB]).toBe("auto");
  });

  it("a declined layer the user switches back on becomes theirs", () => {
    const w = world();
    w.sync([SUB]);
    w.user(SUB, false);
    w.user(SUB, true);
    expect(w.state.owners[SUB]).toBe("user");
    expect(w.sync([])).toEqual({});
    expect(w.vis[SUB]).toBe(true);
  });

  it("survives a re-run before React applies the change (StrictMode)", () => {
    const w = world();
    const first = w.pending([SUB]);
    const second = w.pending([SUB]); // same snapshot: still off
    expect(first).toEqual({ [SUB]: true });
    expect(second).toEqual({ [SUB]: true }); // asked again, not taken as "the user switched it off"
    expect(w.state.owners[SUB]).toBe("auto");
    w.apply(first);
    w.apply(second);
    expect(w.sync([SUB])).toEqual({});
    expect(w.state.owners[SUB]).toBe("auto");
    expect(w.state.expect).toEqual({});
  });

  it("a need removed and re-added before the switch-off applies ends up on", () => {
    const w = world();
    w.sync([SUB]);
    const off = w.pending([]);
    expect(off).toEqual({ [SUB]: false });
    const on = w.pending([SUB]); // the snapshot still shows it on, but off was requested
    expect(on).toEqual({ [SUB]: true });
    w.apply(off);
    w.apply(on);
    expect(w.vis[SUB]).toBe(true);
    expect(w.sync([SUB])).toEqual({});
    expect(w.state.owners[SUB]).toBe("auto");
  });

  it("unmounting mid-request still switches the layer off", () => {
    const w = world();
    const on = w.pending([SUB]); // effect ran; update not applied yet
    const off = w.pending([]); // cleanup
    expect(off).toEqual({ [SUB]: false });
    w.apply(on);
    w.apply(off);
    expect(w.vis[SUB]).toBe(false);
  });

  it("toggling a partly shown chip on keeps the user's layers theirs", () => {
    const w = world({ [SUB]: true });
    w.sync([SUB, LINES]);
    w.user(LINES, false); // LINES declined, SUB still the user's
    expect(w.toggle([SUB, LINES], true)).toEqual({ [LINES]: true });
    expect(w.state.owners).toEqual({ [SUB]: "user", [LINES]: "auto" });
    expect(w.sync([])).toEqual({ [LINES]: false });
    expect(w.vis[SUB]).toBe(true);
  });
});

describe("layerEntries / loadingByNeed", () => {
  const power: LayerNeed = {
    key: "power",
    label: "Power grid",
    icon: "bolt",
    reason: "Draws ~12 MW of electricity at peak",
    layers: [
      { kind: "infra", id: "transmission_lines" },
      { kind: "infra", id: "substations" },
    ],
  };
  const water: LayerNeed = { key: "water", label: "Water", icon: "water", reason: "x", layers: [{ kind: "feature", id: "hydrorivers" }] };

  it("reports on, partly on and switched on by the build flow", () => {
    const vis: Record<string, boolean> = { [LINES]: true, [SUB]: true };
    const entries = layerEntries([power, water], { [LINES]: "auto", [SUB]: "user" }, (k) => !!vis[k]);
    expect(entries.map(({ need, ...rest }) => [need.key, rest])).toEqual([
      ["power", { on: true, partial: false, auto: true }],
      ["water", { on: false, partial: false, auto: false }],
    ]);
    vis[LINES] = false;
    const partly = layerEntries([power], { [LINES]: "declined", [SUB]: "user" }, (k) => !!vis[k]);
    expect(partly[0]).toMatchObject({ on: false, partial: true, auto: false });
  });

  it("maps a per-layer loading status to need keys", () => {
    const loading = loadingByNeed([{ need: power }, { need: water }], (r) => r.kind === "infra" && r.id === "substations");
    expect(loading("power")).toBe(true);
    expect(loading("water")).toBe(false);
    expect(loading("missing")).toBe(false);
  });
});
