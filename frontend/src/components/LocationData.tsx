import type { ReactNode } from "react";
import { formatValue, type CellFeatureContext, type CellProfile, type FeatureLayerMeta, type FeatureProps, type ProfileValue } from "../lib/datalayers";
import {
  cleanLayerName,
  GLANCE,
  hasData,
  isMetaValue,
  isMonthly,
  slug,
  visibleAttributes,
  type ProfileLayer,
} from "../lib/insights";
import Icon, { type IconName } from "./Icon";

type ShowLayer = (layerId: string, sliceId?: string) => void;

export const CATEGORY_ICON: Record<string, IconName> = {
  "Solar & climate": "sun",
  Prices: "chart",
  Water: "water",
  "Terrain & land cover": "mountain",
  "People & settlement": "building",
  "Air quality": "fog",
  Vegetation: "sprout",
  Soil: "wheat",
  Hazards: "flame",
  Geology: "pickaxe",
};

const MONTHS = "JFMAMJJASOND".split("");
const unitText = (u: string | null | undefined) => (!u || u === "class" ? "" : u.replace(/^% of (cell|area|observed area)$/, "%"));

function Num({ v, units }: { v: number | null; units?: string | null }) {
  const u = unitText(units);
  return (
    <span className="num-value">
      <strong>{formatValue(v)}</strong>
      {u && v !== null && <small>{u}</small>}
    </span>
  );
}

/* ---------------- At a glance ---------------- */

export function AtAGlance({ profile }: { profile: CellProfile }) {
  const facts = GLANCE.flatMap((g) => {
    const layer = profile.layers.find((l) => l.layer === g.layer);
    const v = layer?.values.find((x) => x.slice === g.slice) ?? layer?.values[0];
    if (!layer || !v || v.display === null) return [];
    let main: ReactNode;
    if (layer.categorical) {
      const cat = layer.categories?.find((c) => c.value === Math.round(v.display!));
      if (!cat) return [];
      main = (
        <span className="num-value">
          <span className="swatch" style={{ background: cat.colour }} />
          <strong className="text">{cat.label.replace(/\s*\(.*\)$/, "")}</strong>
        </span>
      );
    } else if (g.layer === "precipitation") {
      main = <Num v={Math.round(v.display * 365)} units="mm/yr" />;
    } else {
      main = <Num v={v.display} units={g.layer === "population_ghsl" ? "/km²" : v.units} />;
    }
    return [{ ...g, main }];
  });
  if (!facts.length) return null;
  return (
    <div className="glance">
      {facts.map((f) => (
        <div key={f.layer} className="glance-fact">
          {f.main}
          <span className="glance-label">{f.label}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Category sections ---------------- */

export function DataSection({ category, layers, total, onShow }: { category: string; layers: ProfileLayer[]; total: number; onShow: ShowLayer }) {
  const withData = layers.filter(hasData);
  const without = layers.filter((l) => !hasData(l));
  // The same measure from two datasets (e.g. two population estimates) reads as one range.
  const merged = new Map<string, ProfileLayer[]>();
  for (const l of withData) {
    const vals = l.values.filter((v) => !isMetaValue(v));
    const key = vals.length === 1 && !l.categorical ? `${cleanLayerName(l.name)}|${vals[0].units}` : l.layer;
    merged.set(key, [...(merged.get(key) ?? []), l]);
  }
  return (
    <section className="insight-section" id={`insight-${slug(category)}`}>
      <h3 className="section-label">
        <Icon name={CATEGORY_ICON[category] ?? "layers"} size={16} /> {category}
      </h3>
      {withData.length > 0 && (
        <div className="tiles">
          {[...merged.values()].map((group) =>
            group.length > 1 ? (
              <RangeTile key={group[0].layer} layers={group} onShow={onShow} />
            ) : (
              <LayerTile key={group[0].layer} layer={group[0]} total={total} onShow={onShow} />
            ),
          )}
        </div>
      )}
      {without.length > 0 && (
        <p className="no-data-line">
          {withData.length ? "Not available here: " : "No data for this location: "}
          {without.map((l) => cleanLayerName(l.name)).join(", ")}
        </p>
      )}
    </section>
  );
}

function Tile({ layer, wide, total, onShow, slice, children }: { layer: ProfileLayer; wide?: boolean; total: number; onShow: ShowLayer; slice?: string; children: ReactNode }) {
  const n = Math.max(0, ...layer.values.map((v) => v.cellsWithData ?? 0));
  const attrs = visibleAttributes(layer);
  return (
    <div className={wide ? "tile wide" : "tile"}>
      <button className="tile-name" onClick={() => onShow(layer.layer, slice)} title="Show this layer on the map">
        <span>{cleanLayerName(layer.name)}</span>
        <Icon name="map" size={12} />
      </button>
      {children}
      {attrs.map((a) => (
        <span key={a.key} className="tile-note">{String(a.value)}</span>
      ))}
      {total > 1 && n > 0 && n < total && (
        <span className="tile-note" title="Simulation cells inside this hexagon that have data">
          {n.toLocaleString()} of {total.toLocaleString()} cells
        </span>
      )}
    </div>
  );
}

function RangeTile({ layers, onShow }: { layers: ProfileLayer[]; onShow: ShowLayer }) {
  const vals = layers.map((l) => l.values.find((v) => !isMetaValue(v))!).filter((v) => v.display !== null);
  const nums = vals.map((v) => v.display!) ;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const u = unitText(vals[0]?.units);
  return (
    <div className="tile">
      <button className="tile-name" onClick={() => onShow(layers[0].layer, vals[0]?.slice)} title="Show this layer on the map">
        <span>{cleanLayerName(layers[0].name)}</span>
        <Icon name="map" size={12} />
      </button>
      <span className="num-value">
        <strong>{formatValue((lo + hi) / 2)}</strong>
        {u && <small>{u}</small>}
      </span>
      {hi !== lo && <span className="tile-note">estimates {formatValue(lo)}–{formatValue(hi)}</span>}
    </div>
  );
}

function LayerTile({ layer, total, onShow }: { layer: ProfileLayer; total: number; onShow: ShowLayer }) {
  const values = layer.values.filter((v) => !isMetaValue(v));

  if (layer.categorical) {
    const dom = values.find((v) => v.categorical) ?? values.find((v) => v.slice === "dominant");
    const cat = dom?.display == null ? undefined : layer.categories?.find((c) => c.value === Math.round(dom.display!));
    const colourOf = (label: string) => layer.categories?.find((c) => c.label === label)?.colour ?? "#94a3b8";
    const shares = values
      .filter((v) => v !== dom && unitText(v.units) === "%" && (v.display ?? 0) > 0)
      .sort((a, b) => (b.display ?? 0) - (a.display ?? 0));
    const extras = values.filter((v) => v !== dom && unitText(v.units) !== "%" && v.display !== null);
    return (
      <Tile layer={layer} total={total} onShow={onShow} slice={dom?.slice} wide={shares.length > 0}>
        <span className="class-value">
          <span className="swatch" style={{ background: cat?.colour ?? "#94a3b8" }} />
          {cat?.label ?? "Unclassified"}
        </span>
        {extras.map((v) => (
          <span key={v.slice} className="tile-note">
            {v.label} {formatValue(v.display, v.label.includes("(") ? null : unitText(v.units) || null)}
          </span>
        ))}
        {shares.length > 0 && (
          <>
            <div className="stack" role="img" aria-label={`${cleanLayerName(layer.name)} shares`}>
              {shares.map((s) => (
                <span key={s.slice} title={`${s.label}: ${formatValue(s.display, "%")}`} style={{ width: `${s.display}%`, background: colourOf(s.label) }} />
              ))}
            </div>
            <ul className="legend data-legend">
              {shares.slice(0, 6).map((s) => (
                <li key={s.slice}>
                  <span className="swatch" style={{ background: colourOf(s.label) }} />
                  {s.label} <span className="muted">{formatValue(s.display)}%</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Tile>
    );
  }

  const monthly = values.filter(isMonthly);
  const clim = monthly.filter((v) => v.slice.startsWith("clim-"));
  const y2024 = monthly.filter((v) => v.slice.startsWith("2024-"));
  if (clim.length === 12 || y2024.length === 12) {
    const annual = values.find((v) => v.slice === "clim-ann") ?? values.find((v) => v.slice.endsWith("-ann")) ?? null;
    const bars = clim.length === 12 ? clim : y2024;
    const dots = clim.length === 12 && y2024.length === 12 ? y2024 : null;
    return (
      <Tile layer={layer} total={total} onShow={onShow} slice={annual?.slice}>
        <Num v={annual?.display ?? null} units={annual?.units ?? bars[0].units} />
        <span className="tile-note">{annual?.slice.startsWith("2024") ? "2024 average" : "yearly average"}</span>
        <MiniMonths bars={bars} dots={dots} />
      </Tile>
    );
  }

  const shown = values.filter((v) => v.display !== null);
  const sameUnits = shown.every((v) => v.units === shown[0]?.units);
  if (shown.length >= 5 && sameUnits) {
    const dated = shown.some((v) => /\b(19|20)\d{2}$/.test(v.label));
    const ordered = dated ? shown : [...shown].sort((a, b) => (b.display ?? 0) - (a.display ?? 0));
    const max = Math.max(...ordered.map((v) => Math.abs(v.display ?? 0))) || 1;
    return (
      <Tile layer={layer} total={total} onShow={onShow} slice={ordered[0]?.slice} wide>
        <ul className="hbars">
          {ordered.slice(0, 8).map((v) => (
            <li key={v.slice}>
              <span className="hbar-label">{v.label}</span>
              <span className="hbar-track"><span style={{ width: `${(Math.abs(v.display ?? 0) / max) * 100}%` }} /></span>
              <span className="hbar-value">{formatValue(v.display, unitText(v.units) === "abundance" ? null : unitText(v.units) || null)}</span>
            </li>
          ))}
        </ul>
      </Tile>
    );
  }

  const [head, ...rest] = shown.filter((v) => !isMonthly(v));
  return (
    <Tile layer={layer} total={total} onShow={onShow} slice={head?.slice}>
      <Num v={head?.display ?? null} units={head?.units} />
      {shown.length > 1 && <span className="tile-note">{head.label}</span>}
      {rest.length > 0 && (
        <dl className="tile-rows">
          {rest.map((v) => (
            <div key={v.slice}>
              <dt>{v.label}</dt>
              <dd>{formatValue(v.display, unitText(v.units) || null)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Tile>
  );
}

/** Twelve months as small bars, a second year as dots on the same scale. */
function MiniMonths({ bars, dots }: { bars: ProfileValue[]; dots: ProfileValue[] | null }) {
  const all = [...bars, ...(dots ?? [])].map((v) => v.display).filter((v): v is number => v !== null);
  if (!all.length) return null;
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const W = 144;
  const H = 40;
  const base = 10;
  const bw = W / 12;
  const y = (v: number) => H - base - ((v - lo) / (hi - lo || 1)) * (H - base - 2);
  const peak = bars.reduce((best, v, i) => ((v.display ?? -Infinity) > (bars[best].display ?? -Infinity) ? i : best), 0);
  return (
    <svg className="mini-months" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Monthly profile">
      {bars.map((v, i) =>
        v.display === null ? null : (
          <rect key={v.slice} x={i * bw + 1.5} width={bw - 3} y={Math.min(y(v.display), y(0))} height={Math.max(1, Math.abs(y(0) - y(v.display)))} rx={1.5} className={i === peak ? "bar peak" : "bar"}>
            <title>{`${v.label}: ${formatValue(v.display, v.units)}${dots?.[i]?.display != null ? ` · 2024: ${formatValue(dots[i].display, v.units)}` : ""}`}</title>
          </rect>
        ),
      )}
      {dots?.map((v, i) => (v.display === null ? null : <circle key={v.slice} cx={i * bw + bw / 2} cy={y(v.display)} r={1.8} className="dot2024" />))}
      {MONTHS.map((m, i) => (
        <text key={i} x={i * bw + bw / 2} y={H - 1} className="tick">{m}</text>
      ))}
    </svg>
  );
}

/* ---------------- Nearby mapped features ---------------- */

export function NearbySection({ context, manifest, onGoTo }: { context: CellFeatureContext; manifest: FeatureLayerMeta[]; onGoTo: (lat: number, lon: number) => void }) {
  const metaOf = (id: string) => manifest.find((m) => m.id === id);
  return (
    <section className="insight-section" id="insight-nearby">
      <h3 className="section-label"><Icon name="pin" size={16} /> Nearby</h3>
      <div className="tiles">
        {context.layers.map((l) => {
          const meta = metaOf(l.layer);
          const name = cleanLayerName(l.name);
          if (l.geometry === "polygon") {
            const f = l.features?.[0];
            if (!f) return null;
            return (
              <div key={l.layer} className="tile wide">
                <span className="tile-name static">{name}</span>
                <FieldList props={f} meta={meta} max={6} />
              </div>
            );
          }
          if (l.geometry === "line") {
            const top = l.features?.[0];
            return (
              <div key={l.layer} className="tile">
                <span className="tile-name static">{name}</span>
                <Num v={l.count ?? 0} units={l.count === 1 ? "crosses here" : "cross here"} />
                {top && meta?.valueField && top[meta.valueField] != null && (
                  <span className="tile-note">largest averages {formatValue(top[meta.valueField] as number, meta.valueUnits)}</span>
                )}
              </div>
            );
          }
          return (
            <div key={l.layer} className="tile wide">
              <span className="tile-name static">
                {name}
                <span className="muted">{l.inCell ?? 0} in this cell</span>
              </span>
              {l.nearest && l.nearest.length > 0 ? (
                <ul className="place-list">
                  {l.nearest.slice(0, 4).map((n, i) => (
                    <li key={i}>
                      <button className="link" onClick={() => onGoTo(n.lat, n.lon)}>
                        <span className="place-name">
                          {String((meta?.nameField && n[meta.nameField]) || n.id || "Unnamed")}
                          {meta?.categoryField && n[meta.categoryField] ? <span className="muted small">{String(n[meta.categoryField])}</span> : null}
                        </span>
                        <span className="muted small dist">{n.distanceKm.toFixed(1)} km</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="tile-note">None within {l.radiusKm} km</span>
              )}
            </div>
          );
        })}
      </div>
    </section>
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
