import type { Project, Scenario, ScenarioSummary } from "../lib/api";
import { typeColour, typeLabel } from "../lib/projectTypes";

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

/** Compact scenario switcher for the application header. */
export function ScenarioSelect({
  scenarios,
  scenario,
  onSwitch,
}: Pick<Props, "scenarios" | "scenario" | "onSwitch">) {
  return (
    <select aria-label="World" value={scenario?.id ?? ""} onChange={(e) => onSwitch(e.target.value)}>
      {scenarios.map((s) => (
        <option key={s.id} value={s.id}>
          {s.parentScenarioId ? "↳ " : ""}
          {s.name}
        </option>
      ))}
    </select>
  );
}

export default function ScenarioPanel(props: Props) {
  const { scenarios, scenario } = props;
  const parent = scenario?.parentScenarioId
    ? (scenarios.find((s) => s.id === scenario.parentScenarioId)?.name ?? "a deleted scenario")
    : null;

  return (
    <>
      <section className="panel">
        <h2>{scenario?.name ?? "No world"}</h2>
        {parent && <p className="subtitle">Branched from {parent}</p>}
        <details className="timeline-details"><summary>Manage world</summary><div className="actions scenario-actions">
          <button onClick={props.onCreate}>New</button>
          <button onClick={props.onBranch} disabled={!scenario}>
            Branch
          </button>
          <button onClick={props.onRename} disabled={!scenario}>
            Rename
          </button>
          <button className="danger right" onClick={props.onDelete} disabled={!scenario}>
            Delete
          </button>
        </div></details>
      </section>

      <section className="panel">
        <h3 style={{ marginTop: 0 }}>Projects</h3>
        {scenario && scenario.projects.length === 0 && (
          <p className="muted">No buildings yet. Choose Build to define a building, or use “Add building” on the map.</p>
        )}
        <ul className="list scenario-projects">
          {scenario?.projects.map((p) => (
            <li key={p.id}>
              <button
                className={`link ${p.id === props.selectedProjectId ? "selected" : ""}`}
                onClick={() => props.onSelectProject(p)}
              >
                <span className="dot" style={{ background: `rgb(${typeColour(p.type).join(",")})` }} />
                <span className="result-title">{p.name || typeLabel(p.type)}</span>
                <span className="muted small right">{typeLabel(p.type)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
