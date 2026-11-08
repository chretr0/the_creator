/**
 * Building-system contract. Mirrors backend/app/building_models.py (camelCase over the wire).
 * Change both together. `null`/absent numbers mean unknown, never zero.
 */

export type BuildingType =
  // energy
  | "power_station"
  | "solar"
  | "wind_farm"
  | "hydro_plant"
  | "geothermal_plant"
  | "battery_storage"
  | "hydrogen_plant"
  // water
  | "water_plant"
  | "wastewater_plant"
  // mining & extraction
  | "mine"
  | "quarry"
  | "oil_gas_field"
  // industry & manufacturing
  | "factory"
  | "steel_mill"
  | "aluminium_smelter"
  | "cement_plant"
  | "chemical_plant"
  | "oil_refinery"
  | "semiconductor_fab"
  // agriculture & food
  | "farm"
  | "livestock_farm"
  | "greenhouse"
  | "vertical_farm"
  | "aquaculture"
  | "food_processing"
  // commercial & digital
  | "data_centre"
  | "office"
  | "retail"
  | "hotel"
  | "research_lab"
  // housing & public services
  | "housing"
  | "hospital"
  | "school"
  | "university"
  | "stadium"
  // transport & logistics
  | "airport"
  | "seaport"
  | "warehouse"
  // waste & recycling
  | "landfill"
  | "recycling_facility"
  | "waste_to_energy"
  // anything else
  | "custom";

/** Grouping used to organise the type picker (backend `BuildingCategory`). */
export type BuildingCategory =
  | "energy"
  | "water"
  | "extraction"
  | "industry"
  | "agriculture"
  | "commercial"
  | "community"
  | "transport"
  | "waste"
  | "other";
export type ProvenanceKind = "user_assumption" | "demo_assumption" | "cited";
export type CheckStatus = "pass" | "fail" | "unknown";
export type AssessmentState = "meets_criteria" | "fails_criteria" | "insufficient_data";
export type Period = "hour" | "day" | "month" | "year";
export type ParamValue = number | string | boolean;

export const DAYS_PER_PERIOD: Record<Period, number> = { hour: 1 / 24, day: 1, month: 30.4375, year: 365.25 };

export type Provenance = { kind: ProvenanceKind; note?: string | null };

export type MaterialItem = {
  id: string;
  name: string;
  phase: "construction" | "operation";
  quantityKg?: number | null; // construction: once; operation: per `period`
  period?: Period | null;
  unitPricePerKg?: number | null;
  provenance?: Provenance;
};

export type EmissionItem = {
  id: string;
  pollutant: string;
  medium?: import("./pollutants").ReleaseMedium;
  rateKgPerHour?: number | null;
  provenance?: Provenance;
};

export type PowerStats = {
  averageDemandKw?: number | null;
  peakDemandKw?: number | null;
  averageOutputKw?: number | null;
  ratedOutputKw?: number | null;
  capacityFactor?: number | null;
  technology?: string | null;
  provenance?: Provenance;
};

export type WaterSource = "fresh" | "seawater" | "wastewater";

export type WaterStats = {
  inputM3PerHour?: number | null;
  outputM3PerHour?: number | null;
  /** Where the intake comes from: only "fresh" draws on rivers and runoff. */
  source?: WaterSource;
  basis?: string | null;
  provenance?: Provenance;
};

export type LightStats = { upwardLumens?: number | null; hoursPerDay?: number | null; provenance?: Provenance };
export type WorkerStats = { capacity?: number | null; staffingRequired?: number | null; provenance?: Provenance };

export type OperatingCost = { amount?: number | null; period: Period; kind: "total" | "fixed" };

/**
 * A unit price the user explicitly took from the map (the cell's average business price), not typed.
 * The price field holds exactly `value`; typing another price drops the source. Never converted.
 */
export type PriceSource = {
  kind: "location_default";
  value: number;
  currency: string; // the dataset's currency (USD)
  customer: "business" | "household";
  h3Id: string;
  priceArea?: string | null;
  priceAreaName?: string | null;
  basis?: string | null; // original price, FX, year, publication, tax
  source?: string | null; // dataset / layer label
};

export type PriceResource = "electricity" | "water";

export type Costs = {
  currency?: string | null; // ISO 4217
  constructionTotal?: number | null;
  priceBasis?: string | null;
  operating?: OperatingCost;
  electricityPricePerKwh?: number | null;
  waterPricePerM3?: number | null;
  /** Only when that price is an explicitly applied location default (absent = typed by the user). */
  electricityPriceSource?: PriceSource | null;
  waterPriceSource?: PriceSource | null;
  provenance?: Provenance;
};

export type BuildingStats = {
  footprintM2?: number | null;
  operatingHoursPerDay?: number | null;
  power?: PowerStats;
  water?: WaterStats;
  materials?: MaterialItem[];
  emissions?: EmissionItem[];
  light?: LightStats;
  workers?: WorkerStats;
  costs?: Costs;
  demandBasis?: "direct" | "derived";
  footprintProvenance?: Provenance;
};

export type CriterionKind =
  | "layer"
  | "site_area"
  | "power_capacity"
  | "energy_budget"
  | "water_budget"
  | "construction_budget"
  | "operating_budget"
  | "material_budget"
  | "staffing"
  | "light_limit"
  | "emission_limit";

export type Criterion = {
  id: string;
  kind: CriterionKind;
  required: boolean;
  label?: string | null;
  layerId?: string | null;
  sliceId?: string | null;
  min?: number | null;
  max?: number | null;
  classes?: number[] | null;
  amount?: number | null;
  materialName?: string | null;
  pollutant?: string | null;
  medium?: import("./pollutants").ReleaseMedium;
};

export type SiteAssumptions = {
  usableAreaM2?: number | null;
  connectedCapacityKw?: number | null;
  energyBudgetKwhPerDay?: number | null;
  waterAllocationM3PerDay?: number | null;
  note?: string | null;
};

export type DefinitionSnapshot = {
  schemaVersion: number;
  name: string;
  description: string;
  templateId?: string | null;
  templateVersion?: number | null;
  stats: BuildingStats;
  criteria: Criterion[];
};

export type BuildingDefinitionInput = {
  name: string;
  description: string;
  type: BuildingType;
  templateId?: string | null;
  templateVersion?: number | null;
  stats: BuildingStats;
  parameters: Record<string, ParamValue>;
  criteria: Criterion[];
};

export type BuildingDefinition = BuildingDefinitionInput & {
  id: string;
  schemaVersion: number;
  createdAt: string;
  updatedAt: string;
};

export type TemplateParam = {
  key: string;
  label: string;
  unit: string;
  kind: "number" | "select";
  options?: string[] | null;
  hint?: string | null;
};

export type BuildingTemplate = {
  id: string;
  version: number;
  type: BuildingType;
  category: BuildingCategory;
  label: string;
  description: string;
  producesPower: boolean;
  producesWater: boolean;
  parameters: TemplateParam[];
  defaults: BuildingStats;
  defaultProvenance?: Provenance | null;
  fieldHelp: Record<string, string>;
};

/** Real example building with cited figures (GET /api/building-presets). */
export type PresetSource = {
  id: string;
  title: string;
  publisher: string;
  url: string;
  year?: string | null;
  accessed?: string | null;
};

export type ReferenceSite = { name: string; latitude: number; longitude: number; country: string };

export type BuildingPreset = {
  id: string;
  name: string;
  type: BuildingType;
  description: string;
  headline: string;
  referenceSite: ReferenceSite;
  stats: BuildingStats;
  parameters: Record<string, ParamValue>;
  sources: PresetSource[];
  notes: string[];
};

/** MIME type used to drag a preset from the palette onto the map. */
export const PRESET_DRAG_TYPE = "application/x-newworlds-preset";

export type StressControls = {
  waterAvailability: number; // 0–1
  powerAvailability: number; // 0–1
  operatingDemand: number; // ≥ 0
  operatingPrices: number; // ≥ 0
};

export const NEUTRAL_STRESS: StressControls = {
  waterAvailability: 1,
  powerAvailability: 1,
  operatingDemand: 1,
  operatingPrices: 1,
};

export type BudgetKind = "power_capacity_kw" | "energy_kwh_per_day" | "water_m3_per_day";

export type BudgetScope = {
  kind: "scenario" | "region" | "radius";
  region?: "arizona" | "uk" | null;
  latitude?: number | null;
  longitude?: number | null;
  radiusKm?: number | null;
};

export type ResourceBudget = {
  id: string;
  label: string;
  kind: BudgetKind;
  amount?: number | null;
  scope: BudgetScope;
  contributingProjectIds: string[];
};

export type ScenarioAssumptions = {
  schemaVersion: number;
  periodDays: number;
  budgets: ResourceBudget[];
  stress: StressControls;
};

export const DEFAULT_ASSUMPTIONS: ScenarioAssumptions = {
  schemaVersion: 1,
  periodDays: 30,
  budgets: [],
  stress: NEUTRAL_STRESS,
};

// --- results ---------------------------------------------------------------------------------

export type Quantity = { value: number | null; unit: string; basis: string; missing: string[] };

export type MaterialTotal = { name: string; phase: "construction" | "operation"; quantity: Quantity };
export type EmissionTotal = { pollutant: string; medium?: import("./pollutants").ReleaseMedium; quantity: Quantity };

export type CostBreakdown = {
  currency: string | null;
  construction: Quantity;
  operatingFixed: Quantity;
  electricity: Quantity;
  water: Quantity;
  materials: Quantity;
  operatingKnownTotal: Quantity;
  missing: string[];
  operatingCostKind: "total" | "fixed";
  electricityPriceSource?: PriceSource | null;
  waterPriceSource?: PriceSource | null;
};

export type BuildingResult = {
  periodDays: number;
  operatingHours: Quantity;
  electricityDemand: Quantity;
  peakDemand: Quantity;
  electricityOutput: Quantity;
  electricityNet: Quantity;
  waterDemand: Quantity;
  waterOutput: Quantity;
  waterNet: Quantity;
  materials: MaterialTotal[];
  emissions: EmissionTotal[];
  light: Quantity;
  lightHours: Quantity;
  workerCapacity: Quantity;
  staffingRequired: Quantity;
  footprint: Quantity;
  costs: CostBreakdown;
  demandBasis: "direct" | "derived";
};

/** Checks generated automatically from what the site (cell + neighbouring cells) can provide. */
export type SiteCheckKind =
  | "site_land"
  | "site_water"
  | "site_power"
  | "site_grid_export"
  | "site_workforce"
  | "site_air"
  | "site_light"
  | "site_material";

export type CheckResult = {
  criterionId: string;
  kind: CriterionKind | SiteCheckKind;
  label: string;
  required: boolean;
  status: CheckStatus;
  actual: number | null;
  requiredValue: number | null;
  unit: string;
  period: string | null;
  source: string;
  explanation: string;
};

export type SuggestedPreset = { id: string; name: string; capacity: number; unit: string; count: number };

/** A building that could be placed alongside to cover a shortfall the site can't (power, water, export). */
export type SupportSuggestion = {
  resource: "power" | "water" | "grid_export";
  shortfall: number;
  unit: string;
  buildingType: BuildingType;
  reachKm: number;
  rings: number;
  title: string;
  explanation: string;
  presets: SuggestedPreset[];
  genericName: string;
  genericStats: BuildingStats;
};

export type Assessment = { state: AssessmentState; checks: CheckResult[]; summary: string; suggestions?: SupportSuggestion[] };

export type Bounds = { west: number; south: number; east: number; north: number };

export type AssessmentRequest = {
  scenarioId?: string | null;
  type: BuildingType;
  stats: BuildingStats;
  parameters: Record<string, ParamValue>;
  criteria: Criterion[];
  site?: SiteAssumptions;
  location?: { latitude: number; longitude: number };
  bounds?: Bounds;
  region?: "arizona" | "uk";
  excludeProjectId?: string | null;
  limit?: number;
};

/** How ideal a site is for the building type (FAO classes S1, S2, S3, N). Separate from the hard state. */
export type SuitabilityTier = "ideal" | "good" | "marginal" | "unsuitable";

/** One graded site factor in a building type's profile (e.g. soil nitrogen for a crop farm). */
export type SuitabilityFactor = {
  key: string;
  label: string;
  group: string;
  unit: string;
  weight: number;
  /** "Unsuitable" here makes the whole site unsuitable, whatever the other factors say. */
  constraint: boolean;
  /** Human text of the bands, e.g. "Ideal 6.0–7.5 · Good 5.5–8.0 · Marginal 5.0–8.5 · otherwise unsuitable". */
  bands: string;
  layerId: string | null;
  sliceId: string | null;
  source: string;
  why: string;
};

export type SuitabilityProfile = { id: string; label: string; method: string; factors: SuitabilityFactor[] };

export type FactorGrade = { key: string; tier: SuitabilityTier | null; value: number | null; display: string; explanation: string };

export type Suitability = {
  profile: SuitabilityProfile;
  tier: SuitabilityTier | null;
  score: number | null; // weighted mean of class points, 0–3
  coverage: number; // share of factor weight with data, 0–1
  limiting: string[]; // factor keys, worst first
  summary: string;
  factors: FactorGrade[]; // same order as profile.factors
};

/**
 * `tier`/`grades` are set when the building type has a suitability profile. `grades` holds one character
 * per profile factor, in profile order: "1" ideal, "2" good, "3" marginal, "4" unsuitable, "0" no data.
 */
export type CellState = { h3Id: string; state: AssessmentState; tier?: SuitabilityTier | null; grades?: string | null };
export type Candidate = {
  h3Id: string;
  latitude: number;
  longitude: number;
  assessment: Assessment;
  suitability?: Suitability | null;
};

export type PriceOfferStatus =
  | "available" // no price entered; the cell's price can be applied explicitly
  | "entered" // the user's own price is used (always wins)
  | "applied" // this location's price is in use
  | "applied_elsewhere" // a location default from another area / value is in use
  | "currency_mismatch" // costs in another currency: never converted, not offered
  | "not_used" // all-inclusive operating cost: unit prices are not added
  | "unavailable"; // no price for this cell in the dataset

/** The cell's average business price, offered as an explicit, labelled location default. */
export type LocationPriceOffer = {
  resource: PriceResource;
  unit: string; // e.g. "USD/kWh"
  price: PriceSource | null;
  status: PriceOfferStatus;
  message: string;
};

export type SiteResourcePart = { label: string; value: number | null; unit: string; text: string | null };

/** One resource the site can provide, estimated from prepared data (never typed in). */
export type SiteResource = {
  key: "land" | "water" | "power" | "workforce" | "air" | "light" | "materials";
  label: string;
  unit: string;
  available: number | null; // null = unknown here
  needed: number | null; // the building's own need, when its specs declare it
  reach: string;
  parts: SiteResourcePart[];
  note: string | null;
  /** Server-decided state when the numbers are not a simple "enough or not" (air, light, materials). */
  status?: "pass" | "fail" | "unknown" | "none" | "advisory" | null;
  /** Raw materials: they can be shipped, so this is shown for planning and never blocks a site. */
  advisory?: boolean;
};

export type SiteCapacity = {
  h3Id: string;
  resources: SiteResource[];
  neighbourCells: string[];
  rings: Record<string, number>;
  note: string;
};

export type LocationAssessment = {
  site?: SiteCapacity | null;
  latitude: number;
  longitude: number;
  h3Id: string;
  result: BuildingResult;
  assessment: Assessment;
  utilityPrices?: LocationPriceOffer[];
  suitability?: Suitability | null;
};

export type AreaAssessment = {
  cellCount: number;
  counts: Partial<Record<AssessmentState, number>>;
  cells: CellState[];
  candidates: Candidate[];
  result: BuildingResult;
  note: string;
  suitability?: SuitabilityProfile | null;
  tierCounts?: Partial<Record<SuitabilityTier | "unknown", number>> | null;
};

export type AssessmentResponse = {
  modelVersion: string;
  schemaVersion: number;
  periodDays: number;
  location?: LocationAssessment | null;
  area?: AreaAssessment | null;
};

export type BudgetResult = {
  id: string;
  label: string;
  kind: BudgetKind;
  unit: string;
  declaredSupply: Quantity;
  demand: Quantity;
  unmet: Quantity;
  projectIds: string[];
};

export type BuildingEvaluation = {
  projectId: string;
  name: string;
  type: BuildingType;
  result: BuildingResult;
  assessment: Assessment;
};

export type ScenarioTotals = {
  electricityDemand: Quantity;
  electricityOutput: Quantity;
  waterDemand: Quantity;
  waterOutput: Quantity;
  constructionCost: Quantity[];
  operatingCost: Quantity[];
  materials: MaterialTotal[];
  emissions: EmissionTotal[];
  light: Quantity;
  workerCapacity: Quantity;
  unknownBuildings: Record<string, string[]>;
};

export type ScenarioResult = { buildings: BuildingEvaluation[]; budgets: BudgetResult[]; totals: ScenarioTotals };

/** Preview overrides for unsaved controls; saved values are used for anything omitted. */
export type EvaluateRequest = { stress?: StressControls; periodDays?: number; budgets?: ResourceBudget[] };

export type ScenarioEvaluation = {
  modelVersion: string;
  schemaVersion: number;
  scenarioId: string;
  periodDays: number;
  stress: StressControls;
  inputsHash: string;
  unstressed: ScenarioResult;
  stressed: ScenarioResult;
  controlNotes: Record<string, string>;
};

export const STATE_LABEL: Record<AssessmentState, string> = {
  meets_criteria: "Buildable",
  fails_criteria: "Not buildable",
  insufficient_data: "Can't tell yet",
};

export const STATE_COLOUR: Record<AssessmentState, [number, number, number]> = {
  meets_criteria: [46, 160, 90],
  fails_criteria: [210, 64, 64],
  insufficient_data: [150, 150, 160],
};

export const TIER_ORDER: SuitabilityTier[] = ["ideal", "good", "marginal", "unsuitable"];

export const TIER_LABEL: Record<SuitabilityTier, string> = {
  ideal: "Ideal",
  good: "Good",
  marginal: "Marginal",
  unsuitable: "Unsuitable",
};

/** Green → yellow → orange; "not buildable" (a resource shortfall) keeps the state red above them. */
export const TIER_COLOUR: Record<SuitabilityTier, [number, number, number]> = {
  ideal: [22, 140, 74],
  good: [132, 196, 84],
  marginal: [238, 196, 64],
  unsuitable: [232, 124, 46],
};

/** `grades` character → tier (see `CellState.grades`). */
export const GRADE_TIER: Record<string, SuitabilityTier | null> = {
  "1": "ideal",
  "2": "good",
  "3": "marginal",
  "4": "unsuitable",
  "0": null,
};
