import { TIER_COLOUR, TIER_LABEL, type FactorGrade, type Suitability, type SuitabilityFactor, type SuitabilityTier } from "../lib/buildings";
import { factorGroups } from "../lib/suitability";
import Icon from "./Icon";

const rgb = (c: [number, number, number]) => `rgb(${c.join(",")})`;

export function TierBadge({ tier }: { tier: SuitabilityTier | null }) {
  const colour = tier ? rgb(TIER_COLOUR[tier]) : undefined;
  return (
    <span className={`badge tier-badge tier-${tier ?? "none"}`} style={colour ? { borderColor: colour } : undefined}>
      <span className="dot" style={{ background: colour ?? "var(--muted)" }} />
      {tier ? `${TIER_LABEL[tier]} site` : "Not graded"}
    </span>
  );
}

type Props = {
  suitability: Suitability;
  /** The Build map's screening overlay is coloured by this factor (or "overall"); omit outside the Build map. */
  colourBy?: string;
  onColourBy?: (key: string) => void;
};

function FactorRow({ factor, grade, mapped, onMap }: { factor: SuitabilityFactor; grade: FactorGrade | undefined; mapped: boolean; onMap?: () => void }) {
  const tier = grade?.tier ?? null;
  return (
    <li className={`factor factor-${tier ?? "none"}`} title={`${factor.why}\n${factor.bands}\nSource: ${factor.source}`}>
      <span className="factor-dot" style={{ background: tier ? rgb(TIER_COLOUR[tier]) : "transparent" }} />
      <span className="factor-label">
        {factor.label}
        {factor.constraint && <span className="factor-limit">limit</span>}
      </span>
      <span className="factor-value num">{grade?.display ?? "no data"}</span>
      <span className="factor-tier">{tier ? TIER_LABEL[tier] : "—"}</span>
      {onMap ? <button
        type="button"
        className={`ghost factor-map${mapped ? " active" : ""}`}
        aria-pressed={mapped}
        aria-label={`Colour the map by ${factor.label.toLowerCase()}`}
        title={mapped ? "Shown on the map" : "Colour the map by this factor"}
        onClick={onMap}
      >
        <Icon name="hexagon" size={13} />
      </button> : <span />}
      {tier !== "ideal" && grade?.explanation && <small className="factor-explanation">{grade.explanation}</small>}
    </li>
  );
}

/** How ideal the clicked site is for the building type, factor by factor. */
export default function SuitabilityView({ suitability, colourBy, onColourBy }: Props) {
  const { profile } = suitability;
  const grades = new Map(suitability.factors.map((g) => [g.key, g]));
  const graded = suitability.factors.filter((g) => g.tier).length;
  return (
    <div className="site-panel-section suitability-view">
      <h4>
        Site quality <span className="muted small">{profile.label}</span>
      </h4>
      <div className="suitability-verdict">
        <TierBadge tier={suitability.tier} />
        {onColourBy && (
          <button type="button" className={`link inline small${colourBy === "overall" ? " active" : ""}`} onClick={() => onColourBy("overall")}>
            Map the overall grade
          </button>
        )}
      </div>
      <p className="small suitability-summary">{suitability.summary}</p>
      <ul className="factor-list">
        {factorGroups(profile).map((g) => (
          <li key={g.group} className="factor-group">
            <span className="factor-group-name">{g.group}</span>
            <ul>
              {g.factors.map((f) => (
                <FactorRow
                  key={f.key}
                  factor={f}
                  grade={grades.get(f.key)}
                  mapped={colourBy === f.key}
                  onMap={onColourBy && (() => onColourBy(colourBy === f.key ? "overall" : f.key))}
                />
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <details className="suitability-method small">
        <summary>How the grade works</summary>
        <p>{profile.method}</p>
        <p className="muted">
          {suitability.score !== null ? `Score here ${suitability.score.toFixed(2)} of 3, ` : ""}
          graded on {graded} of {profile.factors.length} factors ({Math.round(suitability.coverage * 100)}% of the weight).
          Weights: {profile.factors.map((f) => `${f.label.toLowerCase()} ${f.weight}`).join(", ")}.
        </p>
      </details>
    </div>
  );
}
