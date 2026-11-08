import type { Scenario, ScenarioSummary } from "../lib/api";

type Props = {
  scenarios: ScenarioSummary[];
  scenario: Scenario | null;
  onSwitch: (id: string) => void;
  onCreate: () => void;
  onBranch: () => void;
  onRename: () => void;
  onDelete: () => void;
};

// Action entries share the select with world ids; the prefix cannot collide with a world id.
const ACTION = "action:";

/** Header world switcher: switch worlds, add a new one, or manage the active one. */
export function ScenarioSelect({ scenarios, scenario, onSwitch, onCreate, onBranch, onRename, onDelete }: Props) {
  const actions: Record<string, () => void> = { new: onCreate, branch: onBranch, rename: onRename, delete: onDelete };
  return (
    <select
      aria-label="World"
      value={scenario?.id ?? ""}
      onChange={(e) => {
        const value = e.target.value;
        // The select stays on the active world; an action only runs its prompt.
        if (value.startsWith(ACTION)) actions[value.slice(ACTION.length)]?.();
        else onSwitch(value);
      }}
    >
      {!scenario && <option value="" disabled>No world</option>}
      {scenarios.length > 0 && (
        <optgroup label="Worlds">
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.parentScenarioId ? "↳ " : ""}
              {s.name}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label="Manage">
        <option value={`${ACTION}new`}>＋ New world…</option>
        {scenario && <option value={`${ACTION}branch`}>Branch this world…</option>}
        {scenario && <option value={`${ACTION}rename`}>Rename this world…</option>}
        {scenario && <option value={`${ACTION}delete`}>Delete this world…</option>}
      </optgroup>
    </select>
  );
}
