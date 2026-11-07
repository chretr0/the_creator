import { useEffect, useMemo, useState } from "react";
import { api, type Project, type ProjectInput, type ProjectType } from "../lib/api";
import type { DefinitionSnapshot, LocationAssessment } from "../lib/buildings";
import {
  criterionToDraft,
  fmtDays,
  parseCriteria,
  parseStats,
  statsToDraft,
  type CriterionDraft,
  type StatsDraft,
} from "../lib/buildingForm";
import type { CellLayer } from "../lib/datalayers";
import { PROJECT_TYPES, typeColour, typeLabel } from "../lib/projectTypes";
import { useBuildingTemplates } from "../lib/useBuildingTemplates";
import BuildingForm from "./BuildingForm";
import { AssessmentView, ResultView } from "./AssessmentView";
import CriteriaEditor from "./CriteriaEditor";
import { Section } from "./FormBits";

type Props = {
  project: Project;
  moving: boolean;
  onSave: (patch: Partial<ProjectInput>) => Promise<void>;
  onMove: () => void;
  onDelete: () => void;
  onClose: () => void;
  /** Layer catalogue for map-layer requirements. */
  catalogue: CellLayer[];
  /** The scenario's evaluation period (days). */
  periodDays: number;
};

type Draft = {
  name: string;
  type: ProjectType;
  latitude: string;
  longitude: string;
  description: string;
  stats: StatsDraft;
  criteria: CriterionDraft[];
};

const EMPTY_SNAPSHOT: DefinitionSnapshot = { schemaVersion: 1, name: "", description: "", stats: {}, criteria: [] };

/** Legacy projects may come without a snapshot; treat every new statistic as unknown. */
const snapshotOf = (p: Project): DefinitionSnapshot => ({ ...EMPTY_SNAPSHOT, ...(p.definition ?? {}) });

function toDraft(p: Project): Draft {
  const snap = snapshotOf(p);
  return {
    name: p.name,
    type: p.type,
    latitude: String(p.latitude),
    longitude: String(p.longitude),
    description: snap.description ?? "",
    stats: statsToDraft(snap.stats, p.parameters ?? {}),
    criteria: (snap.criteria ?? []).map(criterionToDraft),
  };
}

/** Change the type; leaving data centre resets the demand basis, whose selector only data centres show. */
function withType(draft: Draft, type: ProjectType): Draft {
  return { ...draft, type, stats: type === "data_centre" ? draft.stats : { ...draft.stats, demandBasis: "direct" } };
}

export default function ProjectEditor({ project, moving, onSave, onMove, onDelete, onClose, catalogue, periodDays }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(project));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { templateFor } = useBuildingTemplates();

  useEffect(() => {
    setDraft(toDraft(project));
    setError(null);
  }, [project]);

  const snap = snapshotOf(project);
  const template = templateFor(draft.type, draft.type === project.type ? snap.templateId : null);
  const parsed = useMemo(() => parseStats(draft.stats, template.parameters), [draft.stats, template]);
  const crit = useMemo(() => parseCriteria(draft.criteria), [draft.criteria]);
  const errorCount = Object.keys(parsed.errors).length + Object.keys(crit.errors).length;

  // Calculated results and checks for the saved building at its saved location (excluding itself
  // from shared budgets so it is not counted twice).
  const [assessed, setAssessed] = useState<{ key: string; value: LocationAssessment; periodDays: number } | null>(null);
  const [assessError, setAssessError] = useState<string | null>(null);
  const assessKey = `${project.id}:${project.updatedAt}:${project.latitude}:${project.longitude}`;
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

  async function save() {
    const latitude = Number(draft.latitude);
    const longitude = Number(draft.longitude);
    if (draft.latitude.trim() === "" || !Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
      return setError("Latitude must be a number between -90 and 90.");
    }
    if (draft.longitude.trim() === "" || !Number.isFinite(longitude)) {
      return setError("Longitude must be a number.");
    }
    if (errorCount) return setError("Fix the highlighted fields before saving.");
    const typeChanged = draft.type !== project.type;
    const definition: DefinitionSnapshot = {
      ...snap,
      description: draft.description,
      criteria: crit.criteria,
      // The derived demand basis only exists for data centres (its selector is hidden for other types).
      stats: draft.type === "data_centre" ? parsed.stats : { ...parsed.stats, demandBasis: "direct" },
      ...(typeChanged
        ? { templateId: template.version > 0 ? template.id : null, templateVersion: template.version > 0 ? template.version : null }
        : {}),
    };
    // Only send coordinates when edited, so exact stored values are never re-rounded.
    const patch: Partial<ProjectInput> = {
      name: draft.name,
      type: draft.type,
      parameters: parsed.parameters,
      definition,
    };
    if (draft.latitude !== String(project.latitude)) patch.latitude = latitude;
    if (draft.longitude !== String(project.longitude)) patch.longitude = longitude;

    setSaving(true);
    setError(null);
    try {
      await onSave(patch);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const label = typeLabel(draft.type);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          <span className="dot" style={{ background: `rgb(${typeColour(draft.type).join(",")})` }} /> {draft.name || label}
        </h2>
        <button className="ghost" onClick={onClose} aria-label="Close project">
          ✕
        </button>
      </div>
      <p className="subtitle small">
        {label}
        {project.sourceDefinitionId && " · from a saved definition (this building keeps its own copy)"}
      </p>
      {snap.description && <p className="small description">{snap.description}</p>}

      <label className="field">
        <span>Name</span>
        <input value={draft.name} placeholder={label} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      </label>
      <label className="field">
        <span>Type</span>
        <select value={draft.type} onChange={(e) => setDraft(withType(draft, e.target.value as ProjectType))}>
          {PROJECT_TYPES.map((t) => (
            <option key={t.type} value={t.type}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <label className="field">
          <span>Latitude (°)</span>
          <input className="mono" value={draft.latitude} onChange={(e) => setDraft({ ...draft, latitude: e.target.value })} />
        </label>
        <label className="field">
          <span>Longitude (°)</span>
          <input className="mono" value={draft.longitude} onChange={(e) => setDraft({ ...draft, longitude: e.target.value })} />
        </label>
      </div>

      <h3>Can it be built here?</h3>
      {assessError && <p className="warn small">Unavailable: {assessError}</p>}
      {!fresh && !assessError && <p className="muted small">Calculating…</p>}
      {fresh && (
        <>
          <AssessmentView assessment={fresh.value.assessment} site={fresh.value.site} />
          <Section title="Calculated usage and costs" meta={`over ${fmtDays(fresh.periodDays)}`} open>
            <ResultView result={fresh.value.result} producesPower={template.producesPower} producesWater={template.producesWater} />
          </Section>
        </>
      )}

      <h3>Statistics</h3>
      <p className="muted small">Blank means unknown. Changes apply to this building only.</p>
      <label className="field">
        <span>Description</span>
        <textarea rows={2} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </label>
      <BuildingForm draft={draft.stats} onChange={(stats) => setDraft({ ...draft, stats })} errors={parsed.errors} template={template} />

      <Section title="Your own extra limits" meta={crit.criteria.length ? `${crit.criteria.length} set` : "optional"} invalid={Object.keys(crit.errors).length}>
        <p className="muted small">
          Land, water, power and workforce are checked automatically against what this hexagon and its neighbours
          provide. Add limits here only for extra preferences (e.g. water stress, slope or a budget).
        </p>
        <CriteriaEditor
          drafts={draft.criteria}
          onChange={(criteria) => setDraft({ ...draft, criteria })}
          errors={crit.errors}
          catalogue={catalogue}
          currency={parsed.stats.costs?.currency || "currency"}
          periodDays={periodDays}
        />
      </Section>


      {error && <p className="warn">{error}</p>}
      <div className="actions">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={onMove} className={moving ? "active" : ""}>
          {moving ? "Click the map…" : "Move"}
        </button>
        <button className="danger right" onClick={onDelete}>
          Delete
        </button>
      </div>
    </section>
  );
}
