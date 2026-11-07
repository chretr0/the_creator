import type { ReactNode } from "react";
import type { CablePath, Earthquake, Fire, LandingPoint, PowerFeature } from "../lib/context";
import { formatKw } from "../lib/infrastructure";
import { CONTEXT_LAYER_IDS, type ContextSelection } from "../lib/useContextData";

type Props = {
  selection: NonNullable<ContextSelection>;
  onClose: () => void;
};

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt>{label}</dt>
    <dd>{children}</dd>
  </>
);

const Link = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} target="_blank" rel="noreferrer">
    {children}
  </a>
);

const unknown = <span className="muted">Unknown</span>;

export default function ContextInspector({ selection, onClose }: Props) {
  const { layerId, object } = selection;
  let title: ReactNode = "";
  let kind = "";
  let body: ReactNode = null;

  if (layerId === CONTEXT_LAYER_IDS.cables) {
    const c = (object as CablePath).cable;
    title = c.name;
    kind = "Submarine cable";
    body = (
      <dl className="kv">
        <Row label="More">
          <Link href={c.url}>Cable details</Link>
        </Row>
      </dl>
    );
  } else if (layerId === CONTEXT_LAYER_IDS.landing) {
    const l = (object as LandingPoint).properties;
    title = l.name;
    kind = "Cable landing point";
    body = (
      <dl className="kv">
        <Row label="More">
          <Link href={l.url}>Landing point details</Link>
        </Row>
      </dl>
    );
  } else if (layerId === CONTEXT_LAYER_IDS.quakes) {
    const q = object as Earthquake;
    title = `Magnitude ${q.magnitude?.toFixed(1) ?? "?"}`;
    kind = q.place ?? "Earthquake";
    body = (
      <dl className="kv">
        <Row label="Time (UTC)">{new Date(q.time).toISOString().replace("T", " ").slice(0, 16)}</Row>
        <Row label="Depth">{q.depthKm !== null ? `${q.depthKm.toFixed(0)} km` : unknown}</Row>
        <Row label="Tsunami alert">{q.tsunami ? "Yes" : "No"}</Row>
        {q.url && (
          <Row label="More">
            <Link href={q.url}>Event page</Link>
          </Row>
        )}
      </dl>
    );
  } else if (layerId === CONTEXT_LAYER_IDS.fires) {
    const f = object as Fire;
    title = "Active fire";
    kind = [f.admin1, f.country].filter(Boolean).join(", ") || "Fire detection";
    body = (
      <dl className="kv">
        <Row label="Detected (UTC)">
          {f.acqDate} {f.acqTime.padStart(4, "0").replace(/(\d\d)(\d\d)/, "$1:$2")}
        </Row>
        <Row label="Intensity">{f.frpMw !== null ? `${f.frpMw} MW` : unknown}</Row>
        <Row label="Confidence">{f.confidence ?? unknown}</Row>
      </dl>
    );
  } else if (layerId === CONTEXT_LAYER_IDS.powerPoints || layerId === CONTEXT_LAYER_IDS.powerLines) {
    const p = (object as PowerFeature).properties;
    kind = { plant: "Power plant", substation: "Substation", line: "Power line", cable: "Power cable" }[p.kind];
    title = p.name ?? kind;
    body = (
      <dl className="kv">
        <Row label="Operator">{p.operator ?? unknown}</Row>
        {p.kind === "plant" && (
          <>
            <Row label="Fuel">{p.plantSource ?? unknown}</Row>
            <Row label="Capacity">{p.outputKw !== null ? formatKw(p.outputKw) : unknown}</Row>
          </>
        )}
        {p.kind !== "plant" && (
          <Row label="Voltage">{p.voltageKv.length ? p.voltageKv.map((v) => `${v} kV`).join(", ") : unknown}</Row>
        )}
        <Row label="More">
          <Link href={p.osmUrl}>OpenStreetMap</Link>
        </Row>
      </dl>
    );
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
      <p className="subtitle">{kind}</p>
      {body}
    </section>
  );
}
