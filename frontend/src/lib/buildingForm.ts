/**
 * Pure helpers for the building forms: string drafts <-> contract objects.
 *
 * Rules shared by every numeric input:
 * - blank  -> null (unknown), never 0
 * - "0"    -> 0 (explicit "none")
 * - invalid (not a plain decimal number, or outside the field's range) -> an inline error that
 *   blocks saving.
 */
import {
  DEFAULT_ASSUMPTIONS,
  NEUTRAL_STRESS,
  type AssessmentState,
  type BudgetKind,
  type BuildingStats,
  type BuildingTemplate,
  type BuildingType,
  type CheckResult,
  type CheckStatus,
  type Criterion,
  type CriterionKind,
  type MaterialItem,
  type ParamValue,
  type LocationPriceOffer,
  type Period,
  type PriceResource,
  type PriceSource,
  type Provenance,
  type Quantity,
  type ResourceBudget,
  type ScenarioAssumptions,
  type SiteAssumptions,
  type StressControls,
  type TemplateParam,
} from "./buildings";

export type Errors = Record<string, string>;

// --------------------------------------------------------------------------------------------
// Numbers

export type Rule = "nonneg" | "positive" | "fraction" | "hours" | "int" | "finite" | "pue" | "multiplier";

const DECIMAL = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;

const RULE_ERROR: Record<Rule, string> = {
  nonneg: "Must be 0 or more",
  positive: "Must be more than 0",
  fraction: "Must be between 0 and 1",
  hours: "Must be between 0 and 24",
  int: "Must be a whole number, 0 or more",
  finite: "Enter a number",
  pue: "Must be at least 1",
  multiplier: "Must be between 0 and 100",
};

function ruleOk(n: number, rule: Rule): boolean {
  switch (rule) {
    case "nonneg":
      return n >= 0;
    case "positive":
      return n > 0;
    case "fraction":
      return n >= 0 && n <= 1;
    case "hours":
      return n >= 0 && n <= 24;
    case "int":
      return n >= 0 && Number.isInteger(n);
    case "pue":
      return n >= 1;
    case "multiplier":
      return n >= 0 && n <= 100;
    case "finite":
      return true;
  }
}

/** Blank -> null (unknown); "0" -> 0; anything else must be a plain finite decimal within `rule`. */
export function parseNumber(raw: string, rule: Rule = "nonneg"): { value: number | null; error: string | null } {
  const s = raw.trim();
  if (s === "") return { value: null, error: null };
  if (!DECIMAL.test(s)) return { value: null, error: "Enter a number" };
  const n = Number(s);
  if (!Number.isFinite(n)) return { value: null, error: "Enter a number" };
  if (!ruleOk(n, rule)) return { value: null, error: RULE_ERROR[rule] };
  return { value: n, error: null };
}

/** Exact kg from a tonne/kg input, without binary floating-point noise (1.1 t -> 1100 kg). */
export function toKg(value: number, unit: "kg" | "t"): number {
  return unit === "t" ? Number((value * 1000).toPrecision(15)) : value;
}

const numStr = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));

let idCounter = 0;
export function newId(prefix = "id"): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}

// --------------------------------------------------------------------------------------------
// Building statistics

export type SectionKey = "footprint" | "power" | "water" | "light" | "workers" | "costs";

export type FieldSpec = {
  path: string;
  label: string;
  unit: string;
  rule?: Rule; // absent = free text
  help?: string;
  section: SectionKey | null;
};

/** Shown wherever the upward-light figure is labelled (spec section 5). */
export const LIGHT_PROXY_NOTE = "Declared upward luminous flux: a proxy, not a sky-brightness prediction or a light-pollution index.";

const f = (path: string, label: string, unit: string, rule: Rule | undefined, section: SectionKey | null, help?: string) => ({
  path,
  label,
  unit,
  rule,
  section,
  help,
});

/** Every scalar statistic, keyed by its path in BuildingStats. */
export const STAT_FIELDS: Record<string, FieldSpec> = Object.fromEntries(
  [
    f("footprintM2", "Footprint", "m²", "positive", "footprint", "Ground area the building occupies. Not a floor area or an H3 cell."),
    f("operatingHoursPerDay", "Operating hours", "h/day", "hours", null, "Used for power, water and emissions over the period."),
    f("power.averageDemandKw", "Average demand", "kW", "nonneg", "power", "Electricity used while operating."),
    f("power.peakDemandKw", "Peak demand", "kW", "nonneg", "power", "Capacity check only; not an energy total."),
    f("power.averageOutputKw", "Average output", "kW", "nonneg", "power", "Gross electricity generated while operating."),
    f("power.ratedOutputKw", "Rated output", "kW", "nonneg", "power", "Nameplate capacity. Needs a capacity factor to give energy."),
    f("power.capacityFactor", "Capacity factor", "0–1", "fraction", "power", "Share of rated output actually produced on average."),
    f("power.technology", "Technology / process", "", undefined, "power"),
    f("water.inputM3PerHour", "Water input", "m³/h", "nonneg", "water", "Water consumed while operating."),
    f("water.outputM3PerHour", "Usable water output", "m³/h", "nonneg", "water", "Treated or produced water. A treatment capacity is not a water allocation."),
    f("water.basis", "Water source / process", "", undefined, "water"),
    f("light.upwardLumens", "Upward light", "lumens", "nonneg", "light", LIGHT_PROXY_NOTE),
    f("light.hoursPerDay", "Lit hours", "h/day", "hours", "light"),
    f("workers.capacity", "Worker capacity", "people", "int", "workers", "Most workers the building holds at one time."),
    f("workers.staffingRequired", "Staff required", "people", "int", "workers"),
    f("costs.currency", "Currency", "ISO code", undefined, "costs", "Three letters, e.g. USD, GBP, EUR. Never converted."),
    f("costs.constructionTotal", "Construction cost", "currency", "nonneg", "costs", "One-time total."),
    f("costs.priceBasis", "Price basis / date", "", undefined, "costs"),
    f("costs.operating.amount", "Operating cost", "currency", "nonneg", "costs"),
    f("costs.electricityPricePerKwh", "Electricity price", "per kWh", "nonneg", "costs"),
    f("costs.waterPricePerM3", "Water price", "per m³", "nonneg", "costs"),
  ].map((x) => [x.path, x]),
);

export type MaterialDraft = {
  id: string;
  name: string;
  phase: "construction" | "operation";
  quantity: string;
  unit: "kg" | "t";
  period: Period;
  price: string;
  provenance: Provenance;
};

export type EmissionDraft = { id: string; pollutant: string; rate: string; provenance: Provenance };

export type StatsDraft = {
  /** Scalar statistics keyed by STAT_FIELDS path. */
  values: Record<string, string>;
  operatingPeriod: Period;
  operatingKind: "total" | "fixed";
  demandBasis: "direct" | "derived";
  materials: MaterialDraft[];
  emissions: EmissionDraft[];
  provenance: Record<SectionKey, Provenance>;
  /** Type-specific template parameters, as typed. */
  params: Record<string, string>;
  /** Parameters as loaded; keys the current template doesn't know are passed through unchanged. */
  originalParams: Record<string, ParamValue>;
  /** Name of the real example the values came from; edits are then labelled "edited from <name>". */
  basedOn?: string | null;
  /** Unit prices explicitly taken from the map's location average (absent = typed or blank). */
  priceSources: Partial<Record<PriceResource, PriceSource | null>>;
};

/** Draft path of each unit price that can come from the location. */
export const PRICE_PATHS: Record<PriceResource, string> = {
  electricity: "costs.electricityPricePerKwh",
  water: "costs.waterPricePerM3",
};
const SOURCE_KEYS: Record<PriceResource, "electricityPriceSource" | "waterPriceSource"> = {
  electricity: "electricityPriceSource",
  water: "waterPriceSource",
};

export const USER: Provenance = { kind: "user_assumption" };

/** Provenance for a value the user has just edited in this draft. */
export function editedProvenance(draft: Pick<StatsDraft, "basedOn">): Provenance {
  return draft.basedOn ? { kind: "user_assumption", note: `edited from ${draft.basedOn}` } : USER;
}

function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const k of path.split(".")) {
    if (cur === null || cur === undefined || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return cur;
}

function setPath(obj: Record<string, unknown>, path: string, value: unknown) {
  const keys = path.split(".");
  let cur = obj;
  for (const k of keys.slice(0, -1)) {
    if (!cur[k] || typeof cur[k] !== "object") cur[k] = {};
    cur = cur[k] as Record<string, unknown>;
  }
  cur[keys[keys.length - 1]] = value;
}

export function statsToDraft(stats: BuildingStats | undefined | null, parameters: Record<string, ParamValue> = {}): StatsDraft {
  const s = stats ?? {};
  const values: Record<string, string> = {};
  for (const path of Object.keys(STAT_FIELDS)) {
    const v = getPath(s, path);
    values[path] = typeof v === "number" ? numStr(v) : typeof v === "string" ? v : "";
  }
  const prov = (p: Provenance | undefined | null): Provenance => p ?? USER;
  return {
    values,
    operatingPeriod: s.costs?.operating?.period ?? "year",
    operatingKind: s.costs?.operating?.kind ?? "fixed",
    demandBasis: s.demandBasis ?? "direct",
    materials: (s.materials ?? []).map((m) => ({
      id: m.id || newId("mat"),
      name: m.name ?? "",
      phase: m.phase ?? "construction",
      quantity: numStr(m.quantityKg),
      unit: "kg",
      period: m.period ?? "year",
      price: numStr(m.unitPricePerKg),
      provenance: prov(m.provenance),
    })),
    emissions: (s.emissions ?? []).map((e) => ({
      id: e.id || newId("em"),
      pollutant: e.pollutant ?? "",
      rate: numStr(e.rateKgPerHour),
      provenance: prov(e.provenance),
    })),
    provenance: {
      footprint: prov(s.footprintProvenance),
      power: prov(s.power?.provenance),
      water: prov(s.water?.provenance),
      light: prov(s.light?.provenance),
      workers: prov(s.workers?.provenance),
      costs: prov(s.costs?.provenance),
    },
    params: Object.fromEntries(Object.entries(parameters).map(([k, v]) => [k, String(v)])),
    originalParams: { ...parameters },
    priceSources: {
      electricity: s.costs?.electricityPriceSource ?? null,
      water: s.costs?.waterPriceSource ?? null,
    },
  };
}

/**
 * Set one scalar statistic; the section it belongs to becomes a user assumption. Typing a unit price
 * replaces an applied location default: the typed price is the user's own and always wins.
 */
export function editValue(draft: StatsDraft, path: string, value: string): StatsDraft {
  const section = STAT_FIELDS[path]?.section;
  const resource = (Object.keys(PRICE_PATHS) as PriceResource[]).find((r) => PRICE_PATHS[r] === path);
  return {
    ...draft,
    values: { ...draft.values, [path]: value },
    provenance: section ? { ...draft.provenance, [section]: editedProvenance(draft) } : draft.provenance,
    priceSources: resource ? { ...draft.priceSources, [resource]: null } : draft.priceSources,
  };
}

/**
 * Explicitly use a location's average price for a blank (or location-default) unit price. Sets the
 * cost currency to the price's currency only when no currency is set; a different currency is never
 * converted, so the draft is then returned unchanged.
 */
export function applyLocationPrice(draft: StatsDraft, offer: LocationPriceOffer): StatsDraft {
  const price = offer.price;
  if (!price) return draft;
  const path = PRICE_PATHS[offer.resource];
  if (draft.values[path]?.trim() && !draft.priceSources[offer.resource]) return draft; // typed price wins
  const currency = (draft.values["costs.currency"] ?? "").trim().toUpperCase();
  if (currency && currency !== price.currency) return draft;
  return {
    ...draft,
    values: { ...draft.values, [path]: String(price.value), "costs.currency": currency || price.currency },
    provenance: { ...draft.provenance, costs: editedProvenance(draft) },
    priceSources: { ...draft.priceSources, [offer.resource]: price },
  };
}

/** Remove an applied location default: the price goes back to blank (unknown). */
export function removeLocationPrice(draft: StatsDraft, resource: PriceResource): StatsDraft {
  return {
    ...draft,
    values: { ...draft.values, [PRICE_PATHS[resource]]: "" },
    priceSources: { ...draft.priceSources, [resource]: null },
  };
}

/** "USD 0.1245/kWh · business average, Arizona · PRICE-01 …" for showing next to the price. */
export function priceSourceText(src: PriceSource, resource: PriceResource): string {
  const unit = resource === "electricity" ? "kWh" : "m³";
  const area = src.priceAreaName || src.priceArea || `cell ${src.h3Id}`;
  return `${src.currency} ${src.value}/${unit} · ${src.customer} average, ${area}${src.source ? ` · ${src.source}` : ""}`;
}

/** Replace one material row; an edited row becomes a user assumption (other rows keep theirs). */
export function editMaterial(draft: StatsDraft, next: MaterialDraft): StatsDraft {
  const provenance = editedProvenance(draft);
  return { ...draft, materials: draft.materials.map((x) => (x.id === next.id ? { ...next, provenance } : x)) };
}

/** Replace one emission row; an edited row becomes a user assumption (other rows keep theirs). */
export function editEmission(draft: StatsDraft, next: EmissionDraft): StatsDraft {
  const provenance = editedProvenance(draft);
  return { ...draft, emissions: draft.emissions.map((x) => (x.id === next.id ? { ...next, provenance } : x)) };
}

/** Change the operating-cost period or kind; the costs section becomes a user assumption. */
export function editOperating(draft: StatsDraft, patch: Partial<Pick<StatsDraft, "operatingPeriod" | "operatingKind">>): StatsDraft {
  return { ...draft, ...patch, provenance: { ...draft.provenance, costs: editedProvenance(draft) } };
}

export function paramRule(p: TemplateParam): Rule {
  if (p.key === "pue") return "pue";
  if (p.unit === "0–1" || p.unit === "0-1") return "fraction";
  if (p.unit.includes("°")) return "finite";
  return "nonneg";
}

export type ParsedStats = { stats: BuildingStats; parameters: Record<string, ParamValue>; errors: Errors };

/**
 * `type`, when given, limits the demand basis to where it is defined: only a data centre can derive
 * demand from IT power × load × PUE, so every other type is sent as "direct" (the draft keeps the
 * choice in case the user switches back).
 */
export function parseStats(draft: StatsDraft, templateParams: TemplateParam[], type?: BuildingType): ParsedStats {
  const errors: Errors = {};
  const out: Record<string, unknown> = {};
  for (const spec of Object.values(STAT_FIELDS)) {
    const raw = draft.values[spec.path] ?? "";
    if (!spec.rule) {
      let text: string | null = raw.trim() || null;
      if (spec.path === "costs.currency" && text) {
        text = text.toUpperCase();
        if (!/^[A-Z]{3}$/.test(text)) errors[spec.path] = "Use a 3-letter ISO code, e.g. USD";
      }
      setPath(out, spec.path, text);
      continue;
    }
    const { value, error } = parseNumber(raw, spec.rule);
    if (error) errors[spec.path] = error;
    setPath(out, spec.path, value);
  }
  // A location-default price keeps its source, and is never mixed with another currency.
  const parsedCurrency = getPath(out, "costs.currency") as string | null;
  for (const r of Object.keys(PRICE_PATHS) as PriceResource[]) {
    const src = draft.priceSources?.[r] ?? null;
    setPath(out, `costs.${SOURCE_KEYS[r]}`, src);
    if (src && parsedCurrency !== src.currency && !errors["costs.currency"]) {
      errors[PRICE_PATHS[r]] =
        `Location price is in ${src.currency} but costs are in ${parsedCurrency || "no currency"}; ` +
        `currencies are never converted. Remove it or set the currency to ${src.currency}.`;
    }
  }
  setPath(out, "costs.operating.period", draft.operatingPeriod);
  setPath(out, "costs.operating.kind", draft.operatingKind);
  setPath(out, "footprintProvenance", draft.provenance.footprint);
  for (const s of ["power", "water", "light", "workers", "costs"] as const) setPath(out, `${s}.provenance`, draft.provenance[s]);

  const materials: MaterialItem[] = draft.materials.map((m) => {
    const q = parseNumber(m.quantity, "nonneg");
    const p = parseNumber(m.price, "nonneg");
    if (!m.name.trim()) errors[`materials.${m.id}.name`] = "Name required";
    if (q.error) errors[`materials.${m.id}.quantity`] = q.error;
    if (p.error) errors[`materials.${m.id}.price`] = p.error;
    return {
      id: m.id,
      name: m.name.trim(),
      phase: m.phase,
      quantityKg: q.value === null ? null : toKg(q.value, m.unit),
      period: m.phase === "operation" ? m.period : null,
      unitPricePerKg: p.value,
      provenance: m.provenance,
    };
  });
  const emissions = draft.emissions.map((e) => {
    const r = parseNumber(e.rate, "nonneg");
    if (!e.pollutant.trim()) errors[`emissions.${e.id}.pollutant`] = "Pollutant required";
    if (r.error) errors[`emissions.${e.id}.rate`] = r.error;
    return { id: e.id, pollutant: e.pollutant.trim(), rateKgPerHour: r.value, provenance: e.provenance };
  });

  const known = new Set(templateParams.map((p) => p.key));
  const parameters: Record<string, ParamValue> = {};
  for (const [k, v] of Object.entries(draft.originalParams)) if (!known.has(k)) parameters[k] = v;
  for (const p of templateParams) {
    const raw = (draft.params[p.key] ?? "").trim();
    if (raw === "") continue; // unknown stays unknown
    if (p.kind === "select") {
      parameters[p.key] = raw;
      continue;
    }
    const { value, error } = parseNumber(raw, paramRule(p));
    if (error) errors[`params.${p.key}`] = error;
    else if (value !== null) parameters[p.key] = value;
  }

  const stats = {
    ...(out as BuildingStats),
    materials,
    emissions,
    demandBasis: type && type !== "data_centre" ? "direct" : draft.demandBasis,
  };
  return { stats, parameters, errors };
}

export function newMaterial(): MaterialDraft {
  return { id: newId("mat"), name: "", phase: "construction", quantity: "", unit: "t", period: "year", price: "", provenance: USER };
}

export function newEmission(): EmissionDraft {
  return { id: newId("em"), pollutant: "", rate: "", provenance: USER };
}

/** Number of errors whose key is one of `prefixes` or starts with it (e.g. "power." or "materials."). */
export function countErrors(errors: Errors, prefixes: string[]): number {
  return Object.keys(errors).filter((k) => prefixes.some((p) => k === p || k.startsWith(p))).length;
}

/** Count of filled scalar fields among `paths`, for section summaries. */
export function filledCount(draft: StatsDraft, paths: string[]): number {
  return paths.filter((p) => (draft.values[p] ?? "").trim() !== "").length;
}

// --------------------------------------------------------------------------------------------
// What is still needed for a conclusive assessment

/**
 * Inputs that the enabled requirements depend on and that are still unknown. Only inputs some
 * check actually uses are listed, so the list matches what keeps the assessment inconclusive.
 */
export function missingInputs(
  stats: BuildingStats,
  parameters: Record<string, ParamValue>,
  template: Pick<BuildingTemplate, "type">,
  criteria: Criterion[],
): string[] {
  const out: string[] = [];
  const add = (s: string) => {
    if (!out.includes(s)) out.push(s);
  };
  const unknown = (v: unknown) => v === null || v === undefined || v === "";
  if (criteria.length === 0) add("At least one location requirement");

  const derived = template.type === "data_centre" && stats.demandBasis === "derived";
  const param = (key: string, label: string) => {
    if (unknown(parameters[key])) add(label);
  };
  const hours = () => {
    if (unknown(stats.operatingHoursPerDay)) add("Operating hours (h/day)");
  };
  const itEnergy = () => {
    hours();
    param("itPowerKw", "IT power (kW)");
    param("loadFraction", "Load fraction (0–1)");
  };
  const energy = () => {
    if (derived) {
      itEnergy();
      param("pue", "PUE");
    } else {
      hours();
      if (unknown(stats.power?.averageDemandKw)) add("Average power demand (kW)");
    }
  };
  const water = () => {
    if (derived) {
      itEnergy();
      if (parameters.wueBasis !== "it_energy") param("pue", "PUE");
      param("wueLPerKwh", "WUE (L/kWh)");
      param("wueBasis", "WUE basis");
    } else {
      hours();
      if (unknown(stats.water?.inputM3PerHour)) add("Water input (m³/h)");
    }
  };
  const currency = () => {
    if (!stats.costs?.currency) add("Currency");
  };

  for (const c of criteria) {
    switch (c.kind) {
      case "site_area":
        if (unknown(stats.footprintM2)) add("Footprint (m²)");
        break;
      case "power_capacity":
        if (derived) {
          param("itPowerKw", "IT power (kW)");
          param("pue", "PUE");
        } else if (unknown(stats.power?.peakDemandKw) && unknown(stats.power?.averageDemandKw)) {
          add("Peak power demand (kW)");
        }
        break;
      case "energy_budget":
        energy();
        break;
      case "water_budget":
        water();
        break;
      case "construction_budget":
        if (unknown(stats.costs?.constructionTotal)) add("Construction cost");
        currency();
        break;
      case "operating_budget":
        if (unknown(stats.costs?.operating?.amount)) add("Operating cost");
        currency();
        break;
      case "staffing":
        if (unknown(stats.workers?.staffingRequired)) add("Staff required (people)");
        if (unknown(stats.workers?.capacity)) add("Worker capacity (people)");
        break;
      case "light_limit":
        if (unknown(stats.light?.upwardLumens)) add("Upward light (lumens)");
        break;
      case "emission_limit": {
        const name = (c.pollutant ?? "").trim().toLowerCase();
        const e = (stats.emissions ?? []).find((x) => x.pollutant.trim().toLowerCase() === name);
        if (!name) add("Pollutant name in the emission limit");
        else if (!e || unknown(e.rateKgPerHour)) add(`Emission rate for ${c.pollutant} (kg/h)`);
        hours();
        break;
      }
      case "material_budget": {
        const name = (c.materialName ?? "").trim().toLowerCase();
        const m = (stats.materials ?? []).find((x) => x.name.trim().toLowerCase() === name);
        if (!name) add("Material name in the material limit");
        else if (!m || unknown(m.quantityKg)) add(`Quantity of ${c.materialName} (kg)`);
        break;
      }
      default:
        break; // layer checks use map data only
    }
  }
  return out;
}

// --------------------------------------------------------------------------------------------
// Criteria

export const CRITERION_KINDS: { kind: CriterionKind; label: string; help: string }[] = [
  { kind: "layer", label: "Map layer limit", help: "Keep cells whose value on a data layer is within a range, or in chosen classes." },
  { kind: "site_area", label: "Usable site area", help: "Compares the footprint with the usable area you declare for a specific site (in the preview)." },
  { kind: "power_capacity", label: "Connected power capacity", help: "Compares peak demand with the connected capacity declared for a site or in a scenario budget." },
  { kind: "energy_budget", label: "Energy budget", help: "Compares energy use over the period with the site's daily energy budget or a scenario budget." },
  { kind: "water_budget", label: "Water allocation", help: "Compares water use over the period with the site's daily allocation or a scenario budget." },
  { kind: "construction_budget", label: "Construction budget", help: "Maximum one-time construction cost." },
  { kind: "operating_budget", label: "Operating budget", help: "Maximum operating cost over the evaluation period." },
  { kind: "material_budget", label: "Material limit", help: "Maximum mass of one named material (construction plus operation over the period)." },
  { kind: "staffing", label: "Staffing fits capacity", help: "Staff required must not exceed worker capacity." },
  { kind: "light_limit", label: "Light limit", help: `Maximum declared upward light. ${LIGHT_PROXY_NOTE}` },
  { kind: "emission_limit", label: "Emission limit", help: "Maximum mass of one named pollutant over the evaluation period." },
];

export const CRITERION_LABEL = Object.fromEntries(CRITERION_KINDS.map((k) => [k.kind, k.label])) as Record<CriterionKind, string>;

/** Kinds whose comparison value comes from site assumptions or scenario budgets, not from the criterion. */
export const SITE_KINDS: CriterionKind[] = ["site_area", "power_capacity", "energy_budget", "water_budget"];
export const AMOUNT_KINDS: CriterionKind[] = ["construction_budget", "operating_budget", "material_budget", "light_limit", "emission_limit"];

export type CriterionDraft = {
  id: string;
  kind: CriterionKind;
  required: boolean;
  layerId: string;
  sliceId: string;
  min: string;
  max: string;
  classes: number[] | null;
  amount: string;
  materialName: string;
  pollutant: string;
};

export function newCriterion(kind: CriterionKind): CriterionDraft {
  return {
    id: newId("crit"),
    kind,
    required: true,
    layerId: "",
    sliceId: "",
    min: "",
    max: "",
    classes: null,
    amount: "",
    materialName: "",
    pollutant: "",
  };
}

export function criterionToDraft(c: Criterion): CriterionDraft {
  return {
    id: c.id,
    kind: c.kind,
    required: c.required,
    layerId: c.layerId ?? "",
    sliceId: c.sliceId ?? "",
    min: numStr(c.min),
    max: numStr(c.max),
    classes: c.classes ?? null,
    amount: numStr(c.amount),
    materialName: c.materialName ?? "",
    pollutant: c.pollutant ?? "",
  };
}

export function parseCriteria(drafts: CriterionDraft[]): { criteria: Criterion[]; errors: Errors } {
  const errors: Errors = {};
  const criteria = drafts.map((d): Criterion => {
    const c: Criterion = { id: d.id, kind: d.kind, required: d.required, label: CRITERION_LABEL[d.kind] };
    if (d.kind === "layer") {
      if (!d.layerId) errors[`${d.id}.layer`] = "Choose a layer";
      c.layerId = d.layerId || null;
      c.sliceId = d.sliceId || null;
      if (d.classes) {
        c.classes = d.classes;
        if (d.classes.length === 0) errors[`${d.id}.classes`] = "Choose at least one class";
      } else {
        const lo = parseNumber(d.min, "finite");
        const hi = parseNumber(d.max, "finite");
        if (lo.error) errors[`${d.id}.min`] = lo.error;
        if (hi.error) errors[`${d.id}.max`] = hi.error;
        if (lo.value !== null && hi.value !== null && lo.value > hi.value) errors[`${d.id}.max`] = "Max must be at least min";
        if (!lo.error && !hi.error && lo.value === null && hi.value === null) errors[`${d.id}.min`] = "Enter a min, a max or both";
        c.min = lo.value;
        c.max = hi.value;
      }
    }
    if (AMOUNT_KINDS.includes(d.kind)) {
      const a = parseNumber(d.amount, "nonneg");
      if (a.error) errors[`${d.id}.amount`] = a.error;
      c.amount = a.value;
    }
    if (d.kind === "material_budget") {
      c.materialName = d.materialName.trim() || null;
      if (!c.materialName) errors[`${d.id}.materialName`] = "Name the material";
    }
    if (d.kind === "emission_limit") {
      c.pollutant = d.pollutant.trim() || null;
      if (!c.pollutant) errors[`${d.id}.pollutant`] = "Name the pollutant";
    }
    return c;
  });
  return { criteria, errors };
}

// --------------------------------------------------------------------------------------------
// Site assumptions (one exact location only)

export type SiteDraft = {
  usableAreaM2: string;
  connectedCapacityKw: string;
  energyBudgetKwhPerDay: string;
  waterAllocationM3PerDay: string;
  note: string;
};

export const SITE_FIELDS: { key: Exclude<keyof SiteDraft, "note">; label: string; unit: string }[] = [
  { key: "usableAreaM2", label: "Usable area", unit: "m²" },
  { key: "connectedCapacityKw", label: "Connected power capacity", unit: "kW" },
  { key: "energyBudgetKwhPerDay", label: "Energy budget", unit: "kWh/day" },
  { key: "waterAllocationM3PerDay", label: "Water allocation", unit: "m³/day" },
];

export function siteToDraft(site: SiteAssumptions | null | undefined): SiteDraft {
  const s = site ?? {};
  return {
    usableAreaM2: numStr(s.usableAreaM2),
    connectedCapacityKw: numStr(s.connectedCapacityKw),
    energyBudgetKwhPerDay: numStr(s.energyBudgetKwhPerDay),
    waterAllocationM3PerDay: numStr(s.waterAllocationM3PerDay),
    note: s.note ?? "",
  };
}

export function parseSite(d: SiteDraft): { site: SiteAssumptions; errors: Errors } {
  const errors: Errors = {};
  const site: SiteAssumptions = { note: d.note.trim() || null };
  for (const { key } of SITE_FIELDS) {
    const r = parseNumber(d[key], "nonneg");
    if (r.error) errors[key] = r.error;
    site[key] = r.value;
  }
  return { site, errors };
}

// --------------------------------------------------------------------------------------------
// Scenario assumptions, budgets and stress controls

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** Defensive merge of whatever the server returned with DEFAULT_ASSUMPTIONS. */
export function mergeAssumptions(raw: unknown): ScenarioAssumptions {
  const a = isObj(raw) ? raw : {};
  const st = isObj(a.stress) ? a.stress : {};
  const budgets = Array.isArray(a.budgets) ? (a.budgets as ResourceBudget[]) : [];
  return {
    schemaVersion: num(a.schemaVersion, DEFAULT_ASSUMPTIONS.schemaVersion),
    periodDays: num(a.periodDays, DEFAULT_ASSUMPTIONS.periodDays),
    budgets: budgets.filter(isObj).map((b) => ({
      id: b.id || newId("budget"),
      label: b.label ?? "",
      kind: b.kind ?? "energy_kwh_per_day",
      amount: b.amount ?? null,
      scope: isObj(b.scope) ? b.scope : { kind: "scenario" },
      contributingProjectIds: Array.isArray(b.contributingProjectIds) ? b.contributingProjectIds : [],
    })),
    stress: {
      waterAvailability: num(st.waterAvailability, NEUTRAL_STRESS.waterAvailability),
      powerAvailability: num(st.powerAvailability, NEUTRAL_STRESS.powerAvailability),
      operatingDemand: num(st.operatingDemand, NEUTRAL_STRESS.operatingDemand),
      operatingPrices: num(st.operatingPrices, NEUTRAL_STRESS.operatingPrices),
    },
  };
}

export const BUDGET_KINDS: { kind: BudgetKind; label: string; unit: string }[] = [
  { kind: "power_capacity_kw", label: "Power capacity", unit: "kW" },
  { kind: "energy_kwh_per_day", label: "Energy", unit: "kWh/day" },
  { kind: "water_m3_per_day", label: "Water", unit: "m³/day" },
];

export type BudgetDraft = {
  id: string;
  label: string;
  kind: BudgetKind;
  amount: string;
  scopeKind: "scenario" | "region" | "radius";
  region: "arizona" | "uk";
  latitude: string;
  longitude: string;
  radiusKm: string;
  contributingProjectIds: string[];
};

export function budgetToDraft(b: ResourceBudget): BudgetDraft {
  return {
    id: b.id,
    label: b.label,
    kind: b.kind,
    amount: numStr(b.amount),
    scopeKind: b.scope?.kind ?? "scenario",
    region: b.scope?.region ?? "arizona",
    latitude: numStr(b.scope?.latitude),
    longitude: numStr(b.scope?.longitude),
    radiusKm: numStr(b.scope?.radiusKm),
    contributingProjectIds: b.contributingProjectIds ?? [],
  };
}

export function newBudget(): BudgetDraft {
  return budgetToDraft({ id: newId("budget"), label: "", kind: "energy_kwh_per_day", amount: null, scope: { kind: "scenario" }, contributingProjectIds: [] });
}

export function parseBudgets(drafts: BudgetDraft[]): { budgets: ResourceBudget[]; errors: Errors } {
  const errors: Errors = {};
  const seen = new Map<string, string>(); // `${kind}|${projectId}` -> label of the first budget
  const budgets = drafts.map((d): ResourceBudget => {
    if (!d.label.trim()) errors[`${d.id}.label`] = "Label required";
    // A plant's net output may feed only one budget of each kind (the server rejects a repeat).
    for (const pid of new Set(d.contributingProjectIds)) {
      const other = seen.get(`${d.kind}|${pid}`);
      if (other !== undefined) errors[`${d.id}.contributors`] = `A ticked plant already adds to "${other || "another budget"}" of this kind; untick it in one of them`;
      else seen.set(`${d.kind}|${pid}`, d.label.trim());
    }
    const amount = parseNumber(d.amount, "nonneg");
    if (amount.error) errors[`${d.id}.amount`] = amount.error;
    const b: ResourceBudget = {
      id: d.id,
      label: d.label.trim(),
      kind: d.kind,
      amount: amount.value,
      scope: { kind: d.scopeKind },
      contributingProjectIds: d.contributingProjectIds,
    };
    if (d.scopeKind === "region") b.scope.region = d.region;
    if (d.scopeKind === "radius") {
      const lat = parseNumber(d.latitude, "finite");
      const lon = parseNumber(d.longitude, "finite");
      const r = parseNumber(d.radiusKm, "positive");
      if (lat.error || lat.value === null || lat.value < -90 || lat.value > 90) errors[`${d.id}.latitude`] = "Latitude between -90 and 90";
      if (lon.error || lon.value === null) errors[`${d.id}.longitude`] = "Enter a longitude";
      if (r.error || r.value === null) errors[`${d.id}.radiusKm`] = r.error ?? "Enter a radius";
      b.scope.latitude = lat.value;
      b.scope.longitude = lon.value;
      b.scope.radiusKm = r.value;
    }
    return b;
  });
  return { budgets, errors };
}

export type StressDraft = Record<keyof StressControls, string>;

export const stressToDraft = (s: StressControls): StressDraft => ({
  waterAvailability: String(s.waterAvailability),
  powerAvailability: String(s.powerAvailability),
  operatingDemand: String(s.operatingDemand),
  operatingPrices: String(s.operatingPrices),
});

export function parseStress(d: StressDraft): { stress: StressControls; errors: Errors } {
  const errors: Errors = {};
  const get = (k: keyof StressControls, rule: Rule) => {
    const r = parseNumber(d[k], rule);
    if (r.error || r.value === null) {
      errors[k] = r.error ?? "Required";
      return NEUTRAL_STRESS[k];
    }
    return r.value;
  };
  return {
    stress: {
      waterAvailability: get("waterAvailability", "fraction"),
      powerAvailability: get("powerAvailability", "fraction"),
      operatingDemand: get("operatingDemand", "multiplier"),
      operatingPrices: get("operatingPrices", "multiplier"),
    },
    errors,
  };
}

// --------------------------------------------------------------------------------------------
// Display

export function fmtNumber(v: number): string {
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v === 0) return "0";
  return v.toLocaleString(undefined, { maximumSignificantDigits: 4 });
}

/** "8,000 kWh", or "unknown" — never 0 for a missing value. */
export function fmtQuantity(q: Quantity | null | undefined): string {
  if (!q || q.value === null || q.value === undefined) return "unknown";
  return `${fmtNumber(q.value)}${q.unit ? ` ${q.unit}` : ""}`;
}

export const fmtPercent = (multiplier: number) => `${Math.round(multiplier * 100)}%`;

export const fmtDays = (days: number) => `${fmtNumber(days)} day${days === 1 ? "" : "s"}`;

/**
 * The "building / site vs limit" line for a check, or null where it would mislead: layer checks
 * compare a cell value with a rule (a range or a set of classes), which their explanation states
 * with the class label, so the raw value/limit pair is not shown for them.
 */
export function checkComparison(c: Pick<CheckResult, "kind" | "actual" | "requiredValue" | "unit">): string | null {
  if (c.kind === "layer") return null;
  const v = (x: number | null) => (x === null || x === undefined ? "unknown" : `${fmtNumber(x)}${c.unit ? ` ${c.unit}` : ""}`);
  return `Building / site: ${v(c.actual)} · Limit: ${v(c.requiredValue)}`;
}

export const STATUS_LABEL: Record<CheckStatus, string> = { pass: "Pass", fail: "Fail", unknown: "Unknown" };

export const PERIOD_LABEL: Record<Period, string> = { hour: "hour", day: "day", month: "month", year: "year" };

export const STATE_ORDER: AssessmentState[] = ["meets_criteria", "insufficient_data", "fails_criteria"];

export const BUILDING_TYPES_ORDER: BuildingType[] = ["power_station", "water_plant", "data_centre", "solar", "greenhouse", "custom"];

export const coordLabel = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(5)}° ${lon >= 0 ? "E" : "W"}`;
