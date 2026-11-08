import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PolygonLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { BODIES, type BodyId } from "../bodies";
import BodySwitch from "../components/BodySwitch";
import CreditsPanel from "../components/CreditsPanel";
import GridOutlinesMenu from "../components/GridOutlinesMenu";
import Icon, { type IconName } from "../components/Icon";
import { BackLink, PanelTabs } from "../components/PanelNavigation";
import WorldMap, { type MapFocus, type MapView, type Picked } from "../components/WorldMap";
import { displayCell, MERCATOR_MAX_LAT, normaliseLongitude, parseHexOutlines, simulationCell, type HexOutlines } from "../lib/h3grid";
import { useTheme } from "../lib/useTheme";
import { PREPARE_REFERENCE_SCRIPT, type MissionFeature, type MoonSite } from "./api";
import { defaultOverlayState, NAMES_DETAIL_ZOOM, pendingGroups, rasterOverlays, type MoonView, type OverlayId, type OverlayState } from "./catalogue";
import { clampToMap, formatLatLon, keepoutHitsAt, type MoonPlaceHit } from "./geo";
import { buildMoonLayers, missionPosition, MOON_LAYER_IDS, moonTooltip, type MissionMarker } from "./layers";
import MoonCellInspector, { type CellSelection, type ReferenceAvailability } from "./MoonCellInspector";
import { ComingNextPanel, MoonH3Legend, NotPreparedHint, OverlaysPanel, SitesPanel, SurfaceDataPanel } from "./MoonExplore";
import MoonPlaceSearch from "./MoonPlaceSearch";
import MoonRecordInspector, { recordId, type MoonRecord } from "./MoonRecordInspector";
import { useMoonData } from "./useMoonData";
import { useMoonH3 } from "./useMoonH3";
import { ScenarioSelect } from "../components/ScenarioPanel";
import { geodesicCircle } from "../lib/bodyGeometry";
import type { Project } from "../lib/api";
import { moonApi } from "./api";
import {
  baseBalance,
  MOON_BUILDING_BY_TYPE,
  siteCheck,
  siteFacts,
  type MoonBuildingType,
  type PlacedMoonBuilding,
  type SiteContext,
} from "./buildings";
import { draftFor, draftValues, MoonBaseSummary, MoonBuildForm, MoonBuildingList, MoonSiteCheck, type BuildDraft } from "./MoonBuild";
import { useMoonBase } from "./useMoonBase";
import "./moon.css";

type Section = "library" | "overlays" | "sites" | "surface" | "coming" | "sources";
type Workspace = "explore" | "build" | "totals";
type BuildSection = "new" | "list";
type Target = { latitude: number; longitude: number };

const HEX_OUTLINES_KEY = "newworlds:hexOutlines";
const NEXT_PHASE = "The Timeline comes next on the Moon";
const MOON = BODIES.moon;

function readHexOutlines(): HexOutlines {
  try {
    return parseHexOutlines(localStorage.getItem(HEX_OUTLINES_KEY));
  } catch {
    return "near";
  }
}

/** The visible band next to a pole that a point beyond ±85.05° belongs to. */
function edgeBBox(latitude: number, longitude: number): [number, number, number, number] {
  const south = latitude < 0;
  return [longitude - 25, south ? -MERCATOR_MAX_LAT : 81, longitude + 25, south ? -81 : MERCATOR_MAX_LAT];
}

/** Keep-out rings and mare outlines only shade the ground: clicks on them pick a nearby record, else the location. */
const BACKGROUND_LAYERS = [MOON_LAYER_IDS.keepout, MOON_LAYER_IDS.mare];

const NO_PROJECTS: never[] = [];
const NO_FACILITIES: never[] = [];
const noColour = (): [number, number, number] => [0, 0, 0];

/** The Moon workspace: LROC basemap and overlays, landed objects, plans and keep-out zones, surface data. */
export default function MoonApp({ onBody }: { onBody: (id: BodyId) => void }) {
  const { theme, toggleTheme } = useTheme();
  const data = useMoonData();
  const [grid, setGrid] = useState<{ resolution: number; count: number; overview: boolean; cells: string[] }>({
    resolution: 0,
    count: 0,
    overview: true,
    cells: [],
  });
  const h3 = useMoonH3(grid.cells);
  const [section, setSection] = useState<Section>("library");
  const [selection, setSelection] = useState<CellSelection | null>(null);
  const [record, setRecord] = useState<MoonRecord | null>(null);
  const [detailView, setDetailView] = useState<"record" | "location">("record");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [overlays, setOverlays] = useState<OverlayState>(defaultOverlayState);
  const [show, setShow] = useState({ sites: true, missions: true, keepout: true, mare: false });
  const [hexOutlines, setHexOutlines] = useState<HexOutlines>(readHexOutlines);
  const [edgeHint, setEdgeHint] = useState<string | null>(null);
  const [tilesNote, setTilesNote] = useState(false);
  const [zoom, setZoom] = useState<number | null>(MOON.initialView.zoom);
  const sideBodyRef = useRef<HTMLDivElement>(null);
  const [workspace, setWorkspace] = useState<Workspace>("explore");
  const building = workspace === "build";
  const totals = workspace === "totals";
  const base = useMoonBase(building || totals);
  const [buildSection, setBuildSection] = useState<BuildSection>("new");
  const [draft, setDraft] = useState<BuildDraft>(() => draftFor("moon_habitat"));
  const [editingId, setEditingId] = useState<string | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [site, setSite] = useState<{ key: string; elevationM: number | null; mare: string | null | undefined } | null>(null);
  const [saving, setSaving] = useState(false);
  const [placedNote, setPlacedNote] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(HEX_OUTLINES_KEY, hexOutlines);
    } catch {
      // The control still works for this session without storage.
    }
  }, [hexOutlines]);
  useEffect(() => {
    sideBodyRef.current?.scrollTo({ top: 0 });
  }, [section, workspace, buildSection]);
  useEffect(() => {
    if (show.mare) data.ensureMare();
  }, [show.mare, data.ensureMare]);
  // LROC WMS tiles take about a second each: say so quietly instead of looking broken.
  useEffect(() => {
    if (!tilesNote) return;
    const t = setTimeout(() => setTilesNote(false), 3500);
    return () => clearTimeout(t);
  }, [tilesNote]);

  /* ---------------- Map layers ---------------- */

  const mareLayer = data.manifest?.layers.find((l) => l.id === "moon_mare");
  const mareVectorUsable = !data.notPrepared && mareLayer?.available !== false && !data.status.mare.error;
  const selectedRecordId = recordId(record);
  const contextLayers = useMemo(
    () =>
      buildMoonLayers({
        sites: data.sites,
        missions: data.missions,
        keepout: data.keepout,
        mare: mareVectorUsable ? data.mare : null,
        show,
        selectedId: selectedRecordId,
      }),
    [data.sites, data.missions, data.keepout, data.mare, mareVectorUsable, show, selectedRecordId],
  );
  const overlayExclude: OverlayId[] = mareVectorUsable ? ["mare_wms"] : [];
  const namesDetail = zoom === null || zoom >= NAMES_DETAIL_ZOOM;
  const overlayKey = JSON.stringify([overlays, mareVectorUsable, namesDetail]);
  const mapOverlays = useMemo(
    () => rasterOverlays(overlays, overlayExclude, namesDetail ? null : 0),
    // overlayKey identifies overlays + exclusions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [overlayKey],
  );

  const onViewChange = useCallback((v: MapView) => setZoom(v.zoom), []);

  const setOverlay = useCallback((id: OverlayId, patch: Partial<{ on: boolean; opacity: number }>) => {
    if (patch.on) setTilesNote(true);
    setOverlays((o) => ({ ...o, [id]: { ...o[id], ...patch } }));
  }, []);

  /* ---------------- Selection ---------------- */

  const fly = useCallback((latitude: number, longitude: number, zoom = 9) => {
    if (Math.abs(latitude) > MERCATOR_MAX_LAT) {
      // Past the map edge: frame the nearest visible band (a fixed box, so it also zooms out).
      const bbox = edgeBBox(latitude, longitude);
      setFocus({ latitude: (bbox[1] + bbox[3]) / 2, longitude, bbox, zoom: 6, nonce: Date.now() });
      return;
    }
    // A place inside the map: an earlier "past the map’s edge" hint no longer applies.
    setEdgeHint(null);
    setFocus({ latitude: clampToMap(latitude), longitude, zoom, nonce: Date.now() });
  }, []);

  const pickSite = useCallback(
    (s: MoonSite, flyTo = true) => {
      const [lon, lat] = s.geometry.coordinates;
      setEdgeHint(null);
      setRecord({ kind: "site", feature: s });
      setDetailView("record");
      setSelection({ h3Id: simulationCell(lat, lon), latitude: lat, longitude: normaliseLongitude(lon) });
      setInspectorOpen(true);
      if (flyTo) fly(lat, lon, 9);
    },
    [fly],
  );

  const pickMission = useCallback(
    (m: MissionFeature, flyTo = true) => {
      const pos = missionPosition(m);
      setEdgeHint(null);
      setRecord({ kind: "mission", feature: m });
      setDetailView("record");
      setInspectorOpen(true);
      if (!pos) {
        setSelection(null);
        return;
      }
      const [lon, lat] = pos;
      setSelection({ h3Id: simulationCell(lat, lon), latitude: lat, longitude: normaliseLongitude(lon) });
      if (!flyTo) return;
      if (Math.abs(lat) > MERCATOR_MAX_LAT) {
        setEdgeHint(`${m.properties.name} is at ${formatLatLon(lat, lon, 2)}, past the map’s 85° edge. Showing the nearest visible area.`);
        fly(lat, lon, 6);
      } else fly(lat, lon, 8);
    },
    [fly],
  );

  function handleMapClick(latitude: number, rawLongitude: number, picked: Picked | null) {
    const longitude = normaliseLongitude(rawLongitude);
    setEdgeHint(null);
    if (building) {
      // In Build a click on a placed building opens it; anywhere else chooses (or moves) the site.
      if (picked?.layerId === "projects") {
        const b = base.buildings.find((x) => x.id === (picked.object as Project).id);
        if (b) return startEdit(b);
      }
      setTarget({ latitude, longitude });
      setPlacedNote(null);
      setBuildSection("new");
      return;
    }
    if (totals && picked?.layerId === "projects") {
      const b = base.buildings.find((x) => x.id === (picked.object as Project).id);
      if (b) return startEdit(b);
    }
    if (picked?.layerId === MOON_LAYER_IDS.sites) return pickSite(picked.object as MoonSite, false);
    if (picked?.layerId === MOON_LAYER_IDS.missions) return pickMission((picked.object as MissionMarker).feature, false);
    if (picked?.layerId === MOON_LAYER_IDS.regions) return pickMission(picked.object as MissionFeature, false);
    // Anything else (keep-out rings and mare outlines are background layers) inspects the location.
    setRecord(null);
    setSelection({ h3Id: displayCell(latitude, longitude, grid.resolution), latitude, longitude });
    setInspectorOpen(true);
  }

  function goToPlace(hit: MoonPlaceHit) {
    setEdgeHint(
      hit.beyondMap
        ? `${hit.label} is at ${formatLatLon(hit.lat, hit.lon, 2)}, past the map’s 85° edge. Showing the nearest visible area; a polar view comes next.`
        : null,
    );
    if (hit.bbox && !hit.beyondMap) {
      const [w, s, e, n] = hit.bbox;
      setFocus({ latitude: (s + n) / 2, longitude: (w + e) / 2, bbox: hit.bbox, zoom: 11, nonce: Date.now() });
    } else {
      fly(hit.lat, hit.lon, hit.beyondMap ? 6 : 8);
    }
    if (hit.source === "coordinates") {
      setRecord(null);
      setSelection({ h3Id: simulationCell(hit.lat, hit.lon), latitude: hit.lat, longitude: hit.lon });
      setInspectorOpen(true);
    }
  }

  const fitView = useCallback((v: MoonView) => {
    const [w, s, e, n] = v.bbox;
    setEdgeHint(null);
    setFocus({ latitude: (s + n) / 2, longitude: (w + e) / 2, bbox: v.bbox, zoom: v.maxZoom ?? 5, nonce: Date.now() });
  }, []);

  /* ---------------- Derived ---------------- */

  const pending = useMemo(() => pendingGroups((h3.layers ?? []).map((l) => l.sourceId)), [h3.layers]);
  // Keep-out for the selected point itself, not the centre of its cell (the ring under the cursor).
  const pointKeepout = useMemo(
    () => (selection ? keepoutHitsAt(selection.latitude, selection.longitude, data.keepout, data.sites) : null),
    [selection, data.keepout, data.sites],
  );
  const manifest = data.manifest;
  const referenceAvailable = useMemo<ReferenceAvailability>(() => {
    const prepared = (id: string) => manifest?.layers.find((l) => l.id === id)?.available !== false;
    return { mare: prepared("moon_mare"), places: prepared("moon_places"), sites: prepared("moon_sites") };
  }, [manifest]);
  const crewed = data.sites?.filter((s) => s.properties.kind === "crewed_landing").length ?? null;
  const planned = data.missions?.filter((m) => m.properties.kind === "planned_mission").length ?? null;

  const activeCredits = new Set<string>(["moon_basemap"]);
  if (mapOverlays.length) activeCredits.add("moon_overlays");
  if (show.sites && data.sites) activeCredits.add("moon_sites");
  if (show.missions && data.missions) activeCredits.add("moon_missions");
  if (show.keepout && data.keepout) activeCredits.add("moon_keepout");
  if (show.mare && mareVectorUsable && data.mare) activeCredits.add("moon_mare");
  if (data.places) activeCredits.add("moon_places");
  if (h3.active) activeCredits.add(`h3:${h3.active.id}`);
  const activeSource = h3.active ? data.sources.find((s) => s.id === h3.active?.sourceId) : null;

  const showSources = () => {
    setSection("sources");
    setInspectorOpen(false);
  };

  const sections: { value: Exclude<Section, "library">; label: string; icon: IconName; detail: string }[] = [
    { value: "overlays", label: "Map & overlays", icon: "map", detail: "Feature names, relief, shadowed regions & maria" },
    { value: "sites", label: "Sites & missions", icon: "pin", detail: "Landers, rovers, impacts, plans & keep-out zones" },
    {
      value: "surface",
      label: "Surface data",
      icon: "mountain",
      detail: h3.layers?.length ? `${h3.layers.map((l) => l.name.replace(/\s*\(.*\)$/, "")).join(", ")} on the hexagon grid` : "Measured layers on the hexagon grid",
    },
    { value: "coming", label: "Coming next", icon: "timeline", detail: "Sunlight, temperature, ice & composition" },
    { value: "sources", label: "Sources & licences", icon: "info", detail: "Provenance & data limitations" },
  ];

  /* ---------------- Build ---------------- */

  const targetKey = target ? `${target.latitude},${target.longitude}` : null;
  // What the prepared data says about the chosen site: mare or highlands, and LOLA elevation.
  useEffect(() => {
    if (!target || !targetKey) return;
    const ctrl = new AbortController();
    const cell = simulationCell(target.latitude, target.longitude);
    const elevation = moonApi.h3Values("elevation", [cell], ctrl.signal).then((r) => r.values[cell] ?? null).catch(() => null);
    // undefined = unknown (not loaded), null = highlands.
    const mare = moonApi.cellContext(cell, ctrl.signal).then((c) => c.mare?.name ?? null).catch(() => undefined);
    Promise.all([elevation, mare]).then(([elevationM, mareName]) => {
      if (!ctrl.signal.aborted) setSite({ key: targetKey, elevationM, mare: mareName });
    });
    return () => ctrl.abort();
    // targetKey identifies target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  const editing = editingId ? (base.buildings.find((b) => b.id === editingId) ?? null) : null;
  const others = useMemo(() => base.buildings.filter((b) => b.id !== editingId), [base.buildings, editingId]);
  const { values: draftVals, problems } = useMemo(() => draftValues(draft), [draft]);
  const siteContext = useMemo<SiteContext | null>(() => {
    if (!target || !site || site.key !== targetKey) return null;
    return {
      latitude: target.latitude,
      longitude: target.longitude,
      elevationM: site.elevationM,
      mare: site.mare,
      heritage: keepoutHitsAt(target.latitude, target.longitude, data.keepout, data.sites),
    };
  }, [target, targetKey, site, data.keepout, data.sites]);
  const facts = useMemo(() => (siteContext ? siteFacts(siteContext) : null), [siteContext]);
  const check = useMemo(
    () => (facts && siteContext ? siteCheck(draft.type, draftVals, facts, siteContext.heritage, others) : null),
    [facts, siteContext, draft.type, draftVals, others],
  );
  const balance = useMemo(() => baseBalance(base.buildings, base.settings), [base.buildings, base.settings]);
  const blockReason = !base.world
    ? "Start a Moon base from the Active world menu first."
    : Object.keys(problems).length
      ? "Fix the highlighted values first."
      : check?.verdict === "unsuitable"
        ? "Fix the failed checks, or choose another site."
        : null;
  const canSave = !!facts && !blockReason;
  const moonProjects: Project[] = building || totals ? (base.world?.projects ?? []) : NO_PROJECTS;

  function startEdit(b: PlacedMoonBuilding) {
    setWorkspace("build");
    setBuildSection("new");
    setEditingId(b.id);
    setDraft(draftFor(b.type, b.name, b.values));
    setTarget({ latitude: b.latitude, longitude: b.longitude });
    setPlacedNote(null);
  }
  function stopEdit(toList = true) {
    setEditingId(null);
    setTarget(null);
    setDraft(draftFor(draft.type));
    if (toList) setBuildSection("list");
  }
  async function deleteBuilding(b: PlacedMoonBuilding) {
    const label = b.name || MOON_BUILDING_BY_TYPE[b.type].label;
    if (!confirm(`Remove “${label}” from ${base.world?.name ?? "this base"}? This can't be undone.`)) return;
    const ok = await base.remove(b.id);
    if (ok && b.id === editingId) stopEdit();
  }
  async function saveBuilding() {
    if (!target || !canSave || saving) return;
    setSaving(true);
    const label = MOON_BUILDING_BY_TYPE[draft.type].label;
    const input = { type: draft.type, name: draft.name, latitude: target.latitude, longitude: target.longitude, values: draftVals };
    if (editingId) {
      const p = await base.update(editingId, input);
      if (p) setPlacedNote(`Saved “${p.name || label}”.`);
    } else {
      const p = await base.place(input);
      if (p) {
        setPlacedNote(`Placed “${p.name || label}”. Choose the next building, or open World totals to see whether it keeps a crew alive.`);
        setTarget(null);
        setDraft(draftFor(draft.type));
      }
    }
    setSaving(false);
  }

  const worldActions = {
    onSwitch: (id: string) => {
      stopEdit(false);
      setPlacedNote(null);
      base.switchWorld(id);
    },
    onCreate: () => {
      const name = prompt("Name for the new Moon base", `Moon base ${String.fromCharCode(65 + (base.worlds?.length ?? 0))}`);
      if (name?.trim()) {
        stopEdit(false);
        base.createWorld(name);
      }
    },
    onBranch: () => {
      if (!base.world) return;
      const name = prompt("Name for the copy (copies every building)", `${base.world.name} – branch`);
      if (name?.trim()) base.branchWorld(name);
    },
    onRename: () => {
      if (!base.world) return;
      const name = prompt("Rename this Moon base", base.world.name);
      if (name?.trim()) base.renameWorld(name);
    },
    onDelete: () => {
      if (base.world && confirm(`Delete Moon base “${base.world.name}” and its buildings? This cannot be undone.`)) {
        stopEdit(false);
        base.deleteWorld();
      }
    },
  };

  // Keep-out rings around landing pads (plume) and reactors (radiation), including the one being placed.
  const buildLayers = useMemo<Layer[]>(() => {
    if (!building) return [];
    type Ring = { id: string; ring: [number, number][]; colour: [number, number, number] };
    const rings: Ring[] = [];
    const add = (id: string, type: MoonBuildingType, values: Record<string, number | null>, latitude: number, longitude: number) => {
      const role = MOON_BUILDING_BY_TYPE[type].role;
      const km = values.keepoutKm;
      if ((role !== "landing_pad" && role !== "fission") || !km || km <= 0) return;
      rings.push({ id, ring: geodesicCircle(latitude, longitude, km, MOON.radiusKm, 96), colour: MOON_BUILDING_BY_TYPE[type].colour });
    };
    for (const b of others) add(b.id, b.type, b.values, b.latitude, b.longitude);
    if (target) add("draft", draft.type, draftVals, target.latitude, target.longitude);
    return [
      new PolygonLayer<Ring>({
        id: "moon-build-keepout",
        data: rings,
        getPolygon: (d) => d.ring,
        stroked: true,
        filled: true,
        getFillColor: (d) => [...d.colour, 26],
        getLineColor: (d) => [...d.colour, 210],
        lineWidthUnits: "pixels",
        getLineWidth: 1.5,
        pickable: false,
      }),
    ];
  }, [building, others, target, draft.type, draftVals]);
  const mapLayers = useMemo(() => (building ? [...contextLayers, ...buildLayers] : contextLayers), [building, contextLayers, buildLayers]);

  const hasDetail = !!(record || selection);
  const dock = building ? !!target : inspectorOpen && hasDetail;

  return (
    <div className="app moon-app">
      <header className="app-header">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setSection("library");
          }}
          aria-label="New Worlds home"
        >
          <span className="brand-symbol">
            <Icon name="globe" size={30} />
          </span>
          <span>New Worlds</span>
        </a>
        <BodySwitch value="moon" onChange={onBody} />
        <nav className="workspace-nav" aria-label="Main navigation">
          <button
            aria-current={workspace === "explore" ? "page" : undefined}
            onClick={() => {
              setWorkspace("explore");
              setSection("library");
            }}
          >
            <Icon name="explore" />
            Explore
          </button>
          <button aria-current={building ? "page" : undefined} onClick={() => setWorkspace("build")}>
            <Icon name="layers" />
            Build
          </button>
          <button className="moon-next" aria-disabled="true" aria-label="Timeline (comes next on the Moon)" title={NEXT_PHASE} onClick={(e) => e.preventDefault()}>
            <Icon name="timeline" />
            Timeline
          </button>
        </nav>
        {(building || totals) && (
          <div className="scenario-switcher">
            <span className="eyebrow">ACTIVE WORLD</span>
            {base.worlds === null ? (
              <span className="small muted moon-world-loading">{base.loading ? "Loading…" : "Unavailable"}</span>
            ) : (
              <ScenarioSelect scenarios={base.worlds} scenario={base.world} {...worldActions} />
            )}
          </div>
        )}
        <button
          className="world-totals-tab"
          aria-label="World totals"
          aria-current={totals ? "page" : undefined}
          onClick={() => setWorkspace("totals")}
          title="Everything your Moon base uses, makes and costs to land, added up"
        >
          <Icon name="chart" size={17} />
          <span>World totals</span>
        </button>
        <div className="header-actions">
          <button className="sources-button" onClick={showSources}>
            <Icon name="info" size={18} />
            <span>Data &amp; sources</span>
          </button>
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to day mode" : "Switch to night mode"}
            title={theme === "dark" ? "Switch to day mode" : "Switch to night mode"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={19} />
          </button>
        </div>
      </header>

      <div className={`workspace ${building ? "moon-workspace-build" : totals ? "workspace-totals" : "workspace-explore"}${dock ? " with-inspector" : ""}`}>
        <main className="map-wrap moon-map-wrap" aria-label="Interactive map of the Moon">
          <WorldMap
            body={MOON}
            // The Moon map is always black, so map furniture uses its night colours whatever the panels do.
            theme="dark"
            hexOutlines={hexOutlines}
            projects={moonProjects}
            selectedProjectId={building ? editingId : null}
            selectedCell={building ? (target ? simulationCell(target.latitude, target.longitude) : null) : (selection?.h3Id ?? null)}
            crosshair={building}
            focus={focus}
            onMapClick={handleMapClick}
            facilities={NO_FACILITIES}
            facilityColour={noColour}
            selectedFacilityId={null}
            tilted={false}
            onGridChange={setGrid}
            contextLayers={mapLayers}
            backgroundLayerIds={BACKGROUND_LAYERS}
            cellFill={h3.cellFill}
            timeline={null}
            cellTooltip={h3.cellTooltip}
            scene={null}
            contextTooltip={moonTooltip}
            imagery={null}
            rasterOverlays={mapOverlays}
            onViewChange={onViewChange}
            assessmentCells={null}
            assessmentStyle={null}
            preview={null}
          />

          <div className="map-top">
            <MoonPlaceSearch index={data.places} status={data.status.places} onFocus={data.ensurePlaces} onGo={goToPlace} />
            <div className="toolbar" role="toolbar" aria-label="Map tools">
              <button
                className={overlays.names.on ? "active" : ""}
                aria-pressed={overlays.names.on}
                onClick={() => setOverlay("names", { on: !overlays.names.on })}
                title="IAU feature names drawn by LROC"
              >
                <Icon name="pin" size={16} /> Names
              </button>
              <span className="sep" />
              <GridOutlinesMenu value={hexOutlines} onChange={setHexOutlines} />
            </div>
          </div>

          <div className="map-context">
            <span className="context-dot" />
            Moon · {building ? "Build" : totals ? "World totals" : "Explore"}
            <span className="map-context-divider" />
            {building || totals
              ? `${base.buildings.length} ${base.buildings.length === 1 ? "building" : "buildings"}${base.world ? ` in ${base.world.name}` : ""}`
              : data.sites
                ? `${data.sites.length} landed objects`
                : data.status.sites.loading
                  ? "Loading sites…"
                  : "No site data"}
          </div>
          {tilesNote && (
            <div className="moon-tiles-note" role="status">
              <span className="pulse-dot" /> Loading LROC tiles…
            </div>
          )}
          {!dock && !edgeHint && workspace === "explore" && <div className="map-guide"><Icon name="info" size={17} />Click a location to explore its data</div>}
          {building && !target && !edgeHint && (
            <div className="hint" role="status">
              {base.world ? `Click the map to place a ${MOON_BUILDING_BY_TYPE[draft.type].label.toLowerCase()}` : "Start a Moon base from the Active world menu"}
            </div>
          )}
          {h3.active && (
            <div className="layer-map-legend moon-map-legend" aria-label="Active surface layer legend">
              <MoonH3Legend h3={h3} onMap />
            </div>
          )}
          {edgeHint && (
            <div className="hint moon-edge-hint" role="status">
              {edgeHint}
              <button onClick={() => setEdgeHint(null)}>Dismiss</button>
            </div>
          )}
          <div className="map-credits small">
            {MOON.credits.map((c) =>
              c.href ? (
                <a key={c.label} href={c.href} target="_blank" rel="noreferrer">
                  {c.label}
                </a>
              ) : (
                <span key={c.label}>{c.label}</span>
              ),
            )}
            {mapOverlays.length > 0 && <span> · Overlays: LROC/ASU</span>}
            {" · "}
            <a href="https://planetarynames.wr.usgs.gov/" target="_blank" rel="noreferrer">
              IAU/USGS nomenclature
            </a>
            {activeSource && <span> · {activeSource.attribution || activeSource.name}</span>}
            {" · "}
            <button className="link inline" onClick={showSources}>
              Sources &amp; licences
            </button>
          </div>
        </main>

        <aside className="sidebar">
          <div className="workspace-heading">
            <div className="eyebrow">{building ? "PLAN & PLACE A MOON BASE" : totals ? "ADDED UP" : "THE MOON, IN CONTEXT"}</div>
            <h1>{building ? (buildSection === "list" ? "Your buildings" : editing ? "Edit building" : "Build on the Moon") : totals ? "World totals" : "Explore the Moon"}</h1>
            <p>
              {building
                ? "A hypothetical base, checked against the Moon data we have."
                : totals
                  ? "Can the base keep a crew alive, and what does it add up to?"
                  : "Landing sites, plans and the ground beneath them."}
            </p>
          </div>
          {building && (
            <PanelTabs
              label="Build sections"
              value={buildSection}
              onChange={setBuildSection}
              options={[
                { value: "new", label: editing ? "Edit building" : "New building" },
                { value: "list", label: `Buildings (${base.buildings.length})` },
              ]}
            />
          )}
          <div className="side-body" ref={sideBodyRef}>
            {building && (
              <div className="moon-build">
                {base.error && (
                  <div className="error" role="alert">
                    {base.error}
                    <button className="ghost" onClick={base.clearError} aria-label="Dismiss">
                      ✕
                    </button>
                  </div>
                )}
                {placedNote && buildSection === "new" && (
                  <p className="moon-placed-note" role="status">
                    {placedNote}
                  </p>
                )}
                {buildSection === "new" && (
                  <MoonBuildForm
                    draft={draft}
                    onDraft={setDraft}
                    editing={editing}
                    target={target}
                    onClearTarget={() => setTarget(null)}
                    onDone={() => stopEdit()}
                    onDelete={() => editing && deleteBuilding(editing)}
                    hasWorld={!!base.world}
                  />
                )}
                {buildSection === "list" && (
                  <MoonBuildingList
                    buildings={base.buildings}
                    worldName={base.world?.name ?? null}
                    editingId={editingId}
                    onShow={(b) => fly(b.latitude, b.longitude, 10)}
                    onEdit={(b) => {
                      startEdit(b);
                      fly(b.latitude, b.longitude, 10);
                    }}
                    onDelete={deleteBuilding}
                    onNew={() => setBuildSection("new")}
                  />
                )}
              </div>
            )}
            {totals && (
              <div className="moon-build">
                {base.error && (
                  <div className="error" role="alert">
                    {base.error}
                    <button className="ghost" onClick={base.clearError} aria-label="Dismiss">
                      ✕
                    </button>
                  </div>
                )}
                {base.worlds === null ? (
                  <section className="panel">
                    <p className="muted small" role="status">
                      {base.loading ? "Loading your Moon base…" : "Moon bases are unavailable right now."}
                    </p>
                  </section>
                ) : (
                <MoonBaseSummary
                  key={base.world?.id ?? "none"}
                  balance={balance}
                  buildings={base.buildings}
                  settings={base.settings}
                  onSettings={base.saveSettings}
                  onShow={(b) => fly(b.latitude, b.longitude, 10)}
                  hasWorld={!!base.world}
                />
                )}
              </div>
            )}
            <div hidden={workspace !== "explore"}>
            {section === "library" ? (
              <section className="panel section-library">
                {data.notPrepared && <NotPreparedHint what="Moon reference data" script={PREPARE_REFERENCE_SCRIPT} />}
                <div className="stats three moon-glance-stats">
                  <button className="stat" onClick={() => setSection("sites")} title="Open Sites & missions">
                    <strong>{crewed ?? "–"}</strong>
                    <span>crewed landing sites</span>
                  </button>
                  <button className="stat" onClick={() => setSection("sites")} title="Open Sites & missions">
                    <strong>{data.sites?.length ?? "–"}</strong>
                    <span>objects on the surface</span>
                  </button>
                  <button className="stat" onClick={() => setSection("sites")} title="Open Sites & missions">
                    <strong>{planned ?? "–"}</strong>
                    <span>missions planned</span>
                  </button>
                </div>
                <h2>What would you like to explore?</h2>
                <p className="subtitle small">Open a section to choose its layers and controls.</p>
                <div className="section-grid">
                  {sections.map((s) => (
                    <button key={s.value} onClick={() => setSection(s.value)}>
                      <Icon name={s.icon} />
                      <strong>{s.label}</strong>
                      <small>{s.detail}</small>
                    </button>
                  ))}
                </div>
                {h3.active && (
                  <button className="active-layer-shortcut" onClick={() => setSection("surface")}>
                    <Icon name="layers" size={18} />
                    <span>
                      <small>ACTIVE SURFACE LAYER</small>
                      {h3.active.name}
                    </span>
                    <Icon name="chevron" size={16} />
                  </button>
                )}
              </section>
            ) : (
              <div className="section-back">
                <BackLink onClick={() => setSection("library")}>All Moon sections</BackLink>
                <h2>{sections.find((s) => s.value === section)?.label}</h2>
              </div>
            )}
            <div hidden={section !== "overlays"}>
              <OverlaysPanel
                overlays={overlays}
                onOverlay={setOverlay}
                mareVector={{
                  usable: mareVectorUsable,
                  on: show.mare,
                  onToggle: () => setShow((s) => ({ ...s, mare: !s.mare })),
                  status: data.status.mare,
                  count: data.mare?.length ?? null,
                }}
                onView={fitView}
              />
            </div>
            <div hidden={section !== "sites"}>
              <SitesPanel
                data={data}
                show={show}
                onShow={(key) => setShow((s) => ({ ...s, [key]: !s[key] }))}
                selectedId={selectedRecordId}
                onPickSite={(s) => pickSite(s)}
                onPickMission={(m) => pickMission(m)}
              />
            </div>
            <div hidden={section !== "surface"}>
              <SurfaceDataPanel h3={h3} onFitView={fitView} />
            </div>
            <div hidden={section !== "coming"}>
              <ComingNextPanel groups={pending} />
            </div>
            <div hidden={section !== "sources"}>
              <CreditsPanel sources={data.sources} activeLayers={activeCredits} />
              {data.status.sources.error && <p className="warn small moon-pad">Couldn’t load the source list: {data.status.sources.error}</p>}
            </div>
            </div>
          </div>
        </aside>

        <aside className="inspector" hidden={!dock} aria-label={building ? "Site check" : "Selected location details"}>
          <div className="inspector-heading">
            <div>
              <span className="eyebrow">{building ? "SITE CHECK" : record ? (record.kind === "site" ? "ON THE SURFACE" : "PLANNED") : "LOCATION INSIGHTS"}</span>
              <h2>
                {building
                  ? editing
                    ? editing.name || MOON_BUILDING_BY_TYPE[editing.type].label
                    : "At this location"
                  : record
                    ? record.kind === "site"
                      ? "Landed object"
                      : record.feature.properties.kind === "artemis_region"
                        ? "Artemis region"
                        : "Planned mission"
                    : "At this location"}
              </h2>
            </div>
            <button
              className="icon-button"
              aria-label={building ? "Close the site check" : "Close location details"}
              onClick={() => (building ? (editing ? stopEdit() : setTarget(null)) : setInspectorOpen(false))}
            >
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="inspector-body">
            {building && target && (
              <MoonSiteCheck
                type={draft.type}
                facts={facts}
                items={check?.items ?? []}
                verdict={check?.verdict ?? null}
                editing={!!editing}
                saving={saving}
                canSave={canSave}
                blockReason={facts ? blockReason : null}
                onSave={saveBuilding}
              />
            )}
            {!building && dock && (
              <>
                {record && selection && (
                  <PanelTabs
                    label="Inspector views"
                    value={detailView}
                    onChange={setDetailView}
                    options={[
                      { value: "record", label: "Record" },
                      { value: "location", label: "Location" },
                    ]}
                  />
                )}
                {record && (
                  <div hidden={detailView !== "record"}>
                    <MoonRecordInspector
                      record={record}
                      sources={data.sources}
                      onClose={() => {
                        setRecord(null);
                        if (!selection) setInspectorOpen(false);
                      }}
                      onZoomTo={(lat, lon) => fly(lat, lon, 11)}
                    />
                  </div>
                )}
                {selection && (
                  <div hidden={!!record && detailView !== "location"}>
                    <MoonCellInspector
                      selection={selection}
                      pointKeepout={pointKeepout}
                      available={referenceAvailable}
                      h3Layers={h3.layers}
                      activeLayer={h3.active}
                      pending={pending}
                      onSelectSimulationCell={() =>
                        setSelection((s) => (s ? { ...s, h3Id: simulationCell(s.latitude, s.longitude) } : s))
                      }
                      onZoomToCell={(bbox) =>
                        setFocus({ latitude: (bbox[1] + bbox[3]) / 2, longitude: (bbox[0] + bbox[2]) / 2, bbox, zoom: 11, nonce: Date.now() })
                      }
                      onGoTo={(lat, lon) => fly(lat, lon, 9)}
                      onPickSite={(id) => {
                        const s = data.sites?.find((x) => x.properties.id === id);
                        if (s) pickSite(s);
                      }}
                      onShowLayer={(id) => {
                        h3.setActive(id);
                        setSection("surface");
                      }}
                      onShowComingNext={() => setSection("coming")}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
