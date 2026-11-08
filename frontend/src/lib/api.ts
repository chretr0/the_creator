import type { TimelineData } from "./timeline";
import type {
  AssessmentRequest,
  AssessmentResponse,
  BuildingDefinition,
  BuildingDefinitionInput,
  BuildingPreset,
  BuildingTemplate,
  BuildingType,
  DefinitionSnapshot,
  ScenarioAssumptions,
  ScenarioEvaluation,
  SiteAssumptions,
  EvaluateRequest,
} from "./buildings";

export type ProjectType = BuildingType;
export type ParamValue = number | string | boolean;

export type Project = {
  id: string;
  scenarioId: string;
  type: ProjectType;
  name: string;
  latitude: number;
  longitude: number;
  h3Id: string;
  h3Resolution: number;
  parameters: Record<string, ParamValue>;
  /** Snapshot of the definition used to place it (legacy projects are adapted server-side). */
  definition: DefinitionSnapshot;
  sourceDefinitionId: string | null;
  site: SiteAssumptions;
  createdAt: string;
  updatedAt: string;
};

export type ScenarioSummary = {
  id: string;
  name: string;
  parentScenarioId: string | null;
  baselineRevision: string;
  modelVersion: string;
  projectCount: number;
  createdAt: string;
  updatedAt: string;
};

export type Scenario = Omit<ScenarioSummary, "projectCount"> & {
  assumptions: Record<string, unknown>;
  projects: Project[];
};

export type CellInfo = {
  h3Id: string;
  resolution: number;
  isPentagon: boolean;
  centre: { latitude: number; longitude: number };
  boundary: [number, number][];
  areaKm2: number;
  neighbours: string[];
  parent: string | null;
  simulationCell: string | null;
  observations: unknown[];
};

export type ProjectInput = {
  type: ProjectType;
  name?: string;
  latitude: number;
  longitude: number;
  parameters?: Record<string, ParamValue>;
  definition?: DefinitionSnapshot;
  sourceDefinitionId?: string | null;
  site?: SiteAssumptions;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  cell: (h3Id: string, signal?: AbortSignal) => request<CellInfo>(`/api/cells/${h3Id}`, { signal }),

  listScenarios: () => request<ScenarioSummary[]>("/api/scenarios"),
  timeline: (id: string, signal?: AbortSignal) => request<TimelineData>(`/api/scenarios/${id}/timeline`, { signal }),
  getScenario: (id: string) => request<Scenario>(`/api/scenarios/${id}`),
  createScenario: (name: string) => request<Scenario>("/api/scenarios", { method: "POST", json: { name } }),
  branchScenario: (id: string, name: string) =>
    request<Scenario>(`/api/scenarios/${id}/branch`, { method: "POST", json: { name } }),
  renameScenario: (id: string, name: string) =>
    request<Scenario>(`/api/scenarios/${id}`, { method: "PATCH", json: { name } }),
  deleteScenario: (id: string) => request<void>(`/api/scenarios/${id}`, { method: "DELETE" }),

  createProject: (scenarioId: string, input: ProjectInput) =>
    request<Project>(`/api/scenarios/${scenarioId}/projects`, { method: "POST", json: input }),
  updateProject: (id: string, patch: Partial<ProjectInput>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", json: patch }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  // --- building system ---
  listTemplates: (signal?: AbortSignal) => request<BuildingTemplate[]>("/api/building-templates", { signal }),
  /** Real example buildings with cited figures. */
  listPresets: (signal?: AbortSignal) => request<BuildingPreset[]>("/api/building-presets", { signal }),
  listDefinitions: (signal?: AbortSignal) => request<BuildingDefinition[]>("/api/building-definitions", { signal }),
  getDefinition: (id: string) => request<BuildingDefinition>(`/api/building-definitions/${id}`),
  createDefinition: (input: BuildingDefinitionInput) =>
    request<BuildingDefinition>("/api/building-definitions", { method: "POST", json: input }),
  updateDefinition: (id: string, patch: Partial<BuildingDefinitionInput>) =>
    request<BuildingDefinition>(`/api/building-definitions/${id}`, { method: "PATCH", json: patch }),
  deleteDefinition: (id: string) => request<void>(`/api/building-definitions/${id}`, { method: "DELETE" }),
  /** Read-only: nothing is saved. Exactly one of location / bounds / region. */
  assess: (req: AssessmentRequest, signal?: AbortSignal) =>
    request<AssessmentResponse>("/api/building-assessments", { method: "POST", json: req, signal }),
  updateScenarioAssumptions: (id: string, assumptions: ScenarioAssumptions) =>
    request<Scenario>(`/api/scenarios/${id}`, { method: "PATCH", json: { assumptions } }),
  /** Overrides preview unsaved controls; saved values are used for anything omitted. */
  evaluateScenario: (id: string, overrides: EvaluateRequest = {}, signal?: AbortSignal) =>
    request<ScenarioEvaluation>(`/api/scenarios/${id}/evaluate`, { method: "POST", json: overrides, signal }),
};

export const locateCell = (latitude: number, longitude: number, signal?: AbortSignal) =>
  request<CellInfo>(`/api/cells/locate?latitude=${latitude}&longitude=${longitude}`, { signal });

/** State update for a scenario returned by a save: apply it only if that scenario is still shown. */
export const keepIfShown = (current: Scenario | null, saved: Scenario): Scenario | null =>
  current && current.id === saved.id ? saved : current;
