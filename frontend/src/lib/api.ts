export type ProjectType = "data_centre" | "solar" | "greenhouse";
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
};

export const locateCell = (latitude: number, longitude: number, signal?: AbortSignal) =>
  request<CellInfo>(`/api/cells/locate?latitude=${latitude}&longitude=${longitude}`, { signal });
