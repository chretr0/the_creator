/**
 * The Moon Build workspace panels: choose and configure a building, list the base's buildings, see whether
 * the base can keep its crew alive, and check a site before placing.
 */
import { useState } from "react";
import Icon from "../components/Icon";
import { formatLatLon } from "./geo";
import {
  LIFE_SUPPORT,
  MOON_BUILDINGS,
  MOON_BUILDING_BY_TYPE,
  paramProblem,
  TAG_LABELS,
  TRANSPORT_CASES,
  formatUsd,
  type BaseBalance,
  type BaseSettings,
  type CheckStatus,
  type MoonBuildingType,
  type MoonParam,
  type MoonValues,
  type PlacedMoonBuilding,
  type SiteCheckItem,
  type SiteFacts,
  type Verdict,
} from "./buildings";

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;
const num = (n: number, digits = 1) => n.toLocaleString(undefined, { maximumFractionDigits: digits });
const STATUS_ICON: Record<CheckStatus, string> = { pass: "✓", warn: "!", fail: "✕", unknown: "?", info: "i" };

export function StatusMark({ status }: { status: CheckStatus }) {
  return (
    <span className={`moon-status moon-status-${status}`} aria-label={status}>
      {STATUS_ICON[status]}
    </span>
  );
}

export function TypeBadge({ type }: { type: MoonBuildingType }) {
  const def = MOON_BUILDING_BY_TYPE[type];
  return (
    <span className="moon-type-badge" style={{ color: rgb(def.colour) }}>
      <Icon name={def.icon} size={18} />
    </span>
  );
}

/* ---------------- New / edit building ---------------- */

export type BuildDraft = { type: MoonBuildingType; name: string; raw: Record<string, string> };

export const draftFor = (type: MoonBuildingType, name = "", values?: MoonValues): BuildDraft => ({
  type,
  name,
  raw: Object.fromEntries(
    MOON_BUILDING_BY_TYPE[type].params.map((p) => {
      const v = values ? values[p.key] : p.default;
      return [p.key, v === null || v === undefined ? "" : String(v)];
    }),
  ),
});

/** Typed values to numbers; blank = unknown. Returns null values for invalid entries too (shown inline). */
export function draftValues(draft: BuildDraft): { values: MoonValues; problems: Record<string, string> } {
  const values: MoonValues = {};
  const problems: Record<string, string> = {};
  for (const p of MOON_BUILDING_BY_TYPE[draft.type].params) {
    const raw = draft.raw[p.key] ?? "";
    const problem = paramProblem(p, raw);
    if (problem) problems[p.key] = problem;
    values[p.key] = problem || raw.trim() === "" ? null : Number(raw);
  }
  return { values, problems };
}

function ParamField({ param, raw, problem, onChange }: { param: MoonParam; raw: string; problem?: string; onChange: (v: string) => void }) {
  const id = `moon-param-${param.key}`;
  return (
    <div className="moon-param">
      <label htmlFor={id}>
        <span>{param.label}</span>
        <span className={`moon-tag moon-tag-${param.tag.toLowerCase()}`} title={`${TAG_LABELS[param.tag]}. ${param.note}`}>
          {param.tag === "ASSUMP" ? "Assumption" : TAG_LABELS[param.tag]}
        </span>
      </label>
      <div className="moon-param-input">
        <input
          id={id}
          inputMode="decimal"
          value={raw}
          placeholder="Unknown"
          aria-invalid={!!problem}
          aria-describedby={`${id}-note`}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="moon-unit">{param.unit}</span>
      </div>
      <small id={`${id}-note`} className={problem ? "error" : "muted"}>
        {problem ?? param.note}
      </small>
    </div>
  );
}

export function MoonBuildForm({
  draft,
  onDraft,
  editing,
  target,
  onClearTarget,
  onDone,
  onDelete,
  hasWorld,
}: {
  draft: BuildDraft;
  onDraft: (d: BuildDraft) => void;
  editing: PlacedMoonBuilding | null;
  target: { latitude: number; longitude: number } | null;
  onClearTarget: () => void;
  onDone: () => void;
  onDelete: () => void;
  hasWorld: boolean;
}) {
  const def = MOON_BUILDING_BY_TYPE[draft.type];
  const { problems } = draftValues(draft);
  return (
    <div className="moon-build-form">
      {editing && (
        <div className="edit-banner" role="status">
          <span className="dot" style={{ background: rgb(def.colour) }} />
          <div className="edit-banner-text">
            <span className="eyebrow">EDITING PLACED BUILDING</span>
            <strong>{editing.name || def.label}</strong>
            <small className="muted">Change it here, or click the map to move it</small>
          </div>
          <div className="edit-banner-actions">
            <button type="button" className="ghost danger" onClick={onDelete}>
              Delete
            </button>
            <button type="button" onClick={onDone} title="Stop editing and go back to the building list">
              Done
            </button>
          </div>
        </div>
      )}
      <section className="panel">
        <h2>Building type</h2>
        <div className="moon-type-grid" role="radiogroup" aria-label="Building type">
          {MOON_BUILDINGS.map((b) => (
            <button
              key={b.type}
              type="button"
              role="radio"
              aria-checked={draft.type === b.type}
              disabled={!!editing && draft.type !== b.type}
              onClick={() => onDraft(draftFor(b.type, draft.name))}
              style={{ ["--type-colour" as string]: rgb(b.colour) }}
            >
              <Icon name={b.icon} size={20} />
              <span>{b.label}</span>
            </button>
          ))}
        </div>
        <p className="moon-type-description">
          {def.description} <span className="muted">Example: {def.example}.</span>
        </p>
      </section>
      <section className="panel">
        <h2>Details</h2>
        <div className="moon-param">
          <label htmlFor="moon-building-name">
            <span>Name</span>
          </label>
          <input id="moon-building-name" value={draft.name} placeholder={def.label} maxLength={120} onChange={(e) => onDraft({ ...draft, name: e.target.value })} />
        </div>
        {def.params.map((p) => (
          <ParamField key={p.key} param={p} raw={draft.raw[p.key] ?? ""} problem={problems[p.key]} onChange={(v) => onDraft({ ...draft, raw: { ...draft.raw, [p.key]: v } })} />
        ))}
        <p className="small muted moon-values-note">
          Values start from published figures where they exist. Hover a tag for its source; leave a box blank if it is unknown.
        </p>
      </section>
      <section className="panel moon-site-pick">
        <Icon name="pin" size={18} />
        {!hasWorld ? (
          <span>Start a Moon base first (the Active world menu above).</span>
        ) : target ? (
          <span>
            <strong>Site: {formatLatLon(target.latitude, target.longitude, 3)}</strong>
            <small className="muted">See the site check on the right. Click elsewhere on the map to move it.</small>
          </span>
        ) : (
          <span>
            <strong>Click the map to choose a site</strong>
            <small className="muted">The site check shows sunlight, night length, Earth contact, ground and keep-outs.</small>
          </span>
        )}
        {target && !editing && (
          <button type="button" className="ghost" onClick={onClearTarget}>
            Clear
          </button>
        )}
      </section>
    </div>
  );
}

/* ---------------- Building list ---------------- */

export function MoonBuildingList({
  buildings,
  worldName,
  editingId,
  onShow,
  onEdit,
  onDelete,
  onNew,
}: {
  buildings: PlacedMoonBuilding[];
  worldName: string | null;
  editingId: string | null;
  onShow: (b: PlacedMoonBuilding) => void;
  onEdit: (b: PlacedMoonBuilding) => void;
  onDelete: (b: PlacedMoonBuilding) => void;
  onNew: () => void;
}) {
  if (!buildings.length)
    return (
      <section className="panel timeline-empty">
        <Icon name="moon" size={32} />
        <h2>No buildings yet</h2>
        <p className="muted">{worldName ? `Buildings you place in “${worldName}” are listed here, ready to edit.` : "Start a Moon base from the Active world menu first."}</p>
        {worldName && (
          <button className="primary" onClick={onNew}>
            <Icon name="plus" size={16} />
            New building
          </button>
        )}
      </section>
    );
  return (
    <section className="panel building-list">
      <p className="muted small">
        {buildings.length} {buildings.length === 1 ? "building" : "buildings"} in {worldName}. Choose one to see it on the map.
      </p>
      <ul className="list">
        {buildings.map((b) => {
          const def = MOON_BUILDING_BY_TYPE[b.type];
          return (
            <li key={b.id} className={b.id === editingId ? "editing" : undefined}>
              <button className="link" title="Show on the map" onClick={() => onShow(b)}>
                <span className="dot" style={{ background: rgb(def.colour) }} />
                <span className="result-title">
                  {b.name || def.label}
                  <small>
                    {b.id === editingId ? "Editing · " : ""}
                    {def.label} · {formatLatLon(b.latitude, b.longitude, 2)}
                  </small>
                </span>
              </button>
              <div className="building-actions">
                <button type="button" onClick={() => onEdit(b)} aria-label={`Edit ${b.name || def.label}`}>
                  Edit
                </button>
                <button type="button" className="ghost danger" onClick={() => onDelete(b)} aria-label={`Delete ${b.name || def.label}`}>
                  Delete
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ---------------- Base summary ---------------- */

function Meter({ label, have, need, unit }: { label: string; have: number; need: number; unit: string }) {
  const ok = have >= need;
  const share = need > 0 ? Math.min(1, have / need) : have > 0 ? 1 : 0;
  return (
    <div className={`moon-meter${ok ? " ok" : " short"}`}>
      <div className="moon-meter-head">
        <span>{label}</span>
        <strong>
          {num(have)} / {num(need)} <small>{unit}</small>
        </strong>
      </div>
      <div className="moon-meter-bar" role="img" aria-label={`${label}: ${num(have)} of ${num(need)} ${unit}`}>
        <span style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
    </div>
  );
}

export function MoonBaseSummary({
  balance,
  settings,
  onSettings,
  hasWorld,
}: {
  balance: BaseBalance;
  settings: BaseSettings;
  onSettings: (patch: Partial<BaseSettings>) => void;
  hasWorld: boolean;
}) {
  const [nightRaw, setNightRaw] = useState(settings.nightHours === null ? "" : String(settings.nightHours));
  const { power, oxygen, water, food, cost, mass } = balance;
  if (!hasWorld)
    return (
      <section className="panel timeline-empty">
        <Icon name="moon" size={32} />
        <h2>No Moon base yet</h2>
        <p className="muted">Start one from the Active world menu, then place a habitat, power and life support.</p>
      </section>
    );
  return (
    <>
      <section className={`panel moon-headline moon-headline-${balance.headline.status}`} role="status">
        <StatusMark status={balance.headline.status} />
        <p>{balance.headline.text}</p>
      </section>
      <section className="panel">
        <h2>Life support</h2>
        <div className="stats three moon-base-stats">
          <div className="stat">
            <strong>{balance.crew}</strong>
            <span>crew housed</span>
          </div>
          <div className="stat">
            <strong>{balance.reserveDays ?? "–"}</strong>
            <span>days of stored reserves</span>
          </div>
          <div className="stat">
            <strong>{num(cost.resupplyKgPerYear / 1000, 1)} t</strong>
            <span>shipped from Earth a year</span>
          </div>
        </div>
        {oxygen.needed + oxygen.produced > 0 && <Meter label="Oxygen made on site" have={oxygen.produced} need={oxygen.needed} unit="kg/day" />}
        {water.needed + water.produced > 0 && <Meter label="Water made on site" have={water.produced} need={water.needed} unit="kg/day" />}
        {food.needed + food.produced > 0 && <Meter label="Food grown on site" have={food.produced} need={food.needed} unit="kg/day" />}
        <p className="small muted">
          Per crew member a day: {LIFE_SUPPORT.oxygenKgPerCrewDay} kg oxygen, {LIFE_SUPPORT.waterKgPerCrewDay} kg water, {LIFE_SUPPORT.foodKgPerCrewDay} kg food (NASA BVAD), less what the habitat recycles.
        </p>
      </section>
      <section className="panel">
        <h2>Power</h2>
        <Meter label="Daytime supply" have={power.daySupplyKw} need={power.demandKw} unit="kW" />
        <Meter label={`Night supply (${num(power.nightHours / 24)}-day night)`} have={power.nightSupplyKw} need={power.demandKw} unit="kW" />
        <ul className="moon-power-facts small">
          <li>Fission: {num(power.fissionKw)} kW, day and night</li>
          <li>
            Solar: {num(power.solarRatedKw)} kW while lit
            {power.solarAverageKw !== null && power.solarRatedKw > 0 ? ` (${num(power.solarAverageKw)} kW averaged over day and night)` : ""}
          </li>
          <li>
            Storage: {num(power.storageKwh, 0)} kWh, up to {num(power.storageKw)} kW. One night draws {num(power.nightDeficitKwh, 0)} kWh beyond fission.
          </li>
        </ul>
        <p className="small muted">{power.nightBasis}</p>
      </section>
      <section className="panel">
        <h2>Checks</h2>
        <ul className="moon-checks">
          {balance.lines.map((l) => (
            <li key={l.id}>
              <StatusMark status={l.status} />
              <span>{l.text}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="panel">
        <h2>Cost of getting it there</h2>
        <div className="moon-param">
          <label htmlFor="moon-transport">
            <span>Transport price</span>
          </label>
          <select id="moon-transport" value={cost.case.id} onChange={(e) => onSettings({ transportCase: e.target.value })}>
            {TRANSPORT_CASES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}: ${c.usdPerKg.toLocaleString()}/kg
              </option>
            ))}
          </select>
          <small className="muted">{cost.case.note}.</small>
        </div>
        <div className="stats two moon-base-stats">
          <div className="stat">
            <strong>{formatUsd(cost.deliveryUsd)}</strong>
            <span>to land {num(mass.knownT)} t of buildings</span>
          </div>
          <div className="stat">
            <strong>{formatUsd(cost.resupplyUsdPerYear)}</strong>
            <span>a year in deliveries</span>
          </div>
        </div>
        {mass.unknown.length > 0 && <p className="warn small">Landed mass unknown for {mass.unknown.join(", ")}: not included in the delivery cost.</p>}
        <p className="small muted">Transport only: no hardware, construction or operating costs.</p>
      </section>
      <section className="panel">
        <h2>Assumptions</h2>
        <div className="moon-param">
          <label htmlFor="moon-night">
            <span>Longest night the base must survive</span>
          </label>
          <div className="moon-param-input">
            <input
              id="moon-night"
              inputMode="decimal"
              value={nightRaw}
              placeholder={`${num(power.nightHours, 0)} (from the site)`}
              onChange={(e) => setNightRaw(e.target.value)}
              onBlur={() => {
                const n = Number(nightRaw);
                const next = nightRaw.trim() === "" || !Number.isFinite(n) || n <= 0 ? null : Math.min(n, 24 * 365);
                if (next !== settings.nightHours) onSettings({ nightHours: next });
                setNightRaw(next === null ? "" : String(next));
              }}
            />
            <span className="moon-unit">hours</span>
          </div>
          <small className="muted">Blank uses the site: ~354 h away from the poles, 120 h for a polar ridge base.</small>
        </div>
        <p className="small muted">
          Buildings are assumed to share one power and supply network. This is a hypothetical planning view: day-to-day operations, maintenance, radiation shielding and
          spare parts are not modelled.
        </p>
      </section>
    </>
  );
}

/* ---------------- Site check (inspector) ---------------- */

const VERDICT: Record<Verdict, { label: string; status: CheckStatus }> = {
  suitable: { label: "Suitable site", status: "pass" },
  warnings: { label: "Suitable, with warnings", status: "warn" },
  unsuitable: { label: "Not suitable here", status: "fail" },
};

export function MoonSiteCheck({
  type,
  facts,
  items,
  verdict,
  editing,
  saving,
  canSave,
  blockReason,
  onSave,
}: {
  type: MoonBuildingType;
  facts: SiteFacts | null;
  items: SiteCheckItem[];
  verdict: Verdict | null;
  editing: boolean;
  saving: boolean;
  canSave: boolean;
  blockReason: string | null;
  onSave: () => void;
}) {
  const def = MOON_BUILDING_BY_TYPE[type];
  return (
    <div className="moon-site-check">
      <div className="moon-site-head">
        <TypeBadge type={type} />
        <div>
          <strong>{def.label}</strong>
          {facts && <small className="muted">{formatLatLon(facts.latitude, facts.longitude, 3)}</small>}
        </div>
      </div>
      {!facts ? (
        <p className="muted small" role="status">
          Reading the site…
        </p>
      ) : (
        <>
          {verdict && (
            <div className={`moon-verdict moon-verdict-${VERDICT[verdict].status}`}>
              <StatusMark status={VERDICT[verdict].status} />
              <strong>{VERDICT[verdict].label}</strong>
            </div>
          )}
          <dl className="moon-facts">
            <div>
              <dt>Sunlight</dt>
              <dd>{facts.sunlitFraction === null ? "Depends on terrain" : `${Math.round(facts.sunlitFraction * 100)}% of the time`}</dd>
            </div>
            <div>
              <dt>Longest night</dt>
              <dd>{facts.longestNightHours === null ? "Depends on terrain" : `${num(facts.longestNightHours / 24)} days`}</dd>
            </div>
            <div>
              <dt>Earth</dt>
              <dd>{facts.earthVisibility === "always" ? "Always in view" : facts.earthVisibility === "sometimes" ? "Rises and sets" : "Never in view"}</dd>
            </div>
            <div>
              <dt>Ground</dt>
              <dd>{facts.terrain === null ? "Loading…" : facts.terrain === "mare" ? facts.mareName : "Highlands"}</dd>
            </div>
          </dl>
          <ul className="moon-checks">
            {items.map((i) => (
              <li key={i.id}>
                <StatusMark status={i.status} />
                <span>
                  <strong>{i.label}</strong> {i.detail}
                </span>
              </li>
            ))}
          </ul>
          {blockReason && <p className="warn small">{blockReason}</p>}
          <button className="primary moon-place" disabled={!canSave || saving} onClick={onSave}>
            <Icon name={editing ? "arrow" : "plus"} size={16} />
            {saving ? "Saving…" : editing ? "Save changes" : `Place ${def.label.toLowerCase()} here`}
          </button>
        </>
      )}
    </div>
  );
}
