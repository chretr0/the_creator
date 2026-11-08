import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import "./moon.css";

type Section = "library" | "overlays" | "sites" | "surface" | "coming" | "sources";

const HEX_OUTLINES_KEY = "newworlds:hexOutlines";
const NEXT_PHASE = "Building on the Moon comes next";
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

  useEffect(() => {
    try {
      localStorage.setItem(HEX_OUTLINES_KEY, hexOutlines);
    } catch {
      // The control still works for this session without storage.
    }
  }, [hexOutlines]);
  useEffect(() => {
    sideBodyRef.current?.scrollTo({ top: 0 });
  }, [section]);
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

  const hasDetail = !!(record || selection);
  const dock = inspectorOpen && hasDetail;

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
          <button aria-current="page" onClick={() => setSection("library")}>
            <Icon name="explore" />
            Explore
          </button>
          <button className="moon-next" aria-disabled="true" aria-label="Build (comes next on the Moon)" title={NEXT_PHASE} onClick={(e) => e.preventDefault()}>
            <Icon name="layers" />
            Build
          </button>
          <button className="moon-next" aria-disabled="true" aria-label="Timeline (comes next on the Moon)" title={NEXT_PHASE} onClick={(e) => e.preventDefault()}>
            <Icon name="timeline" />
            Timeline
          </button>
        </nav>
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

      <div className={`workspace workspace-explore${dock ? " with-inspector" : ""}`}>
        <main className="map-wrap moon-map-wrap" aria-label="Interactive map of the Moon">
          <WorldMap
            body={MOON}
            // The Moon map is always black, so map furniture uses its night colours whatever the panels do.
            theme="dark"
            hexOutlines={hexOutlines}
            projects={NO_PROJECTS}
            selectedProjectId={null}
            selectedCell={selection?.h3Id ?? null}
            crosshair={false}
            focus={focus}
            onMapClick={handleMapClick}
            facilities={NO_FACILITIES}
            facilityColour={noColour}
            selectedFacilityId={null}
            tilted={false}
            onGridChange={setGrid}
            contextLayers={contextLayers}
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
            Moon · Explore
            <span className="map-context-divider" />
            {data.sites ? `${data.sites.length} landed objects` : data.status.sites.loading ? "Loading sites…" : "No site data"}
          </div>
          {tilesNote && (
            <div className="moon-tiles-note" role="status">
              <span className="pulse-dot" /> Loading LROC tiles…
            </div>
          )}
          {!dock && !edgeHint && <div className="map-guide"><Icon name="info" size={17} />Click a location to explore its data</div>}
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
            <div className="eyebrow">THE MOON, IN CONTEXT</div>
            <h1>Explore the Moon</h1>
            <p>Landing sites, plans and the ground beneath them.</p>
          </div>
          <div className="side-body" ref={sideBodyRef}>
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
        </aside>

        <aside className="inspector" hidden={!dock} aria-label="Selected location details">
          <div className="inspector-heading">
            <div>
              <span className="eyebrow">{record ? (record.kind === "site" ? "ON THE SURFACE" : "PLANNED") : "LOCATION INSIGHTS"}</span>
              <h2>{record ? (record.kind === "site" ? "Landed object" : record.feature.properties.kind === "artemis_region" ? "Artemis region" : "Planned mission") : "At this location"}</h2>
            </div>
            <button className="icon-button" aria-label="Close location details" onClick={() => setInspectorOpen(false)}>
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="inspector-body">
            {dock && (
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
