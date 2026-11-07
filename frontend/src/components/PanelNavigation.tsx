import type { ReactNode } from "react";
import Icon from "./Icon";

/** Focused subviews: the parent owns drafts, so changing views never discards input. */
export function PanelTabs<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
}) {
  return (
    <nav className="panel-tabs" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} aria-pressed={value === option.value} onClick={() => onChange(option.value)}>
          {option.label}{!!option.count && <span className="nav-count">{option.count}</span>}
        </button>
      ))}
    </nav>
  );
}

export function BackLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="back-link" onClick={onClick}><Icon name="arrow" size={15} />{children}</button>;
}
