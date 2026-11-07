import { useEffect, useId, useRef, type ReactNode } from "react";
import { STATE_COLOUR, STATE_LABEL, type AssessmentState, type CheckStatus, type Provenance } from "../lib/buildings";
import { STATUS_LABEL } from "../lib/buildingForm";

/**
 * Labelled text input with its unit beside the label and an inline error or help line.
 * The label is tied to the input with htmlFor/id, so the input's accessible name is the label
 * (never the "Unknown" placeholder); the error or help line is its description.
 */
export function Field(props: {
  label: string;
  unit?: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  help?: string;
  placeholder?: string;
  numeric?: boolean;
  mono?: boolean;
  /** Longer explanation, shown on hover. */
  title?: string;
}) {
  const id = useId();
  const note = props.error ?? props.help;
  return (
    <div className="field" title={props.title}>
      <label htmlFor={id}>
        {props.label} {props.unit && <em>({props.unit})</em>}
      </label>
      <input
        id={id}
        // Same text as the visible label; also set explicitly because some accessibility tools
        // otherwise fall back to the placeholder.
        aria-label={props.unit ? `${props.label} (${props.unit})` : props.label}
        aria-describedby={note ? `${id}-note` : undefined}
        className={props.mono ? "mono" : undefined}
        inputMode={props.numeric === false ? undefined : "decimal"}
        value={props.value}
        placeholder={props.placeholder ?? (props.numeric === false ? "" : "Unknown")}
        aria-invalid={!!props.error}
        onChange={(e) => props.onChange(e.target.value)}
      />
      {note && (
        <small id={`${id}-note`} className={props.error ? "field-error" : "muted"}>
          {note}
        </small>
      )}
    </div>
  );
}

export function Select<T extends string>(props: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  help?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      <select id={id} aria-label={props.label} aria-describedby={props.help ? `${id}-note` : undefined} value={props.value} onChange={(e) => props.onChange(e.target.value as T)}>
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {props.help && (
        <small id={`${id}-note`} className="muted">
          {props.help}
        </small>
      )}
    </div>
  );
}

/**
 * Collapsible form section. `invalid` is the number of invalid fields inside: the summary then says
 * so, and the section opens so the highlighted fields are visible.
 */
export function Section(props: { title: string; meta?: ReactNode; open?: boolean; emphasis?: boolean; invalid?: number; children: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const invalid = props.invalid ?? 0;
  useEffect(() => {
    if (invalid > 0 && ref.current) ref.current.open = true;
  }, [invalid]);
  return (
    <details ref={ref} className={`section${props.emphasis ? " emphasis" : ""}`} open={props.open || invalid > 0}>
      <summary>
        <span className="section-title">{props.title}</span>
        {invalid > 0 && (
          <span className="section-error">
            Fix {invalid} field{invalid === 1 ? "" : "s"}
          </span>
        )}
        {props.meta && <span className="section-meta">{props.meta}</span>}
      </summary>
      <div className="section-body">{props.children}</div>
    </details>
  );
}

const PROV_LABEL: Record<Provenance["kind"], string> = {
  user_assumption: "user assumption",
  demo_assumption: "demo assumption",
  cited: "cited",
};

export function ProvenanceTag({ provenance }: { provenance?: Provenance | null }) {
  const p = provenance ?? { kind: "user_assumption" as const };
  return (
    <span className={`tag prov-${p.kind}`} title={p.note ?? undefined}>
      {PROV_LABEL[p.kind]}
    </span>
  );
}

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

export function StateBadge({ state }: { state: AssessmentState }) {
  return (
    <span className="badge" style={{ borderColor: rgb(STATE_COLOUR[state]), color: rgb(STATE_COLOUR[state]) }}>
      <span className="dot" style={{ background: rgb(STATE_COLOUR[state]) }} />
      {STATE_LABEL[state]}
    </span>
  );
}

export function StatusBadge({ status }: { status: CheckStatus }) {
  return <span className={`badge status-${status}`}>{STATUS_LABEL[status]}</span>;
}

export function StateLegend({ counts }: { counts?: Partial<Record<AssessmentState, number>> }) {
  return (
    <ul className="legend single">
      {(["meets_criteria", "insufficient_data", "fails_criteria"] as AssessmentState[]).map((s) => (
        <li key={s}>
          <span className="swatch" style={{ background: rgb(STATE_COLOUR[s]) }} />
          {STATE_LABEL[s]}
          {counts && <span className="right num">{(counts[s] ?? 0).toLocaleString()}</span>}
        </li>
      ))}
    </ul>
  );
}
