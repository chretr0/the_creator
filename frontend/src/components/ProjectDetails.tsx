import { PanelTabs } from "./PanelNavigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Project } from "../lib/api";
import type { BuildingTemplate, Criterion, DefinitionSnapshot, LocationAssessment } from "../lib/buildings";
import { coordLabel, CRITERION_LABEL, fmtDays, PERIOD_LABEL, STAT_FIELDS, statsToDraft, type StatsDraft } from "../lib/buildingForm";
import type { CellLayer } from "../lib/datalayers";
import { MEDIA, pollutantKey, pollutantLabel, releaseMedium } from "../lib/pollutants";
import { typeColour, typeLabel } from "../lib/projectTypes";
import { useBuildingTemplates } from "../lib/useBuildingTemplates";
import { AssessmentView, ResultView } from "./AssessmentView";
import SuitabilityView from "./SuitabilityView";
import { Section } from "./FormBits";
import Icon from "./Icon";

type Props = {
  project: Project;
  /** Open the building in the Build tab, where it can be changed. */
  onEdit: () => void;
  onClose: () => void;
  /** Layer catalogue, to name map-layer limits. */
  catalogue: CellLayer[];
  /** The scenario's evaluation period (days). */
  periodDays: number;
  /** Refresh shared site capacity when other buildings in this world change. */
  contextRevision?: string;
};

const EMPTY_SNAPSHOT: DefinitionSnapshot = { schemaVersion: 1, name: "", description: "", stats: {}, criteria: [] };

/** Legacy projects may come without a snapshot; treat every statistic as unknown. */
const snapshotOf = (p: Project): DefinitionSnapshot => ({ ...EMPTY_SNAPSHOT, ...(p.definition ?? {}) });

/** A placed building, read-only. Changes are made in the Build tab. */
export default function ProjectDetails({ project, onEdit, onClose, catalogue, periodDays, contextRevision }: Props) {
  const { templateFor } = useBuildingTemplates();
  const snap = snapshotOf(project);
  const template = templateFor(project.type, snap.templateId ?? null);
  const draft = useMemo(() => statsToDraft(snapshotOf(project).stats, project.parameters ?? {}), [project]);
  const label = typeLabel(project.type);

  // Calculated results and checks for the saved building at its saved location (excluding itself
  // from shared budgets so it is not counted twice).
  const [assessed, setAssessed] = useState<{ key: string; value: LocationAssessment; periodDays: number } | null>(null);
  const [assessError, setAssessError] = useState<string | null>(null);
  const assessKey = `${project.id}:${project.updatedAt}:${project.latitude}:${project.longitude}:${contextRevision ?? ""}:${periodDays}`;
  useEffect(() => {
    const ctrl = new AbortController();
    setAssessError(null);
    const s = snapshotOf(project);
    api
      .assess(
        {
          scenarioId: project.scenarioId,
          type: project.type,
          stats: s.stats ?? {},
          parameters: project.parameters ?? {},
          criteria: s.criteria ?? [],
          location: { latitude: project.latitude, longitude: project.longitude },
          excludeProjectId: project.id,
        },
        ctrl.signal,
      )
      .then((r) => {
        if (!ctrl.signal.aborted && r.location) setAssessed({ key: assessKey, value: r.location, periodDays: r.periodDays });
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setAssessError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
    // assessKey identifies the saved inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessKey]);
  const fresh = assessed?.key === assessKey ? assessed : null;

  const [view, setView] = useState<"overview" | "statistics" | "site" | "results">("overview");
  const criteria = snap.criteria ?? [];

  return (
    <section className="panel project-details">
      <div className="panel-head">
        <h2>
          <span className="dot" style={{ background: `rgb(${typeColour(project.type).join(",")})` }} /> {project.name || label}
        </h2>
        <button className="ghost" onClick={onClose} aria-label="Close building details">
          ✕
        </button>
      </div>
      <p className="subtitle small">
        {label}
        {project.sourceDefinitionId && <span title="This building keeps its own copy of the saved definition."> · from a saved definition</span>}
      </p>
      <PanelTabs label="Placed building sections" value={view} onChange={setView} options={[
        { value: "overview", label: "Overview" }, { value: "statistics", label: "Statistics" },
        { value: "site", label: "Limits" }, { value: "results", label: "Results" },
      ]} />
      <div hidden={view !== "overview"}>
        {snap.description && <p className="small description">{snap.description}</p>}
        <dl className="kv">
          <dt>Type</dt>
          <dd>{template.label}</dd>
          <dt>Location</dt>
          <dd className="mono">{coordLabel(project.latitude, project.longitude)}</dd>
          <dt>Placed</dt>
          <dd>{new Date(project.createdAt).toLocaleDateString()}</dd>
          {project.updatedAt !== project.createdAt && (
            <>
              <dt>Last changed</dt>
              <dd>{new Date(project.updatedAt).toLocaleDateString()}</dd>
            </>
          )}
        </dl>
      </div>
      <div hidden={view !== "statistics"}>
        <StatsSummary draft={draft} template={template} />
      </div>
      <div hidden={view !== "site"}>
        <LimitsSummary criteria={criteria} catalogue={catalogue} currency={draft.values["costs.currency"]?.trim().toUpperCase() || "currency"} period={fmtDays(periodDays)} />
      </div>
      <div hidden={view !== "results"}>
        <h3>Can it be built here?</h3>
        {assessError && <p className="warn small">Unavailable: {assessError}</p>}
        {!fresh && !assessError && <p className="muted small">Calculating…</p>}
        {fresh && (
          <>
            <AssessmentView assessment={fresh.value.assessment} site={fresh.value.site} />
            {fresh.value.suitability && <SuitabilityView suitability={fresh.value.suitability} />}
            <Section title="Calculated usage and costs" meta={`over ${fmtDays(fresh.periodDays)}`}>
              <ResultView result={fresh.value.result} producesPower={template.producesPower} producesWater={template.producesWater} />
            </Section>
          </>
        )}
      </div>
      <div className="actions">
        <button className="primary" onClick={onEdit}>
          <Icon name="layers" size={16} /> Edit in Build
        </button>
      </div>
    </section>
  );
}

/** Rows of a read-only key/value list; rows without a value are left out. */
type Row = [label: string, value: ReactNode];

function Rows({ rows }: { rows: Row[] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} className="kv-pair">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A number as typed, with thousands separators; text is shown as is. */
const fmt = (v: string) => (/^-?\d+(\.\d+)?$/.test(v) ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 6 }) : v);

const DEMAND_BASIS = { direct: "Average demand", derived: "IT power × PUE" } as const;
const WATER_SOURCE = { fresh: "Fresh water", seawater: "Seawater (coastal)", wastewater: "Treated wastewater" } as const;

/** The building's statistics as entered; blank (unknown) values are left out. */
function StatsSummary({ draft, template }: { draft: StatsDraft; template: BuildingTemplate }) {
  const currency = draft.values["costs.currency"]?.trim().toUpperCase() || "";
  const units: Record<string, string> = {
    "costs.constructionTotal": currency,
    "costs.operating.amount": currency,
    "costs.electricityPricePerKwh": currency ? `${currency}/kWh` : "per kWh",
    "costs.waterPricePerM3": currency ? `${currency}/m³` : "per m³",
  };
  const value = (path: string): Row | null => {
    const v = draft.values[path]?.trim();
    if (!v) return null;
    const spec = STAT_FIELDS[path];
    const unit = path in units ? units[path] : spec.unit;
    return [spec.label, unit ? `${fmt(v)} ${unit}` : v];
  };
  const rows = (...items: (Row | null | false)[]) => items.filter((x): x is Row => !!x);

  const params = template.parameters
    .map((p): Row | null => {
      const v = draft.params[p.key]?.trim();
      return v ? [p.label, p.unit ? `${fmt(v)} ${p.unit}` : fmt(v).replace(/_/g, " ")] : null;
    });
  const sections: { title: string; rows: Row[] }[] = [
    { title: "Size & hours", rows: rows(value("footprintM2"), value("operatingHoursPerDay")) },
    {
      title: `${template.label} details`,
      rows: rows(template.type === "data_centre" && ["Demand from", DEMAND_BASIS[draft.demandBasis]], ...params),
    },
    {
      title: "Power",
      rows: rows(
        value("power.averageDemandKw"), value("power.peakDemandKw"), value("power.averageOutputKw"),
        value("power.ratedOutputKw"), value("power.capacityFactor"), value("power.technology"),
      ),
    },
    {
      title: "Water",
      rows: rows(
        value("water.inputM3PerHour"),
        !!draft.values["water.inputM3PerHour"]?.trim() && ["Intake source", WATER_SOURCE[draft.waterSource]],
        value("water.outputM3PerHour"), value("water.basis"),
      ),
    },
    {
      title: "Raw materials",
      rows: draft.materials.map((m, i): Row => [
        m.name || `Material ${i + 1}`,
        [
          m.quantity && `${fmt(m.quantity)} ${m.unit === "t" ? "t" : "kg"}${m.phase === "operation" ? ` per ${PERIOD_LABEL[m.period]}` : ""}`,
          m.phase === "construction" ? "construction" : "operation",
          m.price && `${fmt(m.price)} ${currency || "currency"}/kg`,
        ].filter(Boolean).join(" · "),
      ]),
    },
    {
      title: "Costs",
      rows: rows(
        value("costs.constructionTotal"),
        !!draft.values["costs.operating.amount"]?.trim() && [
          "Operating cost",
          `${fmt(draft.values["costs.operating.amount"].trim())} ${currency} per ${PERIOD_LABEL[draft.operatingPeriod]} · ${draft.operatingKind === "total" ? "all-inclusive" : "fixed part only"}`,
        ],
        value("costs.electricityPricePerKwh"), value("costs.waterPricePerM3"), value("costs.priceBasis"),
      ),
    },
    { title: "Workers", rows: rows(value("workers.capacity"), value("workers.staffingRequired")) },
    {
      title: "Pollutants & releases",
      rows: draft.emissions.map((e, i): Row => {
        const medium = releaseMedium(e.pollutant, e.medium);
        return [
          e.pollutant ? pollutantLabel(pollutantKey(e.pollutant), e.pollutant) : `Pollutant ${i + 1}`,
          `${e.rate ? `${fmt(e.rate)} ${medium === "climate" ? "kg CO₂e/h" : "kg/h"}` : "Rate unknown"} · ${MEDIA[medium]}`,
        ];
      }),
    },
    { title: "Light", rows: rows(value("light.upwardLumens"), value("light.hoursPerDay")) },
  ];
  const shown = sections.filter((s) => s.rows.length > 0);
  if (shown.length === 0) return <p className="muted small">No statistics entered: every value is unknown.</p>;
  return (
    <>
      {shown.map((s) => (
        <Section key={s.title} title={s.title}>
          <Rows rows={s.rows} />
        </Section>
      ))}
      <p className="muted small">Values left blank are unknown and not shown.</p>
    </>
  );
}

const num = (v: number | null | undefined) => (v == null ? null : v.toLocaleString());

function limitDetail(c: Criterion, catalogue: CellLayer[], currency: string, period: string): string {
  const max = (unit: string) => (c.amount == null ? "No maximum set" : `At most ${num(c.amount)} ${unit}`);
  switch (c.kind) {
    case "layer": {
      const layer = catalogue.find((l) => l.id === c.layerId);
      const slice = layer?.slices.find((s) => s.id === c.sliceId);
      const name = [layer?.name ?? c.layerId ?? "No layer chosen", layer && layer.slices.length > 1 ? slice?.label : null].filter(Boolean).join(" · ");
      if (c.classes) {
        const names = c.classes.map((v) => layer?.categories?.find((x) => x.value === v)?.label ?? String(v));
        return `${name}: ${names.length ? names.join(", ") : "no classes chosen"}`;
      }
      const unit = slice?.units ? ` ${slice.units}` : "";
      const range =
        c.min != null && c.max != null ? `${num(c.min)}–${num(c.max)}${unit}`
        : c.min != null ? `at least ${num(c.min)}${unit}`
        : c.max != null ? `at most ${num(c.max)}${unit}`
        : "any value";
      return `${name}: ${range}`;
    }
    case "construction_budget":
      return max(currency);
    case "operating_budget":
      return max(`${currency} over ${period}`);
    case "light_limit":
      return max("lumens");
    case "material_budget":
      return `${c.materialName || "Unnamed material"}: ${max(`kg over ${period}`).toLowerCase()}`;
    case "emission_limit": {
      const medium = releaseMedium(c.pollutant ?? "", c.medium);
      const name = c.pollutant ? pollutantLabel(pollutantKey(c.pollutant), c.pollutant) : "Unnamed pollutant";
      return `${name} to ${MEDIA[medium].toLowerCase()}: ${max(`${medium === "climate" ? "kgCO₂e" : "kg"} over ${period}`).toLowerCase()}`;
    }
    default:
      return "Uses the site's declared capacity or a scenario budget";
  }
}

function LimitsSummary({ criteria, catalogue, currency, period }: { criteria: Criterion[]; catalogue: CellLayer[]; currency: string; period: string }) {
  if (criteria.length === 0) return <p className="muted small">No limits set for this building.</p>;
  return (
    <ul className="limit-list">
      {criteria.map((c) => (
        <li key={c.id}>
          <div className="limit-head">
            <strong>{c.label || CRITERION_LABEL[c.kind]}</strong>
            <span className="tag">{c.required ? "Required" : "Optional"}</span>
          </div>
          <small className="muted">{limitDetail(c, catalogue, currency, period)}</small>
        </li>
      ))}
    </ul>
  );
}
