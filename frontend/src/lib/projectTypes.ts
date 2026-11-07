import type { ProjectType } from "./api";

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
];

export const PROJECT_TYPE_BY_ID = Object.fromEntries(PROJECT_TYPES.map((d) => [d.type, d])) as Record<
  ProjectType,
  ProjectTypeDef
>;
