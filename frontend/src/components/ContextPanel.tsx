import { useState, type ReactNode } from "react";
import {
  IMAGERY_PRODUCTS,
  searchImageryDays,
  type BoundaryLayerId,
  type Hazard,
  type ImageryDay,
  type ImageryProductId,
  type ImageryState,
} from "../lib/context";
import type { ContextToggles } from "../lib/useContextData";
import type { MapView } from "./WorldMap";

type Status = Record<string, { loading: boolean; error: string | null }>;

type Props = {
  toggles: ContextToggles;
  onToggles: (t: ContextToggles) => void;
  status: Status;
  quakes: Hazard<unknown> | null;
  fires: Hazard<unknown> | null;
  fireHint: string | null;
};

const BOUNDARY_LABEL: Record<BoundaryLayerId, string> = {
  countries: "Countries",
  admin1: "States / provinces",
  us_counties: "US counties",
};

function Note({ s, count }: { s?: { loading: boolean; error: string | null }; count?: number | null }) {
  if (s?.loading) return <span className="muted small right">Loading…</span>;
  if (s?.error) return <span className="warn small right" title={s.error}>Unavailable</span>;
  if (count != null) return <span className="muted small right num">{count.toLocaleString()}</span>;
  return null;
}

export default function ContextPanel({ toggles, onToggles, status, quakes, fires, fireHint }: Props) {
  const set = (patch: Partial<ContextToggles>) => onToggles({ ...toggles, ...patch });
  const fireNote = toggles.fires ? (fireHint ?? (fires?.source.available === false ? fires.source.reason : null)) : null;

  return (
    <section className="panel">
      <h2>Context</h2>

      <h3>Boundaries</h3>
      {(Object.keys(BOUNDARY_LABEL) as BoundaryLayerId[]).map((id) => (
        <label key={id} className="toggle">
          <input
            type="checkbox"
            checked={toggles.boundaries[id]}
            onChange={() => set({ boundaries: { ...toggles.boundaries, [id]: !toggles.boundaries[id] } })}
          />
          <span>{BOUNDARY_LABEL[id]}</span>
          <Note s={status[`boundaries:${id}`]} />
        </label>
      ))}

      <h3>Connectivity &amp; hazards</h3>
      <label className="toggle">
        <input type="checkbox" checked={toggles.cables} onChange={() => set({ cables: !toggles.cables })} />
        <span>Submarine cables</span>
        <Note s={status.cables} />
      </label>
      <label className="toggle">
        <input type="checkbox" checked={toggles.earthquakes} onChange={() => set({ earthquakes: !toggles.earthquakes })} />
        <span>Earthquakes, last 7 days</span>
        <Note s={status.earthquakes} count={toggles.earthquakes ? quakes?.records.length : null} />
      </label>
      <label className="toggle">
        <input type="checkbox" checked={toggles.fires} onChange={() => set({ fires: !toggles.fires })} />
        <span>Active fires, last 24 h</span>
        <Note s={status.fires} count={toggles.fires && fires?.source.available !== false ? fires?.records.length : null} />
      </label>
      {fireNote && <p className="muted small sub">{fireNote}</p>}
    </section>
  );
}

type ImageryProps = {
  imagery: ImageryState | null;
  onImagery: (s: ImageryState | null) => void;
  defaultImageryDate: string;
  view: MapView | null;
  children?: ReactNode;
};

export function ImageryPanel({ imagery, onImagery, defaultImageryDate, view, children }: ImageryProps) {
  const [days, setDays] = useState<ImageryDay[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const product = imagery?.product ?? "VIIRS";
  const spec = IMAGERY_PRODUCTS[product];
  const canSearch = !!spec.cmr && !!view && view.zoom >= 6;

  async function findDays() {
    if (!view || !spec.cmr) return;
    setSearching(true);
    setError(null);
    try {
      setDays(await searchImageryDays(product as "S30" | "L30", view.bounds));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }

  return (
    <section className="panel">
      <h2>Satellite imagery</h2>
      <label className="toggle">
        <input
          type="checkbox"
          checked={!!imagery}
          onChange={() => onImagery(imagery ? null : { product: "VIIRS", date: defaultImageryDate, opacity: 0.9 })}
        />
        <span>True-colour imagery</span>
      </label>
      {imagery && (
        <div className="sub">
          <div className="row">
            <label className="field">
              <span>Product</span>
              <select
                value={imagery.product}
                onChange={(e) => {
                  setDays(null);
                  onImagery({ ...imagery, product: e.target.value as ImageryProductId });
                }}
              >
                {(Object.keys(IMAGERY_PRODUCTS) as ImageryProductId[]).map((id) => (
                  <option key={id} value={id}>
                    {IMAGERY_PRODUCTS[id].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Date</span>
              <input
                type="date"
                value={imagery.date}
                max={defaultImageryDate}
                onChange={(e) => onImagery({ ...imagery, date: e.target.value })}
              />
            </label>
          </div>
          <label className="field">
            <span>Opacity</span>
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={imagery.opacity}
              onChange={(e) => onImagery({ ...imagery, opacity: Number(e.target.value) })}
            />
          </label>
          {spec.cmr && (
            <div className="actions">
              <button disabled={!canSearch || searching} onClick={findDays}>
                {searching ? "Searching…" : "Find clear dates here"}
              </button>
              {!canSearch && <span className="muted small" style={{ alignSelf: "center" }}>Zoom in first</span>}
            </div>
          )}
          {error && <p className="warn small">{error}</p>}
          {days && (
            <ul className="list" style={{ marginTop: 8, maxHeight: 220, overflowY: "auto" }}>
              {days.length === 0 && <li className="muted small">No scenes here in the last 30 days.</li>}
              {days.map((d) => (
                <li key={d.date}>
                  <button
                    className={`link ${d.date === imagery.date ? "selected" : ""}`}
                    onClick={() => onImagery({ ...imagery, date: d.date })}
                  >
                    <span className="num">{d.date}</span>
                    <span className="muted small right">
                      {d.cloudMin === null ? "cloud unknown" : `${Math.round(d.cloudMin)}% cloud`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {children}
    </section>
  );
}
