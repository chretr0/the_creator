/**
 * Switches on the map layers about what the building in the Build workspace needs, and off again
 * when the need goes away or the workspace closes. Decisions come from the pure functions in
 * buildLayers.ts; this hook only applies them to App's layer state.
 *
 * Usage (App):
 *   const isAvailable = useMemo(() => layerAvailability(manifest?.layers, data.manifest), [manifest, data.manifest]);
 *   const buildLayers = useBuildLayers({ active: workspace === "build", needs, infraVisible: visibleLayers,
 *     setInfraVisible: setVisibleLayers, featureEnabled: data.enabled, setFeatureEnabled: data.setEnabled, isAvailable });
 *   <BuildLayerChips entries={buildLayers.entries} onToggle={buildLayers.toggle} />
 */
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  availableNeeds,
  EMPTY_OWNERSHIP,
  effectiveOn,
  layerEntries,
  parseRefKey,
  reconcileLayers,
  refKey,
  toggleLayers,
  type BuildLayerEntry,
  type LayerNeed,
  type LayerOwner,
  type LayerRef,
  type OwnershipResult,
  type OwnershipState,
} from "./buildLayers";
import { INFRA_LAYER_IDS, type InfraLayerId } from "./infrastructure";

export type UseBuildLayersOptions = {
  /** The Build workspace is open. */
  active: boolean;
  needs: LayerNeed[];
  infraVisible: Record<InfraLayerId, boolean>;
  setInfraVisible: Dispatch<SetStateAction<Record<InfraLayerId, boolean>>>;
  featureEnabled: Record<string, boolean>;
  setFeatureEnabled: Dispatch<SetStateAction<Record<string, boolean>>>;
  isAvailable: (ref: LayerRef) => boolean;
};

/** Set some keys of a boolean record; the same object when nothing changes (so React bails out). */
function patch<K extends string>(changes: [K, boolean][]): (prev: Record<K, boolean>) => Record<K, boolean> {
  return (prev) => {
    let next = prev;
    for (const [k, on] of changes) {
      if (!!prev[k] === on) continue;
      if (next === prev) next = { ...prev };
      next[k] = on;
    }
    return next;
  };
}

const ownersSig = (owners: Readonly<Record<string, LayerOwner>>) =>
  Object.keys(owners)
    .sort()
    .map((k) => `${k}=${owners[k]}`)
    .join(",");

export function useBuildLayers(opts: UseBuildLayersOptions): {
  entries: BuildLayerEntry[];
  toggle: (key: string) => void;
} {
  const latest = useRef(opts);
  latest.current = opts;
  const state = useRef<OwnershipState>(EMPTY_OWNERSHIP);
  // Mirror of the owners for rendering (the ref is the source of truth for decisions).
  const [owners, setOwners] = useState<Readonly<Record<string, LayerOwner>>>({});

  const shown = opts.active ? availableNeeds(opts.needs, opts.isAvailable) : [];
  // Effects are keyed on strings, so a new `needs` array with equal content changes nothing.
  const neededSig = [...new Set(shown.flatMap((n) => n.layers.map(refKey)))].sort().join("|");
  const visibleSig =
    INFRA_LAYER_IDS.map((id) => (opts.infraVisible[id] ? "1" : "0")).join("") +
    "|" +
    Object.keys(opts.featureEnabled)
      .filter((k) => opts.featureEnabled[k])
      .sort()
      .join(",");

  const isOn = useCallback((key: string) => {
    const ref = parseRefKey(key);
    if (!ref) return false;
    const o = latest.current;
    return ref.kind === "infra" ? !!o.infraVisible[ref.id] : !!o.featureEnabled[ref.id];
  }, []);

  const commit = useCallback((res: OwnershipResult) => {
    state.current = res.state;
    const infra: [InfraLayerId, boolean][] = [];
    const features: [string, boolean][] = [];
    for (const [key, on] of Object.entries(res.changes)) {
      const ref = parseRefKey(key);
      if (ref?.kind === "infra") infra.push([ref.id, on]);
      else if (ref) features.push([ref.id, on]);
    }
    if (infra.length) latest.current.setInfraVisible(patch(infra));
    if (features.length) latest.current.setFeatureEnabled(patch(features));
    const next = res.state.owners;
    setOwners((prev) => (ownersSig(prev) === ownersSig(next) ? prev : next));
  }, []);

  useEffect(() => {
    commit(reconcileLayers(state.current, neededSig ? neededSig.split("|") : [], isOn));
  }, [neededSig, visibleSig, commit, isOn]);

  // Unmounting counts as leaving the workspace. (Under StrictMode the remount switches them back on.)
  useEffect(
    () => () => {
      commit(reconcileLayers(state.current, [], isOn));
    },
    [commit, isOn],
  );

  const toggle = useCallback(
    (key: string) => {
      const o = latest.current;
      if (!o.active) return;
      const need = availableNeeds(o.needs, o.isAvailable).find((n) => n.key === key);
      if (!need) return;
      const keys = need.layers.map(refKey);
      const allOn = keys.every((k) => effectiveOn(state.current, k, isOn));
      commit(toggleLayers(state.current, keys, !allOn, isOn));
    },
    [commit, isOn],
  );

  return { entries: layerEntries(shown, owners, isOn), toggle };
}
