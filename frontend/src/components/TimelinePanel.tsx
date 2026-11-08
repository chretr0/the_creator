import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Project, type Scenario } from "../lib/api";
import { DEFAULT_DISPERSION, dailyEmission, impactCells, knownTotal, DEFAULT_ENVIRONMENT, ENVIRONMENT_FIELDS, validEnvironment, impactUnit, pollutantKey, pollutantLabel, timeLabel, validDispersion,
  DEFAULT_AIR_MEASURE, FIRST_STEP, defaultScale, releasedPollutants, projectDispersion, type TimelineScale, type TimelineProject, type WindSource, LAST_STEP, PLAYBACK_INTERVAL_MS, TIMELINE_DAYS, TIMELINE_HORIZON_DAYS, stepLabel, type Dispersion, type Environment, type TimelineData, type TimelineMeasure, type TimelineMode, type TimelineOverlay } from "../lib/timeline";
import { MEDIA, type ReleaseMedium } from "../lib/pollutants";
import Icon from "./Icon";
import { PanelTabs } from "./PanelNavigation";

type Props = {
  scenario: Scenario | null; active: boolean; onOverlay: (overlay: TimelineOverlay | null) => void;
  onFocus: (latitude: number, longitude: number) => void; onEdit: (project: Project) => void; onBuild: () => void;
};
const number = (n: number | null) => n === null ? "Unknown" : n.toLocaleString(undefined, { maximumFractionDigits: 2, maximumSignificantDigits: 4 });

export default function TimelinePanel({ scenario, active, onOverlay, onFocus, onEdit, onBuild }: Props) {
  const revision = scenario ? JSON.stringify([scenario.id, scenario.projects.map((p) => [p.id, p.updatedAt])]) : "";
  const [loaded, setLoaded] = useState<{ revision: string; value: TimelineData } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [medium, setMedium] = useState<ReleaseMedium>("air");
  const [environment, setEnvironment] = useState(DEFAULT_ENVIRONMENT);
  const [envDraft, setEnvDraft] = useState(Object.fromEntries(Object.entries(DEFAULT_ENVIRONMENT).map(([k, v]) => [k, String(v)])));
  const [pollutant, setPollutant] = useState("co2");
  const [mode, setMode] = useState<TimelineMode>("added");
  const [airMeasure, setAirMeasure] = useState<TimelineMeasure>(DEFAULT_AIR_MEASURE);
  const measure = medium === "air" ? airMeasure : "concentration";
  const exposure = measure === "exposure";
  // null follows the measure's default; once chosen, the viewer's scale choice is kept.
  const [scaleChoice, setScaleChoice] = useState<TimelineScale | null>(null);
  const scale = scaleChoice ?? defaultScale(medium, measure);
  const [step, setStep] = useState(FIRST_STEP);
  const days = TIMELINE_DAYS[step];
  const [playing, setPlaying] = useState(false);
  const [dispersion, setDispersion] = useState(DEFAULT_DISPERSION);
  // null follows the default: each building's local climate wind when the world has it.
  const [windChoice, setWindChoice] = useState<WindSource | null>(null);
  const [draft, setDraft] = useState(Object.fromEntries(Object.entries(DEFAULT_DISPERSION).map(([k, v]) => [k, String(v)])));
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const data = loaded?.revision === revision ? loaded.value : null;
  const initialPollutantWorld = useRef<string | null>(null);
  useEffect(() => {
    if (!active || !scenario) return;
    const ctrl = new AbortController();
    setError(null);
    api.timeline(scenario.id, ctrl.signal).then((value) => {
      if (!ctrl.signal.aborted) setLoaded({ revision, value });
    }).catch((e) => { if (!ctrl.signal.aborted) setError(String(e.message ?? e)); });
    return () => ctrl.abort();
  }, [active, revision, scenario?.id, retry]);
  useEffect(() => { setStep(FIRST_STEP); setPlaying(false); setPollutant("co2"); setMedium("air"); setMode("added"); setAirMeasure(DEFAULT_AIR_MEASURE); setScaleChoice(null); setWindChoice(null); initialPollutantWorld.current = null; }, [scenario?.id]);
  // Only offer environments and pollutants that this world's buildings actually release.
  const released = useMemo(() => releasedPollutants(data?.projects ?? []), [data]);
  const mediaOptions = (Object.keys(MEDIA) as ReleaseMedium[]).filter((m) => released[m]?.length);
  const options = released[medium] ?? [];
  const choose = useCallback((preferred?: ReleaseMedium) => {
    const available = (Object.keys(MEDIA) as ReleaseMedium[]).filter((m) => released[m]?.length);
    const next = preferred && available.includes(preferred) ? preferred : available[0];
    if (!next || !data) return;
    const list = released[next]!;
    // Prefer a pollutant with a known, nonzero rate so the first view has something to show.
    const known = list.filter((key) => data.projects.some((p) => (dailyEmission(p, key, next) ?? 0) > 0));
    setMedium(next); setMode("added");
    setPollutant(next === "air" && known.includes("co2") ? "co2" : known[0] ?? list[0]);
  }, [data, released]);
  useEffect(() => {
    if (!data || !scenario) return;
    if (initialPollutantWorld.current !== scenario.id) {
      initialPollutantWorld.current = scenario.id;
      choose("air");
    } else if (!released[medium]?.includes(pollutant)) {
      // A building edit removed the selected release; move to one that still exists.
      setPlaying(false); choose(medium);
    }
  }, [data, scenario, released, medium, pollutant, choose]);
  useEffect(() => {
    const first = scenario?.projects[0];
    if (active && first) onFocus(first.latitude, first.longitude);
    // Focus once when entering a world, without interrupting panning or playback after edits.
  }, [active, scenario?.id, onFocus]);
  useEffect(() => { if (!active || !data) setPlaying(false); }, [active, data]);
  useEffect(() => {
    if (!playing || !active || !data) return;
    if (step >= LAST_STEP) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setStep((m) => Math.min(LAST_STEP, m + 1)), PLAYBACK_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [playing, active, data, step]);
  const displayName = (key: string) => pollutantLabel(key, data?.projects.flatMap((p) => p.emissions).find((e) => pollutantKey(e.pollutant) === key)?.pollutant);
  const label = displayName(pollutant), unit = impactUnit(medium, measure), massUnit = medium === "climate" ? "kgCO₂e" : "kg";
  const hasBaseline = medium === "air" && (pollutant === "pm25" || pollutant === "pm10");
  const rates = useMemo(() => data?.projects.map((p) => dailyEmission(p, pollutant, medium)) ?? [], [data, pollutant, medium]);
  const emitted = knownTotal(rates, days);
  const unresolved = data?.projects.filter((p, i) => rates[i] !== null && rates[i] !== 0 && (
    medium === "freshwater" && (!p.river?.cells.length || p.river.cells.some((c) => c.flowM3PerSecond === null)) ||
    medium === "marine" && p.marineRelease?.latitude == null ||
    medium === "soil" && !data.cells.some((c) => c.surface === "land"))) ?? [];
  const partial = emitted.known < emitted.total || unresolved.length > 0;
  const hasLocalWind = !!data?.projects.some((p) => p.wind);
  const windSource: WindSource = windChoice ?? (hasLocalWind ? "local" : "custom");
  // Buildings releasing this air pollutant, each with the wind its releases drift with.
  const airSources = medium === "air" && data ? data.projects.filter((_, i) => (rates[i] ?? 0) > 0)
    .map((project) => ({ project, wind: projectDispersion(project, dispersion, windSource), local: windSource === "local" && !!project.wind })) : [];
  const cells = useMemo(() => active && data ? impactCells(data, pollutant, days, dispersion, mode, medium, environment, measure, windSource) : [], [active, data, pollutant, days, dispersion, mode, medium, environment, measure, windSource]);
  // The five-year scale keeps colours comparable during playback; the step scale fits the frame shown.
  const horizonPeak = useMemo(() => !active || !data || scale !== "horizon" ? 0
    : impactCells(data, pollutant, TIMELINE_HORIZON_DAYS, dispersion, mode, medium, environment, measure, windSource).reduce((max, c) => Math.max(max, c.value ?? 0), 0),
  [active, data, scale, pollutant, dispersion, mode, medium, environment, measure, windSource]);
  const max = useMemo(() => {
    const peak = scale === "horizon" ? horizonPeak : cells.reduce((max, c) => Math.max(max, c.value ?? 0), 0);
    return peak > 0 ? peak * 1.05 : 1;
  }, [scale, horizonPeak, cells]);
  const hasReleases = mediaOptions.length > 0;
  const overlay = useMemo(() => active && data && !error && hasReleases ? { cells, pollutant: label, mode, measure, scale, days, partial, max, medium, unit } : null, [active, data, error, hasReleases, cells, label, mode, measure, scale, days, partial, max, medium, unit]);
  useEffect(() => { onOverlay(overlay); }, [overlay, onOverlay]);
  useEffect(() => () => onOverlay(null), [onOverlay]);
  const peak = cells.reduce<number | null>((p, c) => c.added === null ? p : Math.max(p ?? 0, c.added), null);
  const changeMedium = (next: ReleaseMedium) => { setPlaying(false); setSettingsError(null); choose(next); };

  if (!scenario || !scenario.projects.length) return <section className="panel timeline-empty">
    <Icon name="timeline" size={32} /><h2>Every project leaves a trace</h2>
    <p className="muted">Place a building, then explore how its emissions and resource use develop over time.</p>
    <button className="primary" onClick={onBuild}><Icon name="plus" size={16} />Add a building</button>
  </section>;
  if (error) return <section className="panel"><p className="error" role="alert">{error}</p><button onClick={() => setRetry((r) => r + 1)}>Retry timeline</button></section>;
  if (!data) return <section className="panel" role="status">Loading project impacts and receiving environments…</section>;
  if (!hasReleases) return <section className="panel timeline-empty">
    <Icon name="timeline" size={32} /><h2>No releases to show</h2>
    <p className="muted">None of the buildings in this world declare a pollutant or emission rate. Add releases in the building editor to see how they spread over time.</p>
    <ul className="list timeline-projects">{scenario.projects.map((p) => <li key={p.id}><button className="link" onClick={() => onFocus(p.latitude, p.longitude)}><Icon name="pin" size={16} /><span>{p.name}</span></button><button className="ghost" onClick={() => onEdit(p)}>Edit</button></li>)}</ul>
  </section>;

  return <>
    <section className="panel timeline-controls">
      <div className="panel-head"><h2>Environment over time</h2><span className="timeline-badge">Illustrative</span></div>
      <label className="timeline-field">Environment<select value={medium} onChange={(e) => changeMedium(e.target.value as ReleaseMedium)}>
        {mediaOptions.map((key) => <option key={key} value={key}>{MEDIA[key]}</option>)}
      </select></label>
      <label className="timeline-field">Pollutant<select value={pollutant} onChange={(e) => { setPlaying(false); setPollutant(e.target.value); setMode("added"); }}>
        {options.map((p) => <option key={p} value={p}>{displayName(p)}</option>)}
      </select></label>
      {medium === "air" && <PanelTabs label="Air impact measure" value={airMeasure} onChange={(value) => { setPlaying(false); setAirMeasure(value); }} options={[
        { value: "exposure", label: "Accumulated exposure" }, { value: "concentration", label: "Concentration now" },
      ]} />}
      <PanelTabs label="Colour scale" value={scale} onChange={(value) => setScaleChoice(value)} options={[
        { value: "step", label: "Fit this step" }, { value: "horizon", label: "Fixed five-year" },
      ]} />
      {hasBaseline && <PanelTabs label="Environmental view" value={mode} onChange={setMode} options={[
        { value: "baseline", label: "Baseline" }, { value: "added", label: "Added impact" }, { value: "combined", label: "Combined" },
      ]} />}
      <p className="timeline-baseline small muted">{exposure && "Exposure adds up concentration over elapsed time (µg·day/m³). "}{scale === "horizon"
          ? "Colours use the five-year peak, so early values are faint but steps are comparable. "
          : "Colours fit the step shown, so compare steps by the legend maximum, not by colour. "}{medium === "climate"
        ? "CO₂e is a climate accounting measure. The map shows cumulative contributions at each building, including any declared indirect emissions; it does not predict a local CO₂ concentration or warming."
        : hasBaseline ? `${data.baseline.label} · ${data.baseline.resolution}. ${exposure ? "Baseline exposure holds this historical mean constant." : "Historical reference, not live conditions."}`
        : `No compatible measured ${label} background is available here. The map shows illustrative added impact only; existing pollution remains unknown.`}</p>
      <div className="timeline-time"><span className="eyebrow">TIME SINCE OPERATION BEGINS</span><strong>{timeLabel(days)}</strong></div>
      <div className="timeline-player">
        <button className="primary icon-button" disabled={!emitted.known && mode !== "baseline"} aria-label={playing ? "Pause timeline" : "Play timeline"} onClick={() => { if (step >= LAST_STEP) setStep(FIRST_STEP); setPlaying((p) => !p); }}><Icon name={playing ? "pause" : "play"} size={18} /></button>
        <button className="icon-button" aria-label="Previous time step" disabled={step <= FIRST_STEP} onClick={() => { setPlaying(false); setStep((m) => Math.max(FIRST_STEP, m - 1)); }}><Icon name="arrow" size={14} style={{ transform: "rotate(180deg)" }} /></button>
        <input type="range" min={FIRST_STEP} max={LAST_STEP} step="1" value={step} aria-label="Time since operation begins" aria-valuetext={timeLabel(days)} onChange={(e) => { setPlaying(false); setStep(Number(e.target.value)); }} />
        <button className="icon-button" aria-label="Next time step" disabled={step >= LAST_STEP} onClick={() => { setPlaying(false); setStep((m) => Math.min(LAST_STEP, m + 1)); }}><Icon name="arrow" size={14} /></button>
        <button className="icon-button" aria-label="Reset timeline" onClick={() => { setPlaying(false); setStep(FIRST_STEP); }}><Icon name="reset" size={18} /></button>
      </div>
      <div className="timeline-stops">{TIMELINE_DAYS.map((d, index) => <button key={d} aria-pressed={step === index} onClick={() => { setPlaying(false); setStep(index); }}>{stepLabel(d)}</button>)}</div>
      <p className="small muted">Starts at day 0, when operation begins. Each step then goes further than the last, from hours to weeks, months and years, ending at 5 years (1,826 days).</p>
      {medium === "air" && mode !== "baseline" && <details className="timeline-transport small muted">
        <summary>{windSummary(airSources.length ? airSources.map((s) => s.wind) : [dispersion], windSource)}</summary>
        <p>{crossingNote(airSources.length ? airSources.map((s) => s.wind) : [dispersion])}
          {windSource === "local" && " Local wind is the long-term net drift at each building (NASA POWER, MERRA-2, 10 m annual mean). Winds that change direction cancel out, so it is slower than the average wind; day-to-day weather is not modelled."}
          {exposure ? " Accumulated exposure continues to grow as releases continue. It integrates the concentration experienced at each location since operation began." : " The map shows concentration at this time; emitted mass below is cumulative."}
          {" Change wind under Wind & mixing assumptions."}</p>
        {airSources.some((s) => windSource === "local" && !s.local) && <p className="warn">Local wind is unavailable for {airSources.filter((s) => !s.local).map((s) => s.project.name).join(", ")}; the assumed wind is used there.</p>}
      </details>}
      <div className="timeline-metrics">
        <div><span>{label} emitted</span><strong>{number(emitted.value)} <small>{massUnit}</small></strong><small>{partial ? `Known subtotal · ${emitted.known}/${emitted.total} projects` : "Cumulative since day 0"}</small></div>
        <div><span>{medium === "climate" ? "Largest source-cell contribution" : exposure ? "Peak added exposure" : "Peak added concentration"}</span><strong>{number(peak)} <small>{unit}</small></strong><small>{`Within displayed cells${partial ? " · partial estimate" : ""}`}</small></div>
      </div>
      {emitted.known < emitted.total && <p className="warn small">{emitted.known} of {emitted.total} projects have complete {label} inputs. Other contributions are unknown. Add rates and operating hours in the building editor.</p>}
      {unresolved.length > 0 && <p className="warn small">Receiving environment or flow is unavailable for {unresolved.map((p) => p.name).join(", ")}. Their cumulative releases are included, but affected concentrations are unknown. See Project contributions.</p>}
    </section>
    <section className="panel">
      <details className="timeline-details"><summary>{medium === "air" ? "Wind & mixing assumptions" : medium === "climate" ? "How CO₂e is counted" : "Transport & mixing assumptions"}</summary>
        <p className="muted small">{MODEL_NOTES[medium]}</p>
        {medium === "air" && hasLocalWind && <PanelTabs label="Wind" value={windSource} onChange={(value) => { setPlaying(false); setWindChoice(value); }} options={[
          { value: "local", label: "Local climate wind" }, { value: "custom", label: "Custom wind" },
        ]} />}
        {medium === "air" && windSource === "local" && <ul className="list timeline-winds">{(airSources.length ? airSources.map((s) => s.project) : data.projects).map((p) => <li key={p.id}>
          <strong>{p.name}</strong><small>{localWindLabel(p)}</small>
        </li>)}</ul>}
        {medium !== "climate" && <form onSubmit={(e) => {
          e.preventDefault();
          const entries = medium === "air" ? Object.entries(draft) : ENVIRONMENT_FIELDS[medium].map(([key]) => [key, envDraft[key]]);
          const parsed = { ...(medium === "air" ? {} : environment), ...Object.fromEntries(entries.map(([k, v]) => [k, v.trim() === "" ? NaN : Number(v)])) };
          if (medium === "air" ? !validDispersion(parsed as Dispersion) : !validEnvironment(parsed as Environment)) { setSettingsError("Enter values within the ranges shown."); return; }
          setSettingsError(null); setPlaying(false);
          if (medium === "air") setDispersion(parsed as Dispersion); else setEnvironment(parsed as Environment);
        }}>
          <div className="timeline-assumptions">{(medium === "air" ? AIR_FIELDS.filter(([key]) => windSource === "custom" || !WIND_FIELDS.includes(key)) : ENVIRONMENT_FIELDS[medium]).map(([key, name, unit, min, max]) => <label key={key}>{name}<input aria-label={name} type="number" required min={min} max={max} step="any" value={(medium === "air" ? draft : envDraft)[key]} onChange={(e) => medium === "air" ? setDraft({ ...draft, [key]: e.target.value }) : setEnvDraft({ ...envDraft, [key]: e.target.value })} /><small>{unit} · {min}–{max}</small></label>)}</div>
          {settingsError && <p className="error small" role="alert">{settingsError}</p>}
          <button type="submit">Apply assumptions</button>
        </form>}
        <p className="small muted">These are prototype estimates, not validated environmental forecasts. All rates remain constant. No chemical reactions, degradation, treatment or ecological toxicity are predicted. The local map is bounded; cumulative releases also include mass that travels outside it.</p>

      </details>
    </section>
    <section className="panel">
      <details className="timeline-details"><summary>Resource use to this point</summary>
      <div className="timeline-metrics">{([['electricityKwhPerDay', 'Electricity used', 'kWh'], ['waterM3PerDay', 'Water used', 'm³']] as const).map(([key, label, unit]) => {
        const total = knownTotal(data.projects.map((p) => p[key]), days);
        return <div key={key}><span>{label}</span><strong>{number(total.value)} <small>{unit}</small></strong><small>{total.known < total.total ? `Known subtotal · ${total.known}/${total.total} projects` : "Cumulative use"}</small></div>;
      })}</div>
      <p className="muted small">Consumption totals do not predict local water depletion or indirect electricity emissions. Site capacity margins are shown on each building.</p>
      </details>
    </section>
    <section className="panel"><details className="timeline-details"><summary>Project contributions ({data.projects.length})</summary><ul className="list timeline-projects">{data.projects.map((p) => {
      const rate = dailyEmission(p, pollutant, medium);
      return <li key={p.id}><button className="link" onClick={() => onFocus(p.latitude, p.longitude)}><Icon name="pin" size={16} /><span>{p.name}<small>{rate === null ? "Emission rate unknown" : `${number(rate)} ${massUnit}/day · ${label}`}</small>{medium === "freshwater" && <small>{p.river?.note ?? "No freshwater release declared."}</small>}{medium === "marine" && <small>{p.marineRelease?.note ?? "No marine release declared."}</small>}</span></button><button className="ghost" onClick={() => { const project = scenario.projects.find((x) => x.id === p.id); if (project) onEdit(project); }}>Edit</button></li>;
    })}</ul></details></section>
  </>;
}

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const speed = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 });
const compass = (degrees: number) => COMPASS[Math.round(degrees / 22.5) % 16];
const fromLabel = (d: Dispersion) => d.windSpeed === 0 ? "calm" : `from ${compass(d.windFrom)} (${Math.round(d.windFrom)}°) at ${speed(d.windSpeed)} m/s`;
function windSummary(winds: Dispersion[], source: WindSource): string {
  const distinct = [...new Map(winds.map((w) => [`${w.windSpeed}|${w.windFrom}`, w])).values()];
  const prefix = source === "local" ? "Local climate wind" : "Assumed wind";
  if (distinct.length === 1) return `${prefix}: ${fromLabel(distinct[0])}${distinct[0].windSpeed > 0 ? ` · ${Math.round(distinct[0].windSpeed * 86.4)} km/day` : ""}`;
  const speeds = distinct.map((w) => w.windSpeed);
  return `${prefix} varies by building: ${speed(Math.min(...speeds))}–${speed(Math.max(...speeds))} m/s`;
}
function crossingNote(winds: Dispersion[]): string {
  const fastest = Math.max(...winds.map((w) => w.windSpeed));
  return fastest === 0 ? "No wind transport; diffusion still spreads releases."
    : `At ${speed(fastest)} m/s releases cross the ~50 km local map in about ${speed(50000 / fastest / 3600)} hours; after that, local concentrations settle.`;
}
function localWindLabel(p: TimelineProject): string {
  const w = p.wind;
  if (!w) return "Local wind unavailable: the assumed wind is used.";
  const drift = w.fromDegrees === null || w.speed === 0 ? "no net drift" : `net drift from ${compass(w.fromDegrees)} (${Math.round(w.fromDegrees)}°) at ${speed(w.speed)} m/s`;
  return `${drift} · average speed ${speed(w.meanSpeed)} m/s · ${w.source}, grid cell ${number(w.gridLatitude)}°, ${number(w.gridLongitude)}°`;
}
const WIND_FIELDS = ["windSpeed", "windFrom"];
const AIR_FIELDS: [string, string, string, number, number][] = [
  ["windSpeed", "Wind speed", "m/s", 0, 30], ["windFrom", "Wind from", "° clockwise from north", 0, 360],
  ["mixingHeight", "Mixing height", "m", 50, 3000], ["diffusion", "Horizontal diffusion", "m²/s", 10, 2000],
];
const MODEL_NOTES: Record<ReleaseMedium, string> = {
  air: "Each building's releases drift with a constant wind: by default its long-term local climate wind (NASA POWER MERRA-2, ~50 km grid), or one custom wind for all. Gaussian puffs and uniform vertical mixing; 750 m initial spread. No terrain, plume rise, deposition or chemistry. CO₂ is a local mass increment, not a climate projection. Neither wind is a weather forecast.",
  soil: "Cumulative release mixed through a fixed soil layer with a Gaussian footprint. Land cells only, using a simplified coastline. No runoff, leaching or decay. Radius is one standard deviation, not a hard boundary. No soil baseline is assumed.",
  freshwater: "Assumes an outfall in the nearest mapped river within 10 km. Follows HydroRIVERS downstream connections for up to 30 km, with complete mixing and long-term average river flow. Speed controls arrival time. It does not simulate lakes, tides, decay or storage; an actual discharge connection is unverified.",
  marine: "Assumes an outfall in the nearest sea cell within 20 km. Gaussian puffs use a separate constant current and mixed water depth; only sea cells are displayed. Simplified coastline, no tides, chemistry or shoreline reflection. This is not a hydrodynamic model; an actual discharge connection is unverified.",
  climate: "Declared kgCO₂e/hour × operating hours/day × elapsed days. Existing annotated CO2e names are recognised automatically. Each source cell adds its buildings’ declared totals. Physical CO₂ and CO₂e remain separate, with no assumed conversion or double counting. Scope boundaries remain those of the entered rate.",
};
