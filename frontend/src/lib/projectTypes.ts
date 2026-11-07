import type { ProjectType } from "./api";
import type { BuildingTemplate } from "./buildings";

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
  colour: [number, number, number];
  params: ParamDef[];
};

export const PROJECT_TYPES: ProjectTypeDef[] = [
  {
    type: "data_centre",
    label: "Data centre",
    colour: [124, 92, 255],
    params: [
      { key: "itPowerKw", label: "IT power", unit: "kW", kind: "number" },
      { key: "loadFraction", label: "Load fraction", unit: "0–1", kind: "number" },
      { key: "pue", label: "PUE", unit: "ratio", kind: "number", hint: "facility energy ÷ IT energy" },
      { key: "wueLPerKwh", label: "WUE", unit: "L/kWh", kind: "number" },
      { key: "wueBasis", label: "WUE basis", unit: "", kind: "select", options: ["it_energy", "facility_energy"] },
      { key: "heatRecoveryFraction", label: "Heat recovery fraction", unit: "0–1", kind: "number" },
    ],
  },
  {
    type: "solar",
    label: "Solar generation",
    colour: [245, 176, 33],
    params: [
      { key: "capacityKwp", label: "Peak capacity", unit: "kWp", kind: "number" },
      { key: "landAreaM2", label: "Occupied land", unit: "m²", kind: "number" },
      { key: "performanceRatio", label: "Performance ratio", unit: "0–1", kind: "number" },
    ],
  },
  {
    type: "greenhouse",
    label: "Greenhouse",
    colour: [46, 184, 114],
    params: [
      { key: "floorAreaM2", label: "Floor area", unit: "m²", kind: "number" },
      { key: "heatDemandKwhPerYear", label: "Heat demand", unit: "kWh/yr", kind: "number" },
      { key: "minSupplyTempC", label: "Min. supply temperature", unit: "°C", kind: "number" },
    ],
  },
  { type: "power_station", label: "Power station", colour: [214, 69, 160], params: [] },
  { type: "water_plant", label: "Water plant", colour: [30, 136, 229], params: [] },
  { type: "custom", label: "Custom building", colour: [96, 108, 128], params: [] },
];

export const PROJECT_TYPE_BY_ID = Object.fromEntries(PROJECT_TYPES.map((d) => [d.type, d])) as Record<
  ProjectType,
  ProjectTypeDef
>;

const FALLBACK_DESCRIPTION: Record<ProjectType, string> = {
  data_centre: "Computing facility. Demand can come from IT power × load × PUE, or be entered directly.",
  solar: "Solar generation. Output must be declared; peak capacity alone is not generated power.",
  greenhouse: "Greenhouse. Floor area is separate from the ground footprint.",
  power_station: "Generates electricity. Describe the technology; output and own use are separate fields.",
  water_plant: "Produces or treats water. Usable output, water input and electricity use are separate.",
  custom: "Define your own statistics.",
};

/**
 * Local stand-in used only when GET /api/building-templates is unavailable, so the forms still
 * render. It carries no numeric defaults.
 */
export function fallbackTemplate(type: ProjectType): BuildingTemplate {
  const def = PROJECT_TYPE_BY_ID[type];
  return {
    id: type,
    version: 0,
    type,
    label: def.label,
    description: FALLBACK_DESCRIPTION[type],
    producesPower: type === "power_station" || type === "solar",
    producesWater: type === "water_plant",
    parameters: def.params.map((p) => ({ ...p, options: p.options ?? null, hint: p.hint ?? null })),
    defaults: {},
    defaultProvenance: null,
    fieldHelp: {},
  };
}

export const typeLabel = (type: string) => PROJECT_TYPE_BY_ID[type as ProjectType]?.label ?? type;
export const typeColour = (type: string): [number, number, number] =>
  PROJECT_TYPE_BY_ID[type as ProjectType]?.colour ?? [96, 108, 128];
