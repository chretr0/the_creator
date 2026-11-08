import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import Icon from "./Icon";
import { HEX_OUTLINE_LABEL, HEX_OUTLINE_MODES, type HexOutlines } from "../lib/h3grid";

const DESCRIPTION: Record<HexOutlines, string> = {
  all: "Every hexagon border",
  near: "Only around the mouse",
  off: "No hexagon borders",
};

/** Toolbar button that opens a small menu to pick how hexagon borders are drawn. */
export default function GridOutlinesMenu({ value, onChange }: { value: HexOutlines; onChange: (mode: HexOutlines) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    // Move focus to the checked option so the menu is keyboard-usable.
    rootRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const moveFocus = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <div className="grid-outlines" ref={rootRef}>
      <button
        ref={buttonRef}
        className={value !== "off" ? "active" : ""}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Hexagon outlines: ${HEX_OUTLINE_LABEL[value]}`}
        title={`Hexagon outlines: ${HEX_OUTLINE_LABEL[value]}`}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="hexagon" size={17} /> Grid <Icon name="chevron" size={14} />
      </button>
      {open && (
        <div className="grid-outlines-menu" role="menu" aria-label="Hexagon outlines" onKeyDown={moveFocus}>
          {HEX_OUTLINE_MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              role="menuitemradio"
              aria-checked={mode === value}
              onClick={() => {
                onChange(mode);
                setOpen(false);
                buttonRef.current?.focus();
              }}
            >
              <span className="grid-outlines-check" aria-hidden="true">{mode === value ? "✓" : ""}</span>
              <span>
                <strong>{HEX_OUTLINE_LABEL[mode]}</strong>
                <small>{DESCRIPTION[mode]}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
