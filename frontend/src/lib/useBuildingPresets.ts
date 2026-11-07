import { useEffect, useState } from "react";
import { api } from "./api";
import type { BuildingPreset } from "./buildings";

// One request per page load; a failure is retried on the next mount.
let cache: Promise<BuildingPreset[]> | null = null;

/** Real example buildings. `error` is set if they can't be loaded; nothing else depends on them. */
export function useBuildingPresets() {
  const [presets, setPresets] = useState<BuildingPreset[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    cache ??= api.listPresets().catch((e) => {
      cache = null;
      throw e;
    });
    cache.then((p) => live && setPresets(p)).catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, []);

  return { presets: presets ?? [], loaded: presets !== null, error };
}
