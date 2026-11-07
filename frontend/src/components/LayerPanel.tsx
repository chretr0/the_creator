import { voltageColour } from "../lib/context";
import {
  COLOURED_COMPANIES,
  fuelColour,
  INFRA_LAYER_IDS,
  LAYER_META,
  OTHER_FUEL,
  UNKNOWN_OWNER,
  type Company,
  type InfraGroup,
  type InfraLayerId,
  type InfraManifest,
} from "../lib/infrastructure";
import type { DataLayersState } from "../lib/useDataLayers";
import { GeometrySwatch, REGION_LABEL } from "./DataPanel";

type Status = { loading: boolean; error: string | null };

type Props = {
  manifest: InfraManifest | null;
  loadError: string | null;
  status: Partial<Record<InfraLayerId, Status>>;
  visible: Record<InfraLayerId, boolean>;
  onToggle: (id: InfraLayerId) => void;
  companies: Company[];
  companyFilter: string | null;
  onCompanyFilter: (key: string | null) => void;
  shownCount: number;
  cables: { on: boolean; onToggle: () => void; status?: Status };
  data: DataLayersState;
  onOpenRecords: () => void;
};

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

const GROUPS: { id: InfraGroup; label: string }[] = [
  { id: "Energy", label: "Energy & grid" },
  { id: "Digital", label: "Digital" },
  { id: "Transport", label: "Transport" },
];

/** Record layers from "Mapped records" that are also infrastructure (mines, wells, industrial sites). */
const RELATED_RECORDS = ["mrds", "nsta_wellbores", "tri_facilities"];

const VOLTAGE_BANDS: { label: string; kv: number }[] = [
  { label: "330 kV +", kv: 400 },
  { label: "220–329 kV", kv: 275 },
  { label: "110–219 kV", kv: 132 },
  { label: "66–109 kV", kv: 66 },
];

const MAIN_FUELS = ["Solar", "Wind", "Hydro", "Gas", "Coal", "Oil", "Nuclear", "Biomass", "Geothermal", "Waste", "Storage"];

function Note({ s, count }: { s?: Status; count?: number }) {
  if (s?.loading) return <span className="muted small right">Loading…</span>;
  if (s?.error) return <span className="warn small right" title={s.error}>Unavailable</span>;
  if (count !== undefined) return <span className="muted small right num">{count.toLocaleString()}</span>;
  return null;
}

export default function LayerPanel(props: Props) {
  const { manifest, visible, companies, status, data } = props;
  const entry = (id: InfraLayerId) => manifest?.layers.find((l) => l.id === id);
  const companyListed = !props.companyFilter || companies.some((c) => c.key === props.companyFilter);
  const related = RELATED_RECORDS.map((id) => data.manifest.find((m) => m.id === id)).filter((m) => !!m);
  const plantKinds = entry("power_plants")?.kinds ?? {};
  const fuels = MAIN_FUELS.filter((f) => plantKinds[f]);

  const toggle = (id: InfraLayerId) => {
    const e = entry(id);
    const unavailable = !manifest || !e || e.available === false;
    const regional = e?.scope === "regions" && e.regions?.length;
    return (
      <label key={id} className="toggle" title={unavailable && e ? "Not prepared on this server: run scripts/prepare_infrastructure.py" : undefined}>
        <input type="checkbox" checked={visible[id]} onChange={() => props.onToggle(id)} disabled={unavailable} />
        {LAYER_META[id].line ? (
          <span className="line-swatch" style={{ background: rgb(LAYER_META[id].colour) }} />
        ) : (
          <span className="dot" style={{ background: rgb(LAYER_META[id].colour) }} />
        )}
        <span>
          {LAYER_META[id].label}
          {regional ? <small className="muted"> · {e!.regions!.map((r) => REGION_LABEL[r] ?? r).join(", ")} only</small> : null}
        </span>
        {e && e.available === false ? <span className="muted small right">Not prepared</span> : <Note s={status[id]} count={e?.stats.features} />}
      </label>
    );
  };

  return (
    <section className="panel">
      <h2>Infrastructure</h2>
      {props.loadError && <p className="warn small">Couldn't load: {props.loadError}</p>}

      {props.companyFilter && (
        <p className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="muted">
            Showing one company only{companyListed ? "" : ` (${props.shownCount.toLocaleString()} sites)`}
          </span>
          <button className="link inline" onClick={() => props.onCompanyFilter(null)}>
            Show all
          </button>
        </p>
      )}

      {GROUPS.map((g) => (
        <div key={g.id}>
          <h3>{g.label}</h3>
          {INFRA_LAYER_IDS.filter((id) => LAYER_META[id].group === g.id).map(toggle)}

          {g.id === "Energy" && visible.power_plants && fuels.length > 0 && (
            <ul className="legend sub">
              {fuels.map((f) => (
                <li key={f}>
                  <span className="dot" style={{ background: rgb(fuelColour(f)) }} />
                  {f}
                </li>
              ))}
              <li>
                <span className="dot" style={{ background: rgb(OTHER_FUEL) }} />
                Other
              </li>
            </ul>
          )}
          {g.id === "Energy" && (visible.substations || visible.transmission_lines) && (
            <>
              <ul className="legend sub">
                {VOLTAGE_BANDS.map((b) => (
                  <li key={b.label}>
                    <span className="line-swatch" style={{ background: rgb(voltageColour([b.kv])) }} />
                    {b.label}
                  </li>
                ))}
              </ul>
              <p className="muted small sub">
                Mapped OSM routes and voltages, not spare capacity. Outside Arizona and the UK, pick a location and use
                “Load OSM power here”.
              </p>
            </>
          )}

          {g.id === "Digital" && (
            <>
              <label className="toggle">
                <input type="checkbox" checked={props.cables.on} onChange={props.cables.onToggle} />
                <span className="line-swatch" style={{ background: "rgb(14, 165, 233)" }} />
                <span>Submarine cables &amp; landing points</span>
                <Note s={props.cables.status} />
              </label>
              {visible.datacenters && (
                <div className="sub">
                  <label className="field">
                    <span>Datacenter operator</span>
                    <select
                      value={companyListed ? props.companyFilter ?? "" : ""}
                      onChange={(e) => props.onCompanyFilter(e.target.value || null)}
                    >
                      <option value="">All operators</option>
                      {companies.slice(0, 60).map((c) => (
                        <option key={c.key} value={c.key}>
                          {c.label} ({c.count})
                        </option>
                      ))}
                    </select>
                  </label>
                  {props.companyFilter && companyListed && (
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
                </div>
              )}
            </>
          )}
        </div>
      ))}

      {related.length > 0 && (
        <>
          <h3>Resources &amp; industry</h3>
          {related.map((m) => (
            <label key={m.id} className="toggle">
              <input
                type="checkbox"
                checked={!!data.enabled[m.id]}
                disabled={!m.available}
                onChange={() => data.setEnabled((e) => ({ ...e, [m.id]: !e[m.id] }))}
              />
              <GeometrySwatch meta={m} />
              <span>
                {m.name}
                {m.regions.length && m.regions[0] !== "global" ? (
                  <small className="muted"> · {m.regions.map((r) => REGION_LABEL[r] ?? r).join(", ")}</small>
                ) : null}
              </span>
              <Note s={data.featureStatus[m.id]} />
            </label>
          ))}
          <p className="muted small">
            Filters for these are in{" "}
            <button className="link inline" onClick={props.onOpenRecords}>
              Mapped records
            </button>
            .
          </p>
        </>
      )}
    </section>
  );
}
