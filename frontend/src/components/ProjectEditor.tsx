import { useEffect, useState } from "react";
import type { ParamValue, Project, ProjectInput, ProjectType } from "../lib/api";
import { PROJECT_TYPES, PROJECT_TYPE_BY_ID } from "../lib/projectTypes";

type Props = {
  project: Project;
  moving: boolean;
  onSave: (patch: Partial<ProjectInput>) => Promise<void>;
  onMove: () => void;
  onDelete: () => void;
  onClose: () => void;
};

type Draft = {
  name: string;
  type: ProjectType;
  latitude: string;
  longitude: string;
  params: Record<string, string>;
};

function toDraft(p: Project): Draft {
  return {
    name: p.name,
    type: p.type,
    latitude: String(p.latitude),
    longitude: String(p.longitude),
    params: Object.fromEntries(Object.entries(p.parameters).map(([k, v]) => [k, String(v)])),
  };
}

export default function ProjectEditor({ project, moving, onSave, onMove, onDelete, onClose }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(project));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(toDraft(project));
    setError(null);
  }, [project]);

  const def = PROJECT_TYPE_BY_ID[draft.type];

  async function save() {
    const latitude = Number(draft.latitude);
    const longitude = Number(draft.longitude);
    if (draft.latitude.trim() === "" || !Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
      return setError("Latitude must be a number between -90 and 90.");
    }
    if (draft.longitude.trim() === "" || !Number.isFinite(longitude)) {
      return setError("Longitude must be a number.");
    }
    const parameters: Record<string, ParamValue> = {};
    for (const p of def.params) {
      const raw = (draft.params[p.key] ?? "").trim();
      if (raw === "") continue; // unknown stays unknown, never 0
      if (p.kind === "number") {
        const n = Number(raw);
        if (!Number.isFinite(n)) return setError(`${p.label} must be a number.`);
        parameters[p.key] = n;
      } else {
        parameters[p.key] = raw;
      }
    }
    // Only send coordinates when edited, so exact stored values are never re-rounded.
    const patch: Partial<ProjectInput> = { name: draft.name, type: draft.type, parameters };
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

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{draft.name || def.label}</h2>
        <button className="ghost" onClick={onClose} aria-label="Close project">
          ✕
        </button>
      </div>

      <label className="field">
        <span>Name</span>
        <input
          value={draft.name}
          placeholder={def.label}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
      </label>
      <label className="field">
        <span>Type</span>
        <select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value as ProjectType })}>
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
          <input
            className="mono"
            value={draft.latitude}
            onChange={(e) => setDraft({ ...draft, latitude: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Longitude (°)</span>
          <input
            className="mono"
            value={draft.longitude}
            onChange={(e) => setDraft({ ...draft, longitude: e.target.value })}
          />
        </label>
      </div>
      <h3>Assumptions</h3>
      <p className="muted small">Leave blank if unknown.</p>
      {def.params.map((p) => (
        <label className="field" key={p.key} title={p.hint}>
          <span>
            {p.label} {p.unit && <em>({p.unit})</em>}
          </span>
          {p.kind === "select" ? (
            <select
              value={draft.params[p.key] ?? ""}
              onChange={(e) => setDraft({ ...draft, params: { ...draft.params, [p.key]: e.target.value } })}
            >
              <option value="">Not set</option>
              {p.options!.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <input
              inputMode="decimal"
              value={draft.params[p.key] ?? ""}
              placeholder="Not set"
              onChange={(e) => setDraft({ ...draft, params: { ...draft.params, [p.key]: e.target.value } })}
            />
          )}
        </label>
      ))}

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
