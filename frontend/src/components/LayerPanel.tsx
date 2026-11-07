import {
  COLOURED_COMPANIES,
  LAYER_META,
  UNKNOWN_OWNER,
  type Company,
  type InfraLayerId,
  type InfraManifest,
} from "../lib/infrastructure";

type Props = {
  manifest: InfraManifest | null;
  loadError: string | null;
  visible: Record<InfraLayerId, boolean>;
  onToggle: (id: InfraLayerId) => void;
  companies: Company[];
  companyFilter: string | null;
  onCompanyFilter: (key: string | null) => void;
  shownCount: number;
};

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

export default function LayerPanel(props: Props) {
  const { manifest, visible, companies } = props;
  const count = (id: InfraLayerId) => manifest?.layers.find((l) => l.id === id)?.stats.features;

  return (
    <section className="panel">
      <h2>Infrastructure</h2>
      {props.loadError && <p className="warn small">Couldn't load: {props.loadError}</p>}

      {(Object.keys(LAYER_META) as InfraLayerId[]).map((id) => (
        <label key={id} className="toggle">
          <input type="checkbox" checked={visible[id]} onChange={() => props.onToggle(id)} disabled={!manifest} />
          <span className="dot" style={{ background: rgb(LAYER_META[id].colour) }} />
          <span>{LAYER_META[id].label}</span>
          {count(id) !== undefined && <span className="muted small right num">{count(id)!.toLocaleString()}</span>}
        </label>
      ))}

      {visible.datacenters && (
        <>
          <label className="field">
            <span>Operator</span>
            <select value={props.companyFilter ?? ""} onChange={(e) => props.onCompanyFilter(e.target.value || null)}>
              <option value="">All operators</option>
              {companies.slice(0, 60).map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label} ({c.count})
                </option>
              ))}
            </select>
          </label>
          {props.companyFilter && (
            <p className="muted small">{props.shownCount.toLocaleString()} shown</p>
          )}
          <ul className="legend">
            {companies.slice(0, COLOURED_COMPANIES).map((c) => (
              <li key={c.key}>
                <span className="dot" style={{ background: rgb(c.colour) }} />
                {c.label}
              </li>
            ))}
            <li>
              <span className="dot" style={{ background: rgb(LAYER_META.datacenters.colour) }} />
              Other
            </li>
            <li>
              <span className="dot" style={{ background: rgb(UNKNOWN_OWNER) }} />
              Unknown
            </li>
          </ul>
        </>
      )}
    </section>
  );
}
