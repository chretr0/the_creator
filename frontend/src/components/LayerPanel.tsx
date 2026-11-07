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
  tilted: boolean;
  onTilt: () => void;
};

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

export default function LayerPanel(props: Props) {
  const { manifest, visible, companies } = props;
  const stats = (id: InfraLayerId) => manifest?.layers.find((l) => l.id === id)?.stats;

  return (
    <section className="panel">
      <h2>Infrastructure</h2>
      {props.loadError && <p className="warn small">Layers unavailable: {props.loadError}</p>}

      {(Object.keys(LAYER_META) as InfraLayerId[]).map((id) => {
        const s = stats(id);
        return (
          <label key={id} className="toggle">
            <input type="checkbox" checked={visible[id]} onChange={() => props.onToggle(id)} disabled={!manifest} />
            <span className="dot" style={{ background: rgb(LAYER_META[id].colour) }} />
            <span>{LAYER_META[id].label}</span>
            {s && (
              <span className="muted small right">
                {s.features.toLocaleString()} · {Math.round((100 * s.withOperator) / s.features)}% with operator
              </span>
            )}
          </label>
        );
      })}

      <label className="toggle">
        <input type="checkbox" checked={props.tilted} onChange={props.onTilt} />
        <span>3D view and buildings</span>
        <span className="muted small right">zoom ≥ 14</span>
      </label>

      <label className="field">
        <span>Company (OSM operator)</span>
        <select value={props.companyFilter ?? ""} onChange={(e) => props.onCompanyFilter(e.target.value || null)}>
          <option value="">All companies</option>
          {companies.slice(0, 60).map((c) => (
            <option key={c.key} value={c.key}>
              {c.label} ({c.count})
            </option>
          ))}
        </select>
      </label>
      <p className="muted small">{props.shownCount.toLocaleString()} facilities shown</p>

      <h3>Datacenter colour = operator</h3>
      <ul className="legend">
        {companies.slice(0, COLOURED_COMPANIES).map((c) => (
          <li key={c.key}>
            <span className="dot" style={{ background: rgb(c.colour) }} />
            {c.label}
          </li>
        ))}
        <li>
          <span className="dot" style={{ background: rgb(LAYER_META.datacenters.colour) }} />
          Other named operator
        </li>
        <li>
          <span className="dot" style={{ background: rgb(UNKNOWN_OWNER) }} />
          Operator not tagged
        </li>
      </ul>

      {manifest && (
        <p className="muted small">
          {manifest.attribution} Evidence: reported records (volunteer-mapped). Power figures are tagged
          capacity ratings; consumption is not reported by this source. Basemap building heights are
          OpenMapTiles display values, not measurements.
        </p>
      )}
    </section>
  );
}
