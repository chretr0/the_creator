import { PanelTabs } from "./PanelNavigation";
import { useEffect, useMemo, useState } from "react";
import { cellArea, cellToBoundary, cellToChildrenSize, getResolution, UNITS } from "h3-js";
import { SIMULATION_RESOLUTION } from "../lib/h3grid";
import type { Project } from "../lib/api";
import { typeColour, typeLabel } from "../lib/projectTypes";
import {
  loadWeather,
  locateRegion,
  WEATHER_MODELS,
  type PointWeather,
  type PowerResult,
  type RegionLocate,
  type WeatherModel,
} from "../lib/context";
import { formatKw, type Facility } from "../lib/infrastructure";
import { fromFacilities, runQuery } from "../lib/query";
import BaselineBlock from "./BaselineBlock";
import type { FeatureLayerMeta } from "../lib/datalayers";

export type CellSelection = { h3Id: string; latitude: number; longitude: number };

type Props = {
  selection: CellSelection;
  projectsInCell: Project[];
  onSelectProject: (id: string) => void;
  facilities: Facility[];
  power: PowerResult | null;
  powerStatus?: { loading: boolean; error: string | null };
  onLoadPower: (lat: number, lon: number) => void;
  onClearPower: () => void;
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
  const [view, setView] = useState<"overview" | "data" | "weather" | "power">("overview");
  const [region, setRegion] = useState<RegionLocate | null>(null);
  const [regionError, setRegionError] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setRegion(null);
    setRegionError(false);
    locateRegion(selection.latitude, selection.longitude, ctrl.signal)
      .then(setRegion)
      .catch(() => !ctrl.signal.aborted && setRegionError(true));
    return () => ctrl.abort();
  }, [selection.latitude, selection.longitude]);

  const place = region
    ? [region.county?.name, region.admin1?.name, region.country?.name].filter(Boolean).join(", ") || "Open water"
    : regionError
      ? "Selected location"
      : "Locating…";
  const area = cellArea(selection.h3Id, UNITS.km2);
  const res = getResolution(selection.h3Id);
  const coarse = res < SIMULATION_RESOLUTION;

  return (
    <section className="panel">
      <h2>{coarse ? `Hexagon · ${place}` : place}</h2>
      <p className="subtitle num">
        {coord(selection.latitude, selection.longitude)} · {Math.round(area).toLocaleString()} km²{" "}
        {coarse ? `hexagon (resolution ${res})` : "cell"}
      </p>
      <PanelTabs label="Location sections" value={view} onChange={setView} options={[
        { value: "overview", label: "Overview" }, { value: "data", label: "Data" }, { value: "weather", label: "Weather" }, { value: "power", label: "Power grid" },
      ]} />
      <div hidden={view !== "overview"}>
      {coarse && (
        <>
          <p className="muted small">
            Values below combine the {cellToChildrenSize(selection.h3Id, SIMULATION_RESOLUTION).toLocaleString()}{" "}
            simulation cells inside it: the mean (totals as density, land cover as the most common class) of the
            cells that have data.
          </p>
          <div className="actions tight">
            <button className="chip" onClick={() => props.onZoomToCell(cellBBox(selection.h3Id))}>
              Zoom to hexagon
            </button>
            <button className="chip" onClick={props.onSelectSimulationCell}>
              Inspect the simulation cell here
            </button>
          </div>
        </>
      )}

      <RegionStats region={region} facilities={props.facilities} onFilterRegion={props.onFilterRegion} />

      {projectsInCell.length > 0 && (
        <>
          <h3>Projects here</h3>
          <ul className="list">
            {projectsInCell.map((p) => (
              <li key={p.id}>
                <button className="link" onClick={() => onSelectProject(p.id)}>
                  <span className="dot" style={{ background: `rgb(${typeColour(p.type).join(",")})` }} />
                  {p.name || typeLabel(p.type)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <button className="primary" style={{ marginTop: 16 }} onClick={() => setView("data")}>Explore this location’s data</button>
      </div>
      <div hidden={view !== "data"}>
      <BaselineBlock
        h3Id={selection.h3Id}
        manifest={props.featureManifest}
        onShowLayer={props.onShowLayer}
        onGoTo={props.onGoTo}
      />

      </div>
      <div hidden={view !== "weather"}><WeatherBlock latitude={selection.latitude} longitude={selection.longitude} /></div>
      <div hidden={view !== "power"}><PowerBlock {...props} /></div>

      <p className="muted small mono" style={{ marginTop: 20 }}>
        Cell {selection.h3Id}
      </p>
    </section>
  );
}

function RegionStats({
  region,
  facilities,
  onFilterRegion,
}: {
  region: RegionLocate | null;
  facilities: Facility[];
  onFilterRegion: Props["onFilterRegion"];
}) {
  const records = useMemo(() => fromFacilities(facilities), [facilities]);
  const country = region?.country?.name ?? null;
  if (!country) return null;
  const admin1 = region?.admin1?.name ?? null;
  const area = admin1 ?? country;
  const dc = runQuery(records, { dataset: "datacenters", country, admin1, sort: "name", limit: 0 }).total;
  const dams = runQuery(records, { dataset: "dams", country, admin1, sort: "name", limit: 0 }).total;

  return (
    <div className="stats">
      <button className="stat" onClick={() => onFilterRegion(country, admin1)} title={`List datacenters in ${area}`}>
        <strong>{dc.toLocaleString()}</strong>
        <span>datacenters in {area}</span>
      </button>
      <div className="stat" style={{ display: "flex" }}>
        <strong>{dams.toLocaleString()}</strong>
        <span>dams in {area}</span>
      </div>
    </div>
  );
}

const fmt1 = (v: number | null, unit: string) => (v === null ? "—" : `${v.toFixed(1)} ${unit}`);

function WeatherBlock({ latitude, longitude }: { latitude: number; longitude: number }) {
  const [model, setModel] = useState<WeatherModel>("gfs_seamless");
  const [weather, setWeather] = useState<PointWeather | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);

  useEffect(() => {
    setWeather(null);
    setError(null);
    setRequested(false);
  }, [latitude, longitude]);

  useEffect(() => {
    if (!requested) return;
    const ctrl = new AbortController();
    setWeather(null);
    setError(null);
    loadWeather(latitude, longitude, model, ctrl.signal)
      .then(setWeather)
      .catch((e) => !ctrl.signal.aborted && setError(String(e.message ?? e)));
    return () => ctrl.abort();
  }, [requested, latitude, longitude, model]);

  return (
    <>
      <h3>Weather forecast</h3>
      {!requested ? (
        <button onClick={() => setRequested(true)}>Show forecast</button>
      ) : (
        <>
          {error && <p className="warn small">{error}</p>}
          {!weather && !error && <p className="muted small">Loading…</p>}
          {weather && (
            <dl className="kv">
              <dt>Now</dt>
              <dd>
                {fmt1(weather.temperatureC, "°C")}, wind {fmt1(weather.windSpeed10m, "m/s")}
              </dd>
              <dt>Next 24 h</dt>
              <dd>
                {fmt1(weather.next24h.tempMinC, "°C")} to {fmt1(weather.next24h.tempMaxC, "°C")}
              </dd>
              <dt>Wind at 100 m</dt>
              <dd>
                avg {fmt1(weather.next24h.wind100mMean, "m/s")}, max {fmt1(weather.next24h.wind100mMax, "m/s")}
              </dd>
            </dl>
          )}
          <label className="field">
            <span>Model</span>
            <select value={model} onChange={(e) => setModel(e.target.value as WeatherModel)}>
              {(Object.keys(WEATHER_MODELS) as WeatherModel[]).map((m) => (
                <option key={m} value={m}>
                  {WEATHER_MODELS[m]}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
    </>
  );
}

function PowerBlock({ selection, power, powerStatus, onLoadPower, onClearPower }: Props) {
  const here =
    power && Math.abs(power.centre.lat - selection.latitude) < 1e-9 && Math.abs(power.centre.lon - selection.longitude) < 1e-9;
  const counts = power
    ? power.features.reduce<Record<string, number>>((acc, f) => ({ ...acc, [f.properties.kind]: (acc[f.properties.kind] ?? 0) + 1 }), {})
    : {};
  const plants = power?.features.filter((f) => f.properties.kind === "plant") ?? [];
  const ratedKw = plants.reduce((a, f) => a + (f.properties.outputKw ?? 0), 0);
  const ratedN = plants.filter((f) => f.properties.outputKw !== null).length;

  return (
    <>
      <h3>Power grid within 10 km</h3>
      {here ? (
        <>
          <dl className="kv">
            <dt>Power plants</dt>
            <dd>
              {counts.plant ?? 0}
              {ratedN > 0 && <span className="muted"> · {formatKw(ratedKw)} capacity</span>}
            </dd>
            <dt>Substations</dt>
            <dd>{counts.substation ?? 0}</dd>
            <dt>Line segments</dt>
            <dd>{(counts.line ?? 0) + (counts.cable ?? 0)}</dd>
          </dl>
          <div className="actions">
            <button className="ghost" onClick={onClearPower} style={{ paddingLeft: 0 }}>
              Hide from map
            </button>
          </div>
        </>
      ) : (
        <button disabled={powerStatus?.loading} onClick={() => onLoadPower(selection.latitude, selection.longitude)}>
          {powerStatus?.loading ? "Loading…" : "Show power grid"}
        </button>
      )}
      {powerStatus?.error && <p className="warn small">{powerStatus.error}</p>}
    </>
  );
}
