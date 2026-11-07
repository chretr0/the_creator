import { useState } from "react";
import { parseCoordinates, searchLocal, searchPhoton, type PlaceHit, type SearchEntry } from "../lib/context";

type Props = {
  index: SearchEntry[] | null;
  onFocus: () => void;
  onGo: (hit: PlaceHit) => void;
};

/** Coordinates and bundled region names resolve with no network; Photon only runs on Enter / "search more". */
export default function PlaceSearch({ index, onFocus, onGo }: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [remote, setRemote] = useState<PlaceHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const coord = parseCoordinates(q);
  const local = coord ? [coord] : index ? searchLocal(index, q) : [];
  const hits = remote ? [...local, ...remote.filter((r) => !local.some((l) => l.label === r.label))] : local;

  async function more() {
    if (q.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setRemote(await searchPhoton(q.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function go(h: PlaceHit) {
    onGo(h);
    setOpen(false);
    setQ(h.label);
  }

  return (
    <div className="place-search">
      <input
        value={q}
        placeholder="Search places or lat, lon"
        aria-label="Search places"
        onFocus={() => {
          onFocus();
          setOpen(true);
        }}
        onChange={(e) => {
          setQ(e.target.value);
          setRemote(null);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter") {
            if (hits[0] && (local.length || remote)) go(hits[0]);
            else more();
          }
        }}
      />
      {open && q.trim().length >= 2 && (
        <ul className="place-results">
          {hits.map((h) => (
            <li key={h.key}>
              <button className="link" onClick={() => go(h)}>
                <span>
                  {h.label}
                  <span className="muted small"> {h.detail}</span>
                </span>
                {h.source === "photon" && <span className="muted small right">Photon</span>}
              </button>
            </li>
          ))}
          {!remote && !coord && (
            <li>
              <button className="link muted" disabled={busy} onClick={more}>
                {busy ? "Searching…" : `Search more places for “${q.trim()}” (Photon)`}
              </button>
            </li>
          )}
          {remote && remote.length === 0 && <li className="muted small pad">No more results.</li>}
          {error && <li className="warn small pad">{error}</li>}
          {remote && <li className="muted small pad">Search by Photon (komoot) · © OpenStreetMap contributors</li>}
        </ul>
      )}
    </div>
  );
}
