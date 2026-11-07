import { facilityTitle, formatKw, LAYER_META, type Facility } from "../lib/infrastructure";

type Props = {
  facility: Facility;
  canModel: boolean;
  onModel: () => void;
  onShowCompany: (key: string) => void;
  onZoomTo: () => void;
  onClose: () => void;
};

const Unknown = () => <span className="muted">Unknown</span>;

export default function FacilityInspector({ facility, canModel, onModel, onShowCompany, onZoomTo, onClose }: Props) {
  const p = facility.properties;
  const isDc = p.layer === "datacenters";
  const ratings = p.powerRatings.filter((r) => r.kw !== null);
  const built = [p.heightM !== null && `${p.heightM} m tall`, p.levels !== null && `${p.levels} floors`].filter(Boolean);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{facilityTitle(p)}</h2>
        <button className="ghost" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <p className="subtitle" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="dot" style={{ background: `rgb(${LAYER_META[p.layer].colour})` }} />
        {isDc ? "Datacenter" : "Dam"}
        {p.nameEn && p.name && p.nameEn !== p.name && <> · {p.name}</>}
      </p>

      <dl className="kv">
        <dt>Operator</dt>
        <dd>{p.operator ?? <Unknown />}</dd>
        <dt>Owner</dt>
        <dd>{p.owner ?? <Unknown />}</dd>
        <dt>Capacity</dt>
        <dd>
          {ratings.length ? ratings.map((r) => <div key={r.tag}>{formatKw(r.kw!)} <span className="muted small">{r.meaning}</span></div>) : <Unknown />}
        </dd>
        {p.river && (
          <>
            <dt>River</dt>
            <dd>{p.river}</dd>
          </>
        )}
        {p.plantSource && (
          <>
            <dt>Source</dt>
            <dd>{p.plantSource}</dd>
          </>
        )}
        {p.startDate && (
          <>
            <dt>Opened</dt>
            <dd>{p.startDate}</dd>
          </>
        )}
        {built.length > 0 && (
          <>
            <dt>Building</dt>
            <dd>{built.join(", ")}</dd>
          </>
        )}
        {(p.website || p.osmUrl) && (
          <>
            <dt>Links</dt>
            <dd style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {p.website && (
                <a href={p.website} target="_blank" rel="noreferrer">
                  Website
                </a>
              )}
              {p.osmUrl && (
                <a href={p.osmUrl} target="_blank" rel="noreferrer">
                  OpenStreetMap
                </a>
              )}
            </dd>
          </>
        )}
      </dl>

      {p.companyKey && p.companyFacilityCount && p.companyFacilityCount > 1 && (
        <p style={{ marginTop: 12 }}>
          <button className="link inline" onClick={() => onShowCompany(p.companyKey!)}>
            Show all {p.companyFacilityCount.toLocaleString()} from this operator
          </button>
        </p>
      )}

      <div className="actions">
        {isDc && (
          <button className="primary" disabled={!canModel} onClick={onModel}>
            Add as project
          </button>
        )}
        <button onClick={onZoomTo}>Zoom in</button>
      </div>
    </section>
  );
}
