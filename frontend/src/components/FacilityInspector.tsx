import {
  facilityTitle,
  formatKw,
  LAYER_META,
  ratedItLoadKw,
  type Facility,
  type InfraManifest,
} from "../lib/infrastructure";

type Props = {
  facility: Facility;
  manifest: InfraManifest | null;
  canModel: boolean;
  onModel: () => void;
  onShowCompany: (key: string) => void;
  onZoomTo: () => void;
  onClose: () => void;
};

const wikidata = (qid: string | null) =>
  qid ? (
    <a href={`https://www.wikidata.org/wiki/${qid}`} target="_blank" rel="noreferrer" className="mono">
      {qid}
    </a>
  ) : null;

const NotReported = () => <span className="muted">not reported in source</span>;

export default function FacilityInspector({ facility, manifest, canModel, onModel, onShowCompany, onZoomTo, onClose }: Props) {
  const p = facility.properties;
  const isDc = p.layer === "datacenters";
  const itLoad = ratedItLoadKw(p);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          <span className="dot" style={{ background: `rgb(${LAYER_META[p.layer].colour})` }} />{" "}
          {isDc ? "Datacenter" : "Dam"}
        </h2>
        <button className="ghost" onClick={onClose} aria-label="Close facility">
          ✕
        </button>
      </div>
      <p>
        <strong>{facilityTitle(p)}</strong>
        {p.nameEn && p.name && p.nameEn !== p.name && <span className="muted"> · {p.name}</span>}
      </p>

      <h3>Ownership</h3>
      <dl className="kv">
        <dt>Operator</dt>
        <dd>
          {p.operator ?? <NotReported />}
          {p.operatorShort && p.operatorShort !== p.operator && <span className="muted"> ({p.operatorShort})</span>}{" "}
          {wikidata(p.operatorWikidata)}
        </dd>
        <dt>Owner</dt>
        <dd>
          {p.owner ?? <NotReported />} {wikidata(p.ownerWikidata)}
        </dd>
        {p.companyKey && p.companyFacilityCount && (
          <>
            <dt>Same operator</dt>
            <dd>
              <button className="link inline" onClick={() => onShowCompany(p.companyKey!)}>
                {p.companyFacilityCount.toLocaleString()} mapped {isDc ? "datacenters" : "dams"} — show only these
              </button>
            </dd>
          </>
        )}
      </dl>
      <p className="muted small">
        Operator (who runs it) and owner (who owns it) are separate OSM tags; neither is inferred from the
        other.
      </p>

      <h3>Power and consumption</h3>
      <dl className="kv">
        {p.powerRatings.map((r) => (
          <FragmentRow key={r.tag} label={r.meaning}>
            {r.kw !== null ? formatKw(r.kw) : <span className="muted">unparsed</span>}{" "}
            <span className="muted mono">
              {r.tag}={r.raw}
            </span>
          </FragmentRow>
        ))}
        {p.powerRatings.length === 0 && (
          <FragmentRow label="Rated capacity">
            <NotReported />
          </FragmentRow>
        )}
        <dt>Electricity use</dt>
        <dd>
          <NotReported />
        </dd>
        {isDc && (
          <>
            <dt>Water use</dt>
            <dd>
              <NotReported />
            </dd>
          </>
        )}
      </dl>
      <p className="muted small">
        {isDc
          ? "A capacity rating (kW) is a maximum, not energy used. Consumption needs an operating time, load fraction, PUE and WUE — model it as a project with explicit assumptions."
          : "Nameplate capacity is not actual generation; output depends on water flow and dispatch."}
      </p>

      <h3>Details</h3>
      <dl className="kv">
        {p.river && (
          <>
            <dt>River</dt>
            <dd>{p.river}</dd>
          </>
        )}
        {p.plantSource && (
          <>
            <dt>Plant source</dt>
            <dd>{p.plantSource}</dd>
          </>
        )}
        {p.startDate && (
          <>
            <dt>Start date</dt>
            <dd>{p.startDate}</dd>
          </>
        )}
        {(p.heightM !== null || p.levels !== null) && (
          <>
            <dt>Building</dt>
            <dd>
              {[p.heightM !== null && `${p.heightM} m tall`, p.levels !== null && `${p.levels} levels`]
                .filter(Boolean)
                .join(" · ")}
            </dd>
          </>
        )}
        <dt>Location</dt>
        <dd className="mono">
          {p.lat.toFixed(5)}, {p.lon.toFixed(5)}
        </dd>
        <dt>H3 cell (res 6)</dt>
        <dd className="mono">{p.h3Id}</dd>
        <dt>Geometry</dt>
        <dd>{facility.geometry.type === "Point" ? "point only" : "mapped footprint"}</dd>
        {p.website && (
          <>
            <dt>Website</dt>
            <dd>
              <a href={p.website} target="_blank" rel="noreferrer">
                {p.website.replace(/^https?:\/\//, "")}
              </a>
            </dd>
          </>
        )}
      </dl>

      <h3>Source</h3>
      <dl className="kv">
        <dt>Record</dt>
        <dd>
          {p.osmUrl ? (
            <a href={p.osmUrl} target="_blank" rel="noreferrer" className="mono">
              OSM {p.osmType} {p.osmId}
            </a>
          ) : (
            "—"
          )}
          <span className="muted small"> (type inferred from ID)</span>
        </dd>
        <dt>Evidence</dt>
        <dd>Reported record (volunteer-mapped)</dd>
        <dt>Licence</dt>
        <dd>{manifest?.licence ?? "ODbL-1.0"}</dd>
        <dt>Snapshot</dt>
        <dd>
          gods-eye-view bundle{manifest?.upstream.commit ? ` @ ${manifest.upstream.commit.slice(0, 7)}` : ""}; OSM
          extraction date not recorded upstream
        </dd>
      </dl>

      <div className="actions">
        <button onClick={onZoomTo}>Zoom to site</button>
        {isDc && (
          <button className="primary" disabled={!canModel} onClick={onModel}>
            Model as data-centre project
          </button>
        )}
      </div>
      {isDc && (
        <p className="muted small">
          Places a project at this point in the current scenario.{" "}
          {itLoad !== null
            ? `IT power is prefilled with the tagged IT load rating (${formatKw(itLoad)}); other parameters stay blank.`
            : "All parameters start blank — none are reported here."}
        </p>
      )}
    </section>
  );
}

function FragmentRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}
