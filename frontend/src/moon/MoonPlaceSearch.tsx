import { useId, useMemo, useState } from "react";
import Icon from "../components/Icon";
import { moonSearch, type IndexedPlace, type MoonPlaceHit } from "./geo";
import type { LoadStatus } from "./useMoonData";

type Props = {
  /** The IAU gazetteer, null until it has loaded (on first focus). */
  index: IndexedPlace[] | null;
  status: LoadStatus;
  onFocus: () => void;
  onGo: (hit: MoonPlaceHit) => void;
};

/** The highlighted row after moving by `delta`: always a row (0 when there are none), never -1. */
export function moveCursor(cursor: number, delta: number, count: number): number {
  return count > 0 ? Math.max(0, Math.min(count - 1, cursor + delta)) : 0;
}

/** The id of the option element for row `i` of the listbox `listId`. */
export const optionId = (listId: string, i: number) => `${listId}-option-${i}`;

/** What to say about the search while the list is open, if anything (read out by a live region). */
export function searchStatusMessage(
  hits: MoonPlaceHit[],
  index: IndexedPlace[] | null,
  status: LoadStatus,
  q: string,
): { text: string; warn: boolean } | null {
  if (!hits.length && status.loading) return { text: "Loading the IAU gazetteer…", warn: false };
  if (!hits.length && !status.loading && index) return { text: `No named feature matches “${q.trim()}”.`, warn: false };
  if (!index && !status.loading && status.notPrepared) {
    return { text: "Place names aren’t prepared on this server yet. Coordinates (lat, lon) still work.", warn: true };
  }
  if (!index && !status.loading && status.error) return { text: `Couldn’t load place names: ${status.error}`, warn: true };
  return null;
}

/** The results listbox: only options inside, each one clickable itself (focus stays in the search box). */
export function MoonPlaceOptions({
  id,
  hits,
  cursor,
  hidden,
  onPick,
}: {
  id: string;
  hits: MoonPlaceHit[];
  cursor: number;
  hidden: boolean;
  onPick: (hit: MoonPlaceHit) => void;
}) {
  return (
    <ul id={id} className="place-results" role="listbox" aria-label="Matching places" hidden={hidden}>
      {hits.map((h, i) => (
        <li
          key={h.key}
          id={optionId(id, i)}
          role="option"
          aria-selected={i === cursor}
          className={`moon-place-option${i === cursor ? " selected" : ""}`}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onPick(h)}
        >
          <span className="moon-hit">
            <span>
              {h.label}
              {h.beyondMap && <span className="tag moon-edge-tag">beyond map edge</span>}
            </span>
            <span className="muted small">{h.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Named lunar features (IAU Gazetteer) and "lat, lon" coordinates. Everything resolves locally. */
export default function MoonPlaceSearch({ index, status, onFocus, onGo }: Props) {
  const listId = useId();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const hits = useMemo(() => moonSearch(index, q), [index, q]);
  // New results (typing, or the gazetteer arriving) start from the first row again.
  const [cursorHits, setCursorHits] = useState(hits);
  if (cursorHits !== hits) {
    setCursorHits(hits);
    setCursor(0);
  }
  const showList = open && q.trim().length >= 2;
  const listShown = showList && hits.length > 0;
  const message = showList ? searchStatusMessage(hits, index, status, q) : null;

  function go(h: MoonPlaceHit) {
    onGo(h);
    setOpen(false);
    setQ(h.label);
  }

  return (
    <div className="place-search moon-place-search">
      <Icon name="search" size={19} />
      <input
        value={q}
        placeholder="Search a crater, mare or coordinates"
        aria-label="Search places on the Moon"
        role="combobox"
        aria-expanded={listShown}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={listShown && hits[cursor] ? optionId(listId, cursor) : undefined}
        onFocus={() => {
          onFocus();
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          setQ(e.target.value);
          setCursor(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setCursor((c) => moveCursor(c, 1, hits.length));
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setCursor((c) => moveCursor(c, -1, hits.length));
          }
          if (e.key === "Enter" && hits[cursor]) go(hits[cursor]);
        }}
      />
      <div className="moon-place-popup">
        <MoonPlaceOptions id={listId} hits={hits} cursor={cursor} hidden={!listShown} onPick={go} />
        {/* Outside the listbox and always present, so screen readers announce the messages. */}
        <div className="moon-place-status" role="status" aria-live="polite">
          {message && (
            <div className="place-results">
              <p className={`${message.warn ? "warn" : "muted"} small pad`}>{message.text}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
