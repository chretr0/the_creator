import type { ProjectType } from "./api";
import type { BuildingCategory, BuildingTemplate, BuildingType } from "./buildings";
import type { IconName } from "../components/Icon";

/**
 * Parameter definitions only: names, units and meaning. No default coefficient values are
 * supplied here — every value is a user assumption until a cited source is attached
 * (see "Simulation meaning and resource accounting" in CLAUDE.md).
 */
export type ParamDef = {
  key: string;
  label: string;
  unit: string;
  kind: "number" | "select";
  options?: string[];
  hint?: string;
};

export type ProjectTypeDef = {
  type: ProjectType;
  label: string;
  /** Map colour. Types in one category share a hue family; every type stays distinguishable. */
  colour: [number, number, number];
  category: BuildingCategory;
  icon: IconName;
  /** Local stand-in for the template's type-specific fields (only used when the API is down). */
  params: ParamDef[];
};

export type CategoryDef = { category: BuildingCategory; label: string; icon: IconName };

/** Display order and labels of the building categories (mirrors the backend template order). */
export const BUILDING_CATEGORIES: CategoryDef[] = [
  { category: "energy", label: "Energy", icon: "bolt" },
  { category: "water", label: "Water", icon: "water" },
  { category: "extraction", label: "Mining & extraction", icon: "pickaxe" },
  { category: "industry", label: "Industry & manufacturing", icon: "factory" },
  { category: "agriculture", label: "Agriculture & food", icon: "wheat" },
  { category: "commercial", label: "Commercial & digital", icon: "office" },
  { category: "community", label: "Housing & public services", icon: "house" },
  { category: "transport", label: "Transport & logistics", icon: "plane" },
  { category: "waste", label: "Waste & recycling", icon: "recycle" },
  { category: "other", label: "Other", icon: "building" },
];

export const CATEGORY_BY_ID = Object.fromEntries(BUILDING_CATEGORIES.map((c) => [c.category, c])) as Record<
  BuildingCategory,
  CategoryDef
>;

type Def = Omit<ProjectTypeDef, "params"> & { params?: ParamDef[] };
const def = (d: Def): ProjectTypeDef => ({ ...d, params: d.params ?? [] });

/** Every building type, in the same order as GET /api/building-templates. */
export const PROJECT_TYPES: ProjectTypeDef[] = [
  // ---- energy: magenta / amber / orange ----
  def({ type: "power_station", label: "Power station", category: "energy", icon: "bolt", colour: [214, 69, 160] }),
  def({
    type: "solar",
    label: "Solar generation",
    category: "energy",
    icon: "sun",
    colour: [245, 176, 33],
    params: [
      { key: "capacityKwp", label: "Peak capacity", unit: "kWp", kind: "number" },
      { key: "landAreaM2", label: "Occupied land", unit: "m²", kind: "number" },
      { key: "performanceRatio", label: "Performance ratio", unit: "0–1", kind: "number" },
    ],
  }),
  def({ type: "wind_farm", label: "Wind farm", category: "energy", icon: "wind", colour: [240, 128, 190] }),
  def({ type: "hydro_plant", label: "Hydroelectric plant", category: "energy", icon: "dam", colour: [142, 36, 124] }),
  def({ type: "geothermal_plant", label: "Geothermal plant", category: "energy", icon: "flame", colour: [232, 104, 40] }),
  def({ type: "battery_storage", label: "Battery storage", category: "energy", icon: "battery", colour: [176, 128, 0] }),
  def({ type: "hydrogen_plant", label: "Hydrogen plant", category: "energy", icon: "molecule", colour: [250, 158, 128] }),
  // ---- water: blues ----
  def({ type: "water_plant", label: "Water plant", category: "water", icon: "water", colour: [30, 136, 229] }),
  def({ type: "wastewater_plant", label: "Wastewater treatment", category: "water", icon: "filter", colour: [18, 82, 152] }),
  // ---- mining & extraction: earth browns ----
  def({ type: "mine", label: "Mine", category: "extraction", icon: "pickaxe", colour: [133, 90, 58] }),
  def({ type: "quarry", label: "Quarry", category: "extraction", icon: "mountain", colour: [204, 168, 112] }),
  def({ type: "oil_gas_field", label: "Oil & gas field", category: "extraction", icon: "derrick", colour: [70, 52, 40] }),
  // ---- industry & manufacturing: reds / rust ----
  def({ type: "factory", label: "Factory", category: "industry", icon: "factory", colour: [200, 64, 56] }),
  def({ type: "steel_mill", label: "Steel mill", category: "industry", icon: "ingot", colour: [118, 38, 38] }),
  def({ type: "aluminium_smelter", label: "Aluminium smelter", category: "industry", icon: "crucible", colour: [224, 132, 124] }),
  def({ type: "cement_plant", label: "Cement plant", category: "industry", icon: "silo", colour: [150, 140, 150] }),
  def({ type: "chemical_plant", label: "Chemical plant", category: "industry", icon: "flask", colour: [232, 46, 92] }),
  def({ type: "oil_refinery", label: "Oil refinery", category: "industry", icon: "refinery", colour: [166, 78, 30] }),
  def({ type: "semiconductor_fab", label: "Semiconductor fab", category: "industry", icon: "chip", colour: [170, 20, 60] }),
  // ---- agriculture & food: greens ----
  def({ type: "farm", label: "Crop farm", category: "agriculture", icon: "wheat", colour: [130, 182, 64] }),
  def({ type: "livestock_farm", label: "Livestock farm", category: "agriculture", icon: "barn", colour: [82, 130, 44] }),
  def({
    type: "greenhouse",
    label: "Greenhouse",
    category: "agriculture",
    icon: "sprout",
    colour: [46, 184, 114],
    params: [
      { key: "floorAreaM2", label: "Floor area", unit: "m²", kind: "number" },
      { key: "heatDemandKwhPerYear", label: "Heat demand", unit: "kWh/yr", kind: "number" },
      { key: "minSupplyTempC", label: "Min. supply temperature", unit: "°C", kind: "number" },
    ],
  }),
  def({ type: "vertical_farm", label: "Vertical farm", category: "agriculture", icon: "rack", colour: [0, 128, 84] }),
  def({ type: "aquaculture", label: "Aquaculture", category: "agriculture", icon: "fish", colour: [60, 200, 170] }),
  def({ type: "food_processing", label: "Food processing plant", category: "agriculture", icon: "utensils", colour: [178, 184, 40] }),
  // ---- commercial & digital: violets ----
  def({
    type: "data_centre",
    label: "Data centre",
    category: "commercial",
    icon: "server",
    colour: [124, 92, 255],
    params: [
      { key: "itPowerKw", label: "IT power", unit: "kW", kind: "number" },
      { key: "loadFraction", label: "Load fraction", unit: "0–1", kind: "number" },
      { key: "pue", label: "PUE", unit: "ratio", kind: "number", hint: "facility energy ÷ IT energy" },
      { key: "wueLPerKwh", label: "WUE", unit: "L/kWh", kind: "number" },
      { key: "wueBasis", label: "WUE basis", unit: "", kind: "select", options: ["it_energy", "facility_energy"] },
      { key: "heatRecoveryFraction", label: "Heat recovery fraction", unit: "0–1", kind: "number" },
    ],
  }),
  def({ type: "office", label: "Office building", category: "commercial", icon: "office", colour: [92, 52, 176] }),
  def({ type: "retail", label: "Retail centre", category: "commercial", icon: "cart", colour: [176, 140, 255] }),
  def({ type: "hotel", label: "Hotel", category: "commercial", icon: "bed", colour: [156, 96, 190] }),
  def({ type: "research_lab", label: "Research laboratory", category: "commercial", icon: "flask", colour: [196, 100, 236] }),
  // ---- housing & public services: teals / cyans ----
  def({ type: "housing", label: "Housing", category: "community", icon: "house", colour: [0, 140, 150] }),
  def({ type: "hospital", label: "Hospital", category: "community", icon: "cross", colour: [0, 190, 214] }),
  def({ type: "school", label: "School", category: "community", icon: "cap", colour: [0, 98, 112] }),
  def({ type: "university", label: "University campus", category: "community", icon: "columns", colour: [100, 206, 224] }),
  def({ type: "stadium", label: "Stadium & arena", category: "community", icon: "stadium", colour: [46, 160, 190] }),
  // ---- transport & logistics: indigos ----
  def({ type: "airport", label: "Airport", category: "transport", icon: "plane", colour: [63, 81, 181] }),
  def({ type: "seaport", label: "Seaport", category: "transport", icon: "anchor", colour: [30, 40, 120] }),
  def({ type: "warehouse", label: "Warehouse & logistics", category: "transport", icon: "warehouse", colour: [124, 138, 210] }),
  // ---- waste & recycling: olives ----
  def({ type: "landfill", label: "Landfill", category: "waste", icon: "trash", colour: [128, 116, 20] }),
  def({ type: "recycling_facility", label: "Recycling facility", category: "waste", icon: "recycle", colour: [120, 160, 128] }),
  def({ type: "waste_to_energy", label: "Waste-to-energy plant", category: "waste", icon: "flame", colour: [96, 84, 16] }),
  // ---- other ----
  def({ type: "custom", label: "Custom building", category: "other", icon: "building", colour: [96, 108, 128] }),
];

export const PROJECT_TYPE_BY_ID = Object.fromEntries(PROJECT_TYPES.map((d) => [d.type, d])) as Record<
  ProjectType,
  ProjectTypeDef
>;

/** Types whose template treats electricity output as the primary result (backend POWER_PRODUCERS). */
export const POWER_PRODUCER_TYPES: ReadonlySet<BuildingType> = new Set<BuildingType>([
  "power_station",
  "solar",
  "wind_farm",
  "hydro_plant",
  "geothermal_plant",
  "battery_storage",
  "waste_to_energy",
]);

/** Types whose template treats water output as the primary result (backend WATER_PRODUCERS). */
export const WATER_PRODUCER_TYPES: ReadonlySet<BuildingType> = new Set<BuildingType>(["water_plant", "wastewater_plant"]);

export const isPowerProducer = (type: string) => POWER_PRODUCER_TYPES.has(type as BuildingType);
export const isWaterProducer = (type: string) => WATER_PRODUCER_TYPES.has(type as BuildingType);

const FALLBACK_DESCRIPTION: Partial<Record<ProjectType, string>> = {
  data_centre: "Computing facility. Demand can come from IT power × load × PUE, or be entered directly.",
  solar: "Solar generation. Output must be declared; peak capacity alone is not generated power.",
  greenhouse: "Greenhouse. Floor area is separate from the ground footprint.",
  power_station: "Generates electricity. Describe the technology; output and own use are separate fields.",
  water_plant: "Produces or treats water. Usable output, water input and electricity use are separate.",
  wastewater_plant: "Treats sewage. Treated output, sewage input and electricity use are separate.",
  battery_storage: "Grid battery. Average output is discharge and average demand is charging; the net is the losses.",
  custom: "Define your own statistics.",
};

function fallbackDescription(type: ProjectType): string {
  const given = FALLBACK_DESCRIPTION[type];
  if (given) return given;
  if (POWER_PRODUCER_TYPES.has(type)) return "Generates electricity. Output and the plant's own use are separate fields.";
  if (WATER_PRODUCER_TYPES.has(type)) return "Produces or treats water. Usable output, water input and electricity use are separate.";
  return "Enter the statistics you know; blank fields stay unknown.";
}

/**
 * Local stand-in used only when GET /api/building-templates is unavailable, so the forms still
 * render. It carries no numeric defaults.
 */
export function fallbackTemplate(type: ProjectType): BuildingTemplate {
  const def = PROJECT_TYPE_BY_ID[type] ?? PROJECT_TYPE_BY_ID.custom;
  return {
    id: type,
    version: 0,
    type,
    category: def.category,
    label: def.label,
    description: fallbackDescription(type),
    producesPower: POWER_PRODUCER_TYPES.has(type),
    producesWater: WATER_PRODUCER_TYPES.has(type),
    parameters: def.params.map((p) => ({ ...p, options: p.options ?? null, hint: p.hint ?? null })),
    defaults: {},
    defaultProvenance: null,
    fieldHelp: {},
  };
}

export const typeLabel = (type: string) => PROJECT_TYPE_BY_ID[type as ProjectType]?.label ?? type;
export const typeColour = (type: string): [number, number, number] =>
  PROJECT_TYPE_BY_ID[type as ProjectType]?.colour ?? [96, 108, 128];
export const typeIcon = (type: string): IconName => PROJECT_TYPE_BY_ID[type as ProjectType]?.icon ?? "building";
export const typeCategory = (type: string): BuildingCategory => PROJECT_TYPE_BY_ID[type as ProjectType]?.category ?? "other";

export type TemplateGroup = { category: BuildingCategory; label: string; icon: IconName; templates: BuildingTemplate[] };

/** The template's category, or its type's when the server sent none (or one this build doesn't know). */
export const templateCategory = (t: BuildingTemplate): BuildingCategory =>
  CATEGORY_BY_ID[t.category] ? t.category : typeCategory(t.type);

const normalise = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[_\-&]/g, " ");

/** True when every word of `query` appears in the template's label, description, category or type id. */
export function templateMatches(t: BuildingTemplate, query: string): boolean {
  const words = normalise(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = normalise([t.label, t.description, t.type, CATEGORY_BY_ID[templateCategory(t)].label].join(" "));
  return words.every((w) => haystack.includes(w));
}

/**
 * Templates grouped by category in display order, filtered by `query`. `keepId` (the selected
 * template) is always kept so the radio group never loses its checked option.
 */
export function groupTemplates(templates: BuildingTemplate[], query = "", keepId?: string | null): TemplateGroup[] {
  const groups = new Map<BuildingCategory, BuildingTemplate[]>();
  for (const t of templates) {
    if (t.id !== keepId && !templateMatches(t, query)) continue;
    const category = templateCategory(t);
    groups.set(category, [...(groups.get(category) ?? []), t]);
  }
  return BUILDING_CATEGORIES.filter((c) => groups.has(c.category)).map((c) => ({ ...c, templates: groups.get(c.category)! }));
}
