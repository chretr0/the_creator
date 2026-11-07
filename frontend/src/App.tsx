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
  type Dataset,
  type Query,
  type QueryRecord,
} from "./lib/query";
import CellInspector, { type CellSelection } from "./components/CellInspector";
import ProjectEditor from "./components/ProjectEditor";
import ScenarioPanel, { ScenarioSelect } from "./components/ScenarioPanel";
import BuildPanel, { type BuildTarget, type PresetRequest } from "./components/BuildPanel";
import StressPanel from "./components/StressPanel";
import { StateLegend } from "./components/FormBits";
import type { CellState } from "./lib/buildings";
import LayerPanel from "./components/LayerPanel";
import FacilityInspector from "./components/FacilityInspector";
import DataPanel, { RecordsPanel, PreparedScenes } from "./components/DataPanel";
import { FieldList } from "./components/BaselineBlock";
import CreditsPanel from "./components/CreditsPanel";
import { useDataLayers } from "./lib/useDataLayers";
import { mergeAssumptions } from "./lib/buildingForm";
import {
  COLOURED_COMPANIES,
  LAYER_META,
  loadInfrastructure,
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

type Tab = "details" | "layers" | "search" | "build" | "projects";
const TAB_LABEL: Record<Tab, string> = {
  details: "Details",
  layers: "Layers",
  search: "Search",
  build: "Build",
  projects: "Projects",
};

/** "pick" = choosing an exact location for a building preview (Build tab). */
type Mode = { kind: "inspect" } | { kind: "pick" } | { kind: "move"; projectId: string };

const LAST_SCENARIO_KEY = "newworlds:lastScenario";

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
  const [allFacilities, setAllFacilities] = useState<Facility[]>([]);
  const [infraError, setInfraError] = useState<string | null>(null);
  const [visibleLayers, setVisibleLayers] = useState<Record<InfraLayerId, boolean>>({ datacenters: true, dams: true });
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null);
  const [tilted, setTilted] = useState(false);
  const [view, setView] = useState<MapView | null>(null);
  const [sideTab, setSideTab] = useState<Tab>("details");
  const [query, setQuery] = useState<Query>({ dataset: "datacenters", sort: "metric" });
  const [buildTarget, setBuildTarget] = useState<BuildTarget | null>(null);
  const [presetRequest, setPresetRequest] = useState<PresetRequest | null>(null);
  const [assessmentCells, setAssessmentCells] = useState<CellState[] | null>(null);
  const ctx = useContextData(view, { country: query.country, admin1: query.admin1 });
  const data = useDataLayers(view, grid.cells);

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
      setAssessmentCells(null);
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
    loadInfrastructure(ctrl.signal)
      .then(({ manifest, facilities }) => {
        setManifest(manifest);
        setAllFacilities(facilities);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setInfraError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, []);

  const companies = useMemo(() => rankCompanies(allFacilities), [allFacilities]);
  const facilityColour = useMemo(() => {
    const top = new Map(companies.slice(0, COLOURED_COMPANIES).map((c) => [c.key, c.colour]));
    return (f: Facility): [number, number, number] => {
      const p = f.properties;
      if (p.layer === "dams") return LAYER_META.dams.colour;
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
      if (e.key === "Escape") {
        setMode({ kind: "inspect" });
        setBuildTarget(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const projects = scenario?.projects ?? [];
  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const projectsInCell = useMemo(
    () => (selection ? projects.filter((p) => cellContains(selection.h3Id, p.h3Id)) : []),
    [projects, selection],
  );

  const replaceProject = (p: Project) =>
    setScenario((s) => (s ? { ...s, projects: s.projects.map((x) => (x.id === p.id ? p : x)) } : s));

  const selectProject = (p: Project) => {
    setSelectedProjectId(p.id);
    setSideTab("details");
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
    if (mode.kind === "pick") {
      if (scenario) setBuildTarget({ latitude, longitude, scenarioId: scenario.id, nonce: Date.now() });
      setMode({ kind: "inspect" });
      setSideTab("build");
      return;
    }
    setSideTab("details");
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

  const crosshair = mode.kind !== "inspect";

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
  const datasetAvailable: Record<Dataset, boolean> = {
    datacenters: allFacilities.length > 0,
    dams: allFacilities.length > 0,
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
    setSideTab("details");
    if (r.dataset === "datacenters" || r.dataset === "dams") {
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
      setSelectedProjectId(p.id);
      setSelection({ h3Id: p.h3Id, latitude: p.latitude, longitude: p.longitude });
      setSideTab("details");
    },
    [refreshList, isShown],
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
    setSideTab("build");
    setPresetRequest({ id: presetId, nonce });
    setBuildTarget({ latitude, longitude, scenarioId: scenario.id, nonce });
  };
  const setPicking = useCallback((on: boolean) => setMode(on ? { kind: "pick" } : { kind: "inspect" }), []);
  const previewMarker = useMemo(
    () => (buildTarget ? { latitude: buildTarget.latitude, longitude: buildTarget.longitude } : null),
    [buildTarget],
  );
  const hasDetail = !!(selectedProject || selectedFacility || data.picked || ctx.selection || selection);

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
    setSideTab("layers");
    requestAnimationFrame(() => document.getElementById("data-credits")?.scrollIntoView({ behavior: "smooth" }));
  };

  return (
    <div className="app">
      <main className="map-wrap">
        <WorldMap
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
            <button disabled={!scenario} className={sideTab === "build" ? "active" : ""} onClick={() => setSideTab("build")}>
              + Add building
            </button>
            <span className="sep" />
            <button className={tilted ? "active" : ""} aria-pressed={tilted} onClick={() => setTilted((t) => !t)} title="Tilt the map and show 3D buildings when zoomed in">
              3D
            </button>
          </div>
        </div>

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

        {crosshair && (
          <div className="hint" role="status">
            {mode.kind === "pick" ? "Click the exact location to preview the building" : "Click the new location"}
            <button onClick={() => setMode({ kind: "inspect" })}>Cancel</button>
          </div>
        )}

        {assessmentCells && assessmentCells.length > 0 && (
          <div className="map-legend small" aria-label="Assessment legend">
            <strong>Screening by cell</strong>
            <StateLegend />
            <button className="link inline" onClick={() => setAssessmentCells(null)}>
              Hide
            </button>
          </div>
        )}
      </main>

      <aside className="sidebar">
        <header className="side-header">
          <h1>New Worlds</h1>
          <ScenarioSelect scenarios={scenarios} scenario={scenario} onSwitch={scenarioActions.onSwitch} />
        </header>

        <nav className="tabs" role="tablist">
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={sideTab === t} onClick={() => setSideTab(t)}>
              {TAB_LABEL[t]}
            </button>
          ))}
        </nav>

        <div className="side-body">
          {error && (
            <div className="error" role="alert" style={{ marginTop: 12 }}>
              {error}
              <button className="ghost" onClick={() => setError(null)} aria-label="Dismiss">
                ✕
              </button>
            </div>
          )}

          {sideTab === "details" && (
            <>
              {!hasDetail && (
                <div className="empty">
                  <strong>Nothing selected</strong>
                  Click anywhere on the map to see what's there.
                </div>
              )}

              {selectedProject && (
                <ProjectEditor
                  project={selectedProject}
                  moving={mode.kind === "move"}
                  onSave={saveProject}
                  onMove={() =>
                    setMode(mode.kind === "move" ? { kind: "inspect" } : { kind: "move", projectId: selectedProject.id })
                  }
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
            </>
          )}

          {sideTab === "layers" && (
            <>
              <DataPanel data={data} onFitBBox={fitBBox} />
              <LayerPanel
                manifest={manifest}
                loadError={infraError}
                visible={visibleLayers}
                onToggle={(id) => setVisibleLayers((v) => ({ ...v, [id]: !v[id] }))}
                companies={companies}
                companyFilter={companyFilter}
                onCompanyFilter={setCompanyFilter}
                shownCount={facilities.length}
              />
              <RecordsPanel data={data} />
              <ContextPanel
                toggles={ctx.toggles}
                onToggles={ctx.setToggles}
                status={ctx.status}
                quakes={ctx.quakes}
                fires={ctx.fires}
                fireHint={ctx.fireHint}
              />
              <ImageryPanel
                imagery={ctx.imagery}
                onImagery={ctx.setImagery}
                defaultImageryDate={ctx.defaultImageryDate}
                view={view}
              >
                <PreparedScenes data={data} onFitBBox={fitBBox} />
              </ImageryPanel>
              <CreditsPanel sources={ctx.sources} activeLayers={activeCredits} />
            </>
          )}

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
          <div hidden={sideTab !== "build"}>
            <BuildPanel
              scenario={scenario}
              view={view}
              catalogue={data.catalogue}
              target={buildTarget}
              onTarget={setBuildTarget}
              picking={mode.kind === "pick"}
              onPick={setPicking}
              onCells={setAssessmentCells}
              onBuilt={onBuilt}
              onFocus={focusOn}
              onFitBounds={(bbox) => fitBBox(bbox, 7)}
              presetRequest={presetRequest}
            />
          </div>

          {sideTab === "projects" && (
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
            <div hidden={sideTab !== "projects"}>
              <StressPanel scenario={scenario} active={sideTab === "projects"} onSaved={applySavedScenario} />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
