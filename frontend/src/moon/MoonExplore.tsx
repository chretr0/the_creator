import { useMemo, useState } from "react";
import Icon from "../components/Icon";
import { PanelTabs } from "../components/PanelNavigation";
import { EVIDENCE_LABEL } from "../lib/datalayers";
import { PREPARE_ELEVATION_SCRIPT, PREPARE_REFERENCE_SCRIPT, type MissionFeature, type MoonSite } from "./api";
import { MOON_VIEWS, OVERLAYS, type ComingGroup, type MoonView, type OverlayId, type OverlayState } from "./catalogue";
import { formatDistanceKm, formatMeasure, UNKNOWN } from "./geo";
import {
  beyondMapEdge,
  countByKind,
  MISSION_COLOUR,
  missionPosition,
  rgb,
  siteKindMeta,
  SITE_KIND_META,
  sortSites,
} from "./layers";
import type { LoadStatus, MoonData } from "./useMoonData";
import type { MoonH3State } from "./useMoonH3";

/* ---------------- Shared bits ---------------- */

function StatusNote({ status, script = PREPARE_REFERENCE_SCRIPT }: { status: LoadStatus; script?: string }) {
  if (status.loading) return <span className="muted small right">Loading…</span>;
  if (status.notPrepared) return <span className="warn small right" title={`Run ${script}`}>Not prepared</span>;
  if (status.error) return <span className="warn small right" title={status.error}>Unavailable</span>;
  return null;
}

/** Friendly 503 hint: the data exists once someone runs the prepare script. */
export function NotPreparedHint({ what, script }: { what: string; script: string }) {
  return (
    <div className="no-coverage moon-not-prepared" role="status">
      <strong>{what} isn’t prepared on this server yet</strong>
      <p className="small">
        Run <code>{script}</code> from the repository root, then reload. Nothing is shown as zero in the meantime.
      </p>
    </div>
  );
}

/* ---------------- Map & overlays ---------------- */

type OverlaysProps = {
  overlays: OverlayState;
  onOverlay: (id: OverlayId, patch: Partial<{ on: boolean; opacity: number }>) => void;
  /** Prepared, named mare polygons (vector) when the server has them; else the WMS outline overlay is offered. */
  mareVector: { usable: boolean; on: boolean; onToggle: () => void; status: LoadStatus; count: number | null };
  onView: (view: MoonView) => void;
};

export function OverlaysPanel({ overlays, onOverlay, mareVector, onView }: OverlaysProps) {
  return (
    <section className="panel moon-overlays">
      <h2>Map &amp; overlays</h2>
      <div className="region-picker moon-views" aria-label="Map views">
        <span>Go to</span>
        {MOON_VIEWS.map((v) => (
          <button key={v.id} onClick={() => onView(v)}>
            {v.label}
          </button>
        ))}
      </div>

      <h3>Basemap</h3>
      <div className="moon-basemap-card">
        <span className="moon-basemap-swatch" aria-hidden />
        <div>
          <strong>LROC WAC global mosaic</strong>
          <span className="block muted small">100 m per pixel · NASA/GSFC/Arizona State University · live tiles</span>
        </div>
      </div>

      <h3>Overlays</h3>
      <ul className="list moon-overlay-list">
        {OVERLAYS.filter((o) => o.id !== "mare_wms" || !mareVector.usable).map((o) => {
          const st = overlays[o.id];
          return (
            <li key={o.id}>
              <label className="toggle">
                <input type="checkbox" checked={st.on} onChange={() => onOverlay(o.id, { on: !st.on })} />
                <span>
                  {o.label}
                  <small className="block muted">{o.detail}</small>
                </span>
              </label>
              {st.on && o.blend && (
                <label className="field moon-opacity">
                  <span>
                    Opacity <em className="right">{Math.round(st.opacity * 100)}%</em>
                  </span>
                  <input
                    type="range"
                    min={0.15}
                    max={1}
                    step={0.05}
                    value={st.opacity}
                    onChange={(e) => onOverlay(o.id, { opacity: Number(e.target.value) })}
                  />
                </label>
              )}
            </li>
          );
        })}
        {mareVector.usable && (
          <li>
            <label className="toggle">
              <input type="checkbox" checked={mareVector.on} onChange={mareVector.onToggle} />
              <span>
                Mare outlines
                <small className="block muted">
                  Named maria, 65° S–65° N{mareVector.count != null ? ` · ${mareVector.count.toLocaleString()} areas` : ""}
                </small>
              </span>
              <StatusNote status={mareVector.status} />
            </label>
          </li>
        )}
      </ul>
      <p className="muted small moon-edge-note">
        <Icon name="info" size={14} /> A Web Mercator map stops at 85° latitude, so Shackleton and most Artemis regions sit just past
        its edge. A polar view comes next.
      </p>
    </section>
  );
}

/* ---------------- Sites & missions ---------------- */

type SitesProps = {
  data: MoonData;
  show: { sites: boolean; missions: boolean; keepout: boolean };
  onShow: (key: "sites" | "missions" | "keepout") => void;
  selectedId: string | null;
  onPickSite: (s: MoonSite) => void;
  onPickMission: (m: MissionFeature) => void;
};

export function SitesPanel({ data, show, onShow, selectedId, onPickSite, onPickMission }: SitesProps) {
  const [view, setView] = useState<"landed" | "planned">("landed");
  const [filter, setFilter] = useState("");
  const kinds = useMemo(() => countByKind(data.sites ?? []), [data.sites]);
  const sorted = useMemo(() => sortSites(data.sites ?? []), [data.sites]);
  const needle = filter.trim().toLocaleLowerCase();
  const shownSites = needle
    ? sorted.filter((s) => `${s.properties.name} ${s.properties.mission ?? ""}`.toLocaleLowerCase().includes(needle))
    : sorted;
  const missions = (data.missions ?? []).filter((m) => m.properties.kind === "planned_mission");
  const regions = (data.missions ?? []).filter((m) => m.properties.kind === "artemis_region");
  const asOf = data.missions?.find((m) => m.properties.asOf)?.properties.asOf ?? null;
  const regionsBeyond = regions.filter((r) => {
    const p = missionPosition(r);
    return p && beyondMapEdge(p[1]);
  }).length;

  if (data.notPrepared) return <section className="panel"><NotPreparedHint what="Moon site data" script={PREPARE_REFERENCE_SCRIPT} /></section>;

  return (
    <section className="panel moon-sites">
      <h2>Sites &amp; missions</h2>
      <h3>On the map</h3>
      <label className="toggle">
        <input type="checkbox" checked={show.sites} onChange={() => onShow("sites")} />
        <span>Landed objects</span>
        {data.status.sites.loading || data.status.sites.error ? (
          <StatusNote status={data.status.sites} />
        ) : (
          <span className="muted small right num">{data.sites?.length.toLocaleString() ?? ""}</span>
        )}
      </label>
      {show.sites && kinds.length > 0 && (
        <ul className="legend moon-kind-legend">
          {kinds.map(({ kind, count }) => (
            <li key={kind}>
              <span className={`dot${kind === "crewed_landing" ? " moon-crewed-dot" : ""}`} style={{ background: rgb(SITE_KIND_META[kind].colour) }} />
              <span>{SITE_KIND_META[kind].plural}</span>
              <span className="muted num moon-count">{count}</span>
            </li>
          ))}
        </ul>
      )}
      <label className="toggle">
        <input type="checkbox" checked={show.missions} onChange={() => onShow("missions")} />
        <span>Planned missions &amp; Artemis regions</span>
        {data.status.missions.loading || data.status.missions.error ? (
          <StatusNote status={data.status.missions} />
        ) : (
          <span className="muted small right num">{data.missions?.length.toLocaleString() ?? ""}</span>
        )}
      </label>
      {show.missions && (data.missions?.length ?? 0) > 0 && (
        <ul className="legend moon-kind-legend">
          <li>
            <span className="dot moon-ring-dot" style={{ borderColor: rgb(MISSION_COLOUR.planned_mission) }} />
            <span>Planned missions</span>
            <span className="muted num moon-count">{missions.length}</span>
          </li>
          <li>
            <span className="dot moon-ring-dot" style={{ borderColor: rgb(MISSION_COLOUR.artemis_region) }} />
            <span>Artemis regions</span>
            <span className="muted num moon-count">{regions.length}</span>
          </li>
        </ul>
      )}
      <label className="toggle">
        <input type="checkbox" checked={show.keepout} onChange={() => onShow("keepout")} />
        <span>
          Heritage keep-out rings
          <small className="block muted">NASA 2011: 2.0 km around landing sites, 0.5 km around impacts</small>
        </span>
        {data.status.keepout.loading || data.status.keepout.error ? (
          <StatusNote status={data.status.keepout} />
        ) : (
          <span className="muted small right num">{data.keepout?.length.toLocaleString() ?? ""}</span>
        )}
      </label>

      <PanelTabs
        label="Site lists"
        value={view}
        onChange={setView}
        options={[
          { value: "landed", label: "Landed", count: data.sites?.length },
          { value: "planned", label: "Planned", count: data.missions?.length },
        ]}
      />

      {view === "landed" && (
        <>
          <input
            className="moon-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by name or mission"
            aria-label="Filter landed objects"
          />
          {data.status.sites.loading && <p className="muted small">Loading landed objects…</p>}
          {data.status.sites.error && !data.status.sites.notPrepared && <p className="warn small">{data.status.sites.error}</p>}
          <ul className="place-list moon-record-list">
            {shownSites.map((s) => {
              const p = s.properties;
              const meta = siteKindMeta(p.kind);
              return (
                <li key={p.id}>
                  <button className={`link${p.id === selectedId ? " selected" : ""}`} onClick={() => onPickSite(s)}>
                    <span className="dot" style={{ background: rgb(meta.colour) }} />
                    <span className="place-name">
                      <span>{p.name}</span>
                      <span className="muted small">
                        {[meta.label, p.mission && p.mission !== p.name ? p.mission : null, p.date ?? "date unknown"].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
            {data.sites && shownSites.length === 0 && <li className="muted small pad">No landed object matches “{filter.trim()}”.</li>}
          </ul>
          <p className="muted small">
            LROC anthropogenic objects (MOON-SITE-01): positions measured from orbit. Luna dates are launch dates.
          </p>
        </>
      )}

      {view === "planned" && (
        <>
          {data.status.missions.loading && <p className="muted small">Loading planned missions…</p>}
          {data.status.missions.error && !data.status.missions.notPrepared && <p className="warn small">{data.status.missions.error}</p>}
          <h4>Planned missions</h4>
          <MissionList items={missions} selectedId={selectedId} onPick={onPickMission} />
          <h4>Artemis candidate regions</h4>
          <MissionList items={regions} selectedId={selectedId} onPick={onPickMission} />
          {regionsBeyond > 0 && (
            <p className="muted small">
              {regionsBeyond} of {regions.length} regions lie past the map’s 85° S edge; they’re listed here and open with full details.
            </p>
          )}
          <p className="muted small">
            Curated plans (MOON-SITE-02){asOf ? `, as of ${asOf}` : ""}. Dates are as published and slip often.
          </p>
        </>
      )}
    </section>
  );
}

function MissionList({ items, selectedId, onPick }: { items: MissionFeature[]; selectedId: string | null; onPick: (m: MissionFeature) => void }) {
  if (!items.length) return <p className="empty-note">None listed.</p>;
  return (
    <ul className="place-list moon-record-list">
      {items.map((m) => {
        const p = m.properties;
        const pos = missionPosition(m);
        return (
          <li key={p.id}>
            <button className={`link${p.id === selectedId ? " selected" : ""}`} onClick={() => onPick(m)}>
              <span className="dot moon-ring-dot" style={{ borderColor: rgb(MISSION_COLOUR[p.kind] ?? MISSION_COLOUR.planned_mission) }} />
              <span className="place-name">
                <span>
                  {p.name}
                  {!pos && <span className="tag">no coordinates</span>}
                  {pos && beyondMapEdge(pos[1]) && <span className="tag moon-edge-tag">beyond map edge</span>}
                </span>
                <span className="muted small">{[p.kind === "artemis_region" ? null : p.target, p.date].filter(Boolean).join(" · ") || UNKNOWN}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------- Surface data ---------------- */

export function SurfaceDataPanel({ h3, onFitView }: { h3: MoonH3State; onFitView: (view: MoonView) => void }) {
  const { layers, active } = h3;
  return (
    <section className="panel moon-surface">
      <h2>Surface data</h2>
      {layers === null && (
        <div aria-busy="true" className="moon-skeleton-rows">
          <div className="skeleton" style={{ height: 54 }} />
        </div>
      )}
      {h3.listError && <p className="warn small">Couldn’t load surface layers: {h3.listError}</p>}
      {layers && layers.length === 0 && !h3.listError && (
        h3.listMissing === "not_served" ? (
          <div className="no-coverage moon-not-prepared" role="status">
            <strong>Surface data isn’t served by this backend yet</strong>
            <p className="small">The Moon H3 endpoint (/api/moon/h3) isn’t available here. Restart the backend on the latest code, then reload.</p>
          </div>
        ) : (
          <NotPreparedHint what="Surface data" script={PREPARE_ELEVATION_SCRIPT} />
        )
      )}
      {layers && layers.length > 0 && (
        <>
          <p className="subtitle small">Colour the hexagon grid by a measured layer.</p>
          <div className="layer-options" aria-label="Surface data layers">
            {layers.map((l) => (
              <button key={l.id} className={`layer-choice${active?.id === l.id ? " selected" : ""}`} onClick={() => h3.setActive(active?.id === l.id ? null : l.id)} aria-pressed={active?.id === l.id} disabled={l.available === false}>
                <span>
                  {l.name}
                  <small>
                    {l.available === false
                      ? "Listed but not prepared"
                      : [l.sourceId, l.nativeResolutionKm ? `≈${formatDistanceKm(l.nativeResolutionKm)} source pixels` : null, `finest res ${l.maxResolution}`].filter(Boolean).join(" · ")}
                  </small>
                </span>
                <Icon name="chevron" size={16} />
              </button>
            ))}
          </div>
        </>
      )}
      {active && (
        <div className="layer-settings">
          <div className="panel-head">
            <h3>{active.name}</h3>
            <span className="tag">Active layer</span>
          </div>
          <label className="field">
            <span>
              Opacity <em className="right">{Math.round(h3.opacity * 100)}%</em>
            </span>
            <input type="range" min={0.2} max={1} step={0.05} value={h3.opacity} onChange={(e) => h3.setOpacity(Number(e.target.value))} />
          </label>
          <MoonH3Legend h3={h3} />
          {h3.status.loading && <p className="muted small">Loading values…</p>}
          {h3.status.notPrepared && <NotPreparedHint what={active.name} script={PREPARE_ELEVATION_SCRIPT} />}
          {h3.status.error && !h3.status.notPrepared && <p className="warn small">{h3.status.error}</p>}
          {active.description && <p className="small">{active.description}</p>}
          <dl className="kv small moon-layer-facts">
            <dt>Unit</dt>
            <dd>{active.unit || UNKNOWN}</dd>
            <dt>Finest cells</dt>
            <dd>Resolution {active.maxResolution}; finer hexagons show their res-{active.maxResolution} parent</dd>
            {active.nativeResolutionKm != null && (
              <>
                <dt>Source grid</dt>
                <dd>≈ {formatDistanceKm(active.nativeResolutionKm)} per pixel</dd>
              </>
            )}
            {active.aggregation && (
              <>
                <dt>Per cell</dt>
                <dd>{active.aggregation} of the source pixels inside</dd>
              </>
            )}
            <dt>Evidence</dt>
            <dd>{active.evidenceType ? (EVIDENCE_LABEL[active.evidenceType] ?? active.evidenceType.replace(/_/g, " ")) : UNKNOWN}</dd>
            <dt>Source</dt>
            <dd className="mono">{active.sourceId}</dd>
          </dl>
          {active.limitations?.length ? (
            <ul className="limitations small muted moon-limitations">
              {active.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          ) : null}
          <div className="actions tight">
            <button className="chip" onClick={() => onFitView(MOON_VIEWS[0])}>Whole near side</button>
            <button className="link inline small" onClick={() => h3.setActive(null)}>
              Remove from map
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** Ramp, range, "No data" swatch and the resolution the values come from. */
export function MoonH3Legend({ h3, onMap = false }: { h3: MoonH3State; onMap?: boolean }) {
  const { active, scale } = h3;
  if (!active) return null;
  if (!scale) return <p className="muted small">{h3.status.loading ? "Loading values…" : "No values on screen yet."}</p>;
  const [lo, hi] = scale.domain;
  const gradient = `linear-gradient(to right, ${scale.stops.map((c) => rgb(c)).join(", ")})`;
  const served = h3.servedResolution;
  const ramp = (
    <div className="ramp" aria-label={`Colour scale ${lo} to ${hi} ${active.unit}`}>
      <div className="ramp-bar" style={{ background: gradient }} />
      <div className="ramp-ticks small">
        <span>≤ {formatMeasure(lo)}</span>
        <span>{formatMeasure((lo + hi) / 2)}</span>
        <span>≥ {formatMeasure(hi)}</span>
      </div>
    </div>
  );
  if (onMap) {
    return (
      <>
        <div>
          <strong>{active.name}</strong>
          <span className="muted small block">
            {active.unit}
            {served != null ? ` · res-${served} cells` : ""}
            {active.nativeResolutionKm != null ? ` · ≈${formatDistanceKm(active.nativeResolutionKm)} source` : ""}
          </span>
        </div>
        {ramp}
        <span className="muted small legend-unknown">
          <span className="swatch no-data" /> No data
        </span>
      </>
    );
  }
  return (
    <>
      {ramp}
      <p className="muted small">
        {active.unit}
        {active.range
          ? active.rangeMethod
            ? ` · colours span the ${active.rangeMethod.replace(/^./, (c) => c.toLocaleLowerCase())}`
            : " · the layer’s published range"
          : " · range of the cells on screen"}
        {active.extent ? `. Full range ${formatMeasure(active.extent[0])} to ${formatMeasure(active.extent[1], active.unit)}.` : ""}
      </p>
      <p className="muted small">
        <span className="swatch no-data" aria-hidden /> Faint grey = no data (unknown, never zero).
        {h3.coverage ? ` ${h3.coverage.withData.toLocaleString()} of ${h3.coverage.known.toLocaleString()} cells on screen have a value.` : ""}
        {served != null ? ` Values on screen come from resolution-${served} cells.` : ""}
      </p>
    </>
  );
}

/* ---------------- Coming next ---------------- */

export function ComingNextPanel({ groups }: { groups: ComingGroup[] }) {
  return (
    <section className="panel moon-coming">
      <h2>Coming next</h2>
      <p className="subtitle small">
        Priority layers from the Moon data catalogue that aren’t mapped yet. Until they are, the inspector says “not measured” rather
        than guessing.
      </p>
      {groups.length === 0 && <p className="empty-note">Everything on the priority list is mapped.</p>}
      {groups.map((g) => (
        <div key={g.id} className="moon-coming-group">
          <div className="moon-coming-head">
            <Icon name={g.icon} size={17} />
            <div>
              <strong>{g.label}</strong>
              <span className="block muted small">{g.why}</span>
            </div>
          </div>
          <ul className="moon-checklist">
            {g.items.map((i) => (
              <li key={i.id}>
                <span className="moon-check" aria-hidden />
                <span className="moon-check-name">
                  {i.name}
                  <span className="block muted small">{i.coverage}</span>
                </span>
                <span className="tag mono">{i.id}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="muted small">IDs refer to the Moon data catalogue (CLAUDE-Moon-Data-Sources.md).</p>
    </section>
  );
}
