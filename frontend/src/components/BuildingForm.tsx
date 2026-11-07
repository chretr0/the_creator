import { useState } from "react";
import { PanelTabs } from "./PanelNavigation";
import type { BuildingTemplate, Period, Provenance } from "../lib/buildings";
import {
  countErrors,
  editEmission,
  editedProvenance,
  editMaterial,
  editOperating,
  editValue,
  fmtNumber,
  newEmission,
  newMaterial,
  parseNumber,
  paramRule,
  priceSourceText,
  removeLocationPrice,
  STAT_FIELDS,
  toKg,
  type EmissionDraft,
  type Errors,
  type MaterialDraft,
  type SectionKey,
  type StatsDraft,
} from "../lib/buildingForm";
import { Field, ProvenanceTag, Section, Select } from "./FormBits";

type Props = {
  page?: "resources" | "impact";
  draft: StatsDraft;
  onChange: (d: StatsDraft) => void;
  errors: Errors;
  template: BuildingTemplate;
};

const PERIODS: { value: Period; label: string }[] = [
  { value: "hour", label: "per hour" },
  { value: "day", label: "per day" },
  { value: "month", label: "per month" },
  { value: "year", label: "per year" },
];

/** Provenance tag, shown only when it says more than "user assumption". */
function Prov({ provenance }: { provenance?: Provenance | null }) {
  return provenance && provenance.kind !== "user_assumption" ? <ProvenanceTag provenance={provenance} /> : null;
}

/**
 * Building statistics form, shared by the Build tab and the placed-building editor.
 * Blank = unknown. Every number shows its unit; invalid values are flagged inline.
 */
export default function BuildingForm({ draft, onChange, errors, template, page }: Props) {
  const [localPage, setLocalPage] = useState<"resources" | "impact">("resources");
  const shownPage = page ?? localPage;
  const currency = (draft.values["costs.currency"] ?? "").trim().toUpperCase() || "currency";

  const num = (path: string, unitOverride?: string) => {
    const spec = STAT_FIELDS[path];
    const tip = [spec.help, template.fieldHelp?.[path]].filter(Boolean).join(" ");
    return (
      <Field
        key={path}
        label={spec.label}
        unit={unitOverride ?? spec.unit}
        value={draft.values[path] ?? ""}
        onChange={(v) => onChange(editValue(draft, path, v))}
        error={errors[path]}
        title={tip || undefined}
        numeric={!!spec.rule}
        placeholder={spec.rule ? undefined : "Not set"}
      />
    );
  };

  const meta = (section: SectionKey) => <Prov provenance={draft.provenance[section]} />;

  const powerOutput = (
    <>
      <h4 title="Output and own use are separate: never enter a net or negative value.">Output</h4>
      <div className="row">
        {num("power.averageOutputKw")}
        {num("power.ratedOutputKw")}
      </div>
      {num("power.capacityFactor")}
      {num("power.technology")}
    </>
  );
  const powerInput = (
    <>
      <h4>Use</h4>
      <div className="row">
        {num("power.averageDemandKw")}
        {num("power.peakDemandKw")}
      </div>
    </>
  );

  const isDataCentre = template.type === "data_centre";
  const bad = (...prefixes: string[]) => countErrors(errors, prefixes);
  const setParam = (key: string, v: string) => onChange({ ...draft, params: { ...draft.params, [key]: v } });

  return (
    <div className="building-form">
      {!page && <PanelTabs label="Building statistics sections" value={localPage} onChange={setLocalPage} options={[
        { value: "resources", label: "Resources" }, { value: "impact", label: "Impact & costs" },
      ]} />}
      <div hidden={shownPage !== "resources"}>
        <Section title="Size & hours" meta={meta("footprint")} invalid={bad("footprintM2", "operatingHoursPerDay")}>
          <div className="row">
            {num("footprintM2")}
            {num("operatingHoursPerDay")}
          </div>
        </Section>

        {(template.parameters.length > 0 || isDataCentre) && (
          <Section title={`${template.label} details`} invalid={bad("params.")}>
            {isDataCentre && (
              <Select
                label="Demand from"
                value={draft.demandBasis}
                options={[
                  { value: "direct", label: "Average demand above" },
                  { value: "derived", label: "IT power × PUE" },
                ]}
                onChange={(v) => onChange({ ...draft, demandBasis: v })}
                title="Only one basis is used, never both. IT power × load fraction × PUE (and WUE for water)."
              />
            )}
            {template.parameters.map((p) =>
              p.kind === "select" ? (
                <Select
                  key={p.key}
                  label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`}
                  value={draft.params[p.key] ?? ""}
                  options={[{ value: "", label: "Not set" }, ...(p.options ?? []).map((o) => ({ value: o, label: o.replace(/_/g, " ") }))]}
                  onChange={(v) => setParam(p.key, v)}
                  title={p.hint ?? undefined}
                />
              ) : (
                <Field
                  key={p.key}
                  label={p.label}
                  unit={p.unit}
                  value={draft.params[p.key] ?? ""}
                  onChange={(v) => setParam(p.key, v)}
                  error={errors[`params.${p.key}`]}
                  title={p.hint ?? (paramRule(p) === "pue" ? "1 or more" : undefined)}
                />
              ),
            )}
          </Section>
        )}

        <Section title="Power" meta={meta("power")} invalid={bad("power.")} emphasis={template.producesPower}>
          {template.producesPower ? (
            <>
              {powerOutput}
              {powerInput}
            </>
          ) : (
            <>
              {powerInput}
              {powerOutput}
            </>
          )}
        </Section>

        <Section title="Water" meta={meta("water")} invalid={bad("water.")} emphasis={template.producesWater}>
          {template.producesWater && (
            <>
              <h4>Output</h4>
              {num("water.outputM3PerHour")}
            </>
          )}
          <h4>Use</h4>
          {num("water.inputM3PerHour")}
          <Select
            label="Intake source"
            value={draft.waterSource}
            options={[
              { value: "fresh", label: "Fresh water" },
              { value: "seawater", label: "Seawater (coastal)" },
              { value: "wastewater", label: "Treated wastewater" },
            ]}
            onChange={(v) => onChange({ ...draft, waterSource: v, provenance: { ...draft.provenance, water: editedProvenance(draft) } })}
            title="Only fresh water uses the local river and runoff supply. Seawater needs a coastal site; treated wastewater comes from towns within ~64 km."
          />
          {num("water.basis")}
          {!template.producesWater && (
            <>
              <h4>Output</h4>
              {num("water.outputM3PerHour")}
            </>
          )}
        </Section>

        <Section title="Raw materials" invalid={bad("materials.")}>
          {draft.materials.map((m) => (
            <MaterialRow
              key={m.id}
              m={m}
              errors={errors}
              currency={currency}
              onChange={(next) => onChange(editMaterial(draft, next))}
              onRemove={() => onChange({ ...draft, materials: draft.materials.filter((x) => x.id !== m.id) })}
            />
          ))}
          <div className="actions tight">
            <button onClick={() => onChange({ ...draft, materials: [...draft.materials, newMaterial()] })}>+ Add material</button>
          </div>
        </Section>
      </div>

      <div hidden={shownPage !== "impact"}>
        <Section title="Costs" meta={meta("costs")} invalid={bad("costs.")}>
          <div className="row">
            {num("costs.currency")}
            {num("costs.constructionTotal", currency)}
          </div>
          {num("costs.priceBasis")}
          <h4>Operating cost</h4>
          <div className="row">
            {num("costs.operating.amount", currency)}
            <Select
              label="Per"
              value={draft.operatingPeriod}
              options={PERIODS.map((p) => ({ value: p.value, label: p.label.replace("per ", "") }))}
              onChange={(v) => onChange(editOperating(draft, { operatingPeriod: v }))}
            />
          </div>
          <Select
            label="This amount is"
            value={draft.operatingKind}
            options={[
              { value: "fixed", label: "Fixed part only" },
              { value: "total", label: "All-inclusive total" },
            ]}
            onChange={(v) => onChange(editOperating(draft, { operatingKind: v }))}
            title="Fixed part only: electricity, water and material costs are added. All-inclusive total: nothing is added on top."
          />
          <h4 title="Blank prices stay unknown. A location's average business price (USD) can be applied from the site check; a price you type always wins.">
            Unit prices
          </h4>
          <div className="row">
            {num("costs.electricityPricePerKwh", `${currency}/kWh`)}
            {num("costs.waterPricePerM3", `${currency}/m³`)}
          </div>
          {(["electricity", "water"] as const).map((r) => {
            const src = draft.priceSources?.[r];
            if (!src) return null;
            return (
              <p key={r} className="small" title={src.basis ? `Basis: ${src.basis}` : undefined}>
                <span className="tag prov-cited">Location default</span> {r === "electricity" ? "Electricity" : "Water"}:{" "}
                {priceSourceText(src, r)}{" "}
                <button className="link inline" onClick={() => onChange(removeLocationPrice(draft, r))}>
                  Remove
                </button>
              </p>
            );
          })}
        </Section>

        <Section title="Workers" meta={meta("workers")} invalid={bad("workers.")}>
          <div className="row">
            {num("workers.capacity")}
            {num("workers.staffingRequired")}
          </div>
        </Section>

        <Section title="Air emissions" invalid={bad("emissions.")}>
          {draft.emissions.map((e) => (
            <EmissionRow
              key={e.id}
              e={e}
              errors={errors}
              onChange={(next) => onChange(editEmission(draft, next))}
              onRemove={() => onChange({ ...draft, emissions: draft.emissions.filter((x) => x.id !== e.id) })}
            />
          ))}
          <div className="actions tight">
            <button onClick={() => onChange({ ...draft, emissions: [...draft.emissions, newEmission()] })}>+ Add pollutant</button>
          </div>
        </Section>

        <Section title="Light" meta={meta("light")} invalid={bad("light.")}>
          <div className="row">
            {num("light.upwardLumens")}
            {num("light.hoursPerDay")}
          </div>
        </Section>
      </div>
    </div>
  );
}

function MaterialRow({
  m,
  errors,
  currency,
  onChange,
  onRemove,
}: {
  m: MaterialDraft;
  errors: Errors;
  currency: string;
  onChange: (m: MaterialDraft) => void;
  onRemove: () => void;
}) {
  const q = parseNumber(m.quantity);
  const kgHint = m.unit === "t" && q.value !== null ? `= ${fmtNumber(toKg(q.value, "t"))} kg` : undefined;
  const e = (k: string) => errors[`materials.${m.id}.${k}`];
  return (
    <div className="list-row">
      <div className="row">
        <Field label="Material" value={m.name} onChange={(v) => onChange({ ...m, name: v })} error={e("name")} numeric={false} placeholder="e.g. Steel" />
        <Select
          label="Used during"
          value={m.phase}
          options={[
            { value: "construction", label: "Construction (once)" },
            { value: "operation", label: "Operation" },
          ]}
          onChange={(v) => onChange({ ...m, phase: v })}
        />
      </div>
      <div className="row">
        <Field label="Quantity" unit={m.unit === "t" ? "tonnes" : "kg"} value={m.quantity} onChange={(v) => onChange({ ...m, quantity: v })} error={e("quantity")} help={kgHint} />
        <div className="field unit-toggle">
          <span>Unit</span>
          <div className="seg" role="group" aria-label="Quantity unit">
            {(["kg", "t"] as const).map((u) => (
              <button key={u} className={m.unit === u ? "active" : ""} aria-pressed={m.unit === u} onClick={() => onChange({ ...m, unit: u })}>
                {u === "t" ? "tonnes" : "kg"}
              </button>
            ))}
          </div>
        </div>
        {m.phase === "operation" && (
          <Select
            label="Per"
            value={m.period}
            // An hourly material rate counts operating hours only (like power, water and emissions).
            options={PERIODS.map((p) => ({ value: p.value, label: p.value === "hour" ? "operating hour" : p.label.replace("per ", "") }))}
            onChange={(v) => onChange({ ...m, period: v })}
          />
        )}
      </div>
      <div className="row align-end">
        <Field label="Price" unit={`${currency}/kg`} value={m.price} onChange={(v) => onChange({ ...m, price: v })} error={e("price")} />
        <Prov provenance={m.provenance} />
        <button className="ghost danger" onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}

function EmissionRow({
  e,
  errors,
  onChange,
  onRemove,
}: {
  e: EmissionDraft;
  errors: Errors;
  onChange: (e: EmissionDraft) => void;
  onRemove: () => void;
}) {
  const err = (k: string) => errors[`emissions.${e.id}.${k}`];
  return (
    <div className="list-row">
      <div className="row align-end">
        <Field label="Pollutant" value={e.pollutant} onChange={(v) => onChange({ ...e, pollutant: v })} error={err("pollutant")} numeric={false} placeholder="e.g. NOx" />
        <Field label="Rate" unit="kg/h" value={e.rate} onChange={(v) => onChange({ ...e, rate: v })} error={err("rate")} />
        <button className="ghost danger" onClick={onRemove}>
          Remove
        </button>
      </div>
      <Prov provenance={e.provenance} />
    </div>
  );
}
