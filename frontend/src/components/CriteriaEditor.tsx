import { useState } from "react";
import type { CriterionKind } from "../lib/buildings";
import type { CellLayer } from "../lib/datalayers";
import { CRITERION_KINDS, CRITERION_LABEL, fmtDays, newCriterion, type CriterionDraft, type Errors } from "../lib/buildingForm";
import { Field } from "./FormBits";

type Props = {
  drafts: CriterionDraft[];
  onChange: (d: CriterionDraft[]) => void;
  errors: Errors;
  catalogue: CellLayer[];
  currency: string;
  /** The scenario's evaluation period; period-based limits are amounts over it. */
  periodDays: number;
};

const HELP = Object.fromEntries(CRITERION_KINDS.map((k) => [k.kind, k.help])) as Record<CriterionKind, string>;

/** Location requirements. Each becomes one pass / fail / unknown check. */
export default function CriteriaEditor({ drafts, onChange, errors, catalogue, currency, periodDays }: Props) {
  const [adding, setAdding] = useState<CriterionKind>("layer");
  const [editing, setEditing] = useState<string | null>(null);
  const activeId = drafts.find((d) => d.id === editing)?.id ?? drafts[0]?.id;
  const update = (id: string, patch: Partial<CriterionDraft>) => onChange(drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)));

  return (
    <div>
      {drafts.length > 0 && <label className="field">
        <span>Edit limit</span>
        <select value={activeId} onChange={(e) => setEditing(e.target.value)}>
          {drafts.map((d, i) => <option key={d.id} value={d.id}>
            {i + 1}. {CRITERION_LABEL[d.kind]}{d.kind === "layer" && d.layerId ? ` · ${catalogue.find((l) => l.id === d.layerId)?.name ?? d.layerId}` : ""}
            {Object.keys(errors).some((key) => key.startsWith(`${d.id}.`)) ? " · needs attention" : ""}
          </option>)}
        </select>
      </label>}
      {drafts.map((d) => (
        <div className="list-row" key={d.id} hidden={d.id !== activeId}>
          <div className="row align-center">
            <strong className="grow" title={HELP[d.kind]}>{CRITERION_LABEL[d.kind]}</strong>
            <label className="toggle compact" title="A failing required check makes the location fail. Optional checks are shown but don't decide the state.">
              <input type="checkbox" checked={d.required} onChange={(e) => update(d.id, { required: e.target.checked })} />
              <span>Required</span>
            </label>
            <button className="ghost danger" onClick={() => onChange(drafts.filter((x) => x.id !== d.id))}>
              Remove
            </button>
          </div>
          <CriterionFields d={d} errors={errors} catalogue={catalogue} currency={currency} period={fmtDays(periodDays)} update={(p) => update(d.id, p)} />
        </div>
      ))}
      <div className="row align-end">
        <label className="field">
          <span>Add a limit</span>
          <select value={adding} onChange={(e) => setAdding(e.target.value as CriterionKind)}>
            {CRITERION_KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => { const next = newCriterion(adding); onChange([...drafts, next]); setEditing(next.id); }}>+ Add</button>
      </div>
    </div>
  );
}

function CriterionFields({
  d,
  errors,
  catalogue,
  currency,
  period,
  update,
}: {
  d: CriterionDraft;
  errors: Errors;
  catalogue: CellLayer[];
  currency: string;
  /** e.g. "30 days" */
  period: string;
  update: (p: Partial<CriterionDraft>) => void;
}) {
  const e = (k: string) => errors[`${d.id}.${k}`];
  const amount = (unit: string) => (
    <Field label="Maximum" unit={unit} value={d.amount} onChange={(v) => update({ amount: v })} error={e("amount")} />
  );

  switch (d.kind) {
    case "layer": {
      const layer = catalogue.find((l) => l.id === d.layerId) ?? null;
      const slice = layer?.slices.find((s) => s.id === d.sliceId) ?? null;
      const categorical = !!slice?.categorical;
      const pickLayer = (id: string) => {
        const l = catalogue.find((x) => x.id === id);
        const s = l?.slices.find((x) => x.id === l.defaultSlice) ?? l?.slices[0];
        update({ layerId: id, sliceId: s?.id ?? "", classes: s?.categorical ? [] : null, min: "", max: "" });
      };
      return (
        <>
          <label className="field">
            <span>Layer</span>
            <select value={d.layerId} onChange={(ev) => pickLayer(ev.target.value)} aria-invalid={!!e("layer")}>
              <option value="">Choose a layer…</option>
              {catalogue.map((l) => (
                <option key={l.id} value={l.id} disabled={!l.available}>
                  {l.name}
                  {l.available ? "" : " (not available)"}
                </option>
              ))}
            </select>
            {e("layer") && <small className="field-error">{e("layer")}</small>}
            {catalogue.length === 0 && <small className="muted">Unavailable</small>}
          </label>
          {layer && layer.slices.length > 1 && (
            <label className="field">
              <span>Variable</span>
              <select
                value={d.sliceId}
                onChange={(ev) => {
                  const s = layer.slices.find((x) => x.id === ev.target.value);
                  update({ sliceId: ev.target.value, classes: s?.categorical ? [] : null, min: "", max: "" });
                }}
              >
                {layer.slices.map((s) => (
                  <option key={s.id} value={s.id} disabled={!s.available}>
                    {s.group ? `${s.group} · ` : ""}
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {layer && categorical && (
            <fieldset className="classes">
              <legend className="small muted">Allowed classes</legend>
              {(layer.categories ?? []).map((c) => {
                const on = d.classes?.includes(c.value) ?? false;
                return (
                  <label key={c.value} className="toggle compact">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        update({ classes: on ? (d.classes ?? []).filter((x) => x !== c.value) : [...(d.classes ?? []), c.value] })
                      }
                    />
                    <span className="swatch" style={{ background: c.colour }} />
                    <span>{c.label}</span>
                  </label>
                );
              })}
              {e("classes") && <small className="field-error">{e("classes")}</small>}
            </fieldset>
          )}
          {layer && !categorical && (
            <div className="row">
              <Field label="Min" unit={slice?.units || undefined} value={d.min} onChange={(v) => update({ min: v })} error={e("min")} placeholder="No minimum" />
              <Field label="Max" unit={slice?.units || undefined} value={d.max} onChange={(v) => update({ max: v })} error={e("max")} placeholder="No maximum" />
            </div>
          )}
        </>
      );
    }
    case "construction_budget":
      return amount(currency);
    case "operating_budget":
      return amount(`${currency} over ${period}`);
    case "light_limit":
      return amount("lumens");
    case "material_budget":
      return (
        <div className="row">
          <Field label="Material" value={d.materialName} onChange={(v) => update({ materialName: v })} error={e("materialName")} numeric={false} placeholder="As named in Raw materials" />
          {amount(`kg, construction + operation over ${period}`)}
        </div>
      );
    case "emission_limit":
      return (
        <div className="row">
          <Field label="Pollutant" value={d.pollutant} onChange={(v) => update({ pollutant: v })} error={e("pollutant")} numeric={false} placeholder="As named in Air emissions" />
          {amount(`kg over ${period}`)}
        </div>
      );
    default:
      return null;
  }
}
