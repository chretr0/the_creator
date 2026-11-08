import { useEffect, useMemo, useState } from "react";
import { cellArea, cellToBoundary, cellToChildrenSize, getResolution, UNITS } from "h3-js";
import { SIMULATION_RESOLUTION } from "../lib/h3grid";
import type { Project } from "../lib/api";
import { typeColour, typeLabel } from "../lib/projectTypes";
import { locateRegion, type PowerResult, type RegionLocate } from "../lib/context";
import { type Facility } from "../lib/infrastructure";
import { fromFacilities, runQuery } from "../lib/query";
import { dataApi, type CellFeatureContext, type CellProfile, type FeatureLayerMeta } from "../lib/datalayers";
import { groupByCategory, slug } from "../lib/insights";
import { AtAGlance, CATEGORY_ICON, DataSection, NearbySection } from "./LocationData";
import WeatherCard from "./WeatherCard";
import PowerGridCard from "./PowerGridCard";
import Icon, { type IconName } from "./Icon";

export type CellSelection = { h3Id: string; latitude: number; longitude: number };

type Props = {
  selection: CellSelection;
  projectsInCell: Project[];
  onSelectProject: (id: string) => void;
  facilities: Facility[];
  /** The power grid currently drawn on the map, if any. */
  gridOnMap: PowerResult | null;
  onShowGrid: (grid: PowerResult | null) => void;
  onFilterRegion: (country: string | null, admin1: string | null) => void;
  featureManifest: FeatureLayerMeta[];
  onShowLayer: (layerId: string, sliceId?: string) => void;
  onGoTo: (lat: number, lon: number) => void;
  /** Narrow a zoomed-out hexagon selection to the resolution-6 cell at the clicked point. */
  onSelectSimulationCell: () => void;
  onZoomToCell: (bbox: [number, number, number, number]) => void;
};

/** [west, south, east, north] of a cell, unwrapped across the antimeridian. */
function cellBBox(h3Id: string): [number, number, number, number] {
  const ring = cellToBoundary(h3Id);
  const lats = ring.map((p) => p[0]);
  let lons = ring.map((p) => p[1]);
  if (Math.max(...lons) - Math.min(...lons) > 180) lons = lons.map((l) => (l < 0 ? l + 360 : l));
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

const coord = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? "E" : "W"}`;

export default function CellInspector(props: Props) {
  const { selection, projectsInCell, onSelectProject } = props;
  const [region, setRegion] = useState<RegionLocate | null>(null);
  const [regionError, setRegionError] = useState(false);
  const [profile, setProfile] = useState<CellProfile | null>(null);
  const [profileError, setProfileError] = useState(false);
  const [nearby, setNearby] = useState<CellFeatureContext | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setRegion(null);
    setRegionError(false);
    locateRegion(selection.latitude, selection.longitude, ctrl.signal)
      .then(setRegion)
      .catch(() => !ctrl.signal.aborted && setRegionError(true));
    return () => ctrl.abort();
  }, [selection.latitude, selection.longitude]);

  useEffect(() => {
    const ctrl = new AbortController();
    setProfile(null);
    setProfileError(false);
    setNearby(null);
    dataApi
      .profile(selection.h3Id, ctrl.signal)
      .then(setProfile)
      .catch(() => !ctrl.signal.aborted && setProfileError(true));
    dataApi
      .cellFeatures(selection.h3Id, ctrl.signal)
      .then(setNearby)
      .catch(() => {
        /* nearby features are optional */
      });
    return () => ctrl.abort();
  }, [selection.h3Id]);

  const place = region
    ? [region.county?.name, region.admin1?.name, region.country?.name].filter(Boolean).join(", ") || "Open water"
    : regionError
      ? "Selected location"
      : "Locating…";
  const area = cellArea(selection.h3Id, UNITS.km2);
  const res = getResolution(selection.h3Id);
  const coarse = res < SIMULATION_RESOLUTION;
  const groups = useMemo(() => groupByCategory(profile?.layers ?? []), [profile]);
  const hasNearby = !!nearby?.layers.length;

  const jumps: { id: string; label: string; icon: IconName }[] = [
    { id: "insight-weather", label: "Weather", icon: "sun" },
    { id: "insight-power", label: "Power grid", icon: "bolt" },
    ...groups.map(([cat]) => ({ id: `insight-${slug(cat)}`, label: cat, icon: CATEGORY_ICON[cat] ?? ("layers" as IconName) })),
    ...(hasNearby ? [{ id: "insight-nearby", label: "Nearby", icon: "pin" as IconName }] : []),
  ];
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <section className="panel insights">
      <header className="insights-place">
        <h2>{coarse ? `Hexagon · ${place}` : place}</h2>
        <p className="subtitle num">
          {coord(selection.latitude, selection.longitude)} · {Math.round(area).toLocaleString()} km²
        </p>
      </header>

      {coarse && (
        <div className="coarse-note">
          <p className="small">
            Averaged over the {cellToChildrenSize(selection.h3Id, SIMULATION_RESOLUTION).toLocaleString()} cells in this hexagon.
          </p>
          <div className="actions tight">
            <button className="chip" onClick={() => props.onZoomToCell(cellBBox(selection.h3Id))}>Zoom to hexagon</button>
            <button className="chip" onClick={props.onSelectSimulationCell}>Inspect the cell here</button>
          </div>
        </div>
      )}

      <RegionStats region={region} facilities={props.facilities} onFilterRegion={props.onFilterRegion} projects={projectsInCell.length} />

      {projectsInCell.length > 0 && (
        <ul className="place-list projects-here">
          {projectsInCell.map((p) => (
            <li key={p.id}>
              <button className="link" onClick={() => onSelectProject(p.id)}>
                <span className="dot" style={{ background: `rgb(${typeColour(p.type).join(",")})` }} />
                <span className="place-name">{p.name || typeLabel(p.type)}<span className="muted small">{typeLabel(p.type)}</span></span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <nav className="insight-jump" aria-label="Jump to section">
        {jumps.map((j) => (
          <button key={j.id} className="chip" onClick={() => jump(j.id)}>
            <Icon name={j.icon} size={13} /> {j.label}
          </button>
        ))}
      </nav>

      {profile && <AtAGlance profile={profile} />}

      <section className="insight-section" id="insight-weather">
        <h3 className="section-label"><Icon name="sun" size={16} /> Weather right now</h3>
        <WeatherCard latitude={selection.latitude} longitude={selection.longitude} />
      </section>

      <section className="insight-section" id="insight-power">
        <h3 className="section-label"><Icon name="bolt" size={16} /> Power grid within 10 km</h3>
        <PowerGridCard
          latitude={selection.latitude}
          longitude={selection.longitude}
          onMap={props.gridOnMap}
          onShowOnMap={props.onShowGrid}
          onGoTo={props.onGoTo}
        />
      </section>

      {profileError && <p className="warn small">The location data couldn’t be loaded.</p>}
      {!profile && !profileError && (
        <div className="insight-section" aria-busy="true">
          <div className="tiles">
            {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 96 }} />)}
          </div>
        </div>
      )}
      {profile && !profile.region && !profile.layers.some((l) => l.coverage === "regions") && (
        <p className="coarse-note small" role="status">
          Detailed terrain, land cover, water and satellite layers are prepared for Arizona and the UK; worldwide data is shown below.
        </p>
      )}
      {groups.map(([category, layers]) => (
        <DataSection key={category} category={category} layers={layers} total={profile?.simulationCells ?? 1} onShow={props.onShowLayer} />
      ))}
      {nearby && hasNearby && <NearbySection context={nearby} manifest={props.featureManifest} onGoTo={props.onGoTo} />}

      <p className="muted small mono cell-id">Cell {selection.h3Id}</p>
    </section>
  );
}

function RegionStats({
  region,
  facilities,
  onFilterRegion,
  projects,
}: {
  region: RegionLocate | null;
  facilities: Facility[];
  onFilterRegion: Props["onFilterRegion"];
  projects: number;
}) {
  const records = useMemo(() => fromFacilities(facilities), [facilities]);
  const country = region?.country?.name ?? null;
  if (!country) return null;
  const admin1 = region?.admin1?.name ?? null;
  const area = admin1 ?? country;
  const dc = runQuery(records, { dataset: "datacenters", country, admin1, sort: "name", limit: 0 }).total;
  const dams = runQuery(records, { dataset: "dams", country, admin1, sort: "name", limit: 0 }).total;

  return (
    <div className="stats three">
      <button className="stat" onClick={() => onFilterRegion(country, admin1)} title={`List datacenters in ${area}`}>
        <strong>{dc.toLocaleString()}</strong>
        <span>datacenters in {area}</span>
      </button>
      <div className="stat">
        <strong>{dams.toLocaleString()}</strong>
        <span>dams in {area}</span>
      </div>
      <div className="stat">
        <strong>{projects.toLocaleString()}</strong>
        <span>{projects === 1 ? "project" : "projects"} in this cell</span>
      </div>
    </div>
  );
}
