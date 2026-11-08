import { useEffect, useId, useRef, useState } from "react";
import Icon from "./Icon";
import { layerLabel, type LayerNeed, type LayerRef } from "../lib/buildLayers";

export type BuildLayerChipEntry = { need: LayerNeed; on: boolean; auto: boolean; partial?: boolean };

/**
 * Map overlay: the layers switched on for the building being defined, one toggle chip per need.
 * A dot marks chips the build flow switched on itself; hovering a chip says why and which layers.
 */
export default function BuildLayerChips({
  entries,
  onToggle,
  loading,
  layerName = layerLabel,
}: {
  entries: BuildLayerChipEntry[];
  onToggle: (key: string) => void;
  /** Whether a need's layers are still loading, by need key. */
  loading?: (key: string) => boolean;
  /** Display name of a layer (defaults to the built-in labels; pass manifest names if preferred). */
  layerName?: (ref: LayerRef) => string;
}) {
  const id = useId();
  // Whether the chip row scrolls sideways (phones), so the CSS can fade the cut-off edge as a cue.
  const listRef = useRef<HTMLUListElement>(null);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const update = () => setOverflows(el.scrollWidth - el.scrollLeft - el.clientWidth > 2);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    el.addEventListener("scroll", update, { passive: true });
    return () => {
      ro.disconnect();
      el.removeEventListener("scroll", update);
    };
  }, [entries.length]);
  if (!entries.length) return null;
  return (
    <section className="build-layer-chips" aria-labelledby={`${id}-title`}>
      <div className="build-layer-chips-title" id={`${id}-title`}>
        <Icon name="layers" size={14} />
        Map layers for this building
      </div>
      <ul className="build-layer-chips-list" ref={listRef} data-overflow={overflows || undefined}>
        {entries.map(({ need, on, auto, partial = false }) => {
          const busy = on && !!loading?.(need.key);
          const names = need.layers.map(layerName).join(", ");
          const state = busy
            ? "Loading."
            : on
              ? auto
                ? "Switched on for this building."
                : "Already on."
              : partial
                ? "Partly shown."
                : "Hidden.";
          const description = `${need.reason}. Layers: ${names}. ${state}`;
          const descId = `${id}-${need.key}`;
          return (
            <li key={need.key}>
              <button
                type="button"
                className="build-layer-chip"
                aria-pressed={on ? true : partial ? "mixed" : false}
                aria-describedby={descId}
                aria-busy={busy || undefined}
                title={`${need.reason}\nLayers: ${names}\n${state} Click to ${on ? "hide" : "show"}.`}
                onClick={() => onToggle(need.key)}
              >
                <Icon name={need.icon} size={14} />
                <span>{need.label}</span>
                {busy ? (
                  <span className="build-layer-chip-spinner" aria-hidden="true" />
                ) : on && auto ? (
                  <span className="build-layer-chip-auto" aria-hidden="true" />
                ) : null}
              </button>
              <span id={descId} hidden>
                {description}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
