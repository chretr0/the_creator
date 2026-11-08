import { useEffect, useMemo, useState } from "react";
import { loadPower, voltageColour, type PowerFeature, type PowerResult } from "../lib/context";
import { formatKw } from "../lib/infrastructure";
import Icon from "./Icon";

type Props = {
  latitude: number;
  longitude: number;
  /** The grid drawn on the map right now, if any. */
  onMap: PowerResult | null;
  onShowOnMap: (result: PowerResult | null) => void;
  onGoTo: (lat: number, lon: number) => void;
};

const RADIUS_KM = 10;

const VOLTAGE_CLASSES = [
  { label: "330 kV+", min: 330 },
  { label: "220 kV", min: 220 },
  { label: "110 kV", min: 110 },
  { label: "50 kV", min: 50 },
  { label: "Under 50 kV", min: 0.001 },
  { label: "Unknown", min: 0 },
];

function km(lat1: number, lon1: number, lat2: number, lon2: number) {
  const r = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * r) / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

const where = (f: PowerFeature) => (f.geometry.type === "Point" ? f.geometry.coordinates : null);
const kvLabel = (kv: number[]) => (kv.length ? `${Math.max(...kv).toLocaleString()} kV` : null);
const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

/** The mapped electricity grid within 10 km, fetched as soon as the location is picked. */
export default function PowerGridCard({ latitude, longitude, onMap, onShowOnMap, onGoTo }: Props) {
  const [grid, setGrid] = useState<PowerResult | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setGrid(null);
    setError(false);
    loadPower(latitude, longitude, RADIUS_KM, ctrl.signal)
      .then(setGrid)
      .catch(() => !ctrl.signal.aborted && setError(true));
    return () => ctrl.abort();
  }, [latitude, longitude, attempt]);

  const summary = useMemo(() => {
    if (!grid) return null;
    const near = (f: PowerFeature) => {
      const p = where(f);
      return p ? km(latitude, longitude, p[1], p[0]) : null;
    };
    const byDistance = (kind: PowerFeature["properties"]["kind"]) =>
      grid.features
        .filter((f) => f.properties.kind === kind)
        .map((f) => ({ f, d: near(f) }))
        .sort((a, b) => (a.d ?? Infinity) - (b.d ?? Infinity));
    const lines = grid.features.filter((f) => f.properties.kind === "line" || f.properties.kind === "cable");
    const classes = VOLTAGE_CLASSES.map((c, i) => {
      const upper = i === 0 ? Infinity : VOLTAGE_CLASSES[i - 1].min;
      const n = lines.filter((f) => {
        const v = Math.max(0, ...f.properties.voltageKv);
        return c.min === 0 ? v === 0 : v >= c.min && v < upper;
      }).length;
      const rgb = voltageColour(c.min === 0 ? [] : [c.min]);
      return { ...c, n, colour: `rgb(${rgb.join(",")})` };
    }).filter((c) => c.n > 0);
    const plants = byDistance("plant");
    const allKv = grid.features.flatMap((f) => f.properties.voltageKv);
    const operators = new Map<string, number>();
    for (const f of grid.features) {
      const o = f.properties.operator;
      if (o) operators.set(o, (operators.get(o) ?? 0) + 1);
    }
    return {
      substations: byDistance("substation"),
      plants,
      ratedKw: plants.reduce((a, p) => a + (p.f.properties.outputKw ?? 0), 0),
      lineCount: lines.length,
      classes,
      maxKv: allKv.length ? Math.max(...allKv) : null,
      operators: [...operators.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([o]) => o),
    };
  }, [grid, latitude, longitude]);

  if (error)
    return (
      <div className="insight-card">
        <p className="muted small">The grid around this point couldn’t be loaded.</p>
        <button className="chip" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </div>
    );
  if (!grid || !summary)
    return (
      <div className="insight-card loading" aria-busy="true">
        <p className="muted small loading-note"><span className="pulse-dot" /> Mapping substations, lines and plants within {RADIUS_KM} km… this can take up to half a minute.</p>
        <div className="mini-stats">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 62 }} />)}
        </div>
        <div className="skeleton" style={{ height: 10, marginTop: 14 }} />
      </div>
    );

  const shown = onMap !== null && onMap.centre.lat === grid.centre.lat && onMap.centre.lon === grid.centre.lon;
  const nearestSub = summary.substations[0];

  if (grid.features.length === 0)
    return (
      <div className="insight-card">
        <p className="empty-note">No mapped substations, lines or power plants within {RADIUS_KM} km.</p>
      </div>
    );

  return (
    <div className="insight-card power-card">
      <div className="mini-stats">
        <div className="mini-stat">
          <strong>{summary.substations.length.toLocaleString()}</strong>
          <span>substations</span>
        </div>
        <div className="mini-stat">
          <strong>{summary.lineCount.toLocaleString()}</strong>
          <span>line segments</span>
        </div>
        <div className="mini-stat">
          <strong>{summary.plants.length.toLocaleString()}</strong>
          <span>{summary.ratedKw > 0 ? `plants · ${formatKw(summary.ratedKw)}` : "power plants"}</span>
        </div>
      </div>

      <div className="grid-highlights">
        {nearestSub?.d != null && (
          <div>
            <span className="muted">Nearest substation</span>
            <strong>{nearestSub.d < 1 ? `${Math.round(nearestSub.d * 1000)} m` : `${nearestSub.d.toFixed(1)} km`}</strong>
          </div>
        )}
        {summary.maxKv !== null && (
          <div>
            <span className="muted">Highest voltage</span>
            <strong>{summary.maxKv.toLocaleString()} kV</strong>
          </div>
        )}
      </div>

      {summary.classes.length > 0 && (
        <>
          <div className="stack voltage-stack" role="img" aria-label="Line segments by voltage">
            {summary.classes.map((c) => (
              <span key={c.label} style={{ flexGrow: c.n, background: c.colour }} title={`${c.label}: ${c.n}`} />
            ))}
          </div>
          <ul className="legend data-legend">
            {summary.classes.map((c) => (
              <li key={c.label}>
                <span className="swatch" style={{ background: c.colour }} />
                {c.label} <span className="muted">{c.n}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {summary.substations.length > 0 && (
        <>
          <h4 className="card-subhead">Closest substations</h4>
          <ul className="place-list">
            {summary.substations.slice(0, 4).map(({ f, d }) => {
              const p = where(f);
              return (
                <li key={f.id}>
                  <button className="link" disabled={!p} onClick={() => p && onGoTo(p[1], p[0])}>
                    <Icon name="pylon" size={16} />
                    <span className="place-name">
                      {f.properties.name ?? "Unnamed substation"}
                      <span className="muted small">{[kvLabel(f.properties.voltageKv), f.properties.operator].filter(Boolean).join(" · ")}</span>
                    </span>
                    {d != null && <span className="muted small dist">{d.toFixed(1)} km</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {summary.plants.length > 0 && (
        <>
          <h4 className="card-subhead">Power plants</h4>
          <ul className="place-list">
            {summary.plants.slice(0, 4).map(({ f, d }) => {
              const p = where(f);
              return (
                <li key={f.id}>
                  <button className="link" disabled={!p} onClick={() => p && onGoTo(p[1], p[0])}>
                    <Icon name={f.properties.plantSource === "solar" ? "sun" : f.properties.plantSource === "wind" ? "wind" : f.properties.plantSource === "hydro" ? "dam" : "factory"} size={16} />
                    <span className="place-name">
                      {f.properties.name ?? "Unnamed plant"}
                      <span className="muted small">
                        {[f.properties.plantSource && titleCase(f.properties.plantSource), f.properties.outputKw ? formatKw(f.properties.outputKw) : null].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    {d != null && <span className="muted small dist">{d.toFixed(1)} km</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {summary.operators.length > 0 && <p className="muted small operators">Operated by {summary.operators.join(", ")}</p>}

      <button className={shown ? "chip on" : "chip"} onClick={() => onShowOnMap(shown ? null : grid)} aria-pressed={shown}>
        <Icon name="map" size={14} /> {shown ? "Hide grid from map" : "Show grid on map"}
      </button>
    </div>
  );
}
