import { useEffect, useState, type ReactNode } from "react";
import { api, type Project, type Scenario } from "../lib/api";
import type { BuildingEvaluation, Quantity, ScenarioEvaluation, ScenarioTotals } from "../lib/buildings";
import { MEDIA, releaseMedium } from "../lib/pollutants";
import { typeColour, typeLabel } from "../lib/projectTypes";
import {
  averageKw,
  balance,
  countByType,
  fmtSigned,
  fmtTotal,
  totalState,
  TOTALS_PERIODS,
  uniqueNames,
  type TotalsPeriod,
} from "../lib/worldTotals";
import Icon from "./Icon";
import { PanelTabs } from "./PanelNavigation";

type Props = {
  scenario: Scenario | null;
  /** The page is open: add the world up (and again whenever its buildings change). */
  active: boolean;
  onShow: (project: Project) => void;
  onBuild: () => void;
};

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Everything the active world's buildings use, make, cost and release, added up. */
export default function WorldTotals({ scenario, active, onShow, onBuild }: Props) {
  const [period, setPeriod] = useState<TotalsPeriod>("year");
  const days = TOTALS_PERIODS.find((p) => p.value === period)!.days;
  const projects = scenario?.projects ?? [];
  // Every input the server adds up: the buildings, the world's saved assumptions and the period.
  const revision = scenario
    ? JSON.stringify([scenario.id, scenario.assumptions, projects.map((p) => [p.id, p.updatedAt]), days])
    : "";
  const [loaded, setLoaded] = useState<{ scenarioId: string; revision: string; value: ScenarioEvaluation } | null>(null);
  const [error, setError] = useState<{ revision: string; text: string } | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!active || !scenario || projects.length === 0) return;
    const ctrl = new AbortController();
    const id = scenario.id;
    api
      .evaluateScenario(id, { periodDays: days }, ctrl.signal)
      .then((value) => {
        if (ctrl.signal.aborted) return;
        setLoaded({ scenarioId: id, revision, value });
        setError(null);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setError({ revision, text: message(e) });
      });
    return () => ctrl.abort();
    // `revision` captures the scenario, its buildings and the period.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, revision, retry]);

  if (!scenario || projects.length === 0)
    return (
      <section className="panel timeline-empty">
        <Icon name="chart" size={32} />
        <h2>Nothing to add up yet</h2>
        <p className="muted">
          {scenario
            ? `Place buildings in “${scenario.name}” and their costs, power, water and emissions are totalled here.`
            : "Choose or add a world from the Active world menu first."}
        </p>
        {scenario && (
          <button className="primary" onClick={onBuild}>
            <Icon name="plus" size={16} />
            New building
          </button>
        )}
      </section>
    );

  // The last result for this world stays on screen (dimmed) while a change is added up again.
  const shown = loaded && loaded.scenarioId === scenario.id ? loaded : null;
  const updating = !shown || shown.revision !== revision;
  const failed = error && error.revision === revision ? error.text : null;
  const data = shown?.value ?? null;
  const per = TOTALS_PERIODS.find((p) => p.days === data?.periodDays)?.per ?? `over ${data?.periodDays} days`;

  return (
    <div className="world-totals">
      <PanelTabs
        label="Totals period"
        value={period}
        onChange={setPeriod}
        options={TOTALS_PERIODS.map((p) => ({ value: p.value, label: p.label }))}
      />
      {failed && (
        <div className="error" role="alert" style={{ margin: "12px 18px 0" }}>
          Couldn't add up this world: {failed}
          <button className="ghost" onClick={() => setRetry((n) => n + 1)}>
            Try again
          </button>
        </div>
      )}
      {!data ? (
        !failed && (
          <section className="panel">
            <p className="muted small" role="status">
              Adding up {plural(projects.length, "building")}…
            </p>
          </section>
        )
      ) : (
        <div className={updating && !failed ? "totals-body updating" : "totals-body"} aria-busy={updating && !failed}>
          <Overview totals={data.unstressed.totals} per={per} count={projects.length} worldName={scenario.name} updating={updating && !failed} />
          <Electricity totals={data.unstressed.totals} per={per} periodDays={data.periodDays} />
          <Water totals={data.unstressed.totals} per={per} />
          <Costs totals={data.unstressed.totals} per={per} />
          <LandAndPeople totals={data.unstressed.totals} />
          <Emissions totals={data.unstressed.totals} per={per} />
          <Materials totals={data.unstressed.totals} per={per} />
          <ByBuilding buildings={data.unstressed.buildings} projects={projects} per={per} onShow={onShow} />
        </div>
      )}
    </div>
  );
}

/* ---------------- pieces ---------------- */

/** A total, with "partial" or "unknown" spelled out (the full list of what is missing on hover). */
function Total({ q, names, signed, children }: { q: Quantity; names?: string[]; signed?: boolean; children?: ReactNode }) {
  const state = totalState(q);
  const text = signed ? fmtSigned(q.value, q.unit) : fmtTotal(q.value, q.unit);
  const who = names && names.length > 0 ? plural(names.length, "building") : plural(q.missing.length, "input");
  const tip = [q.basis, ...(q.missing.length ? ["Missing:", ...q.missing.map((m) => `• ${m}`)] : [])].filter(Boolean).join("\n");
  return (
    <span className="total-value" title={tip || undefined}>
      {state === "none" ? (
        <span className="muted">none</span>
      ) : (
        <span className={state === "unknown" ? "muted" : "num"}>{text}</span>
      )}
      {children}
      {state === "partial" && <small className="warn block">partial · {who} not declared</small>}
      {state === "unknown" && <small className="muted block">not declared by {who}</small>}
    </span>
  );
}

function Row({ label, sub, children }: { label: ReactNode; sub?: ReactNode; children: ReactNode }) {
  return (
    <tr>
      <th scope="row">
        {label}
        {sub && <small className="muted block">{sub}</small>}
      </th>
      <td>{children}</td>
    </tr>
  );
}

function Panel({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel totals-panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {meta && <span className="small muted">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

/** "+1.2 GWh surplus" / "−300 MWh short" for a balance tile. */
function BalanceTile({ q, label, names }: { q: Quantity; label: string; names: string[] }) {
  const v = q.value;
  const tone = v === null ? "" : v > 0 ? "ok" : v < 0 ? "warn" : "";
  return (
    <div className="stat">
      <strong className={tone}>{fmtSigned(v, q.unit)}</strong>
      <span>
        {label}
        {v !== null && v !== 0 && (v > 0 ? " · surplus" : " · shortfall")}
      </span>
      {totalState(q) !== "complete" && <small className="muted">{totalState(q) === "unknown" ? `${plural(names.length, "building")} not declared` : "partial"}</small>}
    </div>
  );
}

function CostTile({ costs, label }: { costs: Quantity[]; label: string }) {
  const known = costs.filter((c) => c.value !== null);
  return (
    <div className="stat">
      {known.length === 0 ? (
        <strong className="muted">{costs.length ? "unknown" : "none"}</strong>
      ) : (
        known.map((c) => <strong key={c.unit}>{fmtTotal(c.value, c.unit)}</strong>)
      )}
      <span>{label}</span>
      {known.length === 0
        ? costs.length > 0 && <small className="muted">not declared</small>
        : costs.some((c) => totalState(c) !== "complete") && <small className="muted">partial</small>}
    </div>
  );
}

function Overview({ totals: t, per, count, worldName, updating }: { totals: ScenarioTotals; per: string; count: number; worldName: string; updating: boolean }) {
  const u = t.unknownBuildings;
  return (
    <section className="panel">
      <p className="muted small" role="status">
        {plural(count, "building")} in {worldName}, added up {per}.{updating ? " Updating…" : ""}
      </p>
      <div className="stats totals-stats">
        <CostTile costs={t.constructionCost} label="to build (one-time)" />
        <CostTile costs={t.operatingCost} label={`to run, ${per}`} />
        <BalanceTile q={t.electricityNet} label={`electricity, ${per}`} names={uniqueNames(u.electricityOutput, u.electricityDemand)} />
        <BalanceTile q={t.waterNet} label={`water, ${per}`} names={uniqueNames(u.waterOutput, u.waterDemand)} />
      </div>
      <p className="small muted totals-note">Everything below is what your buildings declare. Hover a value to see how it was added up and what is missing.</p>
    </section>
  );
}

function Electricity({ totals: t, per, periodDays }: { totals: ScenarioTotals; per: string; periodDays: number }) {
  const u = t.unknownBuildings;
  const avg = (q: Quantity) => {
    const kw = averageKw(q.value, periodDays);
    return kw === null || q.value === 0 ? null : <small className="muted block">≈ {fmtTotal(kw, "kW")} on average</small>;
  };
  return (
    <Panel title="Electricity" meta={per}>
      <table className="mini totals-table">
        <tbody>
          <Row label="Generated">
            <Total q={t.electricityOutput} names={u.electricityOutput}>{avg(t.electricityOutput)}</Total>
          </Row>
          <Row label="Used">
            <Total q={t.electricityDemand} names={u.electricityDemand}>{avg(t.electricityDemand)}</Total>
          </Row>
          <Row label="Net" sub="generated − used">
            <Total q={t.electricityNet} names={uniqueNames(u.electricityOutput, u.electricityDemand)} signed />
          </Row>
          <Row label="Peak demand" sub="if every peak coincides">
            <Total q={t.peakDemand} names={u.peakDemand} />
          </Row>
        </tbody>
      </table>
    </Panel>
  );
}

function Water({ totals: t, per }: { totals: ScenarioTotals; per: string }) {
  const u = t.unknownBuildings;
  return (
    <Panel title="Water" meta={per}>
      <table className="mini totals-table">
        <tbody>
          <Row label="Produced">
            <Total q={t.waterOutput} names={u.waterOutput} />
          </Row>
          <Row label="Used">
            <Total q={t.waterDemand} names={u.waterDemand} />
          </Row>
          <Row label="Net" sub="produced − used">
            <Total q={t.waterNet} names={uniqueNames(u.waterOutput, u.waterDemand)} signed />
          </Row>
        </tbody>
      </table>
    </Panel>
  );
}

function Costs({ totals: t, per }: { totals: ScenarioTotals; per: string }) {
  const u = t.unknownBuildings;
  const rows = (costs: Quantity[], names: string[] | undefined, label: string, sub: string) =>
    costs.length === 0 ? (
      <Row label={label} sub={sub}>
        <span className="muted">none</span>
      </Row>
    ) : (
      costs.map((c) => (
        <Row key={`${label}-${c.unit}`} label={label} sub={sub}>
          <Total q={c} names={names} />
        </Row>
      ))
    );
  return (
    <Panel title="Costs" meta="never converted between currencies">
      <table className="mini totals-table">
        <tbody>
          {rows(t.constructionCost, u.constructionCost, "Construction", "one-time")}
          {rows(t.operatingCost, u.operatingCost, "Operating", `${per}, known part`)}
        </tbody>
      </table>
    </Panel>
  );
}

function LandAndPeople({ totals: t }: { totals: ScenarioTotals }) {
  const u = t.unknownBuildings;
  return (
    <Panel title="Land, people & light">
      <table className="mini totals-table">
        <tbody>
          <Row label="Land used" sub="building footprints">
            <Total q={t.footprint} names={u.footprint} />
          </Row>
          <Row label="Staff needed">
            <Total q={t.staffingRequired} names={u.staffingRequired} />
          </Row>
          <Row label="Worker capacity" sub="at one time">
            <Total q={t.workerCapacity} names={u.workerCapacity} />
          </Row>
          <Row label="Upward light" sub="declared lumens">
            <Total q={t.light} names={u.light} />
          </Row>
        </tbody>
      </table>
    </Panel>
  );
}

function Emissions({ totals: t, per }: { totals: ScenarioTotals; per: string }) {
  if (t.emissions.length === 0) return null;
  return (
    <Panel title="Emissions" meta={`released ${per}`}>
      <table className="mini totals-table">
        <tbody>
          {t.emissions.map((e, i) => (
            <Row key={`${e.medium}-${e.pollutant}-${i}`} label={e.pollutant} sub={`into ${MEDIA[releaseMedium(e.pollutant, e.medium)].toLowerCase()}`}>
              <Total q={e.quantity} />
            </Row>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Materials({ totals: t, per }: { totals: ScenarioTotals; per: string }) {
  if (t.materials.length === 0) return null;
  const order = [...t.materials].sort((a, b) => (a.phase === b.phase ? 0 : a.phase === "construction" ? -1 : 1));
  return (
    <Panel title="Materials">
      <table className="mini totals-table">
        <tbody>
          {order.map((m, i) => (
            <Row key={`${m.phase}-${m.name}-${i}`} label={m.name} sub={m.phase === "construction" ? "to build, once" : `to run, ${per}`}>
              <Total q={m.quantity} />
            </Row>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ByBuilding({ buildings, projects, per, onShow }: { buildings: BuildingEvaluation[]; projects: Project[]; per: string; onShow: (p: Project) => void }) {
  const byId = new Map(projects.map((p) => [p.id, p]));
  const types = countByType(projects);
  return (
    <Panel title="By building" meta={types.map((t) => `${t.count} ${typeLabel(t.type).toLowerCase()}`).join(" · ")}>
      <table className="mini totals-table by-building">
        <thead>
          <tr>
            <th scope="col">Building</th>
            <th scope="col">Electricity</th>
            <th scope="col">To build</th>
          </tr>
        </thead>
        <tbody>
          {buildings.map((b) => {
            const p = byId.get(b.projectId);
            const net = balance(b.result.electricityOutput, b.result.electricityDemand);
            const build = b.result.costs.construction;
            const name = b.name || typeLabel(b.type);
            return (
              <tr key={b.projectId}>
                <td>
                  <button className="link totals-building" title="Show on the map" disabled={!p} onClick={() => p && onShow(p)}>
                    <span className="dot" style={{ background: `rgb(${typeColour(b.type).join(",")})` }} />
                    <span className="result-title">
                      {name}
                      <small>{typeLabel(b.type)}</small>
                    </span>
                  </button>
                </td>
                <td className={`num${net === null ? " muted" : ""}`}>{fmtSigned(net, "kWh")}</td>
                <td className={`num${build.value === null ? " muted" : ""}`}>
                  {build.value === null && !build.missing.length ? "none" : fmtTotal(build.value, build.unit)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="small muted totals-note">Electricity is what each building generates minus what it uses, {per}. Choose a building to see it on the map.</p>
    </Panel>
  );
}
