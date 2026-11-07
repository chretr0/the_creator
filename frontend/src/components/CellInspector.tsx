import { useEffect, useMemo, useState } from "react";
import { locateCell, type CellInfo, type Project } from "../lib/api";
import { PROJECT_TYPE_BY_ID } from "../lib/projectTypes";
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
};

const fmt = (n: number, d = 5) => n.toFixed(d);

export default function CellInspector(props: Props) {
  const { selection, projectsInCell, onSelectProject } = props;
  const [cell, setCell] = useState<CellInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setCell(null);
    setError(null);
    locateCell(selection.latitude, selection.longitude, ctrl.signal)
      .then(setCell)
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(String(e.message ?? e));
      });
    return () => ctrl.abort();
  }, [selection.latitude, selection.longitude]);

  const matches = cell ? cell.h3Id === selection.h3Id : null;

  return (
    <section className="panel">
      <h2>Cell</h2>
      <dl className="kv">
        <dt>H3 ID</dt>
        <dd className="mono">{selection.h3Id}</dd>
        <dt>Resolution</dt>
        <dd>6 (simulation)</dd>
        <dt>Clicked point</dt>
        <dd className="mono">
          {fmt(selection.latitude)}, {fmt(selection.longitude)}
        </dd>
        {cell && (
          <>
            <dt>Cell centre</dt>
            <dd className="mono">
              {fmt(cell.centre.latitude)}, {fmt(cell.centre.longitude)}
            </dd>
            <dt>Area</dt>
            <dd>{cell.areaKm2.toFixed(2)} km²</dd>
            <dt>Shape</dt>
            <dd>
              {cell.isPentagon ? "pentagon" : "hexagon"} · {cell.neighbours.length} neighbours
            </dd>
            <dt>Backend</dt>
            <dd className={matches ? "ok" : "warn"}>
              {matches ? "same cell ID ✓" : `mismatch: ${cell.h3Id}`}
            </dd>
          </>
        )}
      </dl>
      {error && <p className="warn">Backend lookup failed: {error}</p>}

      <RegionBlock {...props} />
      <WeatherBlock latitude={selection.latitude} longitude={selection.longitude} />
      <PowerBlock {...props} />

      <h3>Baseline data</h3>
      <p className="muted small">
        No measured baseline layers loaded yet. Missing values stay unknown, not zero.
      </p>

      {projectsInCell.length > 0 && (
        <>
          <h3>Projects in this cell</h3>
          <ul className="list">
            {projectsInCell.map((p) => (
              <li key={p.id}>
                <button className="link" onClick={() => onSelectProject(p.id)}>
                  <span className="dot" style={{ background: `rgb(${PROJECT_TYPE_BY_ID[p.type].colour})` }} />
                  {p.name || PROJECT_TYPE_BY_ID[p.type].label}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function RegionBlock({ selection, facilities, onFilterRegion }: Props) {
  const [region, setRegion] = useState<RegionLocate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setRegion(null);
    setError(null);
    locateRegion(selection.latitude, selection.longitude, ctrl.signal)
      .then(setRegion)
      .catch((e) => !ctrl.signal.aborted && setError(String(e.message ?? e)));
    return () => ctrl.abort();
  }, [selection.latitude, selection.longitude]);

  const records = useMemo(() => fromFacilities(facilities), [facilities]);
  const summary = (country: string, admin1: string | null) => {
    const dc = runQuery(records, { dataset: "datacenters", country, admin1, sort: "name", limit: 0 });
    const dams = runQuery(records, { dataset: "dams", country, admin1, sort: "name", limit: 0 });
    return { dc, dams };
  };
  const country = region?.country?.name ?? null;
  const admin1 = region?.admin1?.name ?? null;
  const rows = country
    ? [
        ...(admin1 ? [{ label: admin1, ...summary(country, admin1), admin1 }] : []),
        { label: country, ...summary(country, null), admin1: null },
      ]
    : [];

  return (
    <>
      <h3>Region</h3>
      {error && <p className="warn small">Region lookup failed: {error}</p>}
      {region && (
        <dl className="kv">
          <dt>Country</dt>
          <dd>{region.country?.name ?? <span className="muted">outside country outlines (sea)</span>}</dd>
          {region.admin1 && (
            <>
              <dt>State / province</dt>
              <dd>{region.admin1.name}</dd>
            </>
          )}
          {region.county && (
            <>
              <dt>County</dt>
              <dd>{region.county.name}</dd>
            </>
          )}
        </dl>
      )}
      {rows.length > 0 && (
        <table className="mini">
          <thead>
            <tr>
              <th>Mapped in</th>
              <th>Datacenters</th>
              <th>Dams</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td>
                  <button className="link inline" onClick={() => onFilterRegion(country, r.admin1)}>
                    {r.label}
                  </button>
                </td>
                <td>
                  {r.dc.total.toLocaleString()}
                  {r.dc.operators[0] && <div className="muted small">top: {r.dc.operators[0].name} ({r.dc.operators[0].count})</div>}
                </td>
                <td>
                  {r.dams.total.toLocaleString()}
                  {r.dams.metric.sum !== null && (
                    <div className="muted small">
                      {formatKw(r.dams.metric.sum)} rated ({r.dams.metric.withValue} tagged)
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {region && (
        <p className="muted small">
          Counts are features mapped in OSM, not complete inventories. Outlines are simplified, so points
          near a border can fall in the neighbour.
        </p>
      )}
    </>
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
        <button onClick={() => setRequested(true)}>Load forecast for this point</button>
      ) : (
        <>
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
          {error && <p className="warn small">{error}</p>}
          {!weather && !error && <p className="muted small">Loading…</p>}
          {weather && (
            <dl className="kv">
              <dt>Now (model)</dt>
              <dd>
                {fmt1(weather.temperatureC, "°C")} · wind 10 m {fmt1(weather.windSpeed10m, "m/s")}
                {weather.windDirection10m !== null && ` from ${Math.round(weather.windDirection10m)}°`}
              </dd>
              <dt>Next 24 h</dt>
              <dd>
                {fmt1(weather.next24h.tempMinC, "°C")} to {fmt1(weather.next24h.tempMaxC, "°C")}
              </dd>
              <dt>Wind 100 m, 24 h</dt>
              <dd>
                mean {fmt1(weather.next24h.wind100mMean, "m/s")} · max {fmt1(weather.next24h.wind100mMax, "m/s")}
              </dd>
              <dt>Valid</dt>
              <dd className="mono">{weather.time}Z</dd>
            </dl>
          )}
          <p className="muted small">
            Model forecast for one point (not an observation). A day of forecast wind says nothing about
            annual wind resource. Cooling and heat-reuse assumptions need climatology.{" "}
            <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">
              Weather data by Open-Meteo.com
            </a>{" "}
            (CC BY 4.0).
          </p>
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
      <h3>Electricity infrastructure (OSM)</h3>
      <div className="actions">
        <button disabled={powerStatus?.loading} onClick={() => onLoadPower(selection.latitude, selection.longitude)}>
          {powerStatus?.loading ? "Querying Overpass…" : here ? "Reload within 10 km" : "Show within 10 km"}
        </button>
        {power && (
          <button className="ghost" onClick={onClearPower}>
            Clear
          </button>
        )}
      </div>
      {powerStatus?.error && <p className="warn small">{powerStatus.error}</p>}
      {power && (
        <p className="small">
          {here ? "Around this point" : "Loaded area elsewhere"}: {counts.plant ?? 0} plants, {counts.substation ?? 0}{" "}
          substations, {(counts.line ?? 0) + (counts.cable ?? 0)} line segments.
          {ratedN > 0 && (
            <>
              {" "}
              Tagged plant nameplate: {formatKw(ratedKw)} ({ratedN} of {plants.length} plants tagged).
            </>
          )}
          {power.source.stale && <span className="warn"> Cached copy (Overpass unreachable).</span>}
        </p>
      )}
      <p className="muted small">
        Mapped routes and nameplate ratings only. This does not show grid headroom or which plant would
        supply a project.
      </p>
    </>
  );
}
