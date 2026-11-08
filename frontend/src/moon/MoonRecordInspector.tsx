import type { ReactNode } from "react";
import Icon from "../components/Icon";
import { EVIDENCE_LABEL } from "../lib/datalayers";
import type { SourceCredit } from "../lib/context";
import type { MissionFeature, MoonSite } from "./api";
import { formatLatLon, UNKNOWN } from "./geo";
import { beyondMapEdge, MISSION_COLOUR, missionPosition, rgb, siteKindMeta } from "./layers";

export type MoonRecord = { kind: "site"; feature: MoonSite } | { kind: "mission"; feature: MissionFeature };

export const recordId = (r: MoonRecord | null) => r?.feature.properties.id ?? null;

const evidence = (e: string | null | undefined) => (e ? (EVIDENCE_LABEL[e] ?? e.replace(/_/g, " ")) : UNKNOWN);
const text = (v: string | null | undefined) => (v && v.trim() ? v : UNKNOWN);

type Props = {
  record: MoonRecord;
  sources: SourceCredit[];
  onClose: () => void;
  onZoomTo: (lat: number, lon: number) => void;
};

/** A landed object or a planned mission, with its provenance. */
export default function MoonRecordInspector({ record, sources, onClose, onZoomTo }: Props) {
  const p = record.feature.properties;
  const source = sources.find((s) => s.id === p.sourceId) ?? sources.find((s) => p.sourceId?.startsWith(s.id)) ?? null;
  const position: [number, number] | null =
    record.kind === "site" ? [record.feature.geometry.coordinates[0], record.feature.geometry.coordinates[1]] : missionPosition(record.feature);
  const colour = record.kind === "site" ? siteKindMeta(record.feature.properties.kind).colour : MISSION_COLOUR[record.feature.properties.kind] ?? MISSION_COLOUR.planned_mission;
  const kindLabel =
    record.kind === "site"
      ? siteKindMeta(record.feature.properties.kind).label
      : record.feature.properties.kind === "artemis_region"
        ? "Artemis candidate region"
        : "Planned mission";

  return (
    <section className="panel moon-record">
      <div className="panel-head">
        <div>
          <span className="moon-record-kind">
            <span className="dot" style={{ background: rgb(colour) }} />
            {kindLabel}
          </span>
          <h2>{p.name}</h2>
        </div>
        <button className="ghost" onClick={onClose} aria-label="Close record">
          ✕
        </button>
      </div>

      {record.kind === "site" ? <SiteFields site={record.feature} /> : <MissionFields mission={record.feature} />}

      <dl className="kv small">
        <dt>Location</dt>
        <dd className="num">
          {position ? formatLatLon(position[1], position[0]) : "Not published"}
          {record.kind === "mission" && record.feature.properties.approximate && position && <span className="tag moon-approx-tag">approximate</span>}
        </dd>
      </dl>
      {position && beyondMapEdge(position[1]) && (
        <p className="coarse-note small">This lies beyond the map’s ±85° edge; a polar view comes next.</p>
      )}
      {position && !beyondMapEdge(position[1]) && (
        <div className="actions tight">
          <button className="chip" onClick={() => onZoomTo(position[1], position[0])}>
            <Icon name="pin" size={13} /> Zoom to
          </button>
        </div>
      )}

      <h3 className="moon-provenance-title">Provenance</h3>
      <dl className="kv small">
        <dt>Source</dt>
        <dd>
          <span className="mono">{p.sourceId ?? UNKNOWN}</span>
          {source && <span className="block muted">{source.name}</span>}
        </dd>
        <dt>Evidence</dt>
        <dd>{evidence(p.evidenceType)}</dd>
        {source?.licence && (
          <>
            <dt>Licence</dt>
            <dd>{source.licence}</dd>
          </>
        )}
        {source?.url && (
          <>
            <dt>Link</dt>
            <dd>
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.url.replace(/^https?:\/\//, "")}
              </a>
            </dd>
          </>
        )}
      </dl>
      {source?.limitations?.length ? (
        <ul className="limitations small muted moon-limitations">
          {source.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function SiteFields({ site }: { site: MoonSite }) {
  const p = site.properties;
  return (
    <>
      <dl className="kv small">
        <Row label="Mission">{text(p.mission)}</Row>
        <Row label="Date">
          {text(p.date)}
          {p.dateNote && <span className="block muted">{p.dateNote}</span>}
        </Row>
        <Row label="Elevation">
          {p.elevationM != null && Number.isFinite(p.elevationM) ? (
            <>
              {p.elevationM > 0 ? "+" : ""}
              {Math.round(p.elevationM).toLocaleString()} m<span className="block muted">vs the 1,737.4 km reference sphere</span>
            </>
          ) : (
            UNKNOWN
          )}
        </Row>
        <Row label="Position error">{text(p.uncertainty)}</Row>
        <Row label="Heritage">
          {p.heritage === "landing"
            ? "Landing site · keep landers 2.0 km away"
            : p.heritage === "impact"
              ? "Impact site · keep landers 0.5 km away"
              : "No keep-out recommendation"}
        </Row>
      </dl>
      {p.note && <p className="small muted">{p.note}</p>}
    </>
  );
}

function MissionFields({ mission }: { mission: MissionFeature }) {
  const p = mission.properties;
  return (
    <>
      <dl className="kv small">
        {p.mission && p.mission !== p.name && <Row label="Mission">{p.mission}</Row>}
        <Row label="Target">{text(p.target)}</Row>
        <Row label="Date">
          {text(p.date)}
          <span className="block muted">As published{p.asOf ? `, as of ${p.asOf}` : ""}. Launch dates slip often.</span>
        </Row>
        {!mission.geometry && <Row label="Map">No published coordinates</Row>}
      </dl>
      {p.note && <p className="small muted">{p.note}</p>}
      {p.kind === "artemis_region" && (
        <p className="small muted">
          NASA publishes no official region outlines: this ~15 × 15 km box around the anchor feature is drawn on the Moon sphere.
        </p>
      )}
    </>
  );
}
