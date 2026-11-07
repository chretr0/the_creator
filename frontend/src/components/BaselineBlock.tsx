import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  dataApi,
  EVIDENCE_LABEL,
  formatValue,
  type CellFeatureContext,
  type CellSource,
  type CellProfile,
  type FeatureLayerMeta,
  type FeatureProps,
  type ProfileValue,
} from "../lib/datalayers";

type Props = {
  h3Id: string;
  manifest: FeatureLayerMeta[];
  onShowLayer: (layerId: string, sliceId?: string) => void;
  onGoTo: (lat: number, lon: number) => void;
};

const MONTHS = "JFMAMJJASOND".split("");

/** Everything the prepared baseline layers know about one cell (a zoomed-out hexagon aggregates its children). */
export default function BaselineBlock({ h3Id, manifest, onShowLayer, onGoTo }: Props) {
  const [category, setCategory] = useState("");
  const [layerId, setLayerId] = useState("");
  const [profile, setProfile] = useState<CellProfile | null>(null);
  const [context, setContext] = useState<CellFeatureContext | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setProfile(null);
    setContext(null);
    setError(null);
    dataApi
      .profile(h3Id, ctrl.signal)
      .then(setProfile)
      .catch((e) => !ctrl.signal.aborted && setError(String(e.message ?? e)));
    dataApi
      .cellFeatures(h3Id, ctrl.signal)
      .then(setContext)
      .catch(() => {
        /* feature context is optional */
      });
    return () => ctrl.abort();
  }, [h3Id]);

  const groups = useMemo(() => {
    const m = new Map<string, CellProfile["layers"]>();
    for (const l of profile?.layers ?? []) m.set(l.category, [...(m.get(l.category) ?? []), l]);
    return [...m.entries()];
  }, [profile]);

  return (
    <>
      {error && <p className="warn small">{error}</p>}
      {!profile && !error && <p className="muted small">Loading…</p>}
      {profile && !profile.region && !profile.layers.some((l) => l.coverage === "regions") && (
        <p className="no-coverage small" role="status">
          <strong>No baseline data for this area.</strong> Regional layers (terrain, land cover, water stress,
          satellite observations) are only prepared for Arizona and the UK; the global layers below still apply.
        </p>
      )}
      {groups.length > 0 && <label className="field"><span>Data category</span><select value={groups.some(([cat]) => cat === category) || category === "__features" ? category : groups[0][0]} onChange={(e) => setCategory(e.target.value)}>
        {groups.map(([cat]) => <option key={cat} value={cat}>{cat}</option>)}
        {!!context?.layers.length && <option value="__features">Mapped features nearby</option>}
      </select></label>}
      {groups.filter(([cat]) => cat === (groups.some(([name]) => name === category) || category === "__features" ? category : groups[0]?.[0])).map(([category, layers]) => (
        <div key={category} className="baseline-group">
          <label className="field"><span>Dataset</span><select value={layers.some((l) => l.layer === layerId) ? layerId : layers[0]?.layer} onChange={(e) => setLayerId(e.target.value)}>
            {layers.map((l) => <option key={l.layer} value={l.layer}>{l.name}</option>)}
          </select></label>
          {layers.filter((l) => l.layer === (layers.some((item) => item.layer === layerId) ? layerId : layers[0]?.layer)).map((l) => (
            <BaselineRow key={l.layer} layer={l} onShow={onShowLayer} total={profile?.simulationCells ?? 1} />
          ))}
        </div>
      ))}
      {context && context.layers.length > 0 && (category === "__features" || groups.length === 0) && (
        <FeatureContext context={context} manifest={manifest} onGoTo={onGoTo} />
      )}
    </>
  );
}

/** "120 of 343 cells" when a zoomed-out hexagon's value only rests on some of its simulation cells. */
function Coverage({ values, total }: { values: ProfileValue[]; total: number }) {
  const n = Math.max(0, ...values.map((v) => v.cellsWithData ?? 0));
  if (total <= 1 || n === 0 || n >= total) return null;
  return (
    <span className="muted small coverage" title="Simulation cells inside this hexagon that have data">
      {n.toLocaleString()} of {total.toLocaleString()} cells
    </span>
  );
}

function BaselineRow({
  layer,
  onShow,
  total,
}: {
  layer: CellProfile["layers"][number];
  onShow: Props["onShowLayer"];
  total: number;
}) {
  const first = layer.values[0];
  const monthly = layer.values.filter((v) => /-\d{2}$/.test(v.slice));
  const clim = monthly.filter((v) => v.slice.startsWith("clim-"));
  const y2024 = monthly.filter((v) => v.slice.startsWith("2024-"));

  if (layer.categorical) {
    const dom = layer.values.find((v) => v.categorical) ?? layer.values.find((v) => v.slice === "dominant");
    const cat = dom?.value == null ? undefined : layer.categories?.find((c) => c.value === Math.round(dom.value!));
    const fractions = layer.values
      .filter((v) => v !== dom && v.units === "% of cell" && (v.display ?? 0) > 0)
      .sort((a, b) => (b.display ?? 0) - (a.display ?? 0));
    const others = layer.values.filter((v) => v !== dom && v.units !== "% of cell");
    const colourOf = (slice: string) => {
      const label = layer.values.find((v) => v.slice === slice)?.label;
      return layer.categories?.find((c) => c.label === label)?.colour ?? "#94a3b8";
    };
    return (
      <div className="baseline-row">
        <button className="link inline" onClick={() => onShow(layer.layer, dom?.slice)} title="Show on map">
          {layer.name}
        </button>
        <span className="value">
          {cat && <span className="swatch" style={{ background: cat.colour, marginRight: 6 }} />}
          {cat ? cat.label : "no data"}
          {others.map((v) => (
            <span key={v.slice} className="muted small">
              {" "}
              · {v.label} {formatValue(v.display, v.label.includes("(") ? null : v.units)}
            </span>
          ))}
        </span>
        <Coverage values={layer.values} total={total} />
        <Attributes layer={layer} />
        {fractions.length > 0 && (
          <>
            <div className="stack" role="img" aria-label="Land-cover shares">
              {fractions.map((f) => (
                <span
                  key={f.slice}
                  title={`${f.label}: ${formatValue(f.display, "%")}`}
                  style={{ width: `${f.display}%`, background: colourOf(f.slice) }}
                />
              ))}
            </div>
            <ul className="legend data-legend">
              {fractions.slice(0, 4).map((f) => (
                <li key={f.slice}>
                  <span className="swatch" style={{ background: colourOf(f.slice) }} />
                  {f.label} {formatValue(f.display)}%
                </li>
              ))}
            </ul>
          </>
        )}
        <SourceDetails source={layer.source} units={dom?.rawUnits ?? null} />
      </div>
    );
  }

  const nonMonthly = layer.values.filter((v) => !/-\d{2}$/.test(v.slice));
  return (
    <div className="baseline-row">
      <button className="link inline" onClick={() => onShow(layer.layer, first?.slice)} title="Show on map">
        {layer.name}
      </button>
      {nonMonthly.length <= 1 || nonMonthly.every((v) => v.display === null) ? (
        <span className="value">
          {headline(first)}
        </span>
      ) : (
        <span className="value multi">
          {nonMonthly.map((v) => (
            <span key={v.slice}>
              <span className="muted">{v.label}</span> {formatValue(v.display, v.units)}
            </span>
          ))}
        </span>
      )}
      <Coverage values={layer.values} total={total} />
      <Attributes layer={layer} />
      {clim.length === 12 && <MonthlyBars clim={clim} y2024={y2024.length === 12 ? y2024 : null} />}
      {clim.length !== 12 && y2024.length === 12 && <MonthlyBars clim={y2024} y2024={null} barLabel="2024" />}
      <SourceDetails source={layer.source} units={first?.units ?? null} />
    </div>
  );
}

function Attributes({ layer }: { layer: CellProfile["layers"][number] }) {
  if (!layer.attributes?.length) return null;
  return (
    <dl className="kv small">
      {layer.attributes.map((a) => (
        <div key={a.key} className="kv-pair">
          <dt>{a.label}</dt>
          <dd>{String(a.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Units, period, native resolution, evidence type, caveats, licence and attribution for one layer. */
function SourceDetails({ source, units }: { source?: CellSource; units: string | null }) {
  if (!source) return null;
  const rows: [string, ReactNode][] = [];
  if (units && units !== "class") rows.push(["Units", units]);
  if (source.period) rows.push(["Period", source.period]);
  if (source.nativeResolution) rows.push(["Native resolution", source.nativeResolution]);
  if (source.sampling) rows.push(["Sampling", source.sampling]);
  if (source.evidenceType) rows.push(["Evidence", EVIDENCE_LABEL[source.evidenceType] ?? source.evidenceType.replace(/_/g, " ")]);
  rows.push(["Source", [source.provider, source.product].filter(Boolean).join(" · ") || source.sourceId]);
  rows.push([
    "Licence",
    source.licenceUrl ? (
      <a href={source.licenceUrl} target="_blank" rel="noreferrer">
        {source.licence ?? "licence"}
      </a>
    ) : (
      (source.licence ?? "see source record")
    ),
  ]);
  if (source.attribution) rows.push(["Attribution", source.attribution]);
  if (source.retrievedAt) rows.push(["Retrieved", source.retrievedAt]);
  return (
    <details className="source-details small">
      <summary>
        Source · {source.licence ?? source.sourceId}
        {source.evidenceType ? ` · ${EVIDENCE_LABEL[source.evidenceType] ?? source.evidenceType.replace(/_/g, " ")}` : ""}
      </summary>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} className="kv-pair">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {source.limitations.length > 0 && (
        <ul className="limitations muted">
          {source.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </details>
  );
}

function headline(v: ProfileValue | undefined) {
  if (!v) return "no data";
  const shown = formatValue(v.display, v.units);
  if (v.value !== null && v.display !== v.value && v.rawUnits && v.units !== "% of cell") {
    return (
      <>
        {shown} <span className="muted small">({formatValue(v.value, v.rawUnits)})</span>
      </>
    );
  }
  return shown;
}

/** Twelve monthly long-term means as bars, 2024 as dots on the same axis. */
function MonthlyBars({
  clim,
  y2024,
  barLabel = "average",
}: {
  clim: ProfileValue[];
  y2024: ProfileValue[] | null;
  barLabel?: string;
}) {
  const vals = [...clim, ...(y2024 ?? [])].map((v) => v.display).filter((v): v is number => v !== null);
  if (!vals.length) return null;
  const lo = Math.min(0, ...vals);
  const hi = Math.max(...vals);
  const W = 300;
  const H = 64;
  const pad = 12;
  const bw = W / 12;
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - pad - 4);
  const units = clim[0].units;
  return (
    <figure className="monthly">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`Monthly values in ${units}`}>
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} className="axis" />
        {clim.map((v, i) =>
          v.display === null ? null : (
            <g key={v.slice}>
              <rect
                x={i * bw + 3}
                width={bw - 6}
                y={Math.min(y(v.display), y(0))}
                height={Math.max(1, Math.abs(y(0) - y(v.display)))}
                rx={2}
                className="bar"
              >
                <title>{`${v.label}${barLabel === "average" ? " long-term" : ""}: ${formatValue(v.display, units)}${y2024?.[i]?.display != null ? ` · 2024: ${formatValue(y2024[i].display, units)}` : ""}`}</title>
              </rect>
            </g>
          ),
        )}
        {y2024?.map((v, i) =>
          v.display === null ? null : (
            <circle key={v.slice} cx={i * bw + bw / 2} cy={y(v.display)} r={3} className="dot2024">
              <title>{`${v.label}: ${formatValue(v.display, units)}`}</title>
            </circle>
          ),
        )}
        {MONTHS.map((m, i) => (
          <text key={i} x={i * bw + bw / 2} y={H - 1} className="tick">
            {m}
          </text>
        ))}
      </svg>
      <figcaption className="muted small">
        <span className="key bar" /> {barLabel} {y2024 && (<><span className="key dot" /> 2024</>)} · {units}
      </figcaption>
    </figure>
  );
}

function FeatureContext({ context, manifest, onGoTo }: { context: CellFeatureContext; manifest: FeatureLayerMeta[]; onGoTo: Props["onGoTo"] }) {
  const metaOf = (id: string) => manifest.find((m) => m.id === id);
  return (
    <>
      <h3>Nearby</h3>
      {context.layers.map((l) => {
        const meta = metaOf(l.layer);
        if (l.geometry === "polygon") {
          return (
            <div key={l.layer} className="baseline-row">
              <span className="baseline-cat">{l.name}</span>
              {l.features?.slice(0, 1).map((p, i) => (
                <FieldList key={i} props={p} meta={meta} max={8} />
              ))}
            </div>
          );
        }
        if (l.geometry === "line") {
          const top = l.features?.[0];
          return (
            <div key={l.layer} className="baseline-row">
              <span className="baseline-cat">{l.name}</span>
              <span className="small">
                {l.count} reach{l.count === 1 ? "" : "es"} cross this cell
                {top && meta?.valueField && top[meta.valueField] != null
                  ? `; the largest averages ${formatValue(top[meta.valueField] as number, meta.valueUnits)}`
                  : ""}
                .
              </span>
            </div>
          );
        }
        return (
          <div key={l.layer} className="baseline-row">
            <span className="baseline-cat">
              {l.name} · {l.inCell ?? 0} in cell
            </span>
            {l.nearest && l.nearest.length > 0 ? (
              <ul className="list nearest">
                {l.nearest.map((n, i) => (
                  <li key={i}>
                    <button className="link" onClick={() => onGoTo(n.lat, n.lon)}>
                      <span className="result-title">
                        {String((meta?.nameField && n[meta.nameField]) || n.id || "Unnamed")}
                        {meta?.categoryField && n[meta.categoryField] ? (
                          <span className="muted"> · {String(n[meta.categoryField])}</span>
                        ) : null}
                      </span>
                      <span className="muted small right">{n.distanceKm.toFixed(1)} km</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="muted small">None within {l.radiusKm} km</span>
            )}
          </div>
        );
      })}
    </>
  );
}

export function FieldList({ props, meta, max = 20 }: { props: FeatureProps; meta?: FeatureLayerMeta; max?: number }) {
  const fields = meta?.fields ?? Object.keys(props).filter((k) => k !== "id").map((k) => ({ key: k, label: k, units: null }));
  const rows = fields.filter((f) => props[f.key] !== null && props[f.key] !== undefined && props[f.key] !== "").slice(0, max);
  return (
    <dl className="kv small">
      {rows.map((f) => {
        const v = props[f.key];
        const isUrl = typeof v === "string" && /^https?:\/\//.test(v);
        return (
          <div key={f.key} className="kv-pair">
            <dt>{f.label}</dt>
            <dd>
              {isUrl ? (
                <a href={v as string} target="_blank" rel="noreferrer">
                  open record
                </a>
              ) : typeof v === "number" ? (
                formatValue(v, f.units)
              ) : (
                String(v)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
