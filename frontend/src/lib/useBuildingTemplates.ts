import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { BuildingTemplate, BuildingType } from "./buildings";
import { BUILDING_TYPES_ORDER } from "./buildingForm";
import { fallbackTemplate } from "./projectTypes";

// One request per page load, shared by the Build tab and the project editor.
let cache: Promise<BuildingTemplate[]> | null = null;

/** Predefined templates from the server; falls back to local field definitions if unavailable. */
export function useBuildingTemplates() {
  const [loaded, setLoaded] = useState<BuildingTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    cache ??= api.listTemplates().catch((e) => {
      cache = null;
      throw e;
    });
    cache.then((t) => live && setLoaded(t)).catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, []);

  const templates = useMemo(() => {
    const byType = new Map((loaded ?? []).map((t) => [t.type, t]));
    const ordered = BUILDING_TYPES_ORDER.map((type) => byType.get(type) ?? fallbackTemplate(type));
    const extra = (loaded ?? []).filter((t) => !BUILDING_TYPES_ORDER.includes(t.type) || ordered.every((o) => o.id !== t.id));
    return [...ordered, ...extra];
  }, [loaded]);

  const templateFor = useCallback(
    (type: BuildingType, templateId?: string | null) =>
      templates.find((t) => templateId && t.id === templateId) ?? templates.find((t) => t.type === type) ?? fallbackTemplate(type),
    [templates],
  );

  return { templates, error, templateFor, fromServer: loaded !== null };
}
