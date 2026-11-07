import { useEffect, useMemo, useState } from "react";
import {
  categoryColours,
  dataApi,
  formatValue,
  makeScale,
  OTHER,
  REGION_VIEWS,
  SEQUENTIAL_ORANGE,
  type CarbonIntensity,
  type CellLayer,
  type FeatureLayerMeta,
  type RGB,
} from "../lib/datalayers";
import type { DataLayersState } from "../lib/useDataLayers";

type Props = {
  data: DataLayersState;
  onFitBBox: (bbox: [number, number, number, number] | null, maxZoom?: number) => void;
};

const css = (c: RGB) => `rgb(${c.join(",")})`;
const REGION_LABEL: Record<string, string> = { arizona: "Arizona", uk: "UK", global: "Global" };

export default function DataPanel({ data, onFitBBox }: Props) {
  return (
    <section className="panel">
      <h2>Colour the grid</h2>
      {data.loadError && <p className="warn small">Couldn't load data layers: {data.loadError}</p>}
      <CellLayerPicker data={data} onFitBBox={onFitBBox} />
      <div className="actions tight" style={{ marginTop: 14 }}>
        <span className="muted small" style={{ alignSelf: "center" }}>Jump to</span>
        <button className="chip" onClick={() => onFitBBox(null)}>World</button>
        {REGION_VIEWS.map((r) => (
          <button key={r.id} className="chip" onClick={() => onFitBBox(r.bbox)}>
            {r.label}
          </button>
        ))}
      </div>
    </section>
  );
}

/** Prepared true-colour clips, shown inside the imagery panel. */
export function PreparedScenes({ data, onFitBBox }: Props) {
  if (data.scenes.length === 0) return null;
  return (
    <>
      <h3>Prepared scenes</h3>
      {data.scenes.map((s) => (
        <div key={s.id} className="toggle">
          <input
            type="checkbox"
            checked={data.scene?.id === s.id}
            onChange={() => data.setSceneId(data.scene?.id === s.id ? null : s.id)}
            aria-label={`Show ${s.name}`}
          />
          <span>{s.name}</span>
          <button
            className="link inline small right"
            onClick={() => {
              data.setSceneId(s.id);
              onFitBBox(s.bounds, 14);
            }}
          >
            Zoom to
          </button>
        </div>
      ))}
    </>
  );
}

function CellLayerPicker({ data, onFitBBox }: Props) {
  const { catalogue, active, activeLayer, activeSlice, values, cellStatus } = data;
  const groups = useMemo(() => {
    const m = new Map<string, CellLayer[]>();
    for (const l of catalogue) m.set(l.category, [...(m.get(l.category) ?? []), l]);
    return [...m.entries()];
  }, [catalogue]);

  const sliceGroups = useMemo(() => {
    const m = new Map<string, CellLayer["slices"]>();
    for (const s of activeLayer?.slices ?? []) {
      const g = s.group ?? "";
      m.set(g, [...(m.get(g) ?? []), s]);
    }
    return [...m.entries()];
  }, [activeLayer]);

  const pick = (layerId: string) => {
    if (!layerId) return data.setActive(null);
    const l = catalogue.find((x) => x.id === layerId);
    if (l) data.setActive({ layerId, sliceId: l.defaultSlice });
  };

  // Month stepping for layers with a monthly series (POWER): keep the period, move the month.
  const monthly = activeLayer?.slices.filter((s) => s.group === activeSlice?.group && /\d{2}$/.test(s.id)) ?? [];

  return (
    <>
      <label className="field">
        <span>Show</span>
        <select value={active?.layerId ?? ""} onChange={(e) => pick(e.target.value)}>
          <option value="">Nothing</option>
          {groups.map(([cat, ls]) => (
            <optgroup key={cat} label={cat}>
              {ls.map((l) => (
                <option key={l.id} value={l.id} disabled={!l.available}>
                  {l.name}
                  {l.coverage === "regions" ? ` · ${l.regions.map((r) => REGION_LABEL[r] ?? r).join(" + ") || "regions"}` : ""}
                  {l.available ? "" : " (unavailable)"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      {activeLayer && activeSlice && active && (
        <>
          {activeLayer.slices.length > 1 && (
            <label className="field">
              <span>Variant</span>
              <select value={active.sliceId} onChange={(e) => data.setActive({ ...active, sliceId: e.target.value })}>
                {sliceGroups.map(([g, ss]) =>
                  g ? (
                    <optgroup key={g} label={g}>
                      {ss.map((s) => (
                        <option key={s.id} value={s.id} disabled={!s.available}>
                          {s.label}
                        </option>
                      ))}
                    </optgroup>
                  ) : (
                    ss.map((s) => (
                      <option key={s.id} value={s.id} disabled={!s.available}>
                        {s.label}
                      </option>
                    ))
                  ),
                )}
              </select>
            </label>
          )}
          {monthly.length === 12 && monthly.some((s) => s.id === activeSlice.id) && (
            <label className="field">
              <span>
                Month <em>({activeSlice.label})</em>
              </span>
              <input
                type="range"
                min={0}
                max={11}
                value={Math.max(0, monthly.findIndex((s) => s.id === activeSlice.id))}
                onChange={(e) => data.setActive({ ...active, sliceId: monthly[Number(e.target.value)].id })}
              />
            </label>
          )}
          <label className="field">
            <span>Opacity</span>
            <input
              type="range"
              min={0.2}
              max={1}
              step={0.05}
              value={data.opacity}
              onChange={(e) => data.setOpacity(Number(e.target.value))}
            />
          </label>

          {data.outsideRegions ? (
            <div className="no-coverage" role="status">
              <strong>No baseline data for this area</strong>
              <p className="small">
                {activeLayer.name} is only prepared for {activeLayer.regions.map((r) => REGION_LABEL[r] ?? r).join(" and ")}.
                Cells here are blank (unknown), not zero.
              </p>
              <div className="actions tight">
                {REGION_VIEWS.filter((r) => activeLayer.regions.includes(r.id)).map((r) => (
                  <button key={r.id} className="chip" onClick={() => onFitBBox(r.bbox)}>
                    Go to {r.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              <Legend data={data} />
              {cellStatus.loading && <p className="muted small">Loading…</p>}
              {cellStatus.error && <p className="warn small">{cellStatus.error}</p>}
              {!cellStatus.loading && !cellStatus.error && values && (
                <p className="muted small">
                  <span className="swatch no-data" aria-hidden /> Faint grey = no data (unknown, never zero).
                  {activeLayer.coverage === "regions" &&
                    ` Available for ${activeLayer.regions.map((r) => REGION_LABEL[r] ?? r).join(" and ")} only.`}
                </p>
              )}
            </>
          )}
          {activeLayer.description && <p className="small">{activeLayer.description}</p>}
        </>
      )}
    </>
  );
}

function Legend({ data }: { data: DataLayersState }) {
  const { activeLayer, activeSlice, scale, values } = data;
  if (!activeLayer || !activeSlice) return null;
  if (activeSlice.categorical) {
    const shown = new Set([...(values?.map.values() ?? [])].filter((v): v is number => v !== null).map(Math.round));
    return (
      <ul className="legend data-legend">
        {(activeLayer.categories ?? [])
          .filter((c) => shown.size === 0 || shown.has(c.value))
          .map((c) => (
            <li key={c.value}>
              <span className="swatch" style={{ background: c.colour }} />
              {c.label}
            </li>
          ))}
      </ul>
    );
  }
  if (!scale) return null;
  const [lo, hi] = scale.domain;
  const mid = scale.log ? Math.sqrt(lo * hi) : (lo + hi) / 2;
  const gradient = `linear-gradient(to right, ${scale.stops.map(css).join(", ")})`;
  return (
    <div className="ramp" aria-label={`Colour scale ${lo} to ${hi} ${values?.units ?? ""}`}>
      <div className="ramp-bar" style={{ background: gradient }} />
      <div className="ramp-ticks small">
        <span>≤ {formatValue(lo)}</span>
        <span>{formatValue(mid)}</span>
        <span>≥ {formatValue(hi)}</span>
      </div>
      <div className="muted small">
        {values?.units ?? activeSlice.units}
        {scale.log ? " · log scale" : ""}
      </div>
    </div>
  );
}

export function RecordsPanel({ data }: { data: DataLayersState }) {
  const { manifest, enabled, featureData, featureStatus } = data;
  const mapped = manifest.filter((m) => m.geometry !== "table");
  const tables = manifest.filter((m) => m.geometry === "table" && m.available);

  return (
    <section className="panel">
      <h2>Records</h2>
      {mapped.length === 0 && <p className="muted small">No record layers available.</p>}
      {mapped.map((m) => {
        const on = !!enabled[m.id];
        const st = featureStatus[m.id];
        const fd = featureData[m.id];
        return (
          <div key={m.id}>
            <label className="toggle">
              <input
                type="checkbox"
                checked={on}
                disabled={!m.available}
                onChange={() => data.setEnabled((e) => ({ ...e, [m.id]: !e[m.id] }))}
              />
              <GeometrySwatch meta={m} />
              <span>{m.name}</span>
              <span className="muted small right">
                {m.regions.length && m.regions[0] !== "global" ? m.regions.map((r) => REGION_LABEL[r] ?? r).join(", ") : ""}
              </span>
            </label>
            {on && (
              <div className="sub">
                {st?.loading && <p className="muted small">Loading…</p>}
                {st?.error && <p className="warn small">{st.error}</p>}
                {!st?.loading && !st?.error && fd && (
                  <p className="muted small">
                    {fd.matched.toLocaleString()} in view{fd.truncated ? " · zoom in to see all" : ""}
                  </p>
                )}
                <FeatureFilters data={data} meta={m} />
                {m.geometry === "polygon" && m.valueField && <PolygonLegend meta={m} />}
              </div>
            )}
          </div>
        );
      })}
      {tables.map((t) =>
        t.id === "neso_carbon_intensity" ? <CarbonIntensityCard key={t.id} meta={t} /> : null,
      )}
    </section>
  );
}

function GeometrySwatch({ meta }: { meta: FeatureLayerMeta }) {
  if (meta.geometry === "line") return <span className="line-swatch" />;
  if (meta.geometry === "polygon")
    return <span className="swatch" style={{ background: meta.valueField ? css(SEQUENTIAL_ORANGE[3]) : "transparent", borderColor: "rgb(99,102,241)" }} />;
  const first = categoryColours(meta).values().next().value ?? OTHER;
  return <span className="dot" style={{ background: css(first) }} />;
}

function FeatureFilters({ data, meta }: { data: DataLayersState; meta: FeatureLayerMeta }) {
  const filter = data.filters[meta.id] ?? { categories: [], q: "" };
  const [q, setQ] = useState(filter.q);
  const colours = categoryColours(meta);
  useEffect(() => {
    const t = setTimeout(() => {
      if (q !== filter.q) data.setFilters((f) => ({ ...f, [meta.id]: { ...filter, q } }));
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const toggleCat = (c: string) => {
    const set = new Set(filter.categories);
    if (set.has(c)) set.delete(c);
    else set.add(c);
    data.setFilters((f) => ({ ...f, [meta.id]: { ...filter, categories: [...set] } }));
  };

  return (
    <>
      {meta.categories && meta.categories.length > 0 && meta.geometry === "point" && (
        <>
          <ul className="chips">
            {meta.categories.map((c) => {
              const on = filter.categories.length === 0 || filter.categories.includes(c);
              return (
                <li key={c}>
                  <button className={`chip ${on ? "" : "off"}`} onClick={() => toggleCat(c)} aria-pressed={on}>
                    <span className="dot" style={{ background: css(colours.get(c) ?? OTHER) }} />
                    {c}
                  </button>
                </li>
              );
            })}
          </ul>
          {filter.categories.length > 0 && (
            <button className="link inline small" style={{ marginTop: 6 }} onClick={() => data.setFilters((f) => ({ ...f, [meta.id]: { ...filter, categories: [] } }))}>
              Show all
            </button>
          )}
        </>
      )}
      {meta.geometry === "point" && (
        <input
          style={{ marginTop: 8 }}
          placeholder={meta.id === "mrds" ? "Filter, e.g. copper, lithium" : "Filter"}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      )}
    </>
  );
}

function PolygonLegend({ meta }: { meta: FeatureLayerMeta }) {
  const sc = makeScale([0, 5], { stops: SEQUENTIAL_ORANGE });
  return (
    <div className="ramp">
      <div className="ramp-bar" style={{ background: `linear-gradient(to right, ${sc.stops.map(css).join(", ")})` }} />
      <div className="ramp-ticks small">
        <span>Low</span>
        <span>Extremely high</span>
      </div>
      <div className="muted small">{meta.fields.find((f) => f.key === meta.valueField)?.label ?? meta.valueField}</div>
    </div>
  );
}

function CarbonIntensityCard({ meta }: { meta: FeatureLayerMeta }) {
  const [table, setTable] = useState<CarbonIntensity | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    dataApi
      .table<CarbonIntensity>(meta.id, ctrl.signal)
      .then(setTable)
      .catch((e) => !ctrl.signal.aborted && setError(String(e.message ?? e)));
    return () => ctrl.abort();
  }, [meta.id]);
  return (
    <details style={{ marginTop: 12 }}>
      <summary>{meta.name}</summary>
      {error && <p className="warn">{error}</p>}
      {table && (
        <>
          <p className="muted small">
            Forecast {table.from?.replace("T", " ")} – {table.to?.slice(11)}
          </p>
          <table className="mini">
            <thead>
              <tr>
                <th>Region</th>
                <th>gCO₂/kWh</th>
                <th>Largest sources</th>
              </tr>
            </thead>
            <tbody>
              {table.regions.map((r) => (
                <tr key={r.regionId}>
                  <td>{r.shortname}</td>
                  <td>
                    {r.forecast ?? "—"} <span className="muted">{r.index ?? ""}</span>
                  </td>
                  <td className="muted">
                    {[...r.generationMix]
                      .sort((a, b) => b.perc - a.perc)
                      .slice(0, 3)
                      .filter((g) => g.perc > 0)
                      .map((g) => `${g.fuel} ${g.perc}%`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </details>
  );
}
