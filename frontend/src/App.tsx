import { useCallback, useEffect, useMemo, useState } from "react";
import WorldMap, { type MapFocus, type MapView, type Picked } from "./components/WorldMap";
import ContextPanel from "./components/ContextPanel";
import ContextInspector from "./components/ContextInspector";
import SearchPanel from "./components/SearchPanel";
import CreditsPanel from "./components/CreditsPanel";
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
import ScenarioPanel from "./components/ScenarioPanel";
import LayerPanel from "./components/LayerPanel";
import FacilityInspector from "./components/FacilityInspector";
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
import { api, type Project, type ProjectInput, type ProjectType, type Scenario, type ScenarioSummary } from "./lib/api";
import { normaliseLongitude, simulationCell, SIMULATION_RESOLUTION } from "./lib/h3grid";
import { PROJECT_TYPES } from "./lib/projectTypes";

type Mode = { kind: "inspect" } | { kind: "place"; type: ProjectType } | { kind: "move"; projectId: string };

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
  const [grid, setGrid] = useState({ resolution: 0, count: 0, overview: true });
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
  const [sideTab, setSideTab] = useState<"layers" | "search" | "sources">("layers");
  const [query, setQuery] = useState<Query>({ dataset: "datacenters", sort: "metric" });
  const ctx = useContextData(view, { country: query.country, admin1: query.admin1 });

  const report = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);

  const refreshList = useCallback(async () => setScenarios(await api.listScenarios()), []);

  const loadScenario = useCallback(
    async (id: string) => {
      const s = await api.getScenario(id);
      setScenario(s);
      setSelectedProjectId(null);
      setMode({ kind: "inspect" });
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
      if (e.key === "Escape") setMode({ kind: "inspect" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const projects = scenario?.projects ?? [];
  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const projectsInCell = useMemo(
    () => (selection ? projects.filter((p) => p.h3Id === selection.h3Id) : []),
    [projects, selection],
  );

  const replaceProject = (p: Project) =>
    setScenario((s) => (s ? { ...s, projects: s.projects.map((x) => (x.id === p.id ? p : x)) } : s));

  const selectProject = (p: Project) => {
    setSelectedProjectId(p.id);
    setSelection({ h3Id: p.h3Id, latitude: p.latitude, longitude: p.longitude });
  };

  async function handleMapClick(latitude: number, rawLongitude: number, picked: Picked | null) {
    const pickedProjectId = picked?.layerId === "projects" ? (picked.object as Project).id : null;
    const pickedFacility =
      picked?.layerId === "infra-points" || picked?.layerId === "infra-footprints" ? (picked.object as Facility) : null;
    const pickedContext =
      picked && Object.values(CONTEXT_LAYER_IDS).includes(picked.layerId as never) ? picked : null;
    setError(null);
    const longitude = normaliseLongitude(rawLongitude);
    try {
      if (mode.kind === "place" && scenario) {
        const created = await api.createProject(scenario.id, { type: mode.type, latitude, longitude });
        setScenario({ ...scenario, projects: [...scenario.projects, created] });
        selectProject(created);
        setMode({ kind: "inspect" });
        refreshList();
        return;
      }
      if (mode.kind === "move") {
        const moved = await api.updateProject(mode.projectId, { latitude, longitude });
        replaceProject(moved);
        selectProject(moved);
        setMode({ kind: "inspect" });
        return;
      }
      const picked = pickedProjectId ? projects.find((p) => p.id === pickedProjectId) : undefined;
      if (picked) return selectProject(picked);
      setSelectedProjectId(null);
      if (pickedFacility) {
        const p = pickedFacility.properties;
        setSelectedFacilityId(pickedFacility.id);
        ctx.setSelection(null);
        setSelection({ h3Id: p.h3Id, latitude: p.lat, longitude: p.lon });
        return;
      }
      setSelectedFacilityId(null);
      if (pickedContext) {
        ctx.setSelection(pickedContext);
        setSelection({ h3Id: simulationCell(latitude, longitude), latitude, longitude });
        return;
      }
      ctx.setSelection(null);
      setSelection({ h3Id: simulationCell(latitude, longitude), latitude, longitude });
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

  const contextTooltip = useCallback((layerId: string, object: unknown): string | null => {
    switch (layerId) {
      case CONTEXT_LAYER_IDS.cables:
        return `${(object as CablePath).cable.name}\nSubmarine cable · © TeleGeography`;
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
  }, []);

  const activeLayers = useMemo(() => {
    const a = new Set<string>(["basemap"]);
    if (tilted) a.add("buildings3d");
    if (visibleLayers.datacenters) a.add("datacenters");
    if (visibleLayers.dams) a.add("dams");
    if (Object.values(ctx.toggles.boundaries).some(Boolean)) a.add("boundaries");
    if (ctx.toggles.cables) a.add("cables");
    if (ctx.toggles.earthquakes) a.add("earthquakes");
    if (ctx.toggles.fires) a.add("fires");
    if (ctx.imagery) a.add("imagery");
    if (ctx.power) a.add("power");
    return a;
  }, [tilted, visibleLayers, ctx.toggles, ctx.imagery, ctx.power]);

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
          contextLayers={ctx.layers}
          contextTooltip={contextTooltip}
          imagery={ctx.rasterImagery}
          onViewChange={setView}
        />



        {ctx.attributions.length > 0 && <div className="map-credits">{ctx.attributions.join(" · ")}</div>}

        <div className="map-top">
        <div className="toolbar" role="toolbar" aria-label="Map tools">
          <button className={mode.kind === "inspect" ? "active" : ""} onClick={() => setMode({ kind: "inspect" })}>
            Inspect
          </button>
          <span className="sep" />
          {PROJECT_TYPES.map((t) => (
            <button
              key={t.type}
              disabled={!scenario}
              className={mode.kind === "place" && mode.type === t.type ? "active" : ""}
              onClick={() => setMode({ kind: "place", type: t.type })}
            >
              <span className="dot" style={{ background: `rgb(${t.colour})` }} />
              {t.label}
            </button>
          ))}
        </div>
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
        </div>
        {crosshair && (
          <div className="hint">
            {mode.kind === "place" ? "Click the map to place the project" : "Click the new location"} · Esc to
            cancel
          </div>
        )}

        <div className="status">
          Display res {grid.resolution}
          {grid.overview ? " (global overview)" : ""} · {grid.count.toLocaleString()} cells · simulation res{" "}
          {SIMULATION_RESOLUTION} · Web Mercator: latitudes beyond ±85° not shown
        </div>
      </main>

      <aside className="sidebar">
        <header className="brand">
          <h1>New Worlds</h1>
          <p className="muted small">Explore the world that exists, then experiment with worlds that could exist.</p>
        </header>
        {error && (
          <div className="error" role="alert">
            {error}
            <button className="ghost" onClick={() => setError(null)} aria-label="Dismiss">
              ✕
            </button>
          </div>
        )}

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

        {selectedFacility && (
          <FacilityInspector
            facility={selectedFacility}
            manifest={manifest}
            canModel={!!scenario}
            onModel={modelFacility}
            onShowCompany={(key) => setCompanyFilter(key)}
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

        {ctx.selection && (
          <ContextInspector
            selection={ctx.selection}
            quakeSource={ctx.quakes?.source ?? null}
            fireSource={ctx.fires?.source ?? null}
            powerSource={ctx.power?.source ?? null}
            onClose={() => ctx.setSelection(null)}
          />
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
          />
        )}

        {selection ? (
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
            onFilterRegion={(country, admin1) => {
              setQuery((q) => ({ ...q, dataset: "datacenters", country, admin1, sort: "metric" }));
              setSideTab("search");
            }}
          />
        ) : (
          <section className="panel">
            <p className="muted small">Click anywhere on the map to inspect its resolution-6 H3 cell.</p>
          </section>
        )}

        <nav className="tabs" role="tablist">
          {(["layers", "search", "sources"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={sideTab === t} className={sideTab === t ? "active" : ""} onClick={() => setSideTab(t)}>
              {{ layers: "Layers", search: "Search & rank", sources: "Data sources" }[t]}
            </button>
          ))}
        </nav>

        {sideTab === "layers" && (
          <>
        <LayerPanel
          manifest={manifest}
          loadError={infraError}
          visible={visibleLayers}
          onToggle={(id) => setVisibleLayers((v) => ({ ...v, [id]: !v[id] }))}
          companies={companies}
          companyFilter={companyFilter}
          onCompanyFilter={setCompanyFilter}
          shownCount={facilities.length}
          tilted={tilted}
          onTilt={() => setTilted((t) => !t)}
        />
            <ContextPanel
              toggles={ctx.toggles}
              onToggles={ctx.setToggles}
              status={ctx.status}
              quakes={ctx.quakes}
              fires={ctx.fires}
              fireHint={ctx.fireHint}
              imagery={ctx.imagery}
              onImagery={ctx.setImagery}
              defaultImageryDate={ctx.defaultImageryDate}
              view={view}
            />
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

        {sideTab === "sources" && <CreditsPanel sources={ctx.sources} activeLayers={activeLayers} />}
      </aside>
    </div>
  );
}
