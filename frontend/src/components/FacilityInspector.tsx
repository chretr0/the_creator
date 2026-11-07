import { facilityTitle, formatKv, formatKw, LAYER_META, layerColour, type Facility } from "../lib/infrastructure";

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
  const meta = LAYER_META[p.layer];
  // Ownership and capacity rows only where the source can report them (not airports or ports).
  const showsOwnership = !["airports", "ports"].includes(p.layer) || !!(p.operator || p.owner);
  const showsCapacity = ["datacenters", "dams", "power_plants"].includes(p.layer);
  const codes = [p.iata && `IATA ${p.iata}`, p.icao && `ICAO ${p.icao}`].filter(Boolean).join(" · ");
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
        <span className="dot" style={{ background: `rgb(${p.layer === "datacenters" ? meta.colour : layerColour(p)})` }} />
        {p.kind && p.layer !== "dams" ? `${p.kind} · ${meta.singular.toLowerCase()}` : meta.singular}
        {p.nameEn && p.name && p.nameEn !== p.name && <> · {p.name}</>}
      </p>

      <dl className="kv">
        {showsOwnership && (
          <>
            <dt>Operator</dt>
            <dd>{p.operator ?? <Unknown />}</dd>
            <dt>Owner</dt>
            <dd>{p.owner ?? <Unknown />}</dd>
          </>
        )}
        {showsCapacity && (
          <>
            <dt>Capacity</dt>
            <dd>
              {ratings.length ? ratings.map((r) => <div key={r.tag}>{formatKw(r.kw!)} <span className="muted small">{r.meaning}</span></div>) : <Unknown />}
            </dd>
          </>
        )}
        {p.generation && (
          <>
            <dt>Generation</dt>
            <dd>
              {p.generation.gwh.toLocaleString(undefined, { maximumFractionDigits: 1 })} GWh in {p.generation.year}{" "}
              <span className="muted small">{p.generation.estimated ? "WRI model estimate, not metered" : "reported"}</span>
            </dd>
          </>
        )}
        {p.otherFuels && p.otherFuels.length > 0 && (
          <>
            <dt>Other fuels</dt>
            <dd>{p.otherFuels.join(", ")}</dd>
          </>
        )}
        {p.voltageKv && p.voltageKv.length > 0 && (
          <>
            <dt>Voltage</dt>
            <dd>
              {formatKv(p.voltageKv)} <span className="muted small">OSM tag, not spare capacity</span>
            </dd>
          </>
        )}
        {p.circuits != null && (
          <>
            <dt>Circuits</dt>
            <dd>{p.circuits}</dd>
          </>
        )}
        {p.lengthKm != null && (
          <>
            <dt>Mapped length</dt>
            <dd>{p.lengthKm.toLocaleString(undefined, { maximumFractionDigits: 1 })} km <span className="muted small">this OSM segment</span></dd>
          </>
        )}
        {codes && (
          <>
            <dt>Codes</dt>
            <dd>{codes}</dd>
          </>
        )}
        {p.municipality && (
          <>
            <dt>Serves</dt>
            <dd>{p.municipality}</dd>
          </>
        )}
        {p.scheduledService != null && p.layer === "airports" && (
          <>
            <dt>Scheduled flights</dt>
            <dd>{p.scheduledService ? "Yes" : "No"}</dd>
          </>
        )}
        {p.elevationM != null && (
          <>
            <dt>Elevation</dt>
            <dd>{p.elevationM.toLocaleString()} m</dd>
          </>
        )}
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
        {(p.website || p.osmUrl || p.recordUrl) && (
          <>
            <dt>Links</dt>
            <dd style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {p.website && (
                <a href={p.website} target="_blank" rel="noreferrer">
                  Website
                </a>
              )}
              {p.recordUrl && (
                <a href={p.recordUrl} target="_blank" rel="noreferrer" title={p.recordSource ?? undefined}>
                  Source record
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
            Show all {p.companyFacilityCount.toLocaleString()} from this {p.operator ? "operator" : "owner"}
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
