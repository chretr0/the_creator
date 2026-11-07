import { useId, useState } from "react";
import { PanelTabs } from "./PanelNavigation";
import type { BuildingTemplate, Period } from "../lib/buildings";
import {
  countErrors,
  editEmission,
  editedProvenance,
  editMaterial,
  editOperating,
  editValue,
  filledCount,
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

/**
 * Building statistics form, shared by the Build tab and the placed-building editor.
 * Blank = unknown. Every number shows its unit; invalid values are flagged inline.
 */
export default function BuildingForm({ draft, onChange, errors, template, page }: Props) {
  const [localPage, setLocalPage] = useState<"resources" | "impact">("resources");
  const shownPage = page ?? localPage;
  const accordion = useId();
  const currency = (draft.values["costs.currency"] ?? "").trim().toUpperCase() || "currency";

  const num = (path: string, unitOverride?: string) => {
    const spec = STAT_FIELDS[path];
    return (
      <Field
        key={path}
        label={spec.label}
        unit={unitOverride ?? spec.unit}
        value={draft.values[path] ?? ""}
        onChange={(v) => onChange(editValue(draft, path, v))}
        error={errors[path]}
        help={spec.help}
        title={template.fieldHelp?.[path]}
        numeric={!!spec.rule}
        placeholder={spec.rule ? undefined : "Not set"}
      />
    );
  };

  const meta = (paths: string[], section?: SectionKey) => (
    <>
      {filledCount(draft, paths)} of {paths.length} set
      {section && <ProvenanceTag provenance={draft.provenance[section]} />}
    </>
  );

  const powerUse = ["power.averageDemandKw", "power.peakDemandKw"];
  const powerOut = ["power.averageOutputKw", "power.ratedOutputKw", "power.capacityFactor", "power.technology"];
  const waterUse = ["water.inputM3PerHour", "water.basis"];
  const waterOut = ["water.outputM3PerHour"];
  const costPaths = [
    "costs.currency",
    "costs.constructionTotal",
    "costs.priceBasis",
    "costs.operating.amount",
    "costs.electricityPricePerKwh",
    "costs.waterPricePerM3",
  ];

  const powerOutput = (
    <>
      <h4>{template.producesPower ? "Electricity output" : "Electricity output (if it generates any)"}</h4>
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
      <h4>Electricity use</h4>
      <div className="row">
        {num("power.averageDemandKw")}
        {num("power.peakDemandKw")}
      </div>
    </>
  );

  const isDataCentre = template.type === "data_centre";
  const bad = (...prefixes: string[]) => countErrors(errors, prefixes);

  return (
    <div className="building-form">
      {!page && <PanelTabs label="Building statistics sections" value={localPage} onChange={setLocalPage} options={[
        { value: "resources", label: "Resources" }, { value: "impact", label: "Impact & costs" },
      ]} />}
      <div hidden={shownPage !== "resources"}>
      <Section group={accordion} title="Size and operating hours" meta={meta(["footprintM2", "operatingHoursPerDay"], "footprint")} invalid={bad("footprintM2", "operatingHoursPerDay")} open={!template.producesPower && !template.producesWater}>
        {num("footprintM2")}
        {num("operatingHoursPerDay")}
      </Section>

      <Section group={accordion} title="Power" meta={meta([...powerUse, ...powerOut], "power")} invalid={bad("power.")} open={template.producesPower} emphasis={template.producesPower}>
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
        <p className="muted small">Output and own use are separate: never enter a net or negative value.</p>
      </Section>

      <Section group={accordion} title="Water" meta={meta([...waterUse, ...waterOut], "water")} invalid={bad("water.")} open={template.producesWater} emphasis={template.producesWater}>
        {template.producesWater && (
          <>
            <h4>Usable water output</h4>
            {num("water.outputM3PerHour")}
          </>
        )}
        <h4>Water use</h4>
        {num("water.inputM3PerHour")}
        <Select
          label="Intake source"
          value={draft.waterSource}
          options={[
            { value: "fresh", label: "Fresh water (rivers, runoff, groundwater)" },
            { value: "seawater", label: "Seawater — needs a coastal site" },
            { value: "wastewater", label: "Treated municipal wastewater — from towns within ~64 km" },
          ]}
          onChange={(v) => onChange({ ...draft, waterSource: v, provenance: { ...draft.provenance, water: editedProvenance(draft) } })}
          help="Only fresh water uses the local river and runoff supply. A plant on seawater or wastewater adds all of its output to the area's supply."
        />
        {num("water.basis")}
        {!template.producesWater && (
          <>
            <h4>Water output (if it produces any)</h4>
            {num("water.outputM3PerHour")}
          </>
        )}
      </Section>

      <Section group={accordion} title="Raw materials" meta={`${draft.materials.length} listed`} invalid={bad("materials.")}>
        {draft.materials.length === 0 && <p className="muted small">None listed. Add one row per material.</p>}
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
      <Section group={accordion} title="Air emissions" meta={`${draft.emissions.length} listed`} invalid={bad("emissions.")}>
        {draft.emissions.length === 0 && <p className="muted small">None listed. One row per pollutant; they are never added together.</p>}
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

      <Section group={accordion} title="Light" meta={meta(["light.upwardLumens", "light.hoursPerDay"], "light")} invalid={bad("light.")}>
        <div className="row">
          {num("light.upwardLumens")}
          {num("light.hoursPerDay")}
        </div>
      </Section>

      <Section group={accordion} title="Workers" meta={meta(["workers.capacity", "workers.staffingRequired"], "workers")} invalid={bad("workers.")}>
        <div className="row">
          {num("workers.capacity")}
          {num("workers.staffingRequired")}
        </div>
        <p className="muted small">Capacity is not available labour or jobs created.</p>
      </Section>

      <Section group={accordion} title="Costs" meta={meta(costPaths, "costs")} invalid={bad("costs.")}>
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
            { value: "fixed", label: "A fixed part only (add electricity, water and material costs)" },
            { value: "total", label: "The all-inclusive total (add nothing on top)" },
          ]}
          onChange={(v) => onChange(editOperating(draft, { operatingKind: v }))}
        />
        <h4>Unit prices</h4>
        <div className="row">
          {num("costs.electricityPricePerKwh", `${currency}/kWh`)}
          {num("costs.waterPricePerM3", `${currency}/m³`)}
        </div>
        {(["electricity", "water"] as const).map((r) => {
          const src = draft.priceSources?.[r];
          if (!src) return null;
          return (
            <p key={r} className="small" title={src.basis ?? undefined}>
              <span className="tag prov-cited">Location default</span> {r === "electricity" ? "Electricity" : "Water"}:{" "}
              {priceSourceText(src, r)}{" "}
              <button className="link inline" onClick={() => onChange(removeLocationPrice(draft, r))}>
                Remove
              </button>
              {src.basis && <small className="muted block">Basis: {src.basis}</small>}
            </p>
          );
        })}
        <p className="muted small">
          Blank prices stay unknown. When previewing a location you can choose to use its average business price
          (USD, never converted); a price you type always wins.
        </p>
      </Section>

      </div>
      <div hidden={shownPage !== "resources"}>
      {(template.parameters.length > 0 || isDataCentre) && (
        <Section group={accordion}
          title={`${template.label} details`}
          meta={`${template.parameters.filter((p) => (draft.params[p.key] ?? "") !== "").length} of ${template.parameters.length} set`}
          invalid={bad("params.")}
        >
          {isDataCentre && (
            <Select
              label="Electricity and water demand comes from"
              value={draft.demandBasis}
              options={[
                { value: "direct", label: "The average demand and water input entered above" },
                { value: "derived", label: "IT power × load fraction × PUE (and WUE) below" },
              ]}
              onChange={(v) => onChange({ ...draft, demandBasis: v })}
              help="Only one basis is used, never both."
            />
          )}
          {template.parameters.map((p) =>
            p.kind === "select" ? (
              <Select
                key={p.key}
                label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`}
                value={draft.params[p.key] ?? ""}
                options={[{ value: "", label: "Not set" }, ...(p.options ?? []).map((o) => ({ value: o, label: o.replace(/_/g, " ") }))]}
                onChange={(v) => onChange({ ...draft, params: { ...draft.params, [p.key]: v } })}
                help={p.hint ?? undefined}
              />
            ) : (
              <Field
                key={p.key}
                label={p.label}
                unit={p.unit}
                value={draft.params[p.key] ?? ""}
                onChange={(v) => onChange({ ...draft, params: { ...draft.params, [p.key]: v } })}
                error={errors[`params.${p.key}`]}
                help={p.hint ?? (paramRule(p) === "pue" ? "1 or more" : undefined)}
              />
            ),
          )}
        </Section>
      )}
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
        <ProvenanceTag provenance={m.provenance} />
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
      <ProvenanceTag provenance={e.provenance} />
    </div>
  );
}
