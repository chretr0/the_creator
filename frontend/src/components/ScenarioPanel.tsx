import type { Project, Scenario, ScenarioSummary } from "../lib/api";
import { PROJECT_TYPE_BY_ID } from "../lib/projectTypes";

type Props = {
  scenarios: ScenarioSummary[];
  scenario: Scenario | null;
  selectedProjectId: string | null;
  onSwitch: (id: string) => void;
  onCreate: () => void;
  onBranch: () => void;
  onRename: () => void;
  onDelete: () => void;
  onSelectProject: (p: Project) => void;
};

export default function ScenarioPanel(props: Props) {
  const { scenarios, scenario } = props;
  const nameOf = (id: string | null) => scenarios.find((s) => s.id === id)?.name;

  return (
    <section className="panel">
      <h2>Scenario</h2>
      <select
        className="scenario-select"
        value={scenario?.id ?? ""}
        onChange={(e) => props.onSwitch(e.target.value)}
      >
        {scenarios.map((s) => (
          <option key={s.id} value={s.id}>
            {s.parentScenarioId ? "↳ " : ""}
            {s.name} ({s.projectCount})
          </option>
        ))}
      </select>
      {scenario && (
        <p className="muted small">
          Baseline <span className="mono">{scenario.baselineRevision}</span> · model{" "}
          <span className="mono">{scenario.modelVersion}</span>
          {scenario.parentScenarioId && <> · branched from {nameOf(scenario.parentScenarioId) ?? "a deleted scenario"}</>}
        </p>
      )}
      <div className="actions">
        <button onClick={props.onCreate}>New</button>
        <button onClick={props.onBranch} disabled={!scenario}>
          Branch
        </button>
        <button onClick={props.onRename} disabled={!scenario}>
          Rename
        </button>
        <button className="danger" onClick={props.onDelete} disabled={!scenario}>
          Delete
        </button>
      </div>

      <h3>Projects</h3>
      {scenario && scenario.projects.length === 0 && (
        <p className="muted small">None yet. Pick a project type above the map, then click a location.</p>
      )}
      <ul className="list">
        {scenario?.projects.map((p) => (
          <li key={p.id}>
            <button
              className={`link ${p.id === props.selectedProjectId ? "selected" : ""}`}
              onClick={() => props.onSelectProject(p)}
            >
              <span className="dot" style={{ background: `rgb(${PROJECT_TYPE_BY_ID[p.type].colour})` }} />
              {p.name || PROJECT_TYPE_BY_ID[p.type].label}
              <span className="mono muted small right">{p.h3Id}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
