import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cellToLatLng, gridDisk } from "h3-js";
import Icon from "./Icon";
import { api, ApiError, type Project, type Scenario } from "../lib/api";
import type {
  AreaAssessment,
  BuildingDefinition,
  BuildingPreset,
  BuildingType,
  DefinitionSnapshot,
  LocationAssessment,
  SupportSuggestion,
} from "../lib/buildings";
import type { CellLayer } from "../lib/datalayers";
import {
  applyLocationPrice,
  countErrors,
  criterionToDraft,
  mergeAssumptions,
  parseCriteria,
  parseStats,
  removeLocationPrice,
  statsToDraft,
  type CriterionDraft,
  type StatsDraft,
} from "../lib/buildingForm";
import { groupTemplates, typeColour, typeIcon } from "../lib/projectTypes";
import { useBuildingTemplates } from "../lib/useBuildingTemplates";
import { useBuildingPresets } from "../lib/useBuildingPresets";
import { presetPlace, presetToForm, splitPresetsByType } from "../lib/presets";
import { screenedArea, type ScreenedArea } from "../lib/suitability";
import { layerNeeds, type LayerNeed } from "../lib/buildLayers";
import type { MapView } from "./WorldMap";
import BuildingForm from "./BuildingForm";
import CriteriaEditor from "./CriteriaEditor";
import SitePanel from "./SitePanel";
import { Field, Section } from "./FormBits";

/** An exact location being previewed, bound to the scenario it was chosen in. */
export type BuildTarget = { latitude: number; longitude: number; scenarioId: string; nonce: number };

/** Ask the panel to load a real example into the form (e.g. after it was dropped on the map). */
export type PresetRequest = { id: string; nonce: number };

export type BuildStage = "building" | "resources" | "impact";

export const BUILD_STAGES: { id: BuildStage; label: string }[] = [
  { id: "building", label: "Building" },
  { id: "resources", label: "Resources" },
  { id: "impact", label: "Impact & costs" },
];

type Props = {
  stage: BuildStage;
  onStage: (stage: BuildStage) => void;
  scenario: Scenario | null;
  view: MapView | null;
  catalogue: CellLayer[];
  /** Set on any map click while the Build tab is open. */
  target: BuildTarget | null;
  onTarget: (t: BuildTarget | null) => void;
  /** The live screening of the visible map (null while hidden or before the first result). */
  onArea: (area: ScreenedArea | null) => void;
  /** What the map's screening overlay is coloured by: "overall" or a suitability factor key. */
  colourBy: string;
  onColourBy: (key: string) => void;
  /** The suitability profile the map is currently coloured by (null: none, or out of date). */
  mapProfileId: string | null;
  /** `stay`: keep the Build tab open (a supporting building is previewed next). */
  onBuilt: (p: Project, opts?: { stay?: boolean }) => void;
  onFocus: (latitude: number, longitude: number) => void;
  /** The Build tab is open: screen the visible map and show the result. */
  active: boolean;
  /** What the map overlay should say about the live screening. */
  onMapStatus?: (status: { note: string | null; loading: boolean }) => void;
  /** Load this example into the form; a new nonce loads it again. */
  presetRequest?: PresetRequest | null;
  /** Right-hand inspector element to portal the live SitePanel into (null until mounted). */
  siteHost: HTMLElement | null;
  /** Map layers about what the building needs (electricity → grid, water → rivers …), as specs change. */
  onNeeds?: (needs: LayerNeed[]) => void;
};

/** The server's cap on one area screening (resolution-6 cells, ~36 km² each). */
const MAX_AREA_CELLS = 30_000;
const CELL_KM2 = 36.13;

/** Rough number of resolution-6 cells inside a lon/lat box. */
function estimateCells(b: { west: number; south: number; east: number; north: number }) {
  const rad = Math.PI / 180;
  const km2 = 6371 ** 2 * (b.east - b.west) * rad * Math.abs(Math.sin(b.north * rad) - Math.sin(b.south * rad));
  return km2 / CELL_KM2;
}

const SCHEMA_VERSION = 1;
const RESOURCE_FIELDS = ["footprintM2", "operatingHoursPerDay", "power.", "water.", "materials.", "params."];

const pristine = (d: StatsDraft) =>
  Object.values(d.values).every((v) => v.trim() === "") &&
  d.materials.length === 0 &&
  d.emissions.length === 0 &&
  Object.values(d.params).every((v) => v.trim() === "");

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const fieldCount = (n: number) => `${n} field${n === 1 ? "" : "s"}`;

export default function BuildPanel(props: Props) {
  const { stage, onStage, scenario, view, catalogue, target, onTarget, onArea, onBuilt, onFocus, presetRequest, siteHost, active, onMapStatus } = props;
  const { templates, templateFor, error: templatesError } = useBuildingTemplates();
  const { presets, loaded: presetsLoaded, error: presetsError } = useBuildingPresets();
  const ids = useId();

  // ---- wizard ----
  const stageIndex = Math.max(0, BUILD_STAGES.findIndex((s) => s.id === stage));
  /** Furthest step reached; later steps stay locked until reached with Next. */
  const [reached, setReached] = useState(stageIndex);
  useEffect(() => setReached((r) => Math.max(r, stageIndex)), [stageIndex]);
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => { contentRef.current?.scrollTo({ top: 0 }); }, [stage]);

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
  const typeGroups = useMemo(() => groupTemplates(templates, "", template.id), [templates, template.id]);
  const examples = useMemo(() => splitPresetsByType(presets, type).matching, [presets, type]);

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
  const resourceErrors = countErrors(parsed.errors, RESOURCE_FIELDS);
  const stepErrors = [0, resourceErrors, Object.keys(parsed.errors).length - resourceErrors + Object.keys(crit.errors).length];
  const firstErrorStep = stepErrors.findIndex((n) => n > 0);
  const currency = parsed.stats.costs?.currency || "currency";
  const periodDays = useMemo(() => mergeAssumptions(scenario?.assumptions).periodDays, [scenario?.assumptions]);

  // Which map layers the building's needs call for; reported only when they change.
  const needs = useMemo(
    () =>
      layerNeeds({
        type,
        stats: parsed.stats,
        parameters: parsed.parameters,
        producesPower: template.producesPower,
        producesWater: template.producesWater,
      }),
    [type, parsed, template.producesPower, template.producesWater],
  );
  const needsKey = JSON.stringify(needs);
  const onNeeds = props.onNeeds;
  useEffect(() => {
    onNeeds?.(needs);
    // needsKey captures `needs`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsKey, onNeeds]);

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

  function chooseTemplate(id: string) {
    const t = templates.find((x) => x.id === id);
    if (!t) return;
    setType(t.type);
    setTemplateId(t.id);
    // An untouched form starts from the template's documented defaults; entered values are kept.
    if (pristine(stats)) setStats(statsToDraft(t.defaults ?? {}, {}));
  }

  /** Load a real example; limits are kept. Presets are not templates: the type's template is used. */
  function loadPreset(p: BuildingPreset, force = false): boolean {
    if (!force && hasEdits && !confirm(`Replace your current building with “${p.name}”? Your edits to the form will be lost (limits are kept).`)) {
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

  const startFrom = basedOn && examples.some((p) => p.id === basedOn.id) ? `p:${basedOn.id}` : definitionId ? `d:${definitionId}` : "";
  function chooseStart(value: string) {
    if (!value) {
      setBasedOn(null);
      setDefinitionId(null);
      return;
    }
    const id = value.slice(2);
    if (value.startsWith("d:")) return loadDefinition(id);
    const p = examples.find((x) => x.id === id);
    if (p) loadPreset(p);
  }

  // A preset dropped on the map: load it once per request.
  const handledPreset = useRef<number | null>(null);
  const [presetNote, setPresetNote] = useState<string | null>(null);
  useEffect(() => {
    if (!presetRequest || handledPreset.current === presetRequest.nonce) return;
    const p = presets.find((x) => x.id === presetRequest.id);
    if (!p && !presetsLoaded && !presetsError) return; // still loading
    handledPreset.current = presetRequest.nonce;
    if (!p) {
      onTarget(null); // don't preview a different building than the one dropped
      return setPresetNote("That example couldn't be loaded, so nothing is previewed.");
    }
    if (!loadPreset(p)) onTarget(null); // kept the user's draft: don't preview it at the drop point unasked
    // loadPreset only sets state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetRequest, presets, presetsLoaded, presetsError]);

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
    setReached(0);
    onStage("building");
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
      setSaveNote({ ok: true, text: `Saved “${saved.name}”.` });
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
      setSaveNote({ ok: true, text: "Saved definition deleted." });
      refreshDefinitions();
    } catch (e) {
      setSaveNote({ ok: false, text: message(e) });
    }
  }

  // ---- live screening of the visible map, refreshed as the definition or view changes ----
  const [areaResult, setAreaResult] = useState<{ key: string; area: AreaAssessment } | null>(null);
  const [areaLoading, setAreaLoading] = useState(false);
  const [areaNote, setAreaNote] = useState<string | null>(null);
  const b = view?.bounds;
  const areaBounds = useMemo(() => {
    if (!b) return null;
    const r = (x: number) => Math.round(x * 100) / 100;
    const bounds = { west: r(Math.max(-180, b.west)), east: r(Math.min(180, b.east)), south: r(Math.max(-85, b.south)), north: r(Math.min(85, b.north)) };
    return bounds.west < bounds.east && bounds.south < bounds.north ? bounds : null;
  }, [b?.west, b?.east, b?.south, b?.north]);
  const boundsKey = JSON.stringify(areaBounds);

  // A result for an earlier version of the building stays visible while it is being refreshed; when no
  // refresh can run (a note explains why: zoom in, fix fields, request failed) it is shown as out of date.
  // Once greyed out it stays so until a result for the current building arrives (it is not repainted
  // in the old building's grades while the refresh runs).
  const areaMismatch = !!areaResult && areaResult.key !== inputKey;
  const [areaGreyed, setAreaGreyed] = useState(false);
  useEffect(() => {
    if (!areaMismatch) setAreaGreyed(false);
    else if (areaNote) setAreaGreyed(true);
  }, [areaMismatch, areaNote]);
  const areaStale = areaMismatch && (areaGreyed || !!areaNote);
  useEffect(() => {
    onArea(active && areaResult ? screenedArea(areaResult.area, areaStale) : null);
  }, [active, areaResult, areaStale, onArea]);

  useEffect(() => {
    if (!active || !scenarioId) return;
    if (errorCount) return setAreaNote("Fix the highlighted fields to update the map");
    if (!areaBounds) return setAreaNote(view ? "Pan so the view doesn't cross the date line" : null);
    if (estimateCells(areaBounds) > MAX_AREA_CELLS) return setAreaNote("Zoom in to see where it fits");
    setAreaNote(null);
    const ctrl = new AbortController();
    const key = inputKey;
    setAreaLoading(true); // "updating…" from the moment a refresh is scheduled, not after the debounce
    const timer = setTimeout(async () => {
      try {
        const r = await api.assess({ ...baseRequest, bounds: areaBounds, limit: 1 }, ctrl.signal);
        if (!ctrl.signal.aborted && r.area) setAreaResult({ key, area: r.area });
      } catch (e) {
        if (ctrl.signal.aborted) return;
        const tooBig = e instanceof ApiError && e.status === 422 && /narrow|too many|smaller|zoom/i.test(e.message);
        setAreaNote(tooBig ? "Zoom in to see where it fits" : "Couldn't update the map");
      } finally {
        if (!ctrl.signal.aborted) setAreaLoading(false);
      }
    }, 450);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
      setAreaLoading(false);
    };
    // inputKey and boundsKey capture every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, scenarioId, errorCount, inputKey, boundsKey]);

  useEffect(() => {
    onMapStatus?.({ note: active ? areaNote : null, loading: active && areaLoading });
  }, [active, areaNote, areaLoading, onMapStatus]);

  // A different scenario invalidates everything that was assessed against the previous one.
  useEffect(() => {
    setAreaResult(null);
    setBuildError(null);
  }, [scenarioId]);

  // ---- live exact-location assessment ----
  const [loc, setLoc] = useState<{ key: string; site: string; value: LocationAssessment; periodDays: number } | null>(null);
  const [locLoading, setLocLoading] = useState(false);
  /** The error belongs to one request revision; an edit makes it stale. */
  const [locErr, setLocErr] = useState<{ key: string; message: string } | null>(null);
  const [building, setBuilding] = useState(false);
  const buildingRef = useRef(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [supportNote, setSupportNote] = useState<string | null>(null);

  const targetOk = !!target && !!scenario && target.scenarioId === scenario.id;
  const locKey = target ? JSON.stringify([inputKey, target.latitude, target.longitude, target.nonce]) : "";
  const siteKey = target ? `${target.latitude},${target.longitude}` : "";
  const locFresh = !!loc && loc.key === locKey;
  const locError = locErr && locErr.key === locKey ? locErr.message : null;
  /** The latest result for this spot stays visible (marked as updating) while an edit is re-assessed. */
  const shownLoc = loc && (locFresh || loc.site === siteKey) ? loc : null;

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
        setLoc({ key, site: `${target.latitude},${target.longitude}`, value: r.location, periodDays: r.periodDays });
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
    setSupportNote(
      `“${main.name}” is placed. Now previewing ${preset ? `“${preset.name}”` : `a ${s.genericName.toLowerCase()}`} in the neighbouring hexagon — place it (or pick another spot within ~${Math.round(s.reachKm)} km) to cover the shortfall.`,
    );
  }


  const colour = `rgb(${typeColour(type).join(",")})`;
  const canBuild = targetOk && !building && !errorCount && (locFresh || !!locError);
  const blocked = firstErrorStep >= 0
    ? `Fix ${fieldCount(stepErrors[firstErrorStep])} in ${BUILD_STAGES[firstErrorStep].label}`
    : null;

  /** Steps ahead stay locked while a step on the way has invalid fields. */
  const canGoTo = (i: number) =>
    i <= reached && stepErrors.slice(stageIndex, Math.max(stageIndex, i)).every((n) => n === 0);
  const next = BUILD_STAGES[stageIndex + 1];

  return (
    <div className="build-workflow">
      <div className="workflow-header">
        <nav className="build-steps" aria-label="Building workflow">
          {BUILD_STAGES.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-current={i === stageIndex ? "step" : undefined}
              className={i < reached && i !== stageIndex ? "done" : undefined}
              disabled={i !== stageIndex && !canGoTo(i)}
              onClick={() => onStage(s.id)}
            >
              <span>{i + 1}</span>
              {s.label}
            </button>
          ))}
        </nav>
      </div>

      <div className="workflow-content" ref={contentRef}>
        {presetNote && <p className="warn small">{presetNote}</p>}

        {stage === "building" && (
          <div className="wizard-step">
            {templatesError && (
              <p className="note small" title={templatesError}>
                Building types couldn't be loaded; using built-in fields.
              </p>
            )}
            <Section title="Building">
              <div className="field">
                <label htmlFor={`${ids}-type`}>Building type</label>
                <div className="type-picker">
                  <Icon name={typeIcon(type)} />
                  <select id={`${ids}-type`} value={template.id} title={template.description} onChange={(e) => chooseTemplate(e.target.value)}>
                    {typeGroups.map((g) => (
                      <optgroup key={g.category} label={g.label}>
                        {g.templates.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.label}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
              </div>

              {(examples.length > 0 || definitions.length > 0) && (
                <div className="field">
                  <label htmlFor={`${ids}-example`}>Start from</label>
                  <div className="wizard-row nowrap">
                    <div className="example-picker">
                      <Icon name={definitionId ? "building" : "globe"} />
                      <select id={`${ids}-example`} value={startFrom} onChange={(e) => chooseStart(e.target.value)}>
                        <option value="">None</option>
                        {examples.length > 0 && (
                          <optgroup label="Real examples">
                            {examples.map((p) => (
                              <option key={p.id} value={`p:${p.id}`} title={p.headline}>
                                {p.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                        {definitions.length > 0 && (
                          <optgroup label="Saved">
                            {definitions.map((d) => (
                              <option key={d.id} value={`d:${d.id}`}>
                                {d.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </select>
                    </div>
                    {definitionId && (
                      <button type="button" className="ghost danger" onClick={deleteDefinition} title="Delete this saved definition">
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}
              {defsError && (
                <p className="small muted" title={defsError}>
                  Saved definitions unavailable.
                </p>
              )}
              {basedOn && <PresetBasis preset={basedOn} />}
            </Section>

            <Section title="Details">
              <Field label="Name" value={name} onChange={setName} numeric={false} placeholder={template.label} />
              <label className="field">
                <span>Description</span>
                <textarea
                  rows={3}
                  value={description}
                  placeholder="e.g. a 50 MW gas turbine plant with evaporative cooling"
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
            </Section>
          </div>
        )}

        {stage === "resources" && (
          <div className="wizard-step">
            <BuildingForm page="resources" draft={stats} onChange={setStats} errors={parsed.errors} template={template} />
          </div>
        )}

        {stage === "impact" && (
          <div className="wizard-step">
            <BuildingForm page="impact" draft={stats} onChange={setStats} errors={parsed.errors} template={template} />
            <Section title="Limits" invalid={Object.keys(crit.errors).length}>
              <CriteriaEditor drafts={criteria} onChange={setCriteria} errors={crit.errors} catalogue={catalogue} currency={currency} periodDays={periodDays} />
            </Section>
          </div>
        )}
      </div>

      <footer className="workflow-footer">
        {stepErrors[stageIndex] > 0 ? (
          <p className="warn small" role="status">
            Fix {fieldCount(stepErrors[stageIndex])} to continue.
          </p>
        ) : saveNote && !next ? (
          <p className={`small ${saveNote.ok ? "ok" : "warn"}`} role="status">
            {saveNote.text}
          </p>
        ) : null}
        <div className="actions">
          {stageIndex > 0 ? (
            <button type="button" onClick={() => onStage(BUILD_STAGES[stageIndex - 1].id)}>
              Back
            </button>
          ) : (
            <button type="button" className="ghost" onClick={startOver}>
              Start over
            </button>
          )}
          {next ? (
            <button type="button" className="primary right" disabled={stepErrors[stageIndex] > 0} onClick={() => onStage(next.id)}>
              Next: {next.label} <Icon name="arrow" size={16} />
            </button>
          ) : (
            <>
              {definitionId && (
                <button type="button" className="right" onClick={() => saveDefinition(true)} disabled={saving}>
                  Save as new
                </button>
              )}
              <button type="button" className={definitionId ? "primary" : "primary right"} onClick={() => saveDefinition(false)} disabled={saving || errorCount > 0}>
                {saving ? "Saving…" : definitionId ? "Save changes" : "Save definition"}
              </button>
            </>
          )}
        </div>
      </footer>

      {siteHost &&
        createPortal(
          <SitePanel
            buildingName={name.trim() || template.label}
            typeLabel={template.label}
            colour={colour}
            target={targetOk ? target : null}
            loading={locLoading || (!!shownLoc && !locFresh && !locError && !errorCount)}
            error={locError}
            blocked={blocked}
            location={shownLoc ? shownLoc.value : null}
            periodDays={shownLoc ? shownLoc.periodDays : periodDays}
            producesPower={template.producesPower}
            producesWater={template.producesWater}
            canBuild={canBuild}
            building={building}
            buildError={buildError}
            supportNote={supportNote}
            onBuild={() => buildHere()}
            onCancel={() => onTarget(null)}
            onSupport={canBuild ? placeWithSupport : undefined}
            onApplyPrice={(o) => setStats((st) => applyLocationPrice(st, o))}
            onRemovePrice={(r) => setStats((st) => removeLocationPrice(st, r))}
            colourBy={props.colourBy}
            onColourBy={props.onColourBy}
            mapProfileId={props.mapProfileId}
          />,
          siteHost,
        )}
    </div>
  );
}

function PresetBasis({ preset }: { preset: BuildingPreset }) {
  return (
    <p className="preset-basis small">
      <span>Based on {presetPlace(preset)}</span>
      {preset.sources.map((src, i) => (
        <a key={src.id} href={src.url} target="_blank" rel="noreferrer noopener" title={`${src.title} · ${src.publisher}${src.year ? ` (${src.year})` : ""}`}>
          [{i + 1}]
        </a>
      ))}
    </p>
  );
}
