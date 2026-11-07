import { useState } from "react";
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
  imagery: ImageryState | null;
  onImagery: (s: ImageryState | null) => void;
  defaultImageryDate: string;
  view: MapView | null;
};

const BOUNDARY_LABEL: Record<BoundaryLayerId, [string, string]> = {
  countries: ["Countries", "all zooms"],
  admin1: ["States / provinces", "zoom ≥ 3"],
  us_counties: ["US counties", "zoom ≥ 5"],
};

function StatusNote({ s }: { s?: { loading: boolean; error: string | null } }) {
  if (!s) return null;
  if (s.loading) return <span className="muted small right">loading…</span>;
  if (s.error) return <span className="warn small right" title={s.error}>failed</span>;
  return null;
}

const fmtTime = (iso?: string) => (iso ? iso.replace("T", " ").replace("+00:00", "Z") : "");

export default function ContextPanel(props: Props) {
  const { toggles, onToggles, status } = props;
  const set = (patch: Partial<ContextToggles>) => onToggles({ ...toggles, ...patch });

  return (
    <section className="panel">
      <h2>Context layers</h2>

      <h3>Boundaries</h3>
      {(Object.keys(BOUNDARY_LABEL) as BoundaryLayerId[]).map((id) => (
        <label key={id} className="toggle">
          <input
            type="checkbox"
            checked={toggles.boundaries[id]}
            onChange={() => set({ boundaries: { ...toggles.boundaries, [id]: !toggles.boundaries[id] } })}
          />
          <span>{BOUNDARY_LABEL[id][0]}</span>
          <StatusNote s={status[`boundaries:${id}`]} />
          <span className="muted small right">{BOUNDARY_LABEL[id][1]}</span>
        </label>
      ))}

      <h3>Connectivity</h3>
      <label className="toggle">
        <input type="checkbox" checked={toggles.cables} onChange={() => set({ cables: !toggles.cables })} />
        <span>Submarine cables & landing points</span>
        <StatusNote s={status.cables} />
      </label>
      {toggles.cables && (
        <p className="warn small">
          © TeleGeography, CC BY-NC-SA 3.0: non-commercial use only. Remove this layer before any commercial
          use. Owners and capacity are not in the public data.
        </p>
      )}

      <h3>Hazards</h3>
      <label className="toggle">
        <input type="checkbox" checked={toggles.earthquakes} onChange={() => set({ earthquakes: !toggles.earthquakes })} />
        <span>Earthquakes M2.5+, last 7 days</span>
        <StatusNote s={status.earthquakes} />
      </label>
      {toggles.earthquakes && props.quakes && (
        <p className="muted small">
          {props.quakes.records.length} events · USGS · retrieved {fmtTime(props.quakes.source.retrievedAt)}
          {props.quakes.source.stale && <span className="warn"> · cached copy (USGS unreachable)</span>}
        </p>
      )}
      <label className="toggle">
        <input type="checkbox" checked={toggles.fires} onChange={() => set({ fires: !toggles.fires })} />
        <span>Active fires (VIIRS, 24 h)</span>
        <StatusNote s={status.fires} />
      </label>
      {toggles.fires && (
        <p className="muted small">
          {props.fireHint ??
            (props.fires?.source.available === false
              ? props.fires.source.reason
              : props.fires
                ? `${props.fires.records.length} detections in view · NASA FIRMS · retrieved ${fmtTime(props.fires.source.retrievedAt)}${props.fires.source.stale ? " (cached)" : ""}`
                : "")}
        </p>
      )}

      <ImageryControls {...props} />
    </section>
  );
}

function ImageryControls({ imagery, onImagery, defaultImageryDate, view }: Props) {
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
    <>
      <h3>Satellite imagery</h3>
      <label className="toggle">
        <input
          type="checkbox"
          checked={!!imagery}
          onChange={() => onImagery(imagery ? null : { product: "VIIRS", date: defaultImageryDate, opacity: 0.9 })}
        />
        <span>NASA GIBS true colour</span>
      </label>
      {imagery && (
        <>
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
              <span>Date (UTC)</span>
              <input type="date" value={imagery.date} max={defaultImageryDate} onChange={(e) => onImagery({ ...imagery, date: e.target.value })} />
            </label>
          </div>
          <label className="field">
            <span>Opacity {Math.round(imagery.opacity * 100)}%</span>
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={imagery.opacity}
              onChange={(e) => onImagery({ ...imagery, opacity: Number(e.target.value) })}
            />
          </label>
          <p className="muted small">
            {spec.sensor} · {spec.resolution}.{" "}
            {spec.cmr
              ? "Sentinel-2/Landsat only cover a place every few days; blank tiles mean no scene that day."
              : "Daily global mosaic with swath gaps and clouds."}{" "}
            Visual context only: nothing here is classified or detected.
          </p>
          {spec.cmr && (
            <div className="actions">
              <button disabled={!canSearch || searching} onClick={findDays}>
                {searching ? "Searching…" : "Find dates over this view (30 days)"}
              </button>
              {!canSearch && <span className="muted small">zoom to ≥ 6 first</span>}
            </div>
          )}
          {error && <p className="warn small">{error}</p>}
          {days && (
            <ul className="list day-list">
              {days.length === 0 && <li className="muted small">No {spec.label} scenes over this view in 30 days.</li>}
              {days.map((d) => (
                <li key={d.date}>
                  <button
                    className={`link ${d.date === imagery.date ? "selected" : ""}`}
                    onClick={() => onImagery({ ...imagery, date: d.date })}
                  >
                    <span className="mono">{d.date}</span>
                    <span className="muted small right">
                      {d.granules} scene{d.granules > 1 ? "s" : ""} ·{" "}
                      {d.cloudMin === null
                        ? "cloud unknown"
                        : d.cloudMin === d.cloudMax
                          ? `${Math.round(d.cloudMin)}% cloud`
                          : `${Math.round(d.cloudMin)}–${Math.round(d.cloudMax!)}% cloud`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}
