import { useId, useState } from "react";
import { effectiveColourBy, factorGroups, factorIndex, legendRows, type ColourBy, type ScreenedArea } from "../lib/suitability";

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

type Props = {
  area: ScreenedArea;
  colourBy: ColourBy;
  onColourBy: (by: ColourBy) => void;
  loading: boolean;
  /** Set when the result is out of date and can't be refreshed now: says why (e.g. "Zoom in …"). */
  staleNote?: string | null;
};

/** Map legend for the live screening: the grade (or one factor) per hexagon, with counts. */
export default function SuitabilityLegend({ area, colourBy, onColourBy, loading, staleNote }: Props) {
  const id = useId();
  const profile = area.profile;
  const by = effectiveColourBy(profile, colourBy);
  const factor = profile && by !== "overall" ? profile.factors[factorIndex(profile, by)] : null;
  const rows = legendRows(area, by);
  /** Phones: the legend starts as a one-line strip of swatches and counts (the map there is short). */
  const [expanded, setExpanded] = useState(false);

  if (area.stale) {
    return (
      <div className="map-legend suitability-legend small" aria-label="Screening legend">
        <div className="suitability-legend-head">
          <strong>Out of date</strong>
          <span className="muted block">The map still shows an earlier version of the building{profile ? ` (${profile.label})` : ""}.</span>
        </div>
        {staleNote && <p className="suitability-legend-note">{staleNote}</p>}
      </div>
    );
  }

  return (
    <div className={`map-legend suitability-legend small${expanded ? " expanded" : ""}`} aria-label="Screening legend">
      <div className="suitability-legend-head">
        <strong>{profile ? "How ideal each site is" : "Where it fits"}</strong>
        {loading && <span className="muted"> · updating…</span>}
        <button type="button" className="ghost suitability-legend-toggle" aria-expanded={expanded} onClick={() => setExpanded((x) => !x)}>
          {expanded ? "Less" : "More"}
        </button>
        {profile && <span className="muted block">{profile.label}</span>}
      </div>
      <ul className="suitability-legend-strip" aria-hidden="true">
        {rows.map((r) => (
          <li key={r.key} title={`${r.label}: ${r.count.toLocaleString()}`}>
            <span className="swatch" style={{ background: rgb(r.colour), opacity: r.faded ? 0.55 : 1 }} />
            {r.count.toLocaleString()}
          </li>
        ))}
      </ul>
      <div className="suitability-legend-body">
      {profile && (
        <label className="suitability-colour-by" htmlFor={`${id}-by`}>
          <span>Colour by</span>
          <select id={`${id}-by`} value={by} onChange={(e) => onColourBy(e.target.value)}>
            <option value="overall">Overall grade</option>
            {factorGroups(profile).map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.factors.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      )}
      <ul className="legend single">
        {rows.map((r) => (
          <li key={r.key} className={r.faded ? "muted" : undefined}>
            <span className="swatch" style={{ background: rgb(r.colour), opacity: r.faded ? 0.55 : 1 }} />
            {r.label}
            <span className="right num">{r.count.toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {factor ? (
        <p className="suitability-legend-note" title={factor.why}>
          {factor.bands}
          <span className="block muted">
            {factor.source}
            {factor.constraint ? " · a hard limit" : ""}
          </span>
        </p>
      ) : profile ? (
        <details className="suitability-legend-note">
          <summary>How the grade works</summary>
          <p>{profile.method}</p>
          <p className="muted">Paler hexagons: some site checks (water, grid, land …) can't be judged there yet.</p>
        </details>
      ) : null}
      </div>
    </div>
  );
}
