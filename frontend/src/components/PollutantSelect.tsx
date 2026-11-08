import { useState } from "react";
import { pollutantKey, pollutantsFor, type ReleaseMedium } from "../lib/pollutants";

export default function PollutantSelect({ value, medium, onChange, error }: {
  value: string; medium: ReleaseMedium; onChange: (value: string) => void; error?: string;
}) {
  const options = pollutantsFor(medium);
  const known = options.find((p) => p.id === pollutantKey(value));
  const [custom, setCustom] = useState(false);
  const other = custom || (!!value && !known);
  return <div className="pollutant-select">
    <label>Pollutant<select aria-label="Pollutant" title={value || "Select a pollutant"} aria-invalid={!!error} value={other ? "__other" : known?.id ?? ""} onChange={(e) => {
      setCustom(e.target.value === "__other");
      onChange(options.find((p) => p.id === e.target.value)?.label ?? "");
    }}><option value="" disabled>Select a pollutant</option>
      {options.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      {medium !== "climate" && <option value="__other">Other / existing pollutant…</option>}
    </select></label>
    {known && value !== known.label && value.includes("(") && <small className="muted">Declared as: {value}</small>}
    {other && <label className="small">Other pollutant name<input aria-label="Other pollutant name" value={value} maxLength={100} onChange={(e) => onChange(e.target.value)} /></label>}
    {error && <span className="field-error" role="alert">{error}</span>}
  </div>;
}
