import type { CablePath, Earthquake, Fire, Hazard, LandingPoint, PowerFeature, PowerResult } from "../lib/context";
import { formatKw } from "../lib/infrastructure";
import { CONTEXT_LAYER_IDS, type ContextSelection } from "../lib/useContextData";

type Props = {
  selection: NonNullable<ContextSelection>;
  quakeSource: Hazard<Earthquake>["source"] | null;
  fireSource: Hazard<Fire>["source"] | null;
  powerSource: PowerResult["source"] | null;
  onClose: () => void;
};

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <>
    <dt>{label}</dt>
    <dd>{children}</dd>
  </>
);

const Link = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} target="_blank" rel="noreferrer">
    {children}
  </a>
);

const notTagged = <span className="muted">not tagged</span>;

export default function ContextInspector({ selection, quakeSource, fireSource, powerSource, onClose }: Props) {
  const { layerId, object } = selection;
  let title = "";
  let body: React.ReactNode = null;
  let source: React.ReactNode = null;

  if (layerId === CONTEXT_LAYER_IDS.cables) {
    const c = (object as CablePath).cable;
    title = "Submarine cable";
    body = (
      <>
        <p>
          <strong>{c.name}</strong>
        </p>
        <dl className="kv">
          <Row label="Owners">
            <span className="muted">not in the public data (TeleGeography licenses it separately)</span>
          </Row>
          <Row label="Details">
            <Link href={c.url}>submarinecablemap.com ↗</Link>
          </Row>
        </dl>
      </>
    );
    source = "© TeleGeography — submarinecablemap.com · CC BY-NC-SA 3.0 (non-commercial). Route is schematic, not a surveyed seabed position.";
  } else if (layerId === CONTEXT_LAYER_IDS.landing) {
    const l = (object as LandingPoint).properties;
    title = "Cable landing point";
    body = (
      <>
        <p>
          <strong>{l.name}</strong>
          {l.isTbd && <span className="muted"> · location to be determined</span>}
        </p>
        <dl className="kv">
          <Row label="Location">
            <span className="mono">
              {l.lat.toFixed(4)}, {l.lon.toFixed(4)}
            </span>
          </Row>
          <Row label="Details">
            <Link href={l.url}>submarinecablemap.com ↗</Link>
          </Row>
        </dl>
      </>
    );
    source = "© TeleGeography — submarinecablemap.com · CC BY-NC-SA 3.0 (non-commercial).";
  } else if (layerId === CONTEXT_LAYER_IDS.quakes) {
    const q = object as Earthquake;
    title = "Earthquake";
    body = (
      <>
        <p>
          <strong>
            M{q.magnitude?.toFixed(1) ?? "?"} {q.magType ? `(${q.magType})` : ""}
          </strong>{" "}
          · {q.place}
        </p>
        <dl className="kv">
          <Row label="Time (UTC)">{new Date(q.time).toISOString().replace("T", " ").slice(0, 19)}</Row>
          <Row label="Depth">{q.depthKm !== null ? `${q.depthKm.toFixed(1)} km` : "unknown"}</Row>
          <Row label="Review status">{q.status ?? "unknown"}</Row>
          <Row label="Tsunami flag">{q.tsunami ? "yes" : "no"}</Row>
          <Row label="Region">{[q.admin1, q.country].filter(Boolean).join(", ") || <span className="muted">offshore / outside outlines</span>}</Row>
          {q.url && (
            <Row label="Event page">
              <Link href={q.url}>USGS ↗</Link>
            </Row>
          )}
        </dl>
      </>
    );
    source = `${quakeSource?.attribution ?? "USGS"} · retrieved ${quakeSource?.retrievedAt ?? "?"}${quakeSource?.stale ? " (cached copy)" : ""}. Automatic solutions are revised after review.`;
  } else if (layerId === CONTEXT_LAYER_IDS.fires) {
    const f = object as Fire;
    title = "Active-fire detection";
    body = (
      <dl className="kv">
        <Row label="Acquired (UTC)">
          {f.acqDate} {f.acqTime.padStart(4, "0").replace(/(\d\d)(\d\d)/, "$1:$2")} · {f.dayNight === "D" ? "day" : "night"}
        </Row>
        <Row label="Fire radiative power">{f.frpMw !== null ? `${f.frpMw} MW` : "unknown"}</Row>
        <Row label="Confidence">{f.confidence ?? "unknown"}</Row>
        <Row label="Satellite">{f.satellite ?? "unknown"}</Row>
        <Row label="Region">{[f.admin1, f.country].filter(Boolean).join(", ") || "—"}</Row>
      </dl>
    );
    source = `${fireSource?.attribution ?? "NASA FIRMS"} A detection is a thermal anomaly in a 375 m pixel, not a fire perimeter; industrial heat can appear.`;
  } else if (layerId === CONTEXT_LAYER_IDS.powerPoints || layerId === CONTEXT_LAYER_IDS.powerLines) {
    const p = (object as PowerFeature).properties;
    title = { plant: "Power plant", substation: "Substation", line: "Power line", cable: "Power cable" }[p.kind];
    body = (
      <>
        <p>
          <strong>{p.name ?? <span className="muted">unnamed</span>}</strong>
        </p>
        <dl className="kv">
          <Row label="Operator">{p.operator ?? notTagged}</Row>
          <Row label="Owner">{p.owner ?? notTagged}</Row>
          {p.kind === "plant" && (
            <>
              <Row label="Source">{p.plantSource ?? notTagged}</Row>
              <Row label="Nameplate output">
                {p.outputKw !== null ? formatKw(p.outputKw) : p.outputRaw ? <span className="muted">{p.outputRaw} (unparsed)</span> : notTagged}
              </Row>
            </>
          )}
          {p.kind !== "plant" && (
            <Row label="Voltage">{p.voltageKv.length ? p.voltageKv.map((v) => `${v} kV`).join(", ") : notTagged}</Row>
          )}
          <Row label="Record">
            <Link href={p.osmUrl}>OpenStreetMap ↗</Link>
          </Row>
        </dl>
        <p className="muted small">
          Nameplate output is not actual generation. A mapped line shows a route, not spare capacity or
          whether a site could connect to it.
        </p>
      </>
    );
    source = `© OpenStreetMap contributors via Overpass · retrieved ${powerSource?.retrievedAt ?? "?"}${powerSource?.stale ? " (cached copy)" : ""}`;
  } else {
    return null;
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <button className="ghost" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      {body}
      <p className="muted small">{source}</p>
    </section>
  );
}
