import type { CheckResult, LocationAssessment, LocationPriceOffer, PriceResource, SiteResource, SupportSuggestion } from "../lib/buildings";
import { coordLabel, fmtDays, fmtNumber } from "../lib/buildingForm";
import { fmtEstimate, LocationPrices, resourceStatus, resourceSummaryText, ResultView } from "./AssessmentView";
import { StateBadge } from "./FormBits";
import Icon from "./Icon";

export type SitePanelProps = {
  buildingName: string; // user's name or the template label
  typeLabel: string; // e.g. "Power station"
  colour: string; // css colour of the building type
  target: { latitude: number; longitude: number } | null; // null → empty state "Click the map to place it"
  loading: boolean; // an assessment request is in flight
  error: string | null; // assessment failed
  blocked: string | null; // form has invalid fields, e.g. "Fix 2 fields in Resources" — show instead of results
  location: LocationAssessment | null; // fresh assessment for target, or null
  periodDays: number;
  producesPower: boolean;
  producesWater: boolean;
  canBuild: boolean;
  building: boolean; // placing in progress
  buildError: string | null;
  supportNote: string | null; // e.g. after "place with support"
  onBuild: () => void; // "Build here"
  onCancel: () => void; // clear target
  onSupport?: (s: SupportSuggestion, presetId: string | null) => void;
  onApplyPrice: (o: LocationPriceOffer) => void;
  onRemovePrice: (r: PriceResource) => void;
};

/** Site checks that restate a site resource: the resource row is shown and the check is skipped. */
const CHECK_RESOURCE: Partial<Record<CheckResult["kind"], SiteResource["key"]>> = {
  site_land: "land",
  site_water: "water",
  site_power: "power",
  site_grid_export: "power",
  site_workforce: "workforce",
  site_air: "air",
  site_light: "light",
  site_material: "materials",
};

type NeedKind = "fail" | "unknown" | "surplus" | "ok";
type Need = { key: string; kind: NeedKind; label: string; advisory?: boolean; amount?: string; detail?: string; title?: string };

const clip = (s: string | null | undefined, n = 90) => (!s ? undefined : s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

/** Status of a resource: its matching site check decides when there is one (it knows reserves and rules). */
function resourceKind(r: SiteResource, checks: CheckResult[]): NeedKind | null {
  const own = checks.filter((c) => CHECK_RESOURCE[c.kind] === r.key);
  if (own.length > 0) {
    if (own.some((c) => c.status === "fail")) return "fail";
    if (own.some((c) => c.status === "unknown")) return "unknown";
    return "ok";
  }
  const cls = resourceStatus(r).cls;
  if (cls === "none") return null;
  if (cls === "pass") return "ok";
  if (cls === "fail") return "fail";
  return "unknown";
}

/** Output the grid can't take: an opportunity to use locally, never a shortfall. */
function surplusNeed(c: CheckResult): Need {
  const spare = c.actual !== null && c.requiredValue !== null ? c.actual - c.requiredValue : null;
  return {
    key: "surplus",
    kind: "surplus",
    label: "Surplus electricity",
    amount: spare !== null && spare > 0 ? `${fmtEstimate(spare, c.unit)} spare` : undefined,
    detail: c.requiredValue !== null && c.actual !== null ? `Grid takes ${fmtEstimate(c.requiredValue, c.unit)} of ${fmtEstimate(c.actual, c.unit)}` : undefined,
    title: c.explanation,
  };
}

function resourceNeed(r: SiteResource, checks: CheckResult[]): Need | null {
  const surplus = r.key === "power" ? checks.find((c) => c.kind === "site_grid_export" && c.status === "fail") : undefined;
  if (surplus) return surplusNeed(surplus);
  let kind = resourceKind(r, checks);
  if (!kind) return null;
  const advisory = !!r.advisory || resourceStatus(r).cls === "advisory";
  if (advisory && kind === "fail") kind = "unknown";
  const numeric = !r.status && r.needed !== null && r.available !== null;
  const need: Need = { key: `r-${r.key}`, kind, label: r.label, advisory, title: r.note ?? undefined };
  if (kind === "fail" && numeric && r.needed! > r.available!) {
    need.amount = `+ ${fmtEstimate(r.needed! - r.available!, r.unit)} more`;
    need.detail = `Site ${fmtEstimate(r.available, r.unit)} · needs ${fmtEstimate(r.needed, r.unit)}`;
  } else if (kind !== "ok") {
    const check = checks.find((c) => CHECK_RESOURCE[c.kind] === r.key && c.status !== "pass");
    need.detail = r.status ? resourceSummaryText(r) : clip(check?.explanation) ?? resourceStatus(r).text;
  }
  return need;
}

function checkNeed(c: CheckResult): Need {
  const advisory = !c.required;
  const kind: NeedKind = c.status === "pass" ? "ok" : c.status === "fail" && !advisory ? "fail" : "unknown";
  const both = c.kind !== "layer" && c.actual !== null && c.requiredValue !== null;
  return {
    key: `c-${c.criterionId}`,
    kind,
    label: c.label,
    advisory,
    amount: c.status === "fail" && both ? `${fmtNumber(c.actual!)} / ${fmtNumber(c.requiredValue!)}${c.unit ? ` ${c.unit}` : ""}` : undefined,
    detail: kind === "ok" ? undefined : clip(c.explanation),
    title: c.source || undefined,
  };
}

function needsFor(location: LocationAssessment): Need[] {
  const checks = location.assessment.checks;
  const resources = location.site?.resources ?? [];
  const keys = new Set(resources.map((r) => r.key));
  const out: Need[] = [];
  for (const r of resources) {
    const n = resourceNeed(r, checks);
    if (n) out.push(n);
  }
  for (const c of checks) {
    const k = CHECK_RESOURCE[c.kind];
    if (k && keys.has(k)) continue;
    out.push(c.kind === "site_grid_export" && c.status === "fail" ? surplusNeed(c) : checkNeed(c));
  }
  return out;
}

function NeedsList({ needs }: { needs: Need[] }) {
  const fails = needs.filter((n) => n.kind === "fail");
  const unknown = needs.filter((n) => n.kind === "unknown");
  const surplus = needs.filter((n) => n.kind === "surplus");
  const ok = needs.filter((n) => n.kind === "ok");
  if (needs.length === 0) return <p className="muted small">Nothing to check yet.</p>;
  const item = (n: Need) => (
    <li key={n.key} className={`need need-${n.kind}`} title={n.title}>
      <span className="need-label">
        {n.label}
        {n.advisory && <span className="muted"> (advisory)</span>}
      </span>
      {n.amount && <span className="need-amount num">{n.amount}</span>}
      {n.detail && <small className="need-detail">{n.detail}</small>}
    </li>
  );
  return (
    <ul className="site-needs">
      {fails.map(item)}
      {unknown.map(item)}
      {surplus.map(item)}
      {ok.length > 0 && (
        <li className="need need-ok">
          <span className="need-label">
            ✓ {ok.map((n) => n.label).join(", ")} {ok.length === 1 ? "is" : "are"} covered
          </span>
        </li>
      )}
    </ul>
  );
}

function SupportOptions({ suggestions, onSupport }: { suggestions: SupportSuggestion[]; onSupport?: (s: SupportSuggestion, presetId: string | null) => void }) {
  return (
    <div className="support-options">
      <h4>Build alongside</h4>
      {suggestions.map((s) => (
        <div key={s.resource} className="support-item" title={s.explanation}>
          <strong>
            {s.title}
            {s.resource !== "grid_export" && <span className="muted small num"> · short {fmtEstimate(s.shortfall, s.unit)}</span>}
          </strong>
          {onSupport && (
            <div className="actions tight wrap">
              {s.presets.map((p) => (
                <button key={p.id} onClick={() => onSupport(s, p.id)} title={`${p.name}: ${fmtEstimate(p.capacity, p.unit)} each`}>
                  + {p.name} ×{p.count}
                </button>
              ))}
              <button className="primary" onClick={() => onSupport(s, null)}>
                + {s.genericName}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Live check of the current building at the clicked map location: what the site still needs. */
export default function SitePanel(props: SitePanelProps) {
  const { target, location } = props;
  if (!target) {
    return (
      <div className="site-panel">
        <div className="site-panel-empty">
          <Icon name="pin" size={28} />
          <p>Click the map to place {props.buildingName}</p>
        </div>
      </div>
    );
  }

  let body;
  if (props.blocked) body = <p className="warn small">{props.blocked}</p>;
  else if (props.error) body = <p className="warn small">{props.error}</p>;
  else if (!location) body = <p className="muted small">{props.loading ? "Checking this site…" : "No result for this site yet."}</p>;
  else {
    const suggestions = location.assessment.suggestions ?? [];
    body = (
      <>
        <div className="site-verdict">
          <StateBadge state={location.assessment.state} />
          {location.assessment.summary && <span className="small">{location.assessment.summary}</span>}
          {props.loading && <span className="muted small">Updating…</span>}
        </div>
        <div className="site-panel-section">
          <h4>What you need here</h4>
          <NeedsList needs={needsFor(location)} />
        </div>
        {suggestions.length > 0 && <SupportOptions suggestions={suggestions} onSupport={props.onSupport} />}
        {props.supportNote && <p className="note small">{props.supportNote}</p>}
        <div className="site-panel-section">
          <h4>
            Usage &amp; costs <span className="muted small">over {fmtDays(props.periodDays)}</span>
          </h4>
          <ResultView result={location.result} producesPower={props.producesPower} producesWater={props.producesWater} />
        </div>
        {(location.utilityPrices?.length ?? 0) > 0 && (
          <div className="site-panel-section">
            <h4>Prices here</h4>
            <LocationPrices offers={location.utilityPrices!} onApply={props.onApplyPrice} onRemove={props.onRemovePrice} />
          </div>
        )}
      </>
    );
  }

  return (
    <div className="site-panel" aria-busy={props.loading || undefined}>
      <div className="site-panel-head">
        <span className="dot" style={{ background: props.colour }} />
        <div>
          <strong>{props.buildingName}</strong>
          <small className="muted mono block">
            {props.typeLabel} · {coordLabel(target.latitude, target.longitude)}
          </small>
        </div>
        <button className="ghost" aria-label="Remove placement" title="Remove placement" onClick={props.onCancel}>
          ✕
        </button>
      </div>
      {body}
      {props.buildError && <p className="warn small">{props.buildError}</p>}
      <div className="site-panel-actions">
        <button className="primary" disabled={!props.canBuild || props.building} onClick={props.onBuild}>
          {props.building ? "Placing…" : "Build here"}
        </button>
        <button className="ghost" onClick={props.onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
