import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WorldMap, { type MapFocus, type MapView, type Picked } from "./components/WorldMap";
import ContextPanel, { ImageryPanel } from "./components/ContextPanel";
import ContextInspector from "./components/ContextInspector";
import SearchPanel from "./components/SearchPanel";
import PlaceSearch from "./components/PlaceSearch";
import { CONTEXT_LAYER_IDS, useContextData } from "./lib/useContextData";
import type { CablePath, Earthquake, Fire, LandingPoint, PowerFeature } from "./lib/context";
import {
  fromEarthquakes,
  fromFacilities,
  fromFires,
  fromLanding,
  fromPower,
  isFacilityDataset,
  type Dataset,
  type Query,
  type QueryRecord,
} from "./lib/query";
import CellInspector, { type CellSelection } from "./components/CellInspector";
import ProjectEditor from "./components/ProjectEditor";
import ScenarioPanel, { ScenarioSelect } from "./components/ScenarioPanel";
import BuildPanel, { type BuildTarget, type PresetRequest, type BuildStage } from "./components/BuildPanel";
import StressPanel from "./components/StressPanel";
import SuitabilityLegend from "./components/SuitabilityLegend";
import BuildLayerChips from "./components/BuildLayerChips";
import { layerAvailability, loadingByNeed, type LayerNeed } from "./lib/buildLayers";
import { useBuildLayers } from "./lib/useBuildLayers";
import type { CellState } from "./lib/buildings";
import { cellColour, cellLineColour, cellTooltip, effectiveColourBy, factorIndex, STALE_FILL, type ColourBy, type ScreenedArea } from "./lib/suitability";
import LayerPanel from "./components/LayerPanel";
import FacilityInspector from "./components/FacilityInspector";
import Icon from "./components/Icon";
import { useTheme } from "./lib/useTheme";
import { BackLink, PanelTabs } from "./components/PanelNavigation";
import DataPanel, { RecordsPanel, PreparedScenes, LayerLegend } from "./components/DataPanel";
import { FieldList } from "./components/BaselineBlock";
import CreditsPanel from "./components/CreditsPanel";
import { useDataLayers } from "./lib/useDataLayers";
import { mergeAssumptions } from "./lib/buildingForm";
import {
  COLOURED_COMPANIES,
  INFRA_LAYER_IDS,
  LAYER_META,
  layerColour,
  loadInfraLayer,
  loadInfraManifest,
  rankCompanies,
  ratedItLoadKw,
  facilityTitle,
  formatKw,
  UNKNOWN_OWNER,
  type Facility,
  type InfraLayerId,
  type InfraManifest,
} from "./lib/infrastructure";
import { api, keepIfShown, type Project, type ProjectInput, type Scenario, type ScenarioSummary } from "./lib/api";
import { cellContains, displayCell, normaliseLongitude, simulationCell } from "./lib/h3grid";

type ExploreSection = "library" | "environment" | "infrastructure" | "records" | "context" | "imagery" | "sources";
const EXPLORE_SECTIONS = [
  { value: "environment", label: "Environment", icon: "sun", detail: "Climate, water, land & more" },
  { value: "infrastructure", label: "Infrastructure", icon: "building", detail: "Energy, grid, datacentres & transport" },
  { value: "records", label: "Mapped records", icon: "pin", detail: "Features, filters & datasets" },
  { value: "context", label: "Context & hazards", icon: "globe", detail: "Boundaries, fires & quakes" },
  { value: "imagery", label: "Satellite imagery", icon: "layers", detail: "Products, dates & prepared scenes" },
  { value: "sources", label: "Sources & licences", icon: "info", detail: "Provenance & data limitations" },
] as const;

type Tab = "layers" | "search" | "build" | "projects";

/** "move" = choosing a new location for an existing project. */
type Mode = { kind: "inspect" } | { kind: "move"; projectId: string };

const LAST_SCENARIO_KEY = "newworlds:lastScenario";
const HEX_OUTLINES_KEY = "newworlds:hexOutlines";

function readHexOutlines(): boolean {
  try {
    return localStorage.getItem(HEX_OUTLINES_KEY) !== "false";
  } catch {
    return true;
  }
}

function readLastScenario(): string | null {
  try {
    return localStorage.getItem(LAST_SCENARIO_KEY);
  } catch {
    return null;
  }
}

// Shared across StrictMode's double-invoked effects so the first scenario is only created once.
let bootstrap: Promise<ScenarioSummary[]> | null = null;
function loadOrCreateScenarios(): Promise<ScenarioSummary[]> {
  bootstrap ??= (async () => {
    const list = await api.listScenarios();
    if (list.length > 0) return list;
    await api.createScenario("World A");
    return api.listScenarios();
  })().finally(() => {
    bootstrap = null;
  });
  return bootstrap;
}

function writeLastScenario(id: string) {
  try {
    localStorage.setItem(LAST_SCENARIO_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "inspect" });
  const [selection, setSelection] = useState<CellSelection | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [grid, setGrid] = useState<{ resolution: number; count: number; overview: boolean; cells: string[] }>({
    resolution: 0,
    count: 0,
    overview: true,
    cells: [],
  });
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<InfraManifest | null>(null);
  const [infraData, setInfraData] = useState<Partial<Record<InfraLayerId, Facility[]>>>({});
  const [infraStatus, setInfraStatus] = useState<Partial<Record<InfraLayerId, { loading: boolean; error: string | null }>>>({});
  const [infraError, setInfraError] = useState<string | null>(null);
  const [visibleLayers, setVisibleLayers] = useState<Record<InfraLayerId, boolean>>({
    datacenters: true,
    power_plants: false,
    dams: true,
    substations: false,
    transmission_lines: false,
    airports: false,
    ports: false,
  });
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null);
  const [tilted, setTilted] = useState(false);
  const [showHexOutlines, setShowHexOutlines] = useState(readHexOutlines);
  useEffect(() => {
    try {
      localStorage.setItem(HEX_OUTLINES_KEY, String(showHexOutlines));
    } catch {
      // Keep the control usable when browser storage is unavailable.
    }
  }, [showHexOutlines]);
  const [view, setView] = useState<MapView | null>(null);
  const [sideTab, setSideTab] = useState<Tab>("layers");
  const [buildStage, setBuildStage] = useState<BuildStage>("building");
  const [buildMapVisible, setBuildMapVisible] = useState(false);
  const [exploreSection, setExploreSection] = useState<ExploreSection>("library");
  const [scenarioSection, setScenarioSection] = useState<"overview" | "resources" | "stress">("overview");
  const [detailView, setDetailView] = useState<"record" | "location">("record");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const sideBodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    sideBodyRef.current?.scrollTo({ top: 0 });
  }, [sideTab, exploreSection, scenarioSection]);
  const [stressHost, setStressHost] = useState<HTMLDivElement | null>(null);
  const [buildSiteHost, setBuildSiteHost] = useState<HTMLElement | null>(null);

  function navigate(tab: Tab) {
    setSideTab(tab);
    setInspectorOpen(false);
    setBuildMapVisible(false);
    sideBodyRef.current?.scrollTo({ top: 0 });
  }

  const [query, setQuery] = useState<Query>({ dataset: "datacenters", sort: "metric" });
  const [buildTarget, setBuildTarget] = useState<BuildTarget | null>(null);
  const [presetRequest, setPresetRequest] = useState<PresetRequest | null>(null);
  const changeBuildStage = useCallback((stage: BuildStage) => {
    setBuildStage(stage);
    setBuildMapVisible(false);
    setInspectorOpen(false);
    setMode({ kind: "inspect" });
  }, []);
  // Placing never changes the wizard step: the user defines and places at the same time.
  const updateBuildTarget = useCallback((target: BuildTarget | null) => {
    setBuildTarget(target);
    if (target) setInspectorOpen(false);
  }, []);
  const [screened, setScreened] = useState<ScreenedArea | null>(null);
  /** The screening overlay's colouring: the overall grade or one suitability factor. */
  const [colourBy, setColourBy] = useState<ColourBy>("overall");
  const assessmentCells = screened?.cells ?? null;
  const stale = !!screened?.stale;
  const assessmentStyle = useMemo(() => {
    const profile = screened?.profile ?? null;
    const by = effectiveColourBy(profile, colourBy);
    if (stale) {
      return {
        key: "stale",
        fill: () => STALE_FILL,
        line: () => STALE_FILL,
        tooltip: () => "Out of date: this shows an earlier version of the building",
      };
    }
    return {
      key: `${profile?.id ?? "-"}:${by}`,
      fill: (c: CellState) => cellColour(c, profile, by),
      line: (c: CellState) => cellLineColour(c, profile, by),
      tooltip: (c: CellState) => cellTooltip(c, profile, by),
    };
  }, [screened?.profile, colourBy, stale]);
  // When a new profile is drawn, a factor it doesn't grade falls back to the overall grade. Keyed on the
  // profile only: a factor picked in the site panel while the old map is still shown must survive.
  const drawnProfile = screened && !screened.stale ? (screened.profile ?? null) : undefined;
  const drawnProfileId = drawnProfile === undefined ? undefined : (drawnProfile?.id ?? null);
  useEffect(() => {
    if (drawnProfile === undefined) return;
    setColourBy((by) => (by !== "overall" && factorIndex(drawnProfile, by) < 0 ? "overall" : by));
    // drawnProfileId identifies drawnProfile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawnProfileId]);
  /** The profile the map is coloured by, so the site panel only marks its factor buttons for that one. */
  const mapProfileId = screened && !screened.stale ? (screened.profile?.id ?? null) : null;
  const [buildMapStatus, setBuildMapStatus] = useState<{ note: string | null; loading: boolean }>({ note: null, loading: false });
  const ctx = useContextData(view, { country: query.country, admin1: query.admin1 });
  const data = useDataLayers(view, grid.cells);
  // Map layers about what the building in the Build tab needs: switched on there, off again on leaving.
  const [buildNeeds, setBuildNeeds] = useState<LayerNeed[]>([]);
  const layerAvailable = useMemo(() => layerAvailability(manifest?.layers, data.manifest), [manifest, data.manifest]);
  const buildLayers = useBuildLayers({
    active: sideTab === "build",
    needs: buildNeeds,
    infraVisible: visibleLayers,
    setInfraVisible: setVisibleLayers,
    featureEnabled: data.enabled,
    setFeatureEnabled: data.setEnabled,
    isAvailable: layerAvailable,
  });
  // The build overlay column's bottom edge (px from the map top), so the floating site card in the
  // narrower layouts can stop below it instead of covering it.
  const [buildStack, setBuildStack] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!buildStack) return;
    const workspaceEl = buildStack.closest<HTMLElement>(".workspace");
    const update = () => workspaceEl?.style.setProperty("--build-stack-bottom", `${Math.round(buildStack.offsetTop + buildStack.offsetHeight)}px`);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(buildStack);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
      workspaceEl?.style.removeProperty("--build-stack-bottom");
    };
  }, [buildStack]);
  const buildLayerLoading = loadingByNeed(buildLayers.entries, (r) =>
    r.kind === "infra" ? !!infraStatus[r.id]?.loading : !!data.featureStatus[r.id]?.loading,
  );

  const report = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);

  // What is shown right now, for async results that finish after the user switched scenarios.
  const shown = useRef<{ scenarioId: string | null; scenarios: ScenarioSummary[] }>({ scenarioId: null, scenarios: [] });
  useEffect(() => {
    shown.current = { scenarioId: scenario?.id ?? null, scenarios };
  }, [scenario?.id, scenarios]);
  /** True if the result belongs to the scenario on screen; otherwise says where it went. */
  const isShown = useCallback((scenarioId: string, what: string) => {
    if (shown.current.scenarioId === scenarioId) return true;
    const name = shown.current.scenarios.find((x) => x.id === scenarioId)?.name ?? "another scenario";
    setError(`${what} was saved in "${name}", not in the scenario shown now.`);
    return false;
  }, []);

  const refreshList = useCallback(async () => setScenarios(await api.listScenarios()), []);

  const loadScenario = useCallback(
    async (id: string) => {
      const s = await api.getScenario(id);
      setScenario(s);
      setSelectedProjectId(null);
      setMode({ kind: "inspect" });
      // A preview or screening result belongs to the scenario it was made for.
      setBuildTarget(null);
      setScreened(null);
      writeLastScenario(id);
    },
    [],
  );

  // Initial load: restore the last scenario or create a first one.
  useEffect(() => {
    (async () => {
      const list = await loadOrCreateScenarios();
      setScenarios(list);
      const last = readLastScenario();
      await loadScenario(list.find((s) => s.id === last)?.id ?? list[0].id);
    })().catch((e) => report(`Backend unavailable: ${e instanceof Error ? e.message : e}`));
  }, [loadScenario, report]);

  useEffect(() => {
    const ctrl = new AbortController();
    loadInfraManifest(ctrl.signal)
      .then(setManifest)
      .catch((e) => {
        if (!ctrl.signal.aborted) setInfraError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  // Each layer is fetched the first time it is shown on the map or searched (some are tens of MB).
  const infraRequested = useRef(new Set<InfraLayerId>());
  const ensureInfraLayer = useCallback(
    (id: InfraLayerId) => {
      const entry = manifest?.layers.find((l) => l.id === id);
      if (!entry || entry.available === false || infraRequested.current.has(id)) return;
      infraRequested.current.add(id);
      setInfraStatus((st) => ({ ...st, [id]: { loading: true, error: null } }));
      loadInfraLayer(id)
        .then((features) => {
          setInfraData((d) => ({ ...d, [id]: features }));
          setInfraStatus((st) => ({ ...st, [id]: { loading: false, error: null } }));
        })
        .catch((e) => {
          infraRequested.current.delete(id);
          setInfraStatus((st) => ({ ...st, [id]: { loading: false, error: e instanceof Error ? e.message : String(e) } }));
        });
    },
    [manifest],
  );
  useEffect(() => {
    for (const id of INFRA_LAYER_IDS) if (visibleLayers[id]) ensureInfraLayer(id);
  }, [visibleLayers, ensureInfraLayer]);
  const allFacilities = useMemo(() => INFRA_LAYER_IDS.flatMap((id) => infraData[id] ?? []), [infraData]);

  const companies = useMemo(() => rankCompanies(allFacilities), [allFacilities]);
  const facilityColour = useMemo(() => {
    const top = new Map(companies.slice(0, COLOURED_COMPANIES).map((c) => [c.key, c.colour]));
    return (f: Facility): [number, number, number] => {
      const p = f.properties;
      if (p.layer !== "datacenters") return layerColour(p);
      if (!p.operator) return UNKNOWN_OWNER;
      return (p.companyKey && top.get(p.companyKey)) || LAYER_META.datacenters.colour;
    };
  }, [companies]);
  const facilities = useMemo(
    () =>
      allFacilities.filter(
        (f) => visibleLayers[f.properties.layer] && (!companyFilter || f.properties.companyKey === companyFilter),
      ),
    [allFacilities, visibleLayers, companyFilter],
  );
  const selectedFacility = allFacilities.find((f) => f.id === selectedFacilityId) ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.defaultPrevented || (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key === "Escape") {
        setBuildMapVisible(false);
        setMode({ kind: "inspect" });
        if (sideTab === "build") updateBuildTarget(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sideTab, updateBuildTarget]);

  const projects = scenario?.projects ?? [];
  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const projectsInCell = useMemo(
    () => (selection ? projects.filter((p) => cellContains(selection.h3Id, p.h3Id)) : []),
    [projects, selection],
  );

  const replaceProject = (p: Project) =>
    setScenario((s) => (s ? { ...s, projects: s.projects.map((x) => (x.id === p.id ? p : x)) } : s));

  const selectProject = (p: Project) => {
    setBuildMapVisible(false);
    setSelectedFacilityId(null);
    ctx.setSelection(null);
    data.setPicked(null);
    setSelectedProjectId(p.id);
    setInspectorOpen(true);
    setSelection({ h3Id: p.h3Id, latitude: p.latitude, longitude: p.longitude });
  };

  async function handleMapClick(latitude: number, rawLongitude: number, picked: Picked | null) {
    const pickedProjectId = picked?.layerId === "projects" ? (picked.object as Project).id : null;
    const pickedFacility =
      picked?.layerId === "infra-points" || picked?.layerId === "infra-footprints" ? (picked.object as Facility) : null;
    const pickedContext =
      picked && Object.values(CONTEXT_LAYER_IDS).includes(picked.layerId as never) ? picked : null;
    const pickedMeta = picked ? data.featureMetaForLayer(picked.layerId) : null;
    const pickedObject = picked?.object;
    setError(null);
    const longitude = normaliseLongitude(rawLongitude);
    // In the Build tab every map click places the building (moving a project still wins).
    if (sideTab === "build" && mode.kind !== "move") {
      if (!scenario) {
        setError("Select a scenario first");
        return;
      }
      updateBuildTarget({ latitude, longitude, scenarioId: scenario.id, nonce: Date.now() });
      setInspectorOpen(false);
      return;
    }
    setInspectorOpen(true);
    setBuildMapVisible(false);
    try {
      if (mode.kind === "move") {
        const moved = await api.updateProject(mode.projectId, { latitude, longitude });
        setMode({ kind: "inspect" });
        if (!isShown(moved.scenarioId, `The move of "${moved.name || moved.type}"`)) return;
        replaceProject(moved);
        selectProject(moved);
        return;
      }
      const picked = pickedProjectId ? projects.find((p) => p.id === pickedProjectId) : undefined;
      if (picked) return selectProject(picked);
      setSelectedProjectId(null);
      if (pickedFacility) {
        const p = pickedFacility.properties;
        setSelectedFacilityId(pickedFacility.id);
        ctx.setSelection(null);
        data.setPicked(null);
        setSelection({ h3Id: p.h3Id, latitude: p.lat, longitude: p.lon });
        return;
      }
      setSelectedFacilityId(null);
      if (pickedMeta) {
        ctx.setSelection(null);
        data.setPicked({ meta: pickedMeta, feature: data.asFeature(pickedObject) });
        setSelection({ h3Id: simulationCell(latitude, longitude), latitude, longitude });
        return;
      }
      data.setPicked(null);
      if (pickedContext) {
        ctx.setSelection(pickedContext);
        setSelection({ h3Id: simulationCell(latitude, longitude), latitude, longitude });
        return;
      }
      ctx.setSelection(null);
      // A plain click selects the hexagon drawn there: zoomed out, that is a larger cell whose values
      // aggregate the resolution-6 simulation cells inside it.
      setSelection({ h3Id: displayCell(latitude, longitude, grid.resolution), latitude, longitude });
    } catch (e) {
      report(e);
    }
  }

  async function modelFacility() {
    if (!selectedFacility || !scenario) return;
    const p = selectedFacility.properties;
    const itLoad = ratedItLoadKw(p);
    try {
      const created = await api.createProject(scenario.id, {
        type: "data_centre",
        name: `${facilityTitle(p)} (modelled)`,
        latitude: p.lat,
        longitude: p.lon,
        parameters: itLoad !== null ? { itPowerKw: itLoad } : {},
      });
      setScenario({ ...scenario, projects: [...scenario.projects, created] });
      setSelectedFacilityId(null);
      selectProject(created);
      refreshList();
    } catch (e) {
      report(e);
    }
  }

  async function saveProject(patch: Partial<ProjectInput>) {
    if (!selectedProject) return;
    const updated = await api.updateProject(selectedProject.id, patch);
    if (!isShown(updated.scenarioId, `"${updated.name || updated.type}"`)) return;
    replaceProject(updated);
    selectProject(updated);
  }

  async function deleteProject() {
    if (!selectedProject || !scenario) return;
    if (!confirm(`Remove "${selectedProject.name || selectedProject.type}" from ${scenario.name}?`)) return;
    try {
      await api.deleteProject(selectedProject.id);
      setScenario({ ...scenario, projects: scenario.projects.filter((p) => p.id !== selectedProject.id) });
      setSelectedProjectId(null);
      refreshList();
    } catch (e) {
      report(e);
    }
  }

  const scenarioActions = {
    onSwitch: (id: string) => loadScenario(id).catch(report),
    onCreate: async () => {
      const name = prompt("Name for the new (empty) scenario", `World ${String.fromCharCode(65 + scenarios.length)}`);
      if (!name?.trim()) return;
      try {
        const s = await api.createScenario(name);
        await refreshList();
        await loadScenario(s.id);
      } catch (e) {
        report(e);
      }
    },
    onBranch: async () => {
      if (!scenario) return;
      const name = prompt("Name for the branch (copies all projects)", `${scenario.name} – branch`);
      if (!name?.trim()) return;
      try {
        const s = await api.branchScenario(scenario.id, name);
        await refreshList();
        await loadScenario(s.id);
      } catch (e) {
        report(e);
      }
    },
    onRename: async () => {
      if (!scenario) return;
      const name = prompt("Rename scenario", scenario.name);
      if (!name?.trim()) return;
      try {
        const s = await api.renameScenario(scenario.id, name);
        setScenario(s);
        refreshList();
      } catch (e) {
        report(e);
      }
    },
    onDelete: async () => {
      if (!scenario || !confirm(`Delete scenario "${scenario.name}" and its projects? This cannot be undone.`)) return;
      try {
        await api.deleteScenario(scenario.id);
        const list = await api.listScenarios();
        setScenarios(list);
        if (list.length) await loadScenario(list[0].id);
        else setScenario(null);
      } catch (e) {
        report(e);
      }
    },
  };

  const crosshair = mode.kind === "move" || sideTab === "build";

  // Records for search & rank: everything currently loaded (independent of the map's company filter).
  const searchRecords = useMemo<QueryRecord[]>(
    () => [
      ...fromFacilities(allFacilities),
      ...(ctx.quakes ? fromEarthquakes(ctx.quakes.records) : []),
      ...(ctx.fires ? fromFires(ctx.fires.records) : []),
      ...(ctx.cables ? fromLanding(ctx.cables.landing) : []),
      ...(ctx.power ? fromPower(ctx.power.features) : []),
    ],
    [allFacilities, ctx.quakes, ctx.fires, ctx.cables, ctx.power],
  );
  useEffect(() => {
    if (sideTab === "search" && isFacilityDataset(query.dataset)) ensureInfraLayer(query.dataset);
  }, [sideTab, query.dataset, ensureInfraLayer]);
  const infraAvailable = (id: InfraLayerId) => manifest?.layers.some((l) => l.id === id && l.available !== false) ?? false;
  const datasetAvailable: Record<Dataset, boolean> = {
    datacenters: infraAvailable("datacenters"),
    power_plants: infraAvailable("power_plants"),
    dams: infraAvailable("dams"),
    substations: infraAvailable("substations"),
    transmission_lines: infraAvailable("transmission_lines"),
    airports: infraAvailable("airports"),
    ports: infraAvailable("ports"),
    earthquakes: !!ctx.quakes,
    fires: !!ctx.fires?.records.length,
    landing_points: !!ctx.cables,
    power: !!ctx.power,
  };

  const contextLayerFor: Partial<Record<Dataset, string>> = {
    earthquakes: CONTEXT_LAYER_IDS.quakes,
    fires: CONTEXT_LAYER_IDS.fires,
    landing_points: CONTEXT_LAYER_IDS.landing,
    power: CONTEXT_LAYER_IDS.powerPoints,
  };

  function pickRecord(r: QueryRecord) {
    setSelectedProjectId(null);
    data.setPicked(null);
    setInspectorOpen(true);
    if (isFacilityDataset(r.dataset)) {
      const f = r.ref as Facility;
      setSelectedFacilityId(f.id);
      ctx.setSelection(null);
      setSelection({ h3Id: f.properties.h3Id, latitude: f.properties.lat, longitude: f.properties.lon });
    } else {
      setSelectedFacilityId(null);
      ctx.setSelection({ layerId: contextLayerFor[r.dataset]!, object: r.ref });
      setSelection({ h3Id: simulationCell(r.lat, r.lon), latitude: r.lat, longitude: r.lon });
    }
    setFocus({ latitude: r.lat, longitude: r.lon, zoom: 11, nonce: Date.now() });
  }

  const featureTooltip = data.featureTooltip;
  const contextTooltip = useCallback((layerId: string, object: unknown): string | null => {
    const ft = featureTooltip(layerId, object);
    if (ft) return ft;
    switch (layerId) {
      case CONTEXT_LAYER_IDS.cables:
        return `${(object as CablePath).cable.name}\nSubmarine cable`;
      case CONTEXT_LAYER_IDS.landing:
        return `${(object as LandingPoint).properties.name}\nCable landing point`;
      case CONTEXT_LAYER_IDS.quakes: {
        const q = object as Earthquake;
        return `M${q.magnitude?.toFixed(1) ?? "?"} · ${q.place ?? ""}\n${new Date(q.time).toISOString().slice(0, 16).replace("T", " ")}Z · depth ${q.depthKm?.toFixed(0) ?? "?"} km`;
      }
      case CONTEXT_LAYER_IDS.fires: {
        const f = object as Fire;
        return `Fire detection ${f.acqDate} ${f.acqTime}Z\nFRP ${f.frpMw ?? "?"} MW · confidence ${f.confidence ?? "?"}`;
      }
      case CONTEXT_LAYER_IDS.powerLines:
      case CONTEXT_LAYER_IDS.powerPoints: {
        const p = (object as PowerFeature).properties;
        const lines = [`${p.name ?? "Unnamed"} · ${p.kind}${p.plantSource ? ` (${p.plantSource})` : ""}`];
        if (p.operator) lines.push(`Operator: ${p.operator}`);
        if (p.voltageKv.length) lines.push(p.voltageKv.map((v) => `${v} kV`).join(", "));
        if (p.outputKw !== null) lines.push(`Nameplate ${formatKw(p.outputKw)}`);
        return lines.join("\n");
      }
      default:
        return null;
    }
  }, [featureTooltip]);

  const mapLayers = useMemo(() => [...data.featureLayers, ...ctx.layers], [data.featureLayers, ctx.layers]);

  const fitBBox = (bbox: [number, number, number, number] | null, maxZoom = 9) =>
    setFocus(
      bbox
        ? { latitude: (bbox[1] + bbox[3]) / 2, longitude: (bbox[0] + bbox[2]) / 2, bbox, zoom: maxZoom, nonce: Date.now() }
        : { latitude: 20, longitude: 0, bbox: [-160, -55, 170, 72], zoom: 2, nonce: Date.now() },
    );


  const onBuilt = useCallback(
    (p: Project, opts?: { stay?: boolean }) => {
      refreshList();
      if (!isShown(p.scenarioId, `"${p.name || p.type}"`)) return;
      setScenario((s) => (s && s.id === p.scenarioId ? { ...s, projects: [...s.projects, p] } : s));
      if (opts?.stay) return; // a supporting building is previewed next in the Build tab
      setSelectedFacilityId(null);
      ctx.setSelection(null);
      data.setPicked(null);
      setSelectedProjectId(p.id);
      setSelection({ h3Id: p.h3Id, latitude: p.latitude, longitude: p.longitude });
      setInspectorOpen(true);
    },
    [refreshList, isShown, ctx.setSelection, data.setPicked],
  );
  // A save result only replaces the scenario it was made for (the user may have switched meanwhile).
  const applySavedScenario = useCallback((saved: Scenario) => setScenario((cur) => keepIfShown(cur, saved)), []);
  const focusOn = useCallback(
    (latitude: number, longitude: number) => setFocus({ latitude, longitude, zoom: 9, nonce: Date.now() }),
    [],
  );
  /** A real example dropped on the map: load it in the Build tab and preview it there (nothing is saved). */
  const dropPreset = (presetId: string, latitude: number, longitude: number) => {
    if (!scenario) {
      setError("Choose or create a scenario first, then drop the example on the map.");
      return;
    }
    const nonce = Date.now();
    setError(null);
    setMode({ kind: "inspect" });
    navigate("build");
    setPresetRequest({ id: presetId, nonce });
    updateBuildTarget({ latitude, longitude, scenarioId: scenario.id, nonce });
  };
  const previewMarker = useMemo(
    () => (buildTarget ? { latitude: buildTarget.latitude, longitude: buildTarget.longitude } : null),
    [buildTarget],
  );
  const hasRecord = !!(selectedProject || selectedFacility || data.picked || ctx.selection);
  const hasDetail = hasRecord || !!selection;
  useEffect(() => { setDetailView("record"); }, [selectedProjectId, selectedFacilityId, data.picked, ctx.selection]);

  // Layer keys (as listed by /api/sources) of everything drawn on the map right now.
  const activeCredits = new Set<string>(["basemap"]);
  if (tilted) activeCredits.add("buildings3d");
  if (data.active) activeCredits.add(`h3:${data.active.layerId}`);
  for (const [id, on] of Object.entries(data.enabled)) if (on) activeCredits.add(`features:${id}`);
  for (const [id, on] of Object.entries(visibleLayers)) if (on) activeCredits.add(id);
  if (Object.values(ctx.toggles.boundaries).some(Boolean)) activeCredits.add("boundaries");
  if (ctx.toggles.cables) activeCredits.add("cables");
  if (ctx.toggles.earthquakes) activeCredits.add("earthquakes");
  if (ctx.toggles.fires) activeCredits.add("fires");
  if (ctx.rasterImagery) activeCredits.add("imagery");
  if (ctx.power) activeCredits.add("power");
  const mapCredits = [
    ...(ctx.rasterImagery ? [ctx.rasterImagery.attribution] : []),
    ...ctx.attributions,
    ...data.attributions,
  ];
  const showCredits = () => {
    navigate("layers");
    setExploreSection("sources");
  };

  const workspace = sideTab === "build" ? "build" : sideTab === "projects" ? "scenarios" : "explore";
  const dock =
    inspectorOpen && hasDetail
      ? "details"
      : sideTab === "build"
        ? "site"
        : sideTab === "projects" && scenario && scenarioSection !== "overview"
          ? "stress"
          : null;

  return (
    <div className={`app${workspace === "build" ? " building-active" : ""}`}>
      <header className="app-header">
        <a className="brand" href="#" onClick={(e) => { e.preventDefault(); navigate("layers"); }} aria-label="New Worlds home">
          <span className="brand-symbol"><Icon name="globe" size={30} /></span><span>New Worlds</span>
        </a>
        <nav className="workspace-nav" aria-label="Main navigation">
          <button aria-current={workspace === "explore" ? "page" : undefined} onClick={() => navigate("layers")}><Icon name="explore" />Explore</button>
          <button aria-current={workspace === "build" ? "page" : undefined} onClick={() => navigate("build")}><Icon name="layers" />Build</button>
          <button aria-current={workspace === "scenarios" ? "page" : undefined} onClick={() => navigate("projects")}><Icon name="chart" />Scenarios</button>
        </nav>
        <div className="scenario-switcher"><span className="eyebrow">ACTIVE SCENARIO</span><ScenarioSelect scenarios={scenarios} scenario={scenario} onSwitch={scenarioActions.onSwitch} /></div>
        <div className="header-actions">
          <button className="sources-button" onClick={showCredits}><Icon name="info" size={18} /><span>Data & sources</span></button>
          <button className="theme-toggle" onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to day mode" : "Switch to night mode"} title={theme === "dark" ? "Switch to day mode" : "Switch to night mode"}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={19} />
          </button>
        </div>
      </header>
      <div className={`workspace workspace-${workspace}${dock ? " with-inspector" : ""}${buildMapVisible ? " mobile-map-open" : ""}`}>
        {workspace === "build" && <button className="mobile-map-toggle" aria-pressed={buildMapVisible} onClick={() => {
          setBuildMapVisible(!buildMapVisible);
          setInspectorOpen(false);
          if (buildMapVisible) setMode({ kind: "inspect" });
        }}><Icon name={buildMapVisible ? "arrow" : "pin"} size={16} />{buildMapVisible ? "Back to building" : "Show map"}</button>}
        <main className="map-wrap" aria-label="Interactive world map">
          <WorldMap
            theme={theme}
            showHexOutlines={showHexOutlines}
            projects={projects}
            selectedProjectId={selectedProjectId}
            selectedCell={selection?.h3Id ?? null}
            crosshair={crosshair}
            focus={focus}
            onMapClick={handleMapClick}
            facilities={facilities}
            facilityColour={facilityColour}
            selectedFacilityId={selectedFacilityId}
            tilted={tilted}
            onGridChange={setGrid}
            contextLayers={mapLayers}
            cellFill={data.cellFill}
            cellTooltip={data.cellTooltip}
            scene={data.scene}
            contextTooltip={contextTooltip}
            imagery={ctx.rasterImagery}
            onViewChange={setView}
            assessmentCells={assessmentCells}
            assessmentStyle={assessmentStyle}
            preview={previewMarker}
            onDropPreset={dropPreset}
          />

          <div className="map-top">
            <PlaceSearch
              index={ctx.searchIndex}
              onFocus={ctx.ensureSearchIndex}
              onGo={(h) =>
                setFocus({
                  latitude: h.lat,
                  longitude: h.lon,
                  zoom: h.bbox ? 12 : 11,
                  bbox: h.bbox,
                  nonce: Date.now(),
                })
              }
            />
            <div className="toolbar" role="toolbar" aria-label="Map tools">
              <button disabled={!scenario} className={sideTab === "build" ? "active" : ""} onClick={() => navigate("build")}>
                <Icon name="plus" size={17} /> Add building
              </button>
              <span className="sep" />
              <button className={showHexOutlines ? "active" : ""} aria-label="Hexagon outlines" aria-pressed={showHexOutlines} onClick={() => setShowHexOutlines((shown) => !shown)} title={showHexOutlines ? "Hide hexagon outlines" : "Show hexagon outlines"}>
                <Icon name="hexagon" size={17} /> Grid
              </button>
              <button className={tilted ? "active" : ""} aria-pressed={tilted} onClick={() => setTilted((t) => !t)} title="Tilt the map and show 3D buildings when zoomed in">
                3D
              </button>
            </div>
          </div>

          <div className="map-context"><span className="context-dot" />{workspace === "explore" ? "Explore mode" : workspace === "build" ? "Building workspace" : "Scenario workspace"}<span className="map-context-divider" />{projects.length} {projects.length === 1 ? "building" : "buildings"}</div>
          {workspace === "build" && (
            // One left-hand column for the build overlays, sized to the map, so they never cover each other.
            <div className="build-map-stack" ref={setBuildStack}>
              <BuildLayerChips entries={buildLayers.entries} onToggle={buildLayers.toggle} loading={buildLayerLoading} />
              {screened && screened.cells.length > 0 && (
                <SuitabilityLegend area={screened} colourBy={colourBy} onColourBy={setColourBy} loading={buildMapStatus.loading} staleNote={screened.stale ? buildMapStatus.note : null} />
              )}
            </div>
          )}
          {!crosshair && !dock && <div className="map-guide"><Icon name="info" size={17} />Click a location to explore its data</div>}
          {data.activeLayer && !data.outsideRegions && !assessmentCells?.length && (
            <div className="layer-map-legend" aria-label="Active data layer legend">
              <div><strong>{data.activeLayer.name}</strong><span className="muted small block">{data.activeSlice?.label}</span></div>
              <LayerLegend data={data} />
              <span className="muted small legend-unknown"><span className="swatch no-data" /> No data</span>
            </div>
          )}
          <div className="map-credits small">
            <a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a>{" "}
            <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">© OpenMapTiles</a> Data from{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
            {mapCredits.map((a) => (
              <span key={a}> · {a}</span>
            ))}
            {" · "}
            <button className="link inline" onClick={showCredits}>
              Sources &amp; licences
            </button>
          </div>

          {mode.kind === "move" ? (
            <div className="hint" role="status">
              Click the new location
              <button onClick={() => { setMode({ kind: "inspect" }); setBuildMapVisible(false); }}>Cancel</button>
            </div>
          ) : sideTab === "build" && (buildMapStatus.note || !buildTarget) ? (
            <div className="hint" role="status">{buildMapStatus.note ?? "Click the map to place your building"}</div>
          ) : null}
        </main>

        <aside className="sidebar">
          <div className="workspace-heading">
            <div className="eyebrow">{sideTab === "build" ? "PLAN & PLACE" : sideTab === "projects" ? "MODEL & COMPARE" : "THE WORLD, IN CONTEXT"}</div>
            <h1>{sideTab === "build" ? ({ building: "Choose a building", resources: "Resources", impact: "Impact & costs" }[buildStage]) : sideTab === "projects" ? "Your scenarios" : "Explore the world"}</h1>
            {sideTab !== "build" && <p>{sideTab === "projects" ? "Understand the impact of change." : "Discover the data behind a place."}</p>}
          </div>
          {(sideTab === "layers" || sideTab === "search") && (
            <nav className="explore-tabs" aria-label="Explore views">
              <button aria-pressed={sideTab === "layers"} onClick={() => setSideTab("layers")}><Icon name="layers" size={17} />Data layers</button>
              <button aria-pressed={sideTab === "search"} onClick={() => setSideTab("search")}><Icon name="search" size={17} />Search records</button>
            </nav>
          )}

          {sideTab === "projects" && <PanelTabs label="Scenario sections" value={scenarioSection} onChange={setScenarioSection} options={[
            { value: "overview", label: "Overview" }, { value: "resources", label: "Resources" }, { value: "stress", label: "Stress test" },
          ]} />}
          <div className="side-body" ref={sideBodyRef}>
            {error && (
              <div className="error" role="alert" style={{ marginTop: 12 }}>
                {error}
                <button className="ghost" onClick={() => setError(null)} aria-label="Dismiss">
                  ✕
                </button>
              </div>
            )}

            <div hidden={sideTab !== "layers"}>
              {exploreSection === "library" ? (
                <section className="panel section-library">
                  <h2>What would you like to explore?</h2>
                  <p className="subtitle small">Open a section to choose its layers and controls.</p>
                  <div className="section-grid">
                    {EXPLORE_SECTIONS.map((section) => <button key={section.value} onClick={() => setExploreSection(section.value)}>
                      <Icon name={section.icon} /><strong>{section.label}</strong><small>{section.detail}</small>
                    </button>)}
                  </div>
                  {data.activeLayer && <button className="active-layer-shortcut" onClick={() => setExploreSection("environment")}><Icon name="layers" size={18} /><span><small>ACTIVE ENVIRONMENTAL LAYER</small>{data.activeLayer.name}</span><Icon name="chevron" size={16} /></button>}
                </section>
              ) : <div className="section-back"><BackLink onClick={() => {
                if (exploreSection === "environment") data.setActive(null);
                setExploreSection("library");
              }}>All data sections</BackLink><h2>{EXPLORE_SECTIONS.find((x) => x.value === exploreSection)?.label}</h2></div>}
              <div hidden={exploreSection !== "environment"}><DataPanel data={data} onFitBBox={fitBBox} /></div>
              <div hidden={exploreSection !== "infrastructure"}>
                <LayerPanel
                  manifest={manifest}
                  loadError={infraError}
                  status={infraStatus}
                  visible={visibleLayers}
                  onToggle={(id) => setVisibleLayers((v) => ({ ...v, [id]: !v[id] }))}
                  companies={companies}
                  companyFilter={companyFilter}
                  onCompanyFilter={setCompanyFilter}
                  shownCount={facilities.length}
                  cables={{
                    on: ctx.toggles.cables,
                    onToggle: () => ctx.setToggles({ ...ctx.toggles, cables: !ctx.toggles.cables }),
                    status: ctx.status.cables,
                  }}
                  data={data}
                  onOpenRecords={() => setExploreSection("records")}
                />

              </div>
              <div hidden={exploreSection !== "records"}><RecordsPanel data={data} /></div>
              <div hidden={exploreSection !== "context"}>
                <ContextPanel
                  toggles={ctx.toggles}
                  onToggles={ctx.setToggles}
                  status={ctx.status}
                  quakes={ctx.quakes}
                  fires={ctx.fires}
                  fireHint={ctx.fireHint}
                />

              </div>
              <div hidden={exploreSection !== "imagery"}>
                <ImageryPanel
                  imagery={ctx.imagery}
                  onImagery={ctx.setImagery}
                  defaultImageryDate={ctx.defaultImageryDate}
                  view={view}
                >
                  <PreparedScenes data={data} onFitBBox={fitBBox} />
                </ImageryPanel>

              </div>
              <div hidden={exploreSection !== "sources"}><CreditsPanel sources={ctx.sources} activeLayers={activeCredits} /></div>
            </div>

            {sideTab === "search" && (
              <SearchPanel
                records={searchRecords}
                available={datasetAvailable}
                query={query}
                onQuery={setQuery}
                near={view?.centre ?? null}
                onPick={pickRecord}
              />
            )}

            {/* Kept mounted so the building draft survives tab switches. */}
            <div className="build-mount" hidden={sideTab !== "build"}>
              <BuildPanel
                stage={buildStage}
                onStage={changeBuildStage}
                scenario={scenario}
                view={view}
                catalogue={data.catalogue}
                target={buildTarget}
                onTarget={updateBuildTarget}
                onArea={setScreened}
                colourBy={colourBy}
                onColourBy={setColourBy}
                mapProfileId={mapProfileId}
                onNeeds={setBuildNeeds}
                onBuilt={onBuilt}
                onFocus={focusOn}
                active={sideTab === "build"}
                onMapStatus={setBuildMapStatus}
                presetRequest={presetRequest}
                siteHost={buildSiteHost}
              />
            </div>

            {sideTab === "projects" && scenarioSection === "overview" && (
              <ScenarioPanel
                scenarios={scenarios}
                scenario={scenario}
                selectedProjectId={selectedProjectId}
                onSelectProject={(p) => {
                  selectProject(p);
                  setFocus({ latitude: p.latitude, longitude: p.longitude, nonce: Date.now() });
                }}
                {...scenarioActions}
              />
            )}
            {/* Kept mounted so unsaved stress and budget edits survive tab switches (not evaluated while hidden). */}
            {scenario && (
              <div hidden={sideTab !== "projects" || scenarioSection === "overview"}>
                <StressPanel scenario={scenario} section={scenarioSection === "resources" ? "resources" : "stress"} onSection={setScenarioSection} active={sideTab === "projects" && scenarioSection !== "overview"} onSaved={applySavedScenario} resultsHost={stressHost} />
              </div>
            )}
          </div>
        </aside>
        <aside className="inspector" hidden={!dock} aria-label={dock === "details" ? "Selected location details" : dock === "site" ? "Site check" : "Scenario results"}>
          <div className="inspector-heading">
            <div><span className="eyebrow">{dock === "details" ? "LOCATION INSIGHTS" : dock === "site" ? "SITE CHECK" : "SCENARIO ANALYSIS"}</span><h2>{dock === "details" || dock === "site" ? "At this location" : "Impact overview"}</h2></div>
            {dock === "details" && <button className="icon-button" aria-label="Close location details" onClick={() => setInspectorOpen(false)}><Icon name="close" size={18} /></button>}
          </div>
          <div className="inspector-body">
            <div hidden={dock !== "details"}>
            {inspectorOpen && hasDetail && (
              <>
                {hasRecord && selection && <PanelTabs label="Inspector views" value={detailView} onChange={setDetailView} options={[
                  { value: "record", label: selectedProject ? "Building" : "Record" }, { value: "location", label: "Location" },
                ]} />}
                <div hidden={detailView !== "record"}>
                {selectedProject && (
                  <ProjectEditor
                    project={selectedProject}
                    moving={mode.kind === "move"}
                    onSave={saveProject}
                    onMove={() => {
                      setBuildMapVisible(mode.kind !== "move");
                      setMode(mode.kind === "move" ? { kind: "inspect" } : { kind: "move", projectId: selectedProject.id });
                    }}
                    onDelete={deleteProject}
                    onClose={() => setSelectedProjectId(null)}
                    catalogue={data.catalogue}
                    periodDays={mergeAssumptions(scenario?.assumptions).periodDays}
                  />
                )}

                {selectedFacility && (
                  <FacilityInspector
                    facility={selectedFacility}
                    canModel={!!scenario}
                    onModel={modelFacility}
                    onShowCompany={(key) => {
                      setCompanyFilter(key);
                      setExploreSection("infrastructure");
                      setSideTab("layers");
                    }}
                    onZoomTo={() =>
                      setFocus({
                        latitude: selectedFacility.properties.lat,
                        longitude: selectedFacility.properties.lon,
                        zoom: 16,
                        nonce: Date.now(),
                      })
                    }
                    onClose={() => setSelectedFacilityId(null)}
                  />
                )}

                {data.picked && (
                  <section className="panel">
                    <div className="panel-head">
                      <h2>
                        {String(
                          (data.picked.meta.nameField && data.picked.feature.properties[data.picked.meta.nameField]) ||
                            data.picked.feature.properties.id ||
                            "Unnamed",
                        )}
                      </h2>
                      <button className="ghost" onClick={() => data.setPicked(null)} aria-label="Close">
                        ✕
                      </button>
                    </div>
                    <p className="subtitle">{data.picked.meta.name}</p>
                    <FieldList props={data.picked.feature.properties} meta={data.picked.meta} />
                  </section>
                )}

                {ctx.selection && <ContextInspector selection={ctx.selection} onClose={() => ctx.setSelection(null)} />}

                </div>
                <div hidden={hasRecord && detailView !== "location"}>
                {selection && (
                  <CellInspector
                    selection={selection}
                    projectsInCell={projectsInCell}
                    onSelectProject={(id) => {
                      const p = projects.find((x) => x.id === id);
                      if (p) selectProject(p);
                    }}
                    facilities={allFacilities}
                    power={ctx.power}
                    powerStatus={ctx.status.power}
                    onLoadPower={(lat, lon) => ctx.requestPower(lat, lon)}
                    onClearPower={() => ctx.setPower(null)}
                    featureManifest={data.manifest}
                    onShowLayer={(layerId, sliceId) => {
                      const l = data.catalogue.find((x) => x.id === layerId);
                      if (l) data.setActive({ layerId, sliceId: sliceId ?? l.defaultSlice });
                      setExploreSection("environment");
                      setSideTab("layers");
                    }}
                    onGoTo={(lat, lon) => setFocus({ latitude: lat, longitude: lon, zoom: 11, nonce: Date.now() })}
                    onSelectSimulationCell={() =>
                      setSelection((s) => (s ? { ...s, h3Id: simulationCell(s.latitude, s.longitude) } : s))
                    }
                    onZoomToCell={(bbox) => setFocus({ latitude: (bbox[1] + bbox[3]) / 2, longitude: (bbox[0] + bbox[2]) / 2, bbox, zoom: 12, nonce: Date.now() })}
                    onFilterRegion={(country, admin1) => {
                      setQuery((q) => ({ ...q, dataset: "datacenters", country, admin1, sort: "metric" }));
                      setSideTab("search");
                    }}
                  />
                )}
                </div>
              </>
            )}
            </div>
            <div ref={setStressHost} hidden={dock !== "stress"} />
            <div ref={setBuildSiteHost} className="site-host" hidden={dock !== "site"} />
          </div>
        </aside>
      </div>
    </div>
  );
}
