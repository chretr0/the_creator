import type { SourceCredit } from "../lib/context";
import { EVIDENCE_LABEL } from "../lib/datalayers";

type Props = { sources: SourceCredit[]; activeLayers: Set<string> };

/** Every source the app can show, with its licence and attribution text. Sources on the map now come first. */
export default function CreditsPanel({ sources, activeLayers }: Props) {
  const isActive = (s: SourceCredit) => s.layers.some((l) => activeLayers.has(l));
  const sorted = [...sources].sort((a, b) => Number(isActive(b)) - Number(isActive(a)));
  return (
    <section className="panel" id="data-credits">
      <h2>Data sources &amp; licences</h2>
      {sources.length === 0 && <p className="muted small">Source list unavailable.</p>}
      <ul className="list credits">
        {sorted.map((s) => {
          const active = isActive(s);
          return (
            <li key={s.id} className={active ? "" : "inactive"}>
              <details>
                <summary>
                  <span className={`dot ${active ? "on" : ""}`} aria-label={active ? "On the map now" : undefined} />
                  <span className="source-name">{s.name}
                    {s.commercialUse === false && <span className="badge warn">non-commercial</span>}
                  </span>
                </summary>
                <dl className="kv small">
                  <dt>Licence</dt>
                  <dd>{s.licence}</dd>
                  <dt>Attribution</dt>
                  <dd>{s.attribution || "—"}</dd>
                  <dt>Evidence</dt>
                  <dd>{EVIDENCE_LABEL[s.evidenceType] ?? s.evidenceType.replace(/_/g, " ")}</dd>
                  {s.retrievedAt && (
                    <>
                      <dt>Retrieved</dt>
                      <dd>{s.retrievedAt}</dd>
                    </>
                  )}
                  {s.url && (
                    <>
                      <dt>Link</dt>
                      <dd>
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.url.replace(/^https?:\/\//, "")}
                        </a>
                      </dd>
                    </>
                  )}
                </dl>
                {(s.limitations?.length || s.notes) && (
                  <ul className="limitations small muted">
                    {s.notes && <li>{s.notes}</li>}
                    {s.limitations?.map((l) => <li key={l}>{l}</li>)}
                  </ul>
                )}
              </details>
            </li>
          );
        })}
      </ul>
      <p className="muted small">Filled dot = shown on the map now. Each source keeps its own licence.</p>
    </section>
  );
}
