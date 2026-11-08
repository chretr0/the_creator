import { BODIES, BODY_IDS, type BodyId } from "../bodies";
import Icon, { type IconName } from "./Icon";

const ICONS: Record<BodyId, IconName> = { earth: "globe", moon: "moon" };
const SWITCH_TITLE: Record<BodyId, string> = { earth: "Switch to Earth", moon: "Switch to the Moon" };

/**
 * Segmented Earth | Moon control for the app header. Each body is its own workspace, so choosing one
 * swaps the whole app. The labels may be hidden on narrow screens; `aria-label` keeps the names.
 */
export default function BodySwitch({ value, onChange }: { value: BodyId; onChange: (id: BodyId) => void }) {
  return (
    <div className="body-switch" role="group" aria-label="World to explore">
      {BODY_IDS.map((id) => {
        const current = id === value;
        return (
          <button
            key={id}
            type="button"
            aria-label={BODIES[id].name}
            aria-pressed={current}
            title={current ? undefined : SWITCH_TITLE[id]}
            onClick={() => {
              if (!current) onChange(id);
            }}
          >
            <Icon name={ICONS[id]} size={16} />
            <span className="body-switch-label">{BODIES[id].name}</span>
          </button>
        );
      })}
    </div>
  );
}
