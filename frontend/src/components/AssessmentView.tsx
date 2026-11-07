import { useState } from "react";
import { PanelTabs } from "./PanelNavigation";
import type {
  Assessment,
  BuildingResult,
  CheckResult,
  LocationPriceOffer,
  PriceResource,
  PriceSource,
  Quantity,
  SiteCapacity,
  SiteResource,
  SupportSuggestion,
} from "../lib/buildings";
import { checkComparison, fmtDays, fmtQuantity, LIGHT_PROXY_NOTE, priceSourceText } from "../lib/buildingForm";
import { Section, StateBadge, StatusBadge } from "./FormBits";

/** A value with its unit, or "unknown" plus the inputs that would be needed. Never 0 for missing. */
export function QuantityText({ q }: { q: Quantity | null | undefined }) {
  if (!q) return <span className="muted">unknown</span>;
  const unknown = q.value === null || q.value === undefined;
  return (
    <span title={q.basis || undefined}>
      <span className={unknown ? "muted" : "num"}>{fmtQuantity(q)}</span>
      {q.missing.length > 0 && (
        <small className="muted block">
          {unknown ? "needs" : "partial, missing"}: {q.missing.join(", ")}
        </small>
      )}
    </span>
  );
}

const ORDER = { fail: 0, unknown: 1, pass: 2 } as const;

function Check({ c }: { c: CheckResult }) {
  // Layer checks: the explanation states the cell value (class label, not code) and the rule.
  const comparison = checkComparison(c);
  return (
    <li className={`check check-${c.status}`}>
      <div className="check-head">
        <StatusBadge status={c.status} />
        <strong>{c.label}</strong>
        {!c.required && <span className="muted small">({c.kind === "site_material" ? "advisory — can be shipped" : "optional"})</span>}
      </div>
      {(comparison || c.period) && (
        <div className="small num">
          {comparison}
          {c.period && <span className="muted">{comparison ? " · " : ""}{c.period}</span>}
        </div>
      )}
      {c.explanation && <div className="small">{c.explanation}</div>}
      {c.source && <div className="small muted">Source: {c.source}</div>}
    </li>
  );
}

/**
 * Overall state, summary and every check (failures and unknowns first, shown together). With `site`,
 * what the hexagon and its neighbours provide is shown first and the detailed checks fold below it.
 */
export function AssessmentView({
  assessment,
  site,
  onSupport,
}: {
  assessment: Assessment;
  site?: SiteCapacity | null;
  /** Place this building, then preview the chosen supporting building next to it. */
  onSupport?: (s: SupportSuggestion, presetId: string | null) => void;
}) {
  const checks = [...assessment.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const list =
    checks.length === 0 ? (
      <p className="muted small">No checks were evaluated. Enter the building's footprint, water, power, staff, emissions, light or materials to check this site.</p>
    ) : (
      <ul className="checks">
        {checks.map((c) => (
          <Check key={c.criterionId} c={c} />
        ))}
      </ul>
    );
  return (
    <div className="assessment">
      <StateBadge state={assessment.state} />
      {assessment.summary && <p className="small">{assessment.summary}</p>}
      {(assessment.suggestions?.length ?? 0) > 0 && <SupportView suggestions={assessment.suggestions!} onSupport={onSupport} />}
      {site ? (
        <>
          <Section title="What the site provides" meta={`${site.resources.length} resources`}>
            <SiteCapacityView site={site} />
          </Section>
          <Section title="Why — each check explained" meta={`${checks.length} checks`}>
            {list}
          </Section>
        </>
      ) : (
        list
      )}
    </div>
  );
}

/** Buildings that could be placed alongside to cover a shortfall (power, water, grid export). */
function SupportView({ suggestions, onSupport }: { suggestions: SupportSuggestion[]; onSupport?: (s: SupportSuggestion, presetId: string | null) => void }) {
  return (
    <div className="support">
      <h4>Fix it by building alongside</h4>
      {suggestions.map((s) => (
        <div key={s.resource} className="support-item">
          <strong>{s.title}</strong>
          <p className="small">{s.explanation}</p>
          {onSupport ? (
            <div className="actions tight wrap">
              {s.presets.map((p) => (
                <button key={p.id} onClick={() => onSupport(s, p.id)} title={`Place this building, then preview ${p.name} next to it`}>
                  + {p.name} ({fmtEstimate(p.capacity, p.unit)}
                  {p.count > 1 ? `, ${p.count} needed` : ""})
                </button>
              ))}
              <button className="primary" onClick={() => onSupport(s, null)} title="Place this building, then preview a building sized to the shortfall next to it">
                + {s.genericName}
              </button>
            </div>
          ) : (
            s.presets.length > 0 && <p className="muted small">Examples: {s.presets.map((p) => p.name).join(", ")}.</p>
          )}
        </div>
      ))}
      {onSupport && <p className="muted small">Each button places this building first, then previews the supporting one in a neighbouring hexagon.</p>}
    </div>
  );
}

const shown = (q: Quantity | undefined) => !!q && (q.value !== null || q.missing.length > 0);

/** Calculated usage, outputs and costs for one building over the evaluation period. */
export function ResultView({ result, producesPower, producesWater }: { result: BuildingResult; producesPower?: boolean; producesWater?: boolean }) {
  const [view, setView] = useState<"usage" | "costs">("usage");
  const period = `over ${fmtDays(result.periodDays)}`;
  const c = result.costs;
  const cur = c.currency ?? "";
  const rows: [string, Quantity | undefined, string?, string?][] = [
    ["Footprint", result.footprint],
    ["Operating hours", result.operatingHours, period],
    ["Electricity use", result.electricityDemand, period],
    ["Peak demand", result.peakDemand, "capacity"],
  ];
  if (producesPower || shown(result.electricityOutput)) {
    rows.push(["Electricity output (gross)", result.electricityOutput, period]);
    rows.push(["Electricity net", result.electricityNet, period]);
  }
  rows.push(["Water use", result.waterDemand, period]);
  if (producesWater || shown(result.waterOutput)) {
    rows.push(["Water output", result.waterOutput, period]);
    rows.push(["Water net", result.waterNet, period]);
  }
  rows.push(["Upward light (declared)", result.light, "proxy, not sky brightness", LIGHT_PROXY_NOTE]);
  rows.push(["Lit hours", result.lightHours, period]);
  rows.push(["Worker capacity", result.workerCapacity]);
  rows.push(["Staff required", result.staffingRequired]);

  return (
    <div className="result">
      <PanelTabs label="Calculated results" value={view} onChange={setView} options={[
        { value: "usage", label: "Usage & output" }, { value: "costs", label: "Costs" },
      ]} />
      <div hidden={view !== "usage"}>
      <p className="muted small">
        Demand basis: {result.demandBasis === "derived" ? "derived from IT power × load × PUE" : "entered directly"}.
      </p>
      <table className="mini">
        <tbody>
          {rows.map(([label, q, note, title]) => (
            <tr key={label} title={title}>
              <th scope="row">
                {label}
                {note && <small className="muted block">{note}</small>}
              </th>
              <td>
                <QuantityText q={q} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {(result.emissions.length > 0 || result.materials.length > 0) && (
        <table className="mini">
          <tbody>
            {result.emissions.map((e) => (
              <tr key={`e-${e.pollutant}`}>
                <th scope="row">
                  {e.pollutant}
                  <small className="muted block">emitted {period}</small>
                </th>
                <td>
                  <QuantityText q={e.quantity} />
                </td>
              </tr>
            ))}
            {result.materials.map((m, i) => (
              <tr key={`m-${m.name}-${m.phase}-${i}`}>
                <th scope="row">
                  {m.name}
                  <small className="muted block">{m.phase === "construction" ? "construction, once" : `operation, ${period}`}</small>
                </th>
                <td>
                  <QuantityText q={m.quantity} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      </div>
      <div hidden={view !== "costs"}>
      <h4>Costs {cur && <span className="muted">({cur}, never converted)</span>}</h4>
      <table className="mini">
        <tbody>
          <tr>
            <th scope="row">Construction<small className="muted block">one-time</small></th>
            <td><QuantityText q={c.construction} /></td>
          </tr>
          <tr>
            <th scope="row">
              Operating, {c.operatingCostKind === "total" ? "all-inclusive total" : "fixed part"}
              <small className="muted block">{period}</small>
            </th>
            <td><QuantityText q={c.operatingFixed} /></td>
          </tr>
          {c.operatingCostKind === "fixed" && (
            <>
              <tr>
                <th scope="row">
                  Electricity<small className="muted block">{period}</small>
                  <PriceSourceNote src={c.electricityPriceSource} resource="electricity" />
                </th>
                <td><QuantityText q={c.electricity} /></td>
              </tr>
              <tr>
                <th scope="row">
                  Water<small className="muted block">{period}</small>
                  <PriceSourceNote src={c.waterPriceSource} resource="water" />
                </th>
                <td><QuantityText q={c.water} /></td>
              </tr>
              <tr>
                <th scope="row">Materials<small className="muted block">{period}</small></th>
                <td><QuantityText q={c.materials} /></td>
              </tr>
            </>
          )}
          <tr>
            <th scope="row">Known operating total<small className="muted block">{period}</small></th>
            <td><QuantityText q={c.operatingKnownTotal} /></td>
          </tr>
        </tbody>
      </table>
      {c.missing.length > 0 && <p className="small warn">Not included (unknown): {c.missing.join(", ")}</p>}
      </div>
    </div>
  );
}

function PriceSourceNote({ src, resource }: { src?: PriceSource | null; resource: PriceResource }) {
  if (!src) return null;
  return (
    <small className="block" title={src.basis ?? undefined}>
      <span className="tag prov-cited">Location default</span> {priceSourceText(src, resource)}
    </small>
  );
}

const RESOURCE_LABEL: Record<PriceResource, string> = { electricity: "Electricity", water: "Water" };

/**
 * The previewed cell's average business prices, offered as explicit location defaults. Nothing is
 * filled in until the user chooses it; a typed price always wins; USD is never mixed with another
 * currency (the server reports that as `currency_mismatch` and no action is offered).
 */
export function LocationPrices({
  offers,
  onApply,
  onRemove,
}: {
  offers: LocationPriceOffer[];
  onApply: (o: LocationPriceOffer) => void;
  onRemove: (r: PriceResource) => void;
}) {
  if (offers.length === 0) return null;
  return (
    <ul className="checks">
      {offers.map((o) => {
        const p = o.price;
        const label = p ? `${p.currency} ${p.value}/${o.resource === "electricity" ? "kWh" : "m³"}` : "";
        const canApply = !!p && (o.status === "available" || o.status === "applied_elsewhere");
        return (
          <li key={o.resource} className="check">
            <div className="check-head">
              <strong>{RESOURCE_LABEL[o.resource]} price</strong>
              {o.status === "applied" && <span className="tag prov-cited">Location default in use</span>}
              {o.status === "entered" && <span className="tag">Your price</span>}
            </div>
            <p className="small">{o.message}</p>
            {p?.basis && <small className="muted block">Source: {p.source} · basis: {p.basis}</small>}
            {canApply && (
              <div className="actions tight">
                <button onClick={() => onApply(o)}>
                  {o.status === "applied_elsewhere" ? "Use this location's price" : "Use location price"} ({label},{" "}
                  {p!.source})
                </button>
              </div>
            )}
            {(o.status === "applied" || o.status === "applied_elsewhere") && (
              <div className="actions tight">
                <button className="ghost" onClick={() => onRemove(o.resource)}>
                  Remove location price (back to unknown)
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Rough estimates: 3 significant figures, kW shown as MW above 1,000, big numbers as "million". */
export function fmtEstimate(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "unknown";
  let value = v;
  let u = unit;
  if (unit === "kW" && Math.abs(v) >= 1000) {
    value = v / 1000;
    u = "MW";
  }
  const sig = (x: number) => Number(x.toPrecision(3));
  const text =
    Math.abs(value) >= 1e6
      ? `${sig(value / 1e6).toLocaleString()} million`
      : sig(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return u === "people" ? `${text} people` : `${text} ${u}`.trim();
}

const STATUS_TEXT: Record<string, Record<string, string>> = {
  air: { pass: "Within the standard", fail: "Already above the standard", unknown: "Unknown here", none: "No local air pollutants" },
  light: { pass: "Zone allows it", fail: "Dark area: no upward light", unknown: "Unknown here", none: "No upward light" },
  materials: { pass: "All local", advisory: "Some shipped in", unknown: "Uncertain locally", none: "No mapped materials" },
};

function resourceStatus(r: SiteResource): { cls: string; text: string } {
  if (r.status) {
    const text = STATUS_TEXT[r.key]?.[r.status] ?? r.status;
    return { cls: r.status === "advisory" ? "advisory" : r.status, text };
  }
  if (r.key === "land" && r.needed === null) return { cls: "unknown", text: "Footprint not entered" };
  if (r.needed === null || r.needed === 0) return { cls: "none", text: "Not needed by its specs" };
  if (r.available === null) return { cls: "unknown", text: "Unknown here" };
  return r.available >= r.needed ? { cls: "pass", text: "Enough" } : { cls: "fail", text: "Not enough" };
}

/** Air, dark-sky and raw-material resources: the server decides the state; show its key figures. */
function ResourceSummary({ r }: { r: SiteResource }) {
  const part = (label: string) => r.parts.find((p) => p.label === label);
  const val = (label: string) => {
    const p = part(label);
    return p ? (p.text ?? fmtEstimate(p.value, p.unit)) : "unknown";
  };
  let text: string;
  if (r.key === "air") text = `Background PM2.5 ${val("Background PM2.5 (2024 mean)")} · standard ${val("Annual standard")}`;
  else if (r.key === "light") text = `${val("Lighting zone (ILP GN01)")} · up to ${fmtEstimate(r.available, r.unit)}`;
  else if (r.key === "materials")
    text = r.needed ? `Local source for ${r.available ?? 0} of ${r.needed} materials` : "None of its materials are mapped raw materials";
  else text = fmtEstimate(r.available, r.unit);
  return <div className="site-res-nums num small">{text}</div>;
}

/** What the cell and its neighbouring cells provide, next to what the building needs. Read-only. */
export function SiteCapacityView({ site }: { site: SiteCapacity }) {
  return (
    <div className="site-capacity">
      {site.resources.map((r) => {
        const st = resourceStatus(r);
        const ratio = r.needed && r.available ? Math.min(1, r.needed / r.available) : r.needed && r.available === 0 ? 1 : 0;
        return (
          <div key={r.key} className={`site-res res-${st.cls}`}>
            <div className="site-res-head">
              <strong>
                {r.label}
                {r.advisory && <span className="muted small"> (advisory)</span>}
              </strong>
              <span className={`res-chip res-${st.cls}`}>{st.text}</span>
            </div>
            {r.status ? (
              <ResourceSummary r={r} />
            ) : (
            <div className="site-res-nums num small">
              <span>
                Site provides <strong>{fmtEstimate(r.available, r.unit)}</strong>
              </span>
              {r.needed !== null && (
                <span>
                  {r.key === "power" && r.note ? "Exports" : "Needs"} <strong>{fmtEstimate(r.needed, r.unit)}</strong>
                </span>
              )}
            </div>
            )}
            {!r.status && r.needed !== null && r.needed > 0 && r.available !== null && (
              <div className="meter" role="img" aria-label={`${st.text}: needs ${Math.round(ratio * 100)}% of what the site provides`}>
                <span style={{ width: `${Math.max(2, ratio * 100)}%` }} />
              </div>
            )}
            <details className="site-res-parts">
              <summary className="small muted">How it's estimated · {r.reach}</summary>
              <ul className="small">
                {r.parts.map((p) => (
                  <li key={p.label}>
                    {p.label}: <span className="num">{p.text ?? fmtEstimate(p.value, p.unit)}</span>
                  </li>
                ))}
              </ul>
            </details>
            {r.note && r.status && <p className="muted small">{r.note}</p>}
          </div>
        );
      })}
      <p className="muted small">{site.note}</p>
    </div>
  );
}
