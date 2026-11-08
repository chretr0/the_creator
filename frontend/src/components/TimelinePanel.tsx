import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Project, type Scenario } from "../lib/api";
import { DEFAULT_DISPERSION, dailyEmission, impactCells, knownTotal, DEFAULT_ENVIRONMENT, ENVIRONMENT_FIELDS, validEnvironment, impactUnit, pollutantKey, pollutantLabel, timeLabel, validDispersion,
  type Dispersion, type Environment, type TimelineData, type TimelineMode, type TimelineOverlay } from "../lib/timeline";
import { MEDIA, pollutantsFor, releaseMedium, type ReleaseMedium } from "../lib/pollutants";
import Icon from "./Icon";
import { PanelTabs } from "./PanelNavigation";

type Props = {
  scenario: Scenario | null; active: boolean; onOverlay: (overlay: TimelineOverlay | null) => void;
  onFocus: (latitude: number, longitude: number) => void; onEdit: (project: Project) => void; onBuild: () => void;
};
const number = (n: number | null) => n === null ? "Unknown" : n.toLocaleString(undefined, { maximumFractionDigits: 2, maximumSignificantDigits: 4 });
const stepToDays = (step: number) => step === 0 ? 0 : step >= 1000 ? 365 : Math.expm1(step / 1000 * Math.log1p(365 * 24)) / 24;
const daysToStep = (days: number) => Math.log1p(days * 24) / Math.log1p(365 * 24) * 1000;

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
  const [days, setDays] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [dispersion, setDispersion] = useState(DEFAULT_DISPERSION);
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
  useEffect(() => { setDays(0); setPlaying(false); setPollutant("co2"); setMedium("air"); setMode("added"); initialPollutantWorld.current = null; }, [scenario?.id]);
  useEffect(() => {
    if (!data?.projects.length || !scenario || initialPollutantWorld.current === scenario.id) return;
    initialPollutantWorld.current = scenario.id;
    const known = data.projects.flatMap((p) => p.emissions.filter((e) => e.kgPerDay !== null));
    const first = known.find((e) => pollutantKey(e.pollutant) === "co2") ?? known[0];
    if (first) { setPollutant(pollutantKey(first.pollutant)); setMedium(releaseMedium(first.pollutant, first.medium)); }

  }, [data, scenario]);
  useEffect(() => {
    const first = scenario?.projects[0];
    if (active && first) onFocus(first.latitude, first.longitude);
    // Focus once when entering a world, without interrupting panning or playback after edits.
  }, [active, scenario?.id, onFocus]);
  useEffect(() => { if (!active || !data) setPlaying(false); }, [active, data]);
  useEffect(() => {
    if (!playing || !active) return;
    const timer = window.setInterval(() => setDays((d) => stepToDays(Math.min(1000, daysToStep(d) + 12))), 200);
    return () => window.clearInterval(timer);
  }, [playing, active]);
  useEffect(() => { if (days >= 365) setPlaying(false); }, [days]);
  const options = useMemo(() => [...new Set([...pollutantsFor(medium).map((p) => p.id), ...(data?.projects.flatMap((p) => p.emissions.filter((e) => releaseMedium(e.pollutant, e.medium) === medium).map((e) => pollutantKey(e.pollutant))) ?? [])])], [data, medium]);
  const displayName = (key: string) => pollutantLabel(key, data?.projects.flatMap((p) => p.emissions).find((e) => pollutantKey(e.pollutant) === key)?.pollutant);
  const label = displayName(pollutant), unit = impactUnit(medium), massUnit = medium === "climate" ? "kgCO₂e" : "kg";
  const hasBaseline = medium === "air" && (pollutant === "pm25" || pollutant === "pm10");
  const rates = useMemo(() => data?.projects.map((p) => dailyEmission(p, pollutant, medium)) ?? [], [data, pollutant, medium]);
  const emitted = knownTotal(rates, days);
  const unresolved = data?.projects.filter((p, i) => rates[i] !== null && rates[i] !== 0 && (
    medium === "freshwater" && (!p.river?.cells.length || p.river.cells.some((c) => c.flowM3PerSecond === null)) ||
    medium === "marine" && p.marineRelease?.latitude == null ||
    medium === "soil" && !data.cells.some((c) => c.surface === "land"))) ?? [];
  const partial = emitted.known < emitted.total || unresolved.length > 0;
  const cells = useMemo(() => active && data ? impactCells(data, pollutant, days, dispersion, mode, medium, environment) : [], [active, data, pollutant, days, dispersion, mode, medium, environment]);
  // Fixed horizon scale keeps colours comparable during playback.
  const max = useMemo(() => {
    if (!data) return 1;
    const peak = impactCells(data, pollutant, 365, dispersion, mode, medium, environment).reduce((max, c) => Math.max(max, c.value ?? 0), 0);
    return peak > 0 ? peak * 1.05 : 1;
  }, [data, pollutant, dispersion, mode, medium, environment]);
  const overlay = useMemo(() => active && data && !error ? { cells, pollutant: label, mode, days, partial, max, medium, unit } : null, [active, data, error, cells, label, mode, days, partial, max, medium, unit]);
  useEffect(() => { onOverlay(overlay); }, [overlay, onOverlay]);
  useEffect(() => () => onOverlay(null), [onOverlay]);
  const peak = cells.reduce<number | null>((p, c) => c.added === null ? p : Math.max(p ?? 0, c.added), null);
  const changeMedium = (next: ReleaseMedium) => {
    setMedium(next); setMode("added"); setPlaying(false); setSettingsError(null);
    const first = data?.projects.flatMap((p) => p.emissions).find((e) => releaseMedium(e.pollutant, e.medium) === next && e.kgPerDay !== null);
    setPollutant(first ? pollutantKey(first.pollutant) : pollutantsFor(next)[0].id);
  };

  if (!scenario || !scenario.projects.length) return <section className="panel timeline-empty">
    <Icon name="timeline" size={32} /><h2>Every project leaves a trace</h2>
    <p className="muted">Place a building, then explore how its emissions and resource use develop over time.</p>
    <button className="primary" onClick={onBuild}><Icon name="plus" size={16} />Add a building</button>
  </section>;
  if (error) return <section className="panel"><p className="error" role="alert">{error}</p><button onClick={() => setRetry((r) => r + 1)}>Retry timeline</button></section>;
  if (!data) return <section className="panel" role="status">Loading project impacts and receiving environments…</section>;

  return <>
    <section className="panel timeline-controls">
      <div className="panel-head"><h2>Environment over time</h2><span className="timeline-badge">Illustrative</span></div>
      <label className="timeline-field">Environment<select value={medium} onChange={(e) => changeMedium(e.target.value as ReleaseMedium)}>
        {Object.entries(MEDIA).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </select></label>
      <label className="timeline-field">Pollutant<select value={pollutant} onChange={(e) => { setPlaying(false); setPollutant(e.target.value); setMode("added"); }}>
        {options.map((p) => <option key={p} value={p}>{displayName(p)}</option>)}
      </select></label>
      {hasBaseline && <PanelTabs label="Environmental view" value={mode} onChange={setMode} options={[
        { value: "baseline", label: "Baseline" }, { value: "added", label: "Added impact" }, { value: "combined", label: "Combined" },
      ]} />}
      <p className="timeline-baseline small muted">{medium === "climate"
        ? "CO₂e is a climate accounting measure. The map shows cumulative contributions at each building, including any declared indirect emissions; it does not predict a local CO₂ concentration or warming."
        : hasBaseline ? `${data.baseline.label} · ${data.baseline.resolution}. Historical reference, not live conditions.`
        : `No compatible measured ${label} background is available here. The map shows illustrative added impact only; existing pollution remains unknown.`}</p>
      <div className="timeline-time"><span className="eyebrow">TIME SINCE OPERATION BEGINS</span><strong>{timeLabel(days)}</strong></div>
      <div className="timeline-player">
        <button className="primary icon-button" disabled={!emitted.known && mode !== "baseline"} aria-label={playing ? "Pause timeline" : "Play timeline"} onClick={() => { if (days >= 365) setDays(0); setPlaying((p) => !p); }}><Icon name={playing ? "pause" : "play"} size={18} /></button>
        <input type="range" min="0" max="1000" step="1" value={daysToStep(days)} aria-label="Time since operation begins" aria-valuetext={timeLabel(days)} onChange={(e) => { setPlaying(false); setDays(stepToDays(Number(e.target.value))); }} />
        <button className="icon-button" aria-label="Reset timeline" onClick={() => { setPlaying(false); setDays(0); }}><Icon name="reset" size={18} /></button>
      </div>
      <div className="timeline-stops">{[[0, "Before"], [1 / 24, "1 hour"], [1, "1 day"], [7, "1 week"], [30, "1 month"], [365, "1 year"]].map(([d, label]) => <button key={d} aria-pressed={days === d} onClick={() => { setPlaying(false); setDays(Number(d)); }}>{label}</button>)}</div>
      <p className="small muted">All placed projects start at day 0. Declared daily operating hours are averaged across each day.</p>
      <div className="timeline-metrics">
        <div><span>{label} emitted</span><strong>{number(emitted.value)} <small>{massUnit}</small></strong><small>{partial ? `Known subtotal · ${emitted.known}/${emitted.total} projects` : "Cumulative since day 0"}</small></div>
        <div><span>{medium === "climate" ? "Largest source-cell contribution" : "Peak added concentration"}</span><strong>{number(peak)} <small>{unit}</small></strong><small>{`Within displayed cells${partial ? " · partial estimate" : ""}`}</small></div>
      </div>
      {emitted.known < emitted.total && <p className="warn small">{emitted.known} of {emitted.total} projects have complete {label} inputs. Other contributions are unknown. Add rates and operating hours in the building editor.</p>}
      {unresolved.length > 0 && <p className="warn small">Receiving environment or flow is unavailable for {unresolved.map((p) => p.name).join(", ")}. Their cumulative releases are included, but affected concentrations are unknown. See Project contributions.</p>}
    </section>
    <section className="panel">
      <details className="timeline-details"><summary>{medium === "air" ? "Wind & mixing assumptions" : medium === "climate" ? "How CO₂e is counted" : "Transport & mixing assumptions"}</summary>
        <p className="muted small">{MODEL_NOTES[medium]}</p>
        {medium !== "climate" && <form onSubmit={(e) => {
          e.preventDefault();
          const entries = medium === "air" ? Object.entries(draft) : ENVIRONMENT_FIELDS[medium].map(([key]) => [key, envDraft[key]]);
          const parsed = { ...(medium === "air" ? {} : environment), ...Object.fromEntries(entries.map(([k, v]) => [k, v.trim() === "" ? NaN : Number(v)])) };
          if (medium === "air" ? !validDispersion(parsed as Dispersion) : !validEnvironment(parsed as Environment)) { setSettingsError("Enter values within the ranges shown."); return; }
          setSettingsError(null); setPlaying(false);
          if (medium === "air") setDispersion(parsed as Dispersion); else setEnvironment(parsed as Environment);
        }}>
          <div className="timeline-assumptions">{(medium === "air" ? AIR_FIELDS : ENVIRONMENT_FIELDS[medium]).map(([key, name, unit, min, max]) => <label key={key}>{name}<input aria-label={name} type="number" required min={min} max={max} step="any" value={(medium === "air" ? draft : envDraft)[key]} onChange={(e) => medium === "air" ? setDraft({ ...draft, [key]: e.target.value }) : setEnvDraft({ ...envDraft, [key]: e.target.value })} /><small>{unit} · {min}–{max}</small></label>)}</div>
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

const AIR_FIELDS: [string, string, string, number, number][] = [
  ["windSpeed", "Wind speed", "m/s", 0, 30], ["windFrom", "Wind from", "° clockwise from north", 0, 360],
  ["mixingHeight", "Mixing height", "m", 50, 3000], ["diffusion", "Horizontal diffusion", "m²/s", 10, 2000],
];
const MODEL_NOTES: Record<ReleaseMedium, string> = {
  air: "Constant assumed wind, Gaussian puffs and uniform vertical mixing; 750 m initial spread. No terrain, plume rise, deposition or chemistry. CO₂ is a local mass increment, not a climate projection. These settings are not measured weather.",
  soil: "Cumulative release mixed through a fixed soil layer with a Gaussian footprint. Land cells only, using a simplified coastline. No runoff, leaching or decay. Radius is one standard deviation, not a hard boundary. No soil baseline is assumed.",
  freshwater: "Assumes an outfall in the nearest mapped river within 10 km. Follows HydroRIVERS downstream connections for up to 30 km, with complete mixing and long-term average river flow. Speed controls arrival time. It does not simulate lakes, tides, decay or storage; an actual discharge connection is unverified.",
  marine: "Assumes an outfall in the nearest sea cell within 20 km. Gaussian puffs use a separate constant current and mixed water depth; only sea cells are displayed. Simplified coastline, no tides, chemistry or shoreline reflection. This is not a hydrodynamic model; an actual discharge connection is unverified.",
  climate: "Declared kgCO₂e/hour × operating hours/day × elapsed days. Existing annotated CO2e names are recognised automatically. Each source cell adds its buildings’ declared totals. Physical CO₂ and CO₂e remain separate, with no assumed conversion or double counting. Scope boundaries remain those of the entered rate.",
};
