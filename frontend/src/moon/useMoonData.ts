import { useCallback, useEffect, useRef, useState } from "react";
import type { SourceCredit } from "../lib/context";
import {
  isNotPrepared,
  moonApi,
  type GazetteerPlace,
  type KeepoutFeature,
  type MareFeature,
  type MissionFeature,
  type MoonManifest,
  type MoonSite,
} from "./api";
import { indexPlaces, type IndexedPlace } from "./geo";

/** Loading state of one reference layer. `notPrepared` = the server answered 503 (run the prepare script). */
export type LoadStatus = { loading: boolean; error: string | null; notPrepared: boolean };
const IDLE: LoadStatus = { loading: false, error: null, notPrepared: false };

type Key = "manifest" | "sites" | "missions" | "keepout" | "mare" | "places" | "sources";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * The Moon's prepared reference data. Sites, missions, keep-out rings and credits load at once; the
 * gazetteer (~9,000 names) loads on the first search and the mare outlines when first shown.
 */
export function useMoonData() {
  const [manifest, setManifest] = useState<MoonManifest | null>(null);
  const [sites, setSites] = useState<MoonSite[] | null>(null);
  const [missions, setMissions] = useState<MissionFeature[] | null>(null);
  const [keepout, setKeepout] = useState<KeepoutFeature[] | null>(null);
  const [mare, setMare] = useState<MareFeature[] | null>(null);
  const [places, setPlaces] = useState<IndexedPlace[] | null>(null);
  const [sources, setSources] = useState<SourceCredit[]>([]);
  const [status, setStatus] = useState<Record<Key, LoadStatus>>({
    manifest: IDLE,
    sites: IDLE,
    missions: IDLE,
    keepout: IDLE,
    mare: IDLE,
    places: IDLE,
    sources: IDLE,
  });
  const requested = useRef(new Set<Key>());
  const ctrl = useRef<AbortController | null>(null);

  const load = useCallback(<T,>(key: Key, fetcher: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void) => {
    if (requested.current.has(key)) return;
    requested.current.add(key);
    const signal = ctrl.current?.signal;
    if (!signal) return;
    setStatus((s) => ({ ...s, [key]: { loading: true, error: null, notPrepared: false } }));
    fetcher(signal)
      .then((value) => {
        apply(value);
        setStatus((s) => ({ ...s, [key]: IDLE }));
      })
      .catch((e) => {
        if (signal.aborted) return;
        requested.current.delete(key); // allow a retry
        setStatus((s) => ({ ...s, [key]: { loading: false, error: message(e), notPrepared: isNotPrepared(e) } }));
      });
  }, []);

  useEffect(() => {
    const c = new AbortController();
    ctrl.current = c;
    requested.current.clear();
    load("manifest", moonApi.manifest, setManifest);
    load("sources", moonApi.sources, setSources);
    load("sites", moonApi.sites, (fc) => setSites((fc.features ?? []).filter((f) => f.geometry?.type === "Point")));
    load("missions", moonApi.missions, (fc) => setMissions(fc.features ?? []));
    load("keepout", moonApi.keepout, (fc) => setKeepout(fc.features ?? []));
    return () => {
      c.abort();
      ctrl.current = null;
    };
  }, [load]);

  const ensurePlaces = useCallback(
    () => load("places", moonApi.places, (rows: GazetteerPlace[]) => setPlaces(indexPlaces(Array.isArray(rows) ? rows : []))),
    [load],
  );
  const ensureMare = useCallback(() => load("mare", moonApi.mare, (fc) => setMare(fc.features ?? [])), [load]);
  /** Retry everything that failed (e.g. after running the prepare script). */
  const retry = useCallback(() => {
    for (const key of ["manifest", "sources", "sites", "missions", "keepout"] as Key[]) requested.current.delete(key);
    load("manifest", moonApi.manifest, setManifest);
    load("sources", moonApi.sources, setSources);
    load("sites", moonApi.sites, (fc) => setSites((fc.features ?? []).filter((f) => f.geometry?.type === "Point")));
    load("missions", moonApi.missions, (fc) => setMissions(fc.features ?? []));
    load("keepout", moonApi.keepout, (fc) => setKeepout(fc.features ?? []));
  }, [load]);

  const notPrepared = status.manifest.notPrepared;
  return { manifest, sites, missions, keepout, mare, places, sources, status, notPrepared, ensurePlaces, ensureMare, retry };
}

export type MoonData = ReturnType<typeof useMoonData>;
