import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Project, type Scenario, type ScenarioSummary } from "../lib/api";
import {
  DEFAULT_BASE_SETTINGS,
  isMoonBuildingType,
  toParameters,
  valuesFromParameters,
  type BaseSettings,
  type MoonBuildingType,
  type MoonValues,
  type PlacedMoonBuilding,
} from "./buildings";

const WORLD_KEY = "newworlds:moonWorld";

/** What a Moon building is saved as: one project row, with its values as numeric parameters. */
export type MoonBuildingInput = { type: MoonBuildingType; name: string; latitude: number; longitude: number; values: MoonValues };

function readWorldId(): string | null {
  try {
    return localStorage.getItem(WORLD_KEY);
  } catch {
    return null;
  }
}

function rememberWorld(id: string | null) {
  try {
    if (id) localStorage.setItem(WORLD_KEY, id);
    else localStorage.removeItem(WORLD_KEY);
  } catch {
    // The choice still holds for this session.
  }
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Base settings live in the world's assumptions under `moonBase`; anything missing keeps its default. */
export function readSettings(world: Scenario | null): BaseSettings {
  const raw = (world?.assumptions as { moonBase?: Partial<BaseSettings> } | undefined)?.moonBase ?? {};
  return {
    transportCase: typeof raw.transportCase === "string" ? raw.transportCase : DEFAULT_BASE_SETTINGS.transportCase,
    nightHours: typeof raw.nightHours === "number" && Number.isFinite(raw.nightHours) ? raw.nightHours : null,
  };
}

export function toPlaced(p: Project): PlacedMoonBuilding | null {
  if (!isMoonBuildingType(p.type)) return null;
  return { id: p.id, type: p.type, name: p.name, latitude: p.latitude, longitude: p.longitude, values: valuesFromParameters(p.type, p.parameters) };
}

/** Moon worlds (bases) and their buildings, stored through the same API as Earth worlds. */
export function useMoonBase(active: boolean) {
  const [worlds, setWorlds] = useState<ScenarioSummary[] | null>(null);
  const [world, setWorld] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id: string) => {
    const s = await api.getScenario(id);
    setWorld(s);
    rememberWorld(s.id);
    return s;
  }, []);

  const refresh = useCallback(async (preferId?: string | null) => {
    const list = await api.listScenarios("moon");
    setWorlds(list);
    const id = preferId && list.some((w) => w.id === preferId) ? preferId : list[0]?.id;
    if (id) await load(id);
    else {
      setWorld(null);
      rememberWorld(null);
    }
    return list;
  }, [load]);

  // Load on first use of the Build workspace only: Explore needs no database.
  useEffect(() => {
    if (!active || worlds !== null || loading) return;
    setLoading(true);
    refresh(readWorldId())
      .catch((e) => setError(message(e)))
      .finally(() => setLoading(false));
  }, [active, worlds, loading, refresh]);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(message(e));
      return undefined;
    }
  }, []);

  const buildings = useMemo(
    () => (world?.projects ?? []).map(toPlaced).filter((b): b is PlacedMoonBuilding => b !== null),
    [world],
  );
  const settings = useMemo(() => readSettings(world), [world]);

  const replaceProject = (p: Project) =>
    setWorld((w) => (w && w.id === p.scenarioId ? { ...w, projects: w.projects.map((x) => (x.id === p.id ? p : x)) } : w));

  const payload = (input: MoonBuildingInput) => ({
    type: input.type as unknown as Project["type"],
    name: input.name.trim(),
    latitude: input.latitude,
    longitude: input.longitude,
    parameters: toParameters(input.values),
    definition: { name: input.name.trim(), templateId: input.type } as unknown as Project["definition"],
  });

  return {
    worlds,
    world,
    buildings,
    settings,
    error,
    loading,
    clearError: () => setError(null),
    switchWorld: (id: string) => run(() => load(id)),
    createWorld: (name: string) =>
      run(async () => {
        const s = await api.createScenario(name.trim(), "moon");
        await refresh(s.id);
        return s;
      }),
    renameWorld: (name: string) =>
      run(async () => {
        if (!world) return;
        const s = await api.renameScenario(world.id, name.trim());
        setWorld(s);
        setWorlds((list) => list?.map((w) => (w.id === s.id ? { ...w, name: s.name } : w)) ?? list);
      }),
    branchWorld: (name: string) =>
      run(async () => {
        if (!world) return;
        const s = await api.branchScenario(world.id, name.trim());
        await refresh(s.id);
      }),
    deleteWorld: () =>
      run(async () => {
        if (!world) return;
        await api.deleteScenario(world.id);
        await refresh(null);
      }),
    place: (input: MoonBuildingInput) =>
      run(async () => {
        if (!world) throw new Error("Choose or start a Moon base first.");
        const p = await api.createProject(world.id, payload(input));
        setWorld((w) => (w && w.id === p.scenarioId ? { ...w, projects: [...w.projects, p] } : w));
        setWorlds((list) => list?.map((w) => (w.id === p.scenarioId ? { ...w, projectCount: w.projectCount + 1 } : w)) ?? list);
        return p;
      }),
    update: (id: string, input: MoonBuildingInput) =>
      run(async () => {
        const p = await api.updateProject(id, payload(input));
        replaceProject(p);
        return p;
      }),
    remove: (id: string) =>
      run(async () => {
        await api.deleteProject(id);
        setWorld((w) => (w ? { ...w, projects: w.projects.filter((x) => x.id !== id) } : w));
        setWorlds((list) => list?.map((w) => (w.id === world?.id ? { ...w, projectCount: Math.max(0, w.projectCount - 1) } : w)) ?? list);
        return true;
      }),
    saveSettings: (patch: Partial<BaseSettings>) =>
      run(async () => {
        if (!world) return;
        const next = { ...settings, ...patch };
        // Optimistic: the summary updates at once; the saved world replaces it when the server answers.
        setWorld((w) => (w ? { ...w, assumptions: { ...w.assumptions, moonBase: next } } : w));
        const s = await api.patchScenarioAssumptions(world.id, { moonBase: next });
        setWorld((w) => (w && w.id === s.id ? s : w));
      }),
  };
}

export type MoonBase = ReturnType<typeof useMoonBase>;
