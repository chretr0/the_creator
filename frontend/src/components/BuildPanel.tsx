import { useEffect, useMemo, useRef, useState } from "react";
import { cellToLatLng, gridDisk } from "h3-js";
import Icon from "./Icon";
import { PanelTabs } from "./PanelNavigation";
import { api, ApiError, type Project, type Scenario } from "../lib/api";
import {
  PRESET_DRAG_TYPE,
  type AreaAssessment,
  type BuildingDefinition,
  type BuildingPreset,
  type BuildingType,
  type CellState,
  type DefinitionSnapshot,
  type LocationAssessment,
  type SupportSuggestion,
} from "../lib/buildings";
import type { CellLayer } from "../lib/datalayers";
import {
  applyLocationPrice,
  coordLabel,
  countErrors,
  criterionToDraft,
  fmtDays,
  mergeAssumptions,
  missingInputs,
  parseCriteria,
  parseStats,
  removeLocationPrice,
  siteNeeds,
  statsToDraft,
  type CriterionDraft,
  type StatsDraft,
} from "../lib/buildingForm";
import { typeColour } from "../lib/projectTypes";
import { useBuildingTemplates } from "../lib/useBuildingTemplates";
import { useBuildingPresets } from "../lib/useBuildingPresets";
import { presetPlace, presetToForm, sourceCount } from "../lib/presets";
import type { MapView } from "./WorldMap";
import BuildingForm from "./BuildingForm";
import CriteriaEditor from "./CriteriaEditor";
import { AssessmentView, LocationPrices, ResultView } from "./AssessmentView";
import { Field, Section, StateBadge, StateLegend } from "./FormBits";

/** An exact location being previewed, bound to the scenario it was chosen in. */
export type BuildTarget = { latitude: number; longitude: number; scenarioId: string; nonce: number };

/** Ask the panel to load a real example into the form (e.g. after it was dropped on the map). */
export type PresetRequest = { id: string; nonce: number };

export type BuildStage = "define" | "site" | "place";

type Props = {
  stage: BuildStage;
  onStage: (stage: BuildStage) => void;
  scenario: Scenario | null;
  view: MapView | null;
  catalogue: CellLayer[];
  target: BuildTarget | null;
  onTarget: (t: BuildTarget | null) => void;
  picking: boolean;
  onPick: (on: boolean) => void;
  onCells: (cells: CellState[] | null) => void;
  /** `stay`: keep the Build tab open (a supporting building is previewed next). */
  onBuilt: (p: Project, opts?: { stay?: boolean }) => void;
  onFocus: (latitude: number, longitude: number) => void;
  /** Fit the map to [west, south, east, north] when a prepared region is searched. */
  onFitBounds?: (bbox: [number, number, number, number]) => void;
  /** Load this example into the form; a new nonce loads it again. */
  presetRequest?: PresetRequest | null;
};

type Area = "view" | "arizona" | "uk";
const AREA_LABEL: Record<Area, string> = { view: "Current map view", arizona: "Arizona (prepared region)", uk: "UK (prepared region)" };
/** [west, south, east, north] of each prepared region, for fitting the map. */
const REGION_BBOX: Record<Exclude<Area, "view">, [number, number, number, number]> = {
  arizona: [-113.5, 31.3, -109.0, 34.5],
  uk: [-8.7, 49.8, 1.9, 60.9],
};
const CANDIDATE_LIMIT = 50;
const SCHEMA_VERSION = 1;

const pristine = (d: StatsDraft) =>
  Object.values(d.values).every((v) => v.trim() === "") &&
  d.materials.length === 0 &&
  d.emissions.length === 0 &&
  Object.values(d.params).every((v) => v.trim() === "");

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function BuildPanel(props: Props) {
  const { stage, onStage, scenario, view, catalogue, target, onTarget, picking, onPick, onCells, onBuilt, onFocus, onFitBounds, presetRequest } = props;
  const { templates, templateFor, error: templatesError } = useBuildingTemplates();
  const { presets, loaded: presetsLoaded, error: presetsError } = useBuildingPresets();

  const [definePage, setDefinePage] = useState<"building" | "resources" | "impact">("building");
  const [sitePage, setSitePage] = useState<"requirements" | "search">("requirements");
  const [previewPage, setPreviewPage] = useState<"assessment" | "usage">("assessment");
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => { contentRef.current?.scrollTo({ top: 0 }); }, [stage, definePage, sitePage, previewPage]);
  useEffect(() => {
    if (stage === "place" && !target) onStage("site");
  }, [stage, target, onStage]);

  // ---- definition draft ----
  const [type, setType] = useState<BuildingType>("power_station");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [definitionId, setDefinitionId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [stats, setStats] = useState<StatsDraft>(() => statsToDraft({}));
  const [criteria, setCriteria] = useState<CriterionDraft[]>([]);
  /** The real example the form was loaded from (shown with its sources until cleared). */
  const [basedOn, setBasedOn] = useState<BuildingPreset | null>(null);
  const template = templateFor(type, templateId);

  // The form as last loaded (empty, a preset or a saved definition). Anything else is the user's own
  // edits, which loading a preset must not discard without asking.
  const formState = JSON.stringify([name, description, stats]);
  const [loadedState, setLoadedState] = useState(formState);
  const hasEdits = formState !== loadedState;
  const markLoaded = (n: string, d: string, st: StatsDraft) => setLoadedState(JSON.stringify([n, d, st]));

  const [definitions, setDefinitions] = useState<BuildingDefinition[]>([]);
  const [defsError, setDefsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState<{ ok: boolean; text: string } | null>(null);

  const refreshDefinitions = () =>
    api
      .listDefinitions()
      .then((d) => {
        setDefinitions(d);
        setDefsError(null);
      })
      .catch((e) => setDefsError(message(e)));
  useEffect(() => {
    refreshDefinitions();
  }, []);

  const parsed = useMemo(() => parseStats(stats, template.parameters, type), [stats, template, type]);
  const crit = useMemo(() => parseCriteria(criteria), [criteria]);
  const formErrors = { ...parsed.errors, ...crit.errors };
  const errorCount = Object.keys(formErrors).length;
  const missing = useMemo(
    () => missingInputs(parsed.stats, parsed.parameters, template, crit.criteria),
    [parsed, template, crit.criteria],
  );
  const needs = useMemo(() => siteNeeds(parsed.stats, parsed.parameters, type), [parsed, type]);
  const currency = parsed.stats.costs?.currency || "currency";
  const periodDays = useMemo(() => mergeAssumptions(scenario?.assumptions).periodDays, [scenario?.assumptions]);

  const scenarioId = scenario?.id ?? null;
  const baseRequest = useMemo(
    () => ({
      scenarioId,
      type,
      stats: parsed.stats,
      parameters: parsed.parameters,
      criteria: crit.criteria,
    }),
    [scenarioId, type, parsed, crit.criteria],
  );
  /**
   * Revision of every input an assessment depends on; results for another revision are stale. The
   * server also reads the scenario's saved assumptions (period, budgets, stress) and its placed
   * buildings (shared budgets), so their revisions are part of the key.
   */
  const scenarioRevision = scenario
    ? JSON.stringify([scenario.updatedAt, scenario.assumptions, scenario.projects.map((p) => `${p.id}@${p.updatedAt}`)])
    : "";
  const inputKey = useMemo(() => JSON.stringify([baseRequest, scenarioRevision]), [baseRequest, scenarioRevision]);

  function snapshot(): DefinitionSnapshot {
    return {
      schemaVersion: SCHEMA_VERSION,
      name: name.trim(),
      description,
      templateId: template.version > 0 ? template.id : null,
      templateVersion: template.version > 0 ? template.version : null,
      stats: parsed.stats,
      criteria: crit.criteria,
    };
  }

  function chooseTemplate(t: (typeof templates)[number]) {
    setType(t.type);
    setTemplateId(t.id);
    // An untouched form starts from the template's documented defaults; entered values are kept.
    if (pristine(stats)) setStats(statsToDraft(t.defaults ?? {}, {}));
  }

  /** Load a real example; requirements (step 2) are kept. Presets are not templates: the type's template is used. */
  function loadPreset(p: BuildingPreset, force = false): boolean {
    if (!force && hasEdits && !confirm(`Replace your current building with “${p.name}”? Your edits to the form will be lost (requirements are kept).`)) {
      return false;
    }
    const form = presetToForm(p);
    setType(form.type);
    setTemplateId(null);
    setDefinitionId(null);
    setName(form.name);
    setDescription(form.description);
    setStats(form.stats);
    markLoaded(form.name, form.description, form.stats);
    setBasedOn(p);
    setSaveNote(null);
    setPresetNote(null);
    return true;
  }

  // A preset dropped on the map: load it once per request, then bring the preview into view.
  const handledPreset = useRef<number | null>(null);
  const [presetNote, setPresetNote] = useState<string | null>(null);
  const [scrollToPreview, setScrollToPreview] = useState(0);
  useEffect(() => {
    if (!presetRequest || handledPreset.current === presetRequest.nonce) return;
    const p = presets.find((x) => x.id === presetRequest.id);
    if (!p && !presetsLoaded && !presetsError) return; // still loading
    handledPreset.current = presetRequest.nonce;
    if (!p) {
      onTarget(null); // don't preview a different building than the one dropped
      return setPresetNote("That example couldn't be loaded, so nothing is previewed.");
    }
    if (!loadPreset(p)) {
      onTarget(null); // kept the user's draft: don't preview it at the drop point unasked
      return;
    }
    setScrollToPreview(presetRequest.nonce);
    // loadPreset only sets state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetRequest, presets, presetsLoaded, presetsError]);
  const previewRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollToPreview) previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [scrollToPreview]);
  useEffect(() => {
    if (target) previewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [target?.nonce]);

  function loadDefinition(id: string) {
    const d = definitions.find((x) => x.id === id);
    if (!d) return;
    setBasedOn(null);
    setType(d.type);
    setTemplateId(d.templateId ?? null);
    setDefinitionId(d.id);
    setName(d.name);
    setDescription(d.description);
    const st = statsToDraft(d.stats, d.parameters);
    setStats(st);
    markLoaded(d.name, d.description, st);
    setCriteria(d.criteria.map(criterionToDraft));
    setSaveNote(null);
  }

  function startOver() {
    if (!confirm("Clear this definition and start again? Saved definitions and placed buildings are not affected.")) return;
    setDefinitionId(null);
    setBasedOn(null);
    setName("");
    setDescription("");
    const st = statsToDraft(templateFor(type, templateId).defaults ?? {}, {});
    setStats(st);
    markLoaded("", "", st);
    setCriteria([]);
    setSaveNote(null);
    onTarget(null);
    onStage("define");
    setDefinePage("building");
  }

  async function saveDefinition(asNew: boolean) {
    if (!name.trim()) return setSaveNote({ ok: false, text: "Give the building a name before saving." });
    if (errorCount) return setSaveNote({ ok: false, text: "Fix the highlighted fields before saving." });
    const s = snapshot();
    const input = {
      name: s.name,
      description,
      type,
      templateId: s.templateId,
      templateVersion: s.templateVersion,
      stats: s.stats,
      parameters: parsed.parameters,
      criteria: s.criteria,
    };
    setSaving(true);
    try {
      const saved = definitionId && !asNew ? await api.updateDefinition(definitionId, input) : await api.createDefinition(input);
      setDefinitionId(saved.id);
      setLoadedState(formState); // saved, so nothing is lost by loading something else
      setSaveNote({ ok: true, text: `Saved “${saved.name}”. Future placements use it; buildings already placed keep their own copy.` });
      refreshDefinitions();
    } catch (e) {
      setSaveNote({ ok: false, text: message(e) });
    } finally {
      setSaving(false);
    }
  }

  async function deleteDefinition() {
    const d = definitions.find((x) => x.id === definitionId);
    if (!d || !confirm(`Delete the saved definition “${d.name}”? Buildings already placed keep their copy.`)) return;
    try {
      await api.deleteDefinition(d.id);
      setDefinitionId(null);
      setSaveNote({ ok: true, text: "Saved definition deleted. The form still holds its values." });
      refreshDefinitions();
    } catch (e) {
      setSaveNote({ ok: false, text: message(e) });
    }
  }

  // ---- step 3: find locations ----
  const [area, setArea] = useState<Area>("view");
  const [areaResult, setAreaResult] = useState<{ key: string; area: AreaAssessment; periodDays: number } | null>(null);
  const [areaLoading, setAreaLoading] = useState(false);
  const [areaError, setAreaError] = useState<string | null>(null);
  const areaCtrl = useRef<AbortController | null>(null);
  const areaFresh = !!areaResult && areaResult.key === inputKey;

  useEffect(() => {
    onCells(areaFresh ? areaResult!.area.cells : null);
  }, [areaFresh, areaResult, onCells]);

  // A different scenario invalidates everything that was assessed against the previous one.
  useEffect(() => {
    areaCtrl.current?.abort();
    setAreaResult(null);
    setAreaError(null);
    setAreaLoading(false);
    setBuildError(null);
  }, [scenarioId]);

  async function findLocations() {
    if (errorCount) return setAreaError("Fix the highlighted fields first.");
    const req = { ...baseRequest, limit: CANDIDATE_LIMIT } as Parameters<typeof api.assess>[0];
    if (area === "view") {
      if (!view) return setAreaError("The map view isn't ready yet.");
      const b = view.bounds;
      const bounds = {
        west: Math.max(-180, b.west),
        east: Math.min(180, b.east),
        south: Math.max(-90, b.south),
        north: Math.min(90, b.north),
      };
      if (bounds.west >= bounds.east) return setAreaError("Pan the map so the view doesn't cross the date line.");
      req.bounds = bounds;
    } else {
      req.region = area;
      onFitBounds?.(REGION_BBOX[area]);
    }
    areaCtrl.current?.abort();
    const ctrl = new AbortController();
    areaCtrl.current = ctrl;
    const key = inputKey;
    setAreaLoading(true);
    setAreaError(null);
    try {
      const r = await api.assess(req, ctrl.signal);
      if (ctrl.signal.aborted) return;
      if (!r.area) throw new Error("The server returned no area result.");
      setAreaResult({ key, area: r.area, periodDays: r.periodDays });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (e instanceof ApiError && e.status === 422 && /narrow|too many|smaller|zoom/i.test(e.message)) {
        setAreaError(`This area has too many cells to assess at once. Zoom in, or choose Arizona or UK. (${e.message})`);
      } else {
        setAreaError(message(e));
      }
    } finally {
      if (!ctrl.signal.aborted) setAreaLoading(false);
    }
  }

  // ---- step 4: exact-location preview ----
  const [loc, setLoc] = useState<{ key: string; value: LocationAssessment; periodDays: number } | null>(null);
  const [locLoading, setLocLoading] = useState(false);
  /** The error belongs to one request revision; an edit makes it stale. */
  const [locErr, setLocErr] = useState<{ key: string; message: string } | null>(null);
  const [building, setBuilding] = useState(false);
  const buildingRef = useRef(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  const targetOk = !!target && !!scenario && target.scenarioId === scenario.id;
  const locKey = target ? JSON.stringify([inputKey, target.latitude, target.longitude]) : "";
  const locFresh = !!loc && loc.key === locKey;
  const locError = locErr && locErr.key === locKey ? locErr.message : null;

  useEffect(() => {
    setBuildError(null);
    setLocErr(null);
  }, [target?.latitude, target?.longitude, target?.nonce]);

  // A preview bound to another scenario is cancelled rather than submitted there.
  useEffect(() => {
    if (target && scenario && target.scenarioId !== scenario.id) onTarget(null);
  }, [target, scenario, onTarget]);

  useEffect(() => {
    if (!target || !targetOk || errorCount) return;
    const ctrl = new AbortController();
    const key = locKey;
    const timer = setTimeout(async () => {
      setLocLoading(true);
      setLocErr(null);
      try {
        const r = await api.assess(
          { ...baseRequest, location: { latitude: target.latitude, longitude: target.longitude } },
          ctrl.signal,
        );
        if (ctrl.signal.aborted) return;
        if (!r.location) throw new Error("The server returned no location result.");
        setLoc({ key, value: r.location, periodDays: r.periodDays });
      } catch (e) {
        if (!ctrl.signal.aborted) setLocErr({ key, message: message(e) });
      } finally {
        if (!ctrl.signal.aborted) setLocLoading(false);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
      // The next run may bail out (invalid input) without starting a request.
      setLocLoading(false);
    };
    // locKey captures every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locKey, targetOk, errorCount]);

  async function buildHere(stay = false): Promise<Project | null> {
    if (!target || buildingRef.current) return null;
    if (!scenario || scenario.id !== target.scenarioId) {
      onTarget(null);
      return null;
    }
    if (errorCount) {
      setBuildError("Fix the highlighted fields first.");
      return null;
    }
    buildingRef.current = true;
    setBuilding(true);
    setBuildError(null);
    try {
      const created = await api.createProject(target.scenarioId, {
        type,
        name: name.trim() || template.label,
        latitude: target.latitude,
        longitude: target.longitude,
        parameters: parsed.parameters,
        definition: snapshot(),
        sourceDefinitionId: definitionId,
      });
      onTarget(null);
      onBuilt(created, { stay });
      setSupportNote(null);
      return created;
    } catch (e) {
      setBuildError(message(e)); // the draft is kept
      return null;
    } finally {
      buildingRef.current = false;
      setBuilding(false);
    }
  }

  /**
   * Place the previewed building, then load a supporting building (a preset, or the suggestion's
   * generic one sized to the shortfall) and preview it in a neighbouring hexagon. Placed buildings
   * feed their neighbours, so once it is placed too the first building's shortfall is covered.
   */
  async function placeWithSupport(s: SupportSuggestion, presetId: string | null) {
    const here = locFresh ? loc!.value.h3Id : null;
    if (!here) return;
    const preset = presetId ? presets.find((x) => x.id === presetId) : null;
    if (presetId && !preset) return setBuildError("That example couldn't be loaded.");
    const main = await buildHere(true);
    if (!main) return;
    if (preset) loadPreset(preset, true);
    else {
      setType(s.buildingType);
      setTemplateId(null);
      setDefinitionId(null);
      setName(s.genericName);
      setDescription(s.explanation);
      const st = statsToDraft(s.genericStats, {});
      setStats(st);
      markLoaded(s.genericName, s.explanation, st);
      setBasedOn(null);
    }
    const next = gridDisk(here, 1).find((c) => c !== here) ?? here;
    const [lat, lon] = cellToLatLng(next);
    onTarget({ latitude: lat, longitude: lon, scenarioId: main.scenarioId, nonce: Date.now() });
    onFocus(lat, lon);
    setPreviewPage("assessment");
    setSupportNote(
      `“${main.name}” is placed. Now previewing ${preset ? `“${preset.name}”` : `a ${s.genericName.toLowerCase()}`} in the neighbouring hexagon — place it (or pick another spot within ~${Math.round(s.reachKm)} km) to cover the shortfall.`,
    );
    setScrollToPreview(Date.now());
  }
  const [supportNote, setSupportNote] = useState<string | null>(null);

  const pickCandidate = (lat: number, lon: number) => {
    if (!scenario) return;
    onPick(false);
    onTarget({ latitude: lat, longitude: lon, scenarioId: scenario.id, nonce: Date.now() });
    onFocus(lat, lon);
  };

  const colour = `rgb(${typeColour(type).join(",")})`;
  const canBuild = targetOk && !building && !errorCount && (locFresh || !!locError);

  const preview = target && targetOk ? (
    <div className="preview" ref={previewRef}>
      <div className="panel-head">
        <h2>
          <span className="dot" style={{ background: colour }} /> {name.trim() || template.label}
        </h2>
        <button className="ghost" onClick={() => onTarget(null)} aria-label="Cancel preview">
          ✕
        </button>
      </div>
      <p className="subtitle small">
        {template.label} · <span className="mono">{coordLabel(target.latitude, target.longitude)}</span>
        {locFresh && <span className="mono"> · {loc!.value.h3Id}</span>}
      </p>

      {locLoading && !locFresh && <p className="muted small">Assessing this location…</p>}
      {locError && <p className="warn small">Assessment unavailable: {locError}</p>}
      {errorCount > 0 && <p className="warn small">Fix the highlighted fields to assess this location.</p>}
      {supportNote && <p className="note small">{supportNote}</p>}

      <PanelTabs label="Placement details" value={previewPage} onChange={setPreviewPage} options={[
        { value: "assessment", label: "Assessment" }, { value: "usage", label: "Usage & costs" },
      ]} />
      {locFresh && (
        <>
          <div hidden={previewPage !== "assessment"}>
          <h4>Can it be built here?</h4>
          <AssessmentView assessment={loc!.value.assessment} site={loc!.value.site} onSupport={canBuild ? placeWithSupport : undefined} />
          {(loc!.value.utilityPrices?.length ?? 0) > 0 && (
            <>
              <h4>Utility prices at this location</h4>
              <LocationPrices
                offers={loc!.value.utilityPrices!}
                onApply={(o) => setStats(applyLocationPrice(stats, o))}
                onRemove={(r) => setStats(removeLocationPrice(stats, r))}
              />
            </>
          )}
          </div>
          <div hidden={previewPage !== "usage"}>
          <Section title="Calculated usage and costs" meta={`over ${fmtDays(loc!.periodDays)}`} open>
            <ResultView result={loc!.value.result} producesPower={template.producesPower} producesWater={template.producesWater} />
          </Section>
          </div>
        </>
      )}

      {buildError && <p className="warn small">Not placed: {buildError}</p>}
    </div>
  ) : null;

  const statsErrorCount = Object.keys(parsed.errors).length;
  const resourceErrors = countErrors(parsed.errors, ["footprintM2", "operatingHoursPerDay", "power.", "water.", "materials.", "params."]);
  const stageIndex = ["define", "site", "place"].indexOf(stage);

  return (
    <div className="build-workflow">
      <div className="workflow-header">
        <nav className="build-steps" aria-label="Building workflow">
          {([ ["define", "Define"], ["site", "Find a site"], ["place", "Place"] ] as const).map(([id, label], i) => (
            <button key={id} aria-current={stage === id ? "step" : undefined}
              disabled={(id === "site" && statsErrorCount > 0) || (id === "place" && (!targetOk || errorCount > 0))}
              onClick={() => onStage(id)}>
              <span>{i + 1}</span>{label}{i < 2 && <Icon name="chevron" size={14} />}
            </button>
          ))}
        </nav>
        <div className="stage-caption">Step {stageIndex + 1} of 3 <span>{stage === "define" ? "Define what you want to build" : stage === "site" ? "Choose where it should go" : "Review before placing"}</span></div>
      </div>
      <div className="workflow-content" ref={contentRef}>
      <div hidden={stage !== "define"}>
        <PanelTabs label="Building definition sections" value={definePage} onChange={setDefinePage} options={[
          { value: "building", label: "Building" }, { value: "resources", label: "Resources", count: resourceErrors },
          { value: "impact", label: "Impact & costs", count: statsErrorCount - resourceErrors },
        ]} />
        {templatesError && <p className="note small">Templates couldn't be loaded ({templatesError}); using built-in field lists.</p>}
      {/* ---------------- 1. Define ---------------- */}
      <section className="panel" id="build-define">
        <div hidden={definePage !== "building"}>
        <h3 className="step">Choose a building type</h3>
        <div className="template-grid" role="radiogroup" aria-label="Building type">
          {templates.map((t) => {
            const on = t.id === template.id;
            return (
              <button key={t.id} role="radio" aria-checked={on} className={on ? "selected" : ""} onClick={() => chooseTemplate(t)}>
                <Icon name={t.type === "water_plant" ? "water" : t.type === "power_station" ? "bolt" : t.type === "solar" ? "sun" : "building"} />
                {t.label}
              </button>
            );
          })}
        </div>
        <details className="readiness-note"><summary>About this building type</summary><p className="muted small">{template.description}</p></details>
        <details className="section example-section"><summary><Icon name="globe" size={17} /><span className="section-title">Start from a real-world example</span></summary><div className="section-body">
          <PresetPalette presets={presets.filter((preset) => preset.type === type)} loaded={presetsLoaded} error={presetsError} selectedId={basedOn?.id ?? null} onLoad={loadPreset} />
        </div></details>
        {presetNote && <p className="warn small">{presetNote}</p>}

        {definitions.length > 0 && (
          <div className="row align-end">
            <label className="field">
              <span>Or load a saved definition</span>
              <select value={definitionId ?? ""} onChange={(e) => loadDefinition(e.target.value)}>
                <option value="">—</option>
                {definitions.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            {definitionId && (
              <button className="ghost danger" onClick={deleteDefinition}>
                Delete saved
              </button>
            )}
          </div>
        )}
        {defsError && <p className="small muted">Saved definitions unavailable: {defsError}</p>}

        <Field label="Name" value={name} onChange={setName} numeric={false} placeholder={template.label} />
        <Section title="Description & source notes">
        <label className="field">
          <span>What do you want to build?</span>
          <textarea
            rows={3}
            value={description}
            placeholder="Plain-language description, e.g. a 50 MW gas turbine plant with evaporative cooling"
            onChange={(e) => setDescription(e.target.value)}
          />
          <small className="muted">Saved with the definition. Numbers are never read from it — enter them in Resources and Impact &amp; costs.</small>
        </label>

        {basedOn && <PresetBasis preset={basedOn} />}
        </Section>
        </div>
        <div hidden={definePage === "building"}>
          <p className="subtitle small">{name.trim() || template.label} · blank fields remain unknown.</p>
          <BuildingForm draft={stats} onChange={setStats} errors={parsed.errors} template={template} page={definePage === "impact" ? "impact" : "resources"} />
        </div>
        {missing.length > 0 && (
          <details className="readiness-note"><summary>{missing.length} item{missing.length === 1 ? "" : "s"} still needed for a conclusive assessment</summary>
          <div className="note">
            <strong>Still needed to calculate everything</strong>
            <ul>
              {missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            <span className="muted small">Blank fields are treated as unknown, never as zero.</span>
          </div></details>
        )}

        {errorCount > 0 && <p className="warn small">Fix {errorCount} highlighted field{errorCount === 1 ? "" : "s"} before saving or placing.</p>}
        <div className="actions">
          <button className="primary" onClick={() => saveDefinition(false)} disabled={saving}>
            {saving ? "Saving…" : definitionId ? "Save changes" : "Save definition"}
          </button>
          {definitionId && (
            <button onClick={() => saveDefinition(true)} disabled={saving}>
              Save as new
            </button>
          )}
          <button className="right" onClick={startOver}>
            Start over
          </button>
        </div>
        {saveNote && <p className={`small ${saveNote.ok ? "ok" : "warn"}`}>{saveNote.text}</p>}
        <p className="muted small">Saving is optional — you can place a building straight from this form.</p>
      </section>

      </div>
      <div hidden={stage !== "site"}>
        <div className="draft-summary"><Icon name="building" size={18} /><span><strong>{name.trim() || template.label}</strong><small>{template.label} · {fmtDays(periodDays)}</small></span><button className="link inline small" onClick={() => onStage("define")}>Edit</button></div>
        <PanelTabs label="Site selection sections" value={sitePage} onChange={setSitePage} options={[
          { value: "requirements", label: "Site needs", count: Object.keys(crit.errors).length }, { value: "search", label: "Find locations" },
        ]} />
      {/* ---------------- 2. Requirements ---------------- */}
      <section className="panel" id="build-requirements" hidden={sitePage !== "requirements"}>
        <h3 className="step">What a site must provide</h3>
        <p className="muted small">
          Worked out from your building's specs. Each location is checked against what its hexagon and the
          surrounding hexagons can supply.
        </p>
        <ul className="site-needs">
          {needs.map((x) => (
            <li key={x.key}>
              <strong>{x.label}{x.advisory && <span className="muted small"> (advisory)</span>}</strong>
              {x.from ? <span className="num">{x.from}</span> : <span className={x.key === "land" ? "warn" : "muted"}>{x.hint}</span>}
            </li>
          ))}
        </ul>
        <Section title="Your own extra limits" meta={crit.criteria.length ? `${crit.criteria.length} set` : "optional"} invalid={Object.keys(crit.errors).length}>
          <p className="muted small">Preferences on top of what the site provides, e.g. avoid high water stress or steep land, or keep within a budget.</p>
          <CriteriaEditor drafts={criteria} onChange={setCriteria} errors={crit.errors} catalogue={catalogue} currency={currency} periodDays={periodDays} />
        </Section>
      </section>

      {/* ---------------- 3. Find locations ---------------- */}
      <section className="panel" hidden={sitePage !== "search"}>
        <h3 className="step">Find a site</h3>
        {targetOk && <div className="selected-site">
          <span className="small">Selected point <strong className="block mono">{coordLabel(target!.latitude, target!.longitude)}</strong></span>
          <button className={picking ? "active" : ""} disabled={!scenario || errorCount > 0} aria-pressed={picking} onClick={() => onPick(!picking)}>{picking ? "Cancel map pick" : "Pick another point"}</button>
        </div>}
        <details className="section search-setup" open={!areaFresh}>
        <summary><span className="section-title">Search area</span><span className="section-meta">{AREA_LABEL[area]}</span></summary>
        <div className="section-body">
        {!needs[0].from && (
          <p className="note small">
            Enter the building's footprint in Define → Resources. Without it, whether a site has room for it
            can't be judged and every hexagon will show “Can't tell yet”.
          </p>
        )}
        <fieldset className="radios">
          <legend className="small muted">Area to assess</legend>
          {(Object.keys(AREA_LABEL) as Area[]).map((a) => (
            <label key={a} className="toggle compact">
              <input type="radio" name="build-area" checked={area === a} onChange={() => setArea(a)} />
              <span>{AREA_LABEL[a]}</span>
            </label>
          ))}
        </fieldset>
        <div className="actions">
          <button className="primary" onClick={findLocations} disabled={!scenario || areaLoading || errorCount > 0}>
            <Icon name="search" size={17} />{areaLoading ? "Assessing…" : "Find locations"}
          </button>
          {areaLoading && (
            <button
              onClick={() => {
                areaCtrl.current?.abort();
                setAreaLoading(false);
              }}
            >
              Stop
            </button>
          )}
          {areaResult && (
            <button className="right" onClick={() => setAreaResult(null)}>
              Clear results
            </button>
          )}
        </div>
        </div></details>
        {areaError && <p className="warn small">{areaError}</p>}
        {areaResult && !areaFresh && (
          <p className="note small">The building, requirements or scenario changed since this search. Find locations again to update the results.</p>
        )}
        {areaResult && areaFresh && <AreaResults area={areaResult.area} periodDays={areaResult.periodDays} onPick={pickCandidate} />}
      </section>

      </div>
      <div hidden={stage !== "place"}>{preview}</div>
      </div>
      <footer className="workflow-footer">
        {stage === "define" && statsErrorCount > 0 && <p className="warn small" role="status">Fix the marked resource or impact fields to continue. Blank fields are allowed.</p>}
        {stage === "site" && !targetOk && <p className="muted small">Choose a candidate or pick an exact point on the map.</p>}
        {stage === "place" && errorCount > 0 && <p className="warn small">Fix highlighted inputs before placing. <button className="link inline small" onClick={() => {
          if (statsErrorCount) { setDefinePage(resourceErrors ? "resources" : "impact"); onStage("define"); }
          else if (Object.keys(crit.errors).length) { setSitePage("requirements"); onStage("site"); }
        }}>Review fields</button></p>}
        <div className="actions">
          {stage === "define" ? (
            <button className="primary right" disabled={statsErrorCount > 0} onClick={() => onStage("site")}>Next: Find a site <Icon name="arrow" size={16} /></button>
          ) : stage === "site" ? (
            <>
              <button onClick={() => onStage("define")}>Back</button>
              {sitePage === "requirements" ? <button className="primary right" onClick={() => setSitePage("search")} disabled={errorCount > 0}>Continue to locations <Icon name="arrow" size={16} /></button>
                : targetOk ? <button className="primary right" disabled={errorCount > 0} onClick={() => onStage("place")}>Next: Review & place <Icon name="arrow" size={16} /></button>
                : <button className={picking ? "active right" : "primary right"} disabled={!scenario || errorCount > 0} aria-pressed={picking} onClick={() => onPick(!picking)}><Icon name="pin" size={16} />{picking ? "Cancel map pick" : "Pick on map"}</button>}
            </>
          ) : (
            <>
              <button disabled={building} onClick={() => { setSitePage("search"); onStage("site"); }}>Change site</button>
              <button className="primary right" disabled={!canBuild} onClick={() => buildHere()}>{building ? "Placing…" : "Build here"}<Icon name="arrow" size={16} /></button>
            </>
          )}
        </div>
      </footer>
    </div>
  );
}

function AreaResults({ area, periodDays, onPick }: { area: AreaAssessment; periodDays: number; onPick: (lat: number, lon: number) => void }) {
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [area]);
  const pages = Math.ceil(area.candidates.length / 5);
  return (
    <div className="results">
      <p className="small">
        {area.cellCount.toLocaleString()} cells assessed (resolution 6) · usage over {fmtDays(periodDays)}
      </p>
      <StateLegend counts={area.counts} />
      {area.note && <details className="readiness-note"><summary>Screening method & limitations</summary><p className="note small">{area.note}</p></details>}
      {area.candidates.length === 0 ? (
        <p className="muted small">No candidate cells in this area.</p>
      ) : (
        <>
          <h4>
            Candidates{" "}
            <span className="muted small">
              (first {area.candidates.length}
              {area.cellCount > area.candidates.length ? ` of ${area.cellCount.toLocaleString()}` : ""}: buildable, then can’t tell yet, then not buildable)
            </span>
          </h4>
          <ol className="list candidates">
            {area.candidates.slice(page * 5, page * 5 + 5).map((c) => {
              const fails = c.assessment.checks.filter((x) => x.status === "fail").length;
              const unknown = c.assessment.checks.filter((x) => x.status === "unknown").length;
              return (
                <li key={c.h3Id}>
                  <button className="link" onClick={() => onPick(c.latitude, c.longitude)}>
                    <StateBadge state={c.assessment.state} />
                    <span className="grow">
                      <span className="mono small">{coordLabel(c.latitude, c.longitude)}</span>
                      <small className="muted block">
                        {fails} failed · {unknown} unknown · {c.assessment.checks.length} check{c.assessment.checks.length === 1 ? "" : "s"}
                      </small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          {pages > 1 && <div className="pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page + 1} of {pages}</span><button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next candidates</button></div>}
        </>
      )}
    </div>
  );
}

/** "Start from a real example": draggable cards; click loads one into the form. */
function PresetPalette(props: {
  presets: BuildingPreset[];
  loaded: boolean;
  error: string | null;
  selectedId: string | null;
  onLoad: (p: BuildingPreset) => void;
}) {
  const { presets, loaded, error, selectedId, onLoad } = props;
  if (error) return <p className="muted small">Examples unavailable.</p>;
  if (!loaded) return <p className="muted small">Loading real examples…</p>;
  if (presets.length === 0) return <p className="muted small">No real-world examples for this building type yet. You can define your own specifications below.</p>;
  return (
    <div className="presets">
      <p className="muted small">Choose an example to load its specifications, or drag it onto the map to preview a site.</p>
      <div className="preset-grid">
        {presets.map((p) => (
          <div
            key={p.id}
            role="button"
            tabIndex={0}
            draggable
            aria-pressed={p.id === selectedId}
            className={`preset-card${p.id === selectedId ? " selected" : ""}`}
            title={`${p.name} — ${presetPlace(p)}. Drag onto the map, or click to load.`}
            onClick={() => onLoad(p)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onLoad(p);
              }
            }}
            onDragStart={(e) => {
              e.dataTransfer.setData(PRESET_DRAG_TYPE, p.id);
              e.dataTransfer.effectAllowed = "copy";
            }}
          >
            <span className="preset-name">
              <span className="dot" style={{ background: `rgb(${typeColour(p.type).join(",")})` }} />
              {p.name}
            </span>
            <span className="preset-headline">{p.headline}</span>
            <span className="preset-sources">{sourceCount(p.sources.length)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Where the loaded example's figures come from. */
function PresetBasis({ preset }: { preset: BuildingPreset }) {
  return (
    <div className="preset-basis small">
      <strong>Based on {presetPlace(preset)}</strong>
      <p className="muted">
        Figures are cited from the sources below; blanks are unknown. Edited sections are marked as your own assumption.
      </p>
      {preset.notes.length > 0 && (
        <ul>
          {preset.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      <ol className="preset-source-list">
        {preset.sources.map((s) => (
          <li key={s.id}>
            <a href={s.url} target="_blank" rel="noreferrer noopener">
              {s.title}
            </a>
            <span className="muted">
              {" "}
              · {s.publisher}
              {s.year ? ` (${s.year})` : ""} [{s.id}]
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
