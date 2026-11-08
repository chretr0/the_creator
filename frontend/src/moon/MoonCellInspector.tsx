import { useEffect, useMemo, useState } from "react";
import { cellToBoundary, cellToChildrenSize, getResolution } from "h3-js";
import Icon from "../components/Icon";
import { MOON_RADIUS_KM } from "../bodies/moon";
import { cellAreaKm2, edgeLengthKm } from "../lib/bodyGeometry";
import { SIMULATION_RESOLUTION } from "../lib/h3grid";
import { isNotPrepared, moonApi, PREPARE_REFERENCE_SCRIPT, type MoonCellContext, type MoonH3Layer } from "./api";
import { pendingSummary, type ComingGroup } from "./catalogue";
import {
  featureTypeLabel,
  formatAreaKm2,
  formatDistanceKm,
  formatLatLon,
  formatMeasure,
  keepoutRuleLabel,
  ringBBox,
  UNKNOWN,
  type KeepoutHit,
} from "./geo";
import { rgb, siteKindMeta } from "./layers";

export type CellSelection = { h3Id: string; latitude: number; longitude: number };

/** Whether the server has prepared each reference layer the cell context reads (the manifest's `available`). */
export type ReferenceAvailability = { mare: boolean; places: boolean; sites: boolean };

type Props = {
  selection: CellSelection;
  /** Keep-out rings containing the selected point itself (null until the rings have loaded). */
  pointKeepout: KeepoutHit[] | null;
  /** A layer that isn't prepared leaves the context empty: its absence is unknown, not measured. */
  available: ReferenceAvailability;
  /** Moon H3 layers on the server (null while loading). */
  h3Layers: MoonH3Layer[] | null;
  activeLayer: MoonH3Layer | null;
  pending: ComingGroup[];
  onSelectSimulationCell: () => void;
  onZoomToCell: (bbox: [number, number, number, number]) => void;
  onGoTo: (lat: number, lon: number, zoom?: number) => void;
  onPickSite: (siteId: string) => void;
  onShowLayer: (layerId: string) => void;
  onShowComingNext: () => void;
};

type LayerValue = { layer: MoonH3Layer; value: number | null; served: number | null };

/** The elevation layer if the server has one (by id, else by unit and name). */
export function findElevationLayer(layers: MoonH3Layer[] | null): MoonH3Layer | null {
  if (!layers?.length) return null;
  return layers.find((l) => l.id === "elevation") ?? layers.find((l) => l.unit === "m" && /elev|height|topo/i.test(`${l.id} ${l.name}`)) ?? null;
}

/** "In Mare Tranquillitatis", "Near Moltke" … for the inspector title. */
export function placeTitle(ctx: MoonCellContext | null): string | null {
  if (!ctx) return null;
  const inside = ctx.nearestPlaces.find((p) => p.within);
  if (inside && ctx.mare && inside.name !== ctx.mare.name) return `${inside.name} · ${ctx.mare.name}`;
  if (inside) return inside.name;
  if (ctx.mare) return ctx.mare.name;
  const near = ctx.nearestPlaces[0];
  return near ? `Near ${near.name}` : null;
}

/** Said instead of an absence when the layer that would show it isn't prepared on the server. */
export const NOT_PREPARED = "Unknown (layer not prepared)";

/** A stated absence only when the layer was read; otherwise Unknown. */
export const absenceText = (prepared: boolean, absence: string): string => (prepared ? absence : NOT_PREPARED);

/** The Mare fact: a name, "not in a mapped mare" only where the prepared mare map covers the point, else Unknown. */
export function mareSummary(
  ctx: Pick<MoonCellContext, "mare"> | null,
  failed: boolean,
  latitude: number,
  prepared: boolean,
): { text: string; note: string } {
  if (!ctx) return { text: failed ? UNKNOWN : "…", note: "LROC mare map" };
  if (ctx.mare) return { text: ctx.mare.name, note: "LROC mare map" };
  if (!prepared) return { text: UNKNOWN, note: "Mare layer not prepared on this server" };
  if (Math.abs(latitude) > 65) return { text: UNKNOWN, note: "The mare map covers 65° S–65° N" };
  return { text: "Not in a mapped mare", note: "Highlands or a small mare patch" };
}

type CentreKeepout = MoonCellContext["keepout"][number];

/**
 * What the keep-out alert says. Once the rings have loaded it is about the selected point (the ring
 * under the cursor); rings that contain only the cell centre are listed apart. Until then it falls
 * back to the server's result, which is for the cell centre.
 */
export function keepoutView(
  point: KeepoutHit[] | null,
  centre: CentreKeepout[] | null,
): { at: "point" | "centre"; hits: (KeepoutHit | CentreKeepout)[]; centreOnly: CentreKeepout[] } {
  if (!point) return { at: "centre", hits: centre ?? [], centreOnly: [] };
  const inside = new Set(point.map((h) => h.siteId));
  return { at: "point", hits: point, centreOnly: (centre ?? []).filter((h) => !inside.has(h.siteId)) };
}

export default function MoonCellInspector(props: Props) {
  const { selection, h3Layers, activeLayer } = props;
  const [ctx, setCtx] = useState<MoonCellContext | null>(null);
  const [ctxError, setCtxError] = useState<{ message: string; notPrepared: boolean } | null>(null);
  const [values, setValues] = useState<LayerValue[] | null>(null);
  const [valuesError, setValuesError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setCtx(null);
    setCtxError(null);
    moonApi
      .cellContext(selection.h3Id, ctrl.signal)
      .then(setCtx)
      .catch((e) => {
        if (!ctrl.signal.aborted) setCtxError({ message: e instanceof Error ? e.message : String(e), notPrepared: isNotPrepared(e) });
      });
    return () => ctrl.abort();
  }, [selection.h3Id]);

  const elevation = useMemo(() => findElevationLayer(h3Layers), [h3Layers]);
  const valueLayers = useMemo(() => {
    const out: MoonH3Layer[] = [];
    if (elevation) out.push(elevation);
    if (activeLayer && activeLayer.id !== elevation?.id) out.push(activeLayer);
    return out;
  }, [elevation, activeLayer]);
  const valueKey = valueLayers.map((l) => l.id).join(",");

  useEffect(() => {
    if (!valueLayers.length) {
      setValues([]);
      return;
    }
    const ctrl = new AbortController();
    setValues(null);
    setValuesError(null);
    Promise.all(
      valueLayers.map((layer) =>
        moonApi.h3Values(layer.id, [selection.h3Id], ctrl.signal).then((r) => {
          const v = r.values?.[selection.h3Id];
          return {
            layer,
            value: typeof v === "number" && Number.isFinite(v) ? v : null,
            served: r.servedResolution?.[selection.h3Id] ?? null,
          };
        }),
      ),
    )
      .then(setValues)
      .catch((e) => {
        if (!ctrl.signal.aborted) setValuesError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
    // valueKey identifies valueLayers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection.h3Id, valueKey]);

  const res = getResolution(selection.h3Id);
  const coarse = res < SIMULATION_RESOLUTION;
  const area = cellAreaKm2(selection.h3Id, MOON_RADIUS_KM);
  const edge = edgeLengthKm(res, MOON_RADIUS_KM);
  const title = placeTitle(ctx) ?? (ctx || ctxError ? "Selected location" : "Locating…");
  const elevationValue = values?.find((v) => v.layer.id === elevation?.id) ?? null;
  const otherValue = values?.find((v) => v.layer.id !== elevation?.id) ?? null;
  const { available } = props;
  const mare = mareSummary(ctx, !!ctxError, selection.latitude, available.mare);
  const keepout = keepoutView(props.pointKeepout, ctx?.keepout ?? null);

  return (
    <section className="panel insights moon-insights">
      <header className="insights-place">
        <h2>{coarse ? `Hexagon · ${title}` : title}</h2>
        <p className="subtitle num">
          {formatLatLon(selection.latitude, selection.longitude)} · {formatAreaKm2(area)}
        </p>
      </header>

      {keepout.hits.length > 0 && (
        <div className="moon-keepout-alert" role="alert">
          <Icon name="info" size={18} />
          <div>
            <strong>{keepout.at === "point" ? "Inside a heritage keep-out zone" : "Cell centre inside a heritage keep-out zone"}</strong>
            {keepout.hits.map((k) => (
              <p key={`${k.siteId}:${k.rule}`} className="small">
                {keepout.at === "point" ? "The selected point is" : "The cell centre is"} {formatDistanceKm(k.distanceKm)} from {k.siteName}, a{" "}
                {keepoutRuleLabel(k.rule)}. NASA’s 2011 recommendations ask landers to stay {formatDistanceKm(k.radiusM / 1000)} away.
              </p>
            ))}
          </div>
        </div>
      )}
      {keepout.centreOnly.length > 0 && (
        <p className="coarse-note small">
          {keepout.centreOnly.map((k) => (
            <span key={`${k.siteId}:${k.rule}`} className="block">
              This cell’s centre is {formatDistanceKm(k.distanceKm)} from {k.siteName}, inside its keep-out zone; the selected point
              is outside it.
            </span>
          ))}
        </p>
      )}

      {coarse && (
        <div className="coarse-note">
          <p className="small">
            This resolution-{res} hexagon holds {cellToChildrenSize(selection.h3Id, SIMULATION_RESOLUTION).toLocaleString()} resolution-6
            simulation cells. Context below is for its centre.
          </p>
          <div className="actions tight">
            <button className="chip" onClick={() => props.onZoomToCell(ringBBox(cellToBoundary(selection.h3Id)))}>
              Zoom to hexagon
            </button>
            <button className="chip" onClick={props.onSelectSimulationCell}>
              Select the resolution-6 cell here
            </button>
          </div>
        </div>
      )}

      <div className="glance moon-glance">
        <div className="glance-fact">
          <span className="glance-label">Elevation</span>
          <ElevationValue layer={elevation} value={elevationValue} loading={values === null && !valuesError} />
          <span className="tile-note">{elevationNote(elevation, elevationValue, res)}</span>
        </div>
        <div className="glance-fact">
          <span className="glance-label">Mare</span>
          <span className="num-value">
            <strong className="text">{mare.text}</strong>
          </span>
          <span className="tile-note">{mare.note}</span>
        </div>
        <div className="glance-fact">
          <span className="glance-label">LAC quad</span>
          <span className="num-value">
            <strong className="text">{ctx ? (ctx.quad ?? UNKNOWN) : ctxError ? UNKNOWN : "…"}</strong>
          </span>
          <span className="tile-note" title="Lunar Astronautical Chart sheet (1:1,000,000)">Lunar chart sheet</span>
        </div>
      </div>

      {otherValue && (
        <div className="moon-layer-value">
          <button className="tile-name" onClick={() => props.onShowLayer(otherValue.layer.id)}>
            {otherValue.layer.name}
            <Icon name="layers" size={13} />
          </button>
          <span className="num-value">
            <strong>{formatMeasure(otherValue.value, otherValue.layer.unit)}</strong>
          </span>
          {otherValue.served !== null && otherValue.served < res && (
            <span className="tile-note">Resolution-{otherValue.served} average (the finest this layer has)</span>
          )}
        </div>
      )}
      {valuesError && <p className="warn small">Surface values couldn’t be loaded: {valuesError}</p>}

      {ctxError && (
        <p className={ctxError.notPrepared ? "coarse-note small" : "warn small"} role="status">
          {ctxError.notPrepared ? (
            <>
              Named features, landed objects and keep-out zones aren’t prepared on this server yet. Run <code>{PREPARE_REFERENCE_SCRIPT}</code>.
            </>
          ) : (
            <>Location context couldn’t be loaded: {ctxError.message}</>
          )}
        </p>
      )}

      <section className="insight-section">
        <h3 className="section-label">
          <Icon name="pin" size={16} /> Nearest named features
        </h3>
        {!ctx && !ctxError && <Skeleton rows={3} />}
        {ctx && ctx.nearestPlaces.length === 0 && <p className="empty-note">{absenceText(available.places, "No named features found.")}</p>}
        {ctx && ctx.nearestPlaces.length > 0 && (
          <ul className="place-list">
            {ctx.nearestPlaces.map((p) => (
              <li key={p.id ?? p.name}>
                <button className="link" onClick={() => props.onGoTo(p.latitude, p.longitude)}>
                  <Icon name="pin" size={15} />
                  <span className="place-name">
                    <span>
                      {p.name}
                      {p.within && <span className="tag moon-inside-tag">inside</span>}
                    </span>
                    <span className="muted small">
                      {[featureTypeLabel(p.type), p.diameterKm != null ? `${formatDistanceKm(p.diameterKm)} across` : null, p.quad]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <span className="dist muted small">{p.within && p.distanceKm < 0.05 ? "here" : formatDistanceKm(p.distanceKm)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {ctx && ctx.nearestPlaces.length > 0 && <p className="muted small moon-dist-note">Distances from the cell centre.</p>}
      </section>

      <section className="insight-section">
        <h3 className="section-label">
          <Icon name="navigation" size={16} /> Landed objects within 150 km
        </h3>
        {!ctx && !ctxError && <Skeleton rows={2} />}
        {ctx && ctx.nearbySites.length === 0 && (
          <p className="empty-note">
            {absenceText(available.sites, "No landers, rovers or impact sites recorded within 150 km.")}
            {!available.sites && " Landed objects and their keep-out zones aren’t prepared on this server."}
          </p>
        )}
        {ctx && ctx.nearbySites.length > 0 && (
          <ul className="place-list">
            {ctx.nearbySites.map((s) => (
              <li key={s.id}>
                <button className="link" onClick={() => props.onPickSite(s.id)}>
                  <span className="dot" style={{ background: rgb(siteKindMeta(s.kind).colour) }} />
                  <span className="place-name">
                    <span>{s.name}</span>
                    <span className="muted small">
                      {[siteKindMeta(s.kind).label, s.mission && s.mission !== s.name ? s.mission : null, s.date].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="dist muted small">{formatDistanceKm(s.distanceKm)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {ctx && ctx.nearbySites.length > 0 && <p className="muted small moon-dist-note">Distances from the cell centre.</p>}
      </section>

      <section className="insight-section">
        <h3 className="section-label">
          <Icon name="hexagon" size={16} /> This cell
        </h3>
        <dl className="kv small moon-cell-kv">
          <dt>H3 cell</dt>
          <dd className="mono">{selection.h3Id}</dd>
          <dt>Resolution</dt>
          <dd>
            {res}
            {res === SIMULATION_RESOLUTION ? " (simulation cell)" : ""}
          </dd>
          <dt>Area</dt>
          <dd className="num">{formatAreaKm2(area)}</dd>
          <dt>Edge length</dt>
          <dd className="num">≈ {formatDistanceKm(edge)} (average)</dd>
          <dt>Clicked point</dt>
          <dd className="num">{formatLatLon(selection.latitude, selection.longitude)}</dd>
          {ctx && (
            <>
              <dt>Cell centre</dt>
              <dd className="num">{formatLatLon(ctx.centre.latitude, ctx.centre.longitude)}</dd>
            </>
          )}
        </dl>
        <p className="muted small">Areas and lengths use the Moon’s radius (1,737.4 km), not Earth’s.</p>
      </section>

      {props.pending.length > 0 && (
        <section className="insight-section">
          <h3 className="section-label">
            <Icon name="timeline" size={16} /> Not measured yet
          </h3>
          <p className="empty-note">
            {pendingSummary(props.pending)} aren’t mapped here yet.{" "}
            <button className="link inline" onClick={props.onShowComingNext}>
              See what’s coming
            </button>
          </p>
        </section>
      )}
    </section>
  );
}

function ElevationValue({ layer, value, loading }: { layer: MoonH3Layer | null; value: LayerValue | null; loading: boolean }) {
  if (!layer) {
    return (
      <span className="num-value">
        <strong className="text">{UNKNOWN}</strong>
      </span>
    );
  }
  if (loading) return <span className="skeleton moon-value-skeleton" aria-label="Loading" />;
  if (!value || value.value === null) {
    return (
      <span className="num-value">
        <strong className="text">{UNKNOWN}</strong>
      </span>
    );
  }
  const v = value.value;
  return (
    <span className="num-value">
      <strong>{v > 0 ? "+" : ""}{Math.round(v).toLocaleString()}</strong>
      <small>{layer.unit}</small>
    </span>
  );
}

function elevationNote(layer: MoonH3Layer | null, value: LayerValue | null, res: number): string {
  if (!layer) return "No elevation layer on this server yet";
  const base = "vs the 1,737.4 km sphere";
  if (value?.served != null && value.served < res) return `${base} · res-${value.served} mean`;
  return base;
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="moon-skeleton-rows" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: 34 }} />
      ))}
    </div>
  );
}
