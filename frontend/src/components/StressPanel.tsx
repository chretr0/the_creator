import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Project, type Scenario } from "../lib/api";
import {
  NEUTRAL_STRESS,
  type BudgetKind,
  type BuildingEvaluation,
  type CheckResult,
  type Quantity,
  type ScenarioEvaluation,
  type ScenarioResult,
  type StressControls,
} from "../lib/buildings";
import {
  BUDGET_KINDS,
  budgetToDraft,
  fmtDays,
  fmtPercent,
  LIGHT_PROXY_NOTE,
  mergeAssumptions,
  newBudget,
  parseBudgets,
  parseNumber,
  parseStress,
  stressToDraft,
  type BudgetDraft,
  type StressDraft,
} from "../lib/buildingForm";
import { typeLabel } from "../lib/projectTypes";
import { checkQuantity, outputRelevant, shortfall, supplyPairs } from "../lib/stressCompare";
import { QuantityText } from "./AssessmentView";
import { Field, Section, StateBadge } from "./FormBits";

type Props = {
  scenario: Scenario;
  onSaved: (s: Scenario) => void;
  /** False while the panel is mounted but hidden: drafts are kept, nothing is evaluated. */
  active?: boolean;
};

type Control = { key: keyof StressControls; label: string; kind: "supply" | "multiplier"; meaning: (v: number) => string };

const CONTROLS: Control[] = [
  { key: "waterAvailability", label: "Water availability", kind: "supply", meaning: (v) => `${fmtPercent(v)} of declared water budgets available` },
  { key: "powerAvailability", label: "Power availability", kind: "supply", meaning: (v) => `${fmtPercent(v)} of declared power capacity and energy budgets available` },
  { key: "operatingDemand", label: "Operating demand", kind: "multiplier", meaning: (v) => `${fmtPercent(v)} of declared operating resource use (construction unchanged)` },
  { key: "operatingPrices", label: "Operating prices", kind: "multiplier", meaning: (v) => `${fmtPercent(v)} of declared unit prices (construction unchanged)` },
];

/** Plants that could contribute supply to a budget of this kind (nothing is connected automatically). */
function canSupply(p: Project, kind: BudgetKind): boolean {
  const s = p.definition?.stats;
  if (kind === "water_m3_per_day") return p.type === "water_plant" || s?.water?.outputM3PerHour != null;
  return p.type === "power_station" || p.type === "solar" || s?.power?.averageOutputKw != null || s?.power?.ratedOutputKw != null;
}

const DEBOUNCE_MS = 450;

const METRIC_LABEL: Record<string, string> = {
  electricityDemand: "Electricity use",
  electricityOutput: "Electricity output",
  waterDemand: "Water use",
  waterOutput: "Water output",
  constructionCost: "Construction cost",
  operatingCost: "Operating cost",
  light: "Upward light",
  workerCapacity: "Worker capacity",
};

export default function StressPanel({ scenario, onSaved, active = true }: Props) {
  const saved = useMemo(() => mergeAssumptions(scenario.assumptions), [scenario.assumptions]);
  // Content, not object identity: a rename or any other refetch returns a new (equal) object.
  const savedKey = JSON.stringify(saved);
  const [period, setPeriod] = useState(String(saved.periodDays));
  const [budgets, setBudgets] = useState<BudgetDraft[]>(() => saved.budgets.map(budgetToDraft));
  const [stressDraft, setStressDraft] = useState<StressDraft>(() => stressToDraft(saved.stress));
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<{ ok: boolean; text: string } | null>(null);

  // Reload the form whenever another scenario is shown or its saved assumptions change.
  useEffect(() => {
    setPeriod(String(saved.periodDays));
    setBudgets(saved.budgets.map(budgetToDraft));
    setStressDraft(stressToDraft(saved.stress));
    // saved is fully described by savedKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario.id, savedKey]);

  // The save note belongs to the scenario it was made for (our own save must not clear it).
  const scenarioIdRef = useRef(scenario.id);
  useEffect(() => {
    scenarioIdRef.current = scenario.id;
    setSaveNote(null);
  }, [scenario.id]);

  const periodParsed = parseNumber(period, "positive");
  const periodError = periodParsed.error ?? (periodParsed.value === null ? "Required" : periodParsed.value > 3660 ? "At most 3660 days" : null);
  const b = useMemo(() => parseBudgets(budgets), [budgets]);
  const st = useMemo(() => parseStress(stressDraft), [stressDraft]);
  const hasErrors = !!periodError || Object.keys(b.errors).length > 0 || Object.keys(st.errors).length > 0;

  const dirty =
    JSON.stringify({ p: periodParsed.value, b: b.budgets, s: st.stress }) !==
    JSON.stringify({ p: saved.periodDays, b: parseBudgets(saved.budgets.map(budgetToDraft)).budgets, s: saved.stress });

  // ---- evaluation (debounced; stress previewed before saving) ----
  const [evaluation, setEvaluation] = useState<{ key: string; value: ScenarioEvaluation } | null>(null);
  const [evalError, setEvalError] = useState<{ key: string; message: string } | null>(null);
  const projectsKey = scenario.projects.map((p) => `${p.id}@${p.updatedAt}`).join(",");
  const evalKey = JSON.stringify([scenario.id, scenario.updatedAt, projectsKey, st.stress, periodParsed.value, b.budgets]);
  const inputsValid = !hasErrors && periodParsed.value !== null;

  useEffect(() => {
    if (!inputsValid || !active) return;
    const ctrl = new AbortController();
    const key = evalKey;
    const timer = setTimeout(() => {
      api
        .evaluateScenario(
          scenario.id,
          { stress: st.stress, periodDays: periodParsed.value ?? undefined, budgets: b.budgets },
          ctrl.signal,
        )
        .then((r) => {
          if (!ctrl.signal.aborted) setEvaluation({ key, value: r });
        })
        .catch((e) => {
          if (!ctrl.signal.aborted) setEvalError({ key, message: e instanceof Error ? e.message : String(e) });
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
    // evalKey captures scenario, buildings, period, budgets and stress controls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evalKey, inputsValid, active]);

  // Loading state is derived from keys, so an aborted or skipped request can never leave it stuck.
  const ev = evaluation?.key === evalKey ? evaluation.value : null;
  const evalErrorNow = evalError?.key === evalKey ? evalError.message : null;
  // Keep showing the previous result (marked as outdated) instead of flashing an empty panel,
  // but only while it belongs to this scenario.
  const shownEval = ev ?? (evaluation && evaluation.value.scenarioId === scenario.id ? evaluation.value : null);
  const status = ev
    ? null
    : !shownEval || evalErrorNow
      ? null
      : inputsValid
        ? "updating…"
        : "showing the last valid values · fix the highlighted fields to update";

  async function save() {
    if (hasErrors || periodParsed.value === null) return setSaveNote({ ok: false, text: "Fix the highlighted fields first." });
    const forScenario = scenario.id;
    setSaving(true);
    try {
      const s = await api.updateScenarioAssumptions(forScenario, {
        schemaVersion: saved.schemaVersion,
        periodDays: periodParsed.value,
        budgets: b.budgets,
        stress: st.stress,
      });
      onSaved(s); // the parent applies it only if this scenario is still shown
      if (scenarioIdRef.current === forScenario) setSaveNote({ ok: true, text: "Saved with this scenario." });
    } catch (e) {
      if (scenarioIdRef.current === forScenario) setSaveNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  const updateBudget = (id: string, patch: Partial<BudgetDraft>) => setBudgets(budgets.map((x) => (x.id === id ? { ...x, ...patch } : x)));

  return (
    <section className="panel">
      <h2>Scenario controls</h2>
      <p className="subtitle small">Declared supplies and stress tests for {scenario.name}. Nothing here changes baseline data.</p>

      <Field label="Evaluation period" unit="days" value={period} onChange={setPeriod} error={periodError ?? undefined} help="Every usage and cost figure is over this period." />

      <Section title="Resource budgets" meta={`${budgets.length} declared`} open={budgets.length > 0}>
        <p className="muted small">
          A budget is a pooled supply shared by every building in its scope, counted once. A plant's net output only adds to a budget if you tick it below.
        </p>
        {budgets.map((d) => {
          const e = (k: string) => b.errors[`${d.id}.${k}`];
          const unit = BUDGET_KINDS.find((k) => k.kind === d.kind)?.unit ?? "";
          const suppliers = scenario.projects.filter((p) => canSupply(p, d.kind));
          return (
            <div className="list-row" key={d.id}>
              <div className="row align-end">
                <Field label="Label" value={d.label} onChange={(v) => updateBudget(d.id, { label: v })} error={e("label")} numeric={false} placeholder="e.g. Local grid" />
                <button className="ghost danger" onClick={() => setBudgets(budgets.filter((x) => x.id !== d.id))}>
                  Remove
                </button>
              </div>
              <div className="row">
                <label className="field">
                  <span>Kind</span>
                  <select value={d.kind} onChange={(ev) => updateBudget(d.id, { kind: ev.target.value as BudgetKind })}>
                    {BUDGET_KINDS.map((k) => (
                      <option key={k.kind} value={k.kind}>
                        {k.label} ({k.unit})
                      </option>
                    ))}
                  </select>
                </label>
                <Field label="Amount" unit={unit} value={d.amount} onChange={(v) => updateBudget(d.id, { amount: v })} error={e("amount")} />
              </div>
              <div className="row">
                <label className="field">
                  <span>Applies to</span>
                  <select value={d.scopeKind} onChange={(ev) => updateBudget(d.id, { scopeKind: ev.target.value as BudgetDraft["scopeKind"] })}>
                    <option value="scenario">Every building in the scenario</option>
                    <option value="region">Buildings in a prepared region</option>
                    <option value="radius">Buildings within a radius</option>
                  </select>
                </label>
                {d.scopeKind === "region" && (
                  <label className="field">
                    <span>Region</span>
                    <select value={d.region} onChange={(ev) => updateBudget(d.id, { region: ev.target.value as BudgetDraft["region"] })}>
                      <option value="arizona">Arizona</option>
                      <option value="uk">UK</option>
                    </select>
                  </label>
                )}
              </div>
              {d.scopeKind === "radius" && (
                <div className="row">
                  <Field label="Latitude" unit="°" value={d.latitude} onChange={(v) => updateBudget(d.id, { latitude: v })} error={e("latitude")} />
                  <Field label="Longitude" unit="°" value={d.longitude} onChange={(v) => updateBudget(d.id, { longitude: v })} error={e("longitude")} />
                  <Field label="Radius" unit="km" value={d.radiusKm} onChange={(v) => updateBudget(d.id, { radiusKm: v })} error={e("radiusKm")} />
                </div>
              )}
              {suppliers.length > 0 && (
                <fieldset className="classes">
                  <legend className="small muted">Placed plants whose net output adds to this budget</legend>
                  {suppliers.map((p) => {
                    const on = d.contributingProjectIds.includes(p.id);
                    return (
                      <label key={p.id} className="toggle compact">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() =>
                            updateBudget(d.id, {
                              contributingProjectIds: on ? d.contributingProjectIds.filter((x) => x !== p.id) : [...d.contributingProjectIds, p.id],
                            })
                          }
                        />
                        <span>{p.name || typeLabel(p.type)}</span>
                      </label>
                    );
                  })}
                </fieldset>
              )}
              {e("contributors") && <small className="field-error">{e("contributors")}</small>}
            </div>
          );
        })}
        <div className="actions tight">
          <button onClick={() => setBudgets([...budgets, newBudget()])}>+ Add budget</button>
        </div>
      </Section>

      <h3>Stress test</h3>
      <p className="muted small">Multipliers on declared inputs. 100% is the unstressed case. Results update as you move them.</p>
      {CONTROLS.map((c) => {
        const raw = stressDraft[c.key];
        const n = Number(raw);
        const err = st.errors[c.key];
        const note = ev?.controlNotes?.[c.key];
        return (
          <div className="control" key={c.key}>
            <div className="row align-center">
              <span className="grow">{c.label}</span>
              <input
                className="num narrow"
                inputMode="decimal"
                aria-label={`${c.label} multiplier`}
                value={raw}
                onChange={(e) => setStressDraft({ ...stressDraft, [c.key]: e.target.value })}
                aria-invalid={!!err}
              />
              <span className="muted small">×</span>
            </div>
            <input
              type="range"
              min={0}
              max={c.kind === "supply" ? 1 : 3}
              step={0.05}
              value={Number.isFinite(n) ? Math.min(n, c.kind === "supply" ? 1 : 3) : 1}
              aria-label={c.label}
              onChange={(e) => setStressDraft({ ...stressDraft, [c.key]: e.target.value })}
            />
            {err ? (
              <small className="field-error">
                {c.kind === "supply" ? "A fraction from 0 to 1 (e.g. 0.5 = 50%)" : "A multiplier from 0 to 100 (e.g. 1.2 = 120%)"}
              </small>
            ) : (
              <small className="muted">{c.meaning(st.stress[c.key])}</small>
            )}
            {note && <small className="muted block">{note}</small>}
          </div>
        );
      })}

      <div className="actions">
        <button className="primary" onClick={save} disabled={saving || hasErrors || !dirty}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={() => setStressDraft(stressToDraft(NEUTRAL_STRESS))} disabled={JSON.stringify(st.stress) === JSON.stringify(NEUTRAL_STRESS)}>
          Reset stress
        </button>
      </div>
      {saveNote && (!saveNote.ok || !dirty) && <p className={`small ${saveNote.ok ? "ok" : "warn"}`}>{saveNote.text}</p>}
      {dirty && <p className="note small">Results below include unsaved changes. Save to keep them with the scenario.</p>}

      <h3>
        Unstressed vs stressed {shownEval && <span className="muted">· over {fmtDays(shownEval.periodDays)}</span>}
        {status && <span className="muted small"> · {status}</span>}
      </h3>
      {evalErrorNow && <p className="warn small">Evaluation unavailable: {evalErrorNow}</p>}
      {!shownEval && !evalErrorNow && (
        <p className="muted small">{inputsValid ? "Calculating…" : "Fix the highlighted fields to see results."}</p>
      )}
      {shownEval && <Comparison ev={shownEval} />}
    </section>
  );
}

function Row({ label, note, help, a, b }: { label: string; note?: string; help?: string; a?: Quantity; b?: Quantity }) {
  const changed = (a?.value ?? null) !== (b?.value ?? null);
  return (
    <tr className={changed ? "changed" : undefined}>
      <th scope="row" title={help}>
        {label}
        {note && <small className="muted block">{note}</small>}
      </th>
      <td>
        <QuantityText q={a} />
      </td>
      <td>
        <QuantityText q={b} />
      </td>
    </tr>
  );
}

/** Pair list entries from both results by a key (e.g. currency or pollutant). */
function pairs<T>(a: T[], b: T[], key: (x: T) => string): [string, T | undefined, T | undefined][] {
  const keys = [...new Set([...a.map(key), ...b.map(key)])];
  return keys.map((k) => [k, a.find((x) => key(x) === k), b.find((x) => key(x) === k)]);
}

function Comparison({ ev }: { ev: ScenarioEvaluation }) {
  const u: ScenarioResult = ev.unstressed;
  const s: ScenarioResult = ev.stressed;
  const period = `over ${fmtDays(ev.periodDays)}`;
  const head = (
    <thead>
      <tr>
        <th />
        <th>Unstressed</th>
        <th>Stressed</th>
      </tr>
    </thead>
  );
  const budgetPairs = pairs(u.budgets, s.budgets, (x) => x.id);
  const buildingPairs = pairs(u.buildings, s.buildings, (x) => x.projectId);
  const unknown = Object.entries(u.totals.unknownBuildings ?? {}).filter(([, names]) => names.length > 0);
  // Notes for the four controls are shown beside them; anything else is listed here.
  const otherNotes = Object.entries(ev.controlNotes ?? {}).filter(([k]) => !CONTROLS.some((c) => c.key === k));

  return (
    <div className="comparison">
      {budgetPairs.length > 0 && (
        <>
          <h4>Budgets</h4>
          {budgetPairs.map(([id, a, b]) => (
            <table className="mini" key={id}>
              <caption>
                {(a ?? b)!.label}{" "}
                <span className="muted">
                  ({(a ?? b)!.unit}) · {(a ?? b)!.kind === "power_capacity_kw" ? "capacity at any time" : period}
                </span>
              </caption>
              {head}
              <tbody>
                <Row label="Declared supply" a={a?.declaredSupply} b={b?.declaredSupply} />
                <Row label="Demand" a={a?.demand} b={b?.demand} />
                <Row label="Unmet demand" a={a?.unmet} b={b?.unmet} />
              </tbody>
            </table>
          ))}
        </>
      )}

      <h4>Scenario totals</h4>
      <table className="mini">
        {head}
        <tbody>
          <Row label="Electricity use" note={period} a={u.totals.electricityDemand} b={s.totals.electricityDemand} />
          <Row label="Electricity output" note={period} a={u.totals.electricityOutput} b={s.totals.electricityOutput} />
          <Row label="Water use" note={period} a={u.totals.waterDemand} b={s.totals.waterDemand} />
          <Row label="Water output" note={period} a={u.totals.waterOutput} b={s.totals.waterOutput} />
          {pairs(u.totals.constructionCost, s.totals.constructionCost, (q) => q.unit).map(([cur, a, b]) => (
            <Row key={`c-${cur}`} label={`Construction cost (${cur})`} note="one-time" a={a} b={b} />
          ))}
          {pairs(u.totals.operatingCost, s.totals.operatingCost, (q) => q.unit).map(([cur, a, b]) => (
            <Row key={`o-${cur}`} label={`Operating cost, known (${cur})`} note={period} a={a} b={b} />
          ))}
          {pairs(u.totals.emissions, s.totals.emissions, (e) => e.pollutant).map(([p, a, b]) => (
            <Row key={`e-${p}`} label={p} note={`emitted ${period}`} a={a?.quantity} b={b?.quantity} />
          ))}
          {pairs(u.totals.materials, s.totals.materials, (m) => `${m.name} · ${m.phase}`).map(([k, a, b]) => (
            <Row key={`m-${k}`} label={k} note={(a ?? b)?.phase === "construction" ? "once" : period} a={a?.quantity} b={b?.quantity} />
          ))}
          <Row label="Upward light (declared)" note="fixed · proxy, not sky brightness" help={LIGHT_PROXY_NOTE} a={u.totals.light} b={s.totals.light} />
          <Row label="Worker capacity" note="fixed" a={u.totals.workerCapacity} b={s.totals.workerCapacity} />
        </tbody>
      </table>
      {unknown.length > 0 && (
        <div className="small muted">
          <strong>Unknown for some buildings</strong> (not counted as zero):
          <ul>
            {unknown.map(([metric, names]) => (
              <li key={metric}>
                {METRIC_LABEL[metric] ?? metric}: {names.join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {buildingPairs.length > 0 && (
        <>
          <h4>Buildings</h4>
          {buildingPairs.map(([id, a, b]) => (
            <BuildingCompare key={id} a={a} b={b} period={period} head={head} />
          ))}
        </>
      )}

      {otherNotes.length > 0 && (
        <ul className="small muted">
          {otherNotes.map(([k, v]) => (
            <li key={k}>
              <strong>{k}:</strong> {v}
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">
        Model {ev.modelVersion} · inputs {ev.inputsHash.slice(0, 10)}
      </p>
    </div>
  );
}

/** One collapsible row per building: state change in the summary, usage, cost and supply checks inside. */
function BuildingCompare({ a, b, period, head }: { a?: BuildingEvaluation; b?: BuildingEvaluation; period: string; head: ReactNode }) {
  const any = (a ?? b)!;
  const ra = a?.result;
  const rb = b?.result;
  const currency = ra?.costs.currency ?? rb?.costs.currency;
  const stateChanged = !!a && !!b && a.assessment.state !== b.assessment.state;
  const badges = (
    <>
      {a && <StateBadge state={a.assessment.state} />}
      {(stateChanged || !a) && b && (
        <>
          <span aria-label="becomes">→</span>
          <StateBadge state={b.assessment.state} />
        </>
      )}
    </>
  );
  return (
    <Section title={any.name || typeLabel(any.type)} meta={badges} emphasis={stateChanged}>
      <table className="mini">
        {head}
        <tbody>
          <Row label="Electricity use" note={period} a={ra?.electricityDemand} b={rb?.electricityDemand} />
          <Row label="Water use" note={period} a={ra?.waterDemand} b={rb?.waterDemand} />
          {outputRelevant(ra?.electricityOutput, rb?.electricityOutput) && (
            <Row label="Electricity output" note={period} a={ra?.electricityOutput} b={rb?.electricityOutput} />
          )}
          {outputRelevant(ra?.waterOutput, rb?.waterOutput) && (
            <Row label="Water output" note={period} a={ra?.waterOutput} b={rb?.waterOutput} />
          )}
          <Row
            label={`Operating cost, known${currency ? ` (${currency})` : ""}`}
            note={period}
            a={ra?.costs.operatingKnownTotal}
            b={rb?.costs.operatingKnownTotal}
          />
          {supplyPairs(a, b).map((p) => (
            <SupplyRows key={p.id} label={p.label} note={p.period ? `over ${p.period}` : "at peak"} unit={p.unit} a={p.a} b={p.b} />
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function SupplyRows({ label, note, unit, a, b }: { label: string; note: string; unit: string; a?: CheckResult; b?: CheckResult }) {
  const q = (v: number | null | undefined) => checkQuantity(v, unit);
  return (
    <>
      <tr className="group">
        <th scope="rowgroup" colSpan={3}>
          {label} <small className="muted">{note}</small>
        </th>
      </tr>
      <Row label="Demand" a={q(a?.actual)} b={q(b?.actual)} />
      <Row label="Supply" a={q(a?.requiredValue)} b={q(b?.requiredValue)} />
      <Row label="Shortfall" a={q(shortfall(a))} b={q(shortfall(b))} />
    </>
  );
}
