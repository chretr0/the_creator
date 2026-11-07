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
} from "../lib/buildings";
import { checkComparison, fmtDays, fmtQuantity, LIGHT_PROXY_NOTE, priceSourceText } from "../lib/buildingForm";
import { StateBadge, StatusBadge } from "./FormBits";

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
        {!c.required && <span className="muted small">(optional)</span>}
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

/** Overall state, summary and every check (failures and unknowns first, shown together). */
export function AssessmentView({ assessment }: { assessment: Assessment }) {
  const checks = [...assessment.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  return (
    <div className="assessment">
      <StateBadge state={assessment.state} />
      {assessment.summary && <p className="small">{assessment.summary}</p>}
      {checks.length === 0 ? (
        <p className="muted small">No checks were evaluated. Add requirements to get a conclusive result.</p>
      ) : (
        <ul className="checks">
          {checks.map((c) => (
            <Check key={c.criterionId} c={c} />
          ))}
        </ul>
      )}
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
