import type { Project, Scenario } from "../lib/api";
import { typeColour, typeLabel } from "../lib/projectTypes";
import Icon from "./Icon";

type Props = {
  scenario: Scenario | null;
  /** The placed building open in the New building tab, if any. */
  editingId: string | null;
  onShow: (project: Project) => void;
  onEdit: (project: Project) => void;
  onDelete: (project: Project) => void;
  onNew: () => void;
};

/** Every building placed in the active world, each opening in the Build form for editing. */
export default function BuildingList({ scenario, editingId, onShow, onEdit, onDelete, onNew }: Props) {
  const projects = scenario?.projects ?? [];
  if (!projects.length) return (
    <section className="panel timeline-empty">
      <Icon name="layers" size={32} /><h2>No buildings yet</h2>
      <p className="muted">{scenario ? `Buildings you place in “${scenario.name}” are listed here, ready to edit.` : "Choose or add a world from the Active world menu first."}</p>
      {scenario && <button className="primary" onClick={onNew}><Icon name="plus" size={16} />New building</button>}
    </section>
  );
  return (
    <section className="panel building-list">
      <p className="muted small">{projects.length} {projects.length === 1 ? "building" : "buildings"} in {scenario?.name}. Choose one to see it on the map.</p>
      <ul className="list">
        {projects.map((p) => (
          <li key={p.id} className={p.id === editingId ? "editing" : undefined}>
            <button className="link" title="Show on the map" onClick={() => onShow(p)}>
              <span className="dot" style={{ background: `rgb(${typeColour(p.type).join(",")})` }} />
              <span className="result-title">{p.name || typeLabel(p.type)}<small>{p.id === editingId ? "Editing · " : ""}{typeLabel(p.type)}</small></span>
            </button>
            <div className="building-actions">
              <button type="button" onClick={() => onEdit(p)} aria-label={`Edit ${p.name || typeLabel(p.type)}`}>Edit</button>
              <button type="button" className="ghost danger" onClick={() => onDelete(p)} aria-label={`Delete ${p.name || typeLabel(p.type)}`}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
