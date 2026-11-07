import type { SourceCredit } from "../lib/context";

type Props = { sources: SourceCredit[]; activeLayers: Set<string> };

const EVIDENCE: Record<string, string> = {
  reported_record: "reported record",
  reference_geometry: "reference geometry",
  reference_map: "reference map",
  in_situ_observation: "in-situ observation",
  satellite_retrieval: "satellite retrieval",
  satellite_imagery: "satellite imagery",
  model_output: "model output",
  reference: "reference service",
};

export default function CreditsPanel({ sources, activeLayers }: Props) {
  const sorted = [...sources].sort(
    (a, b) => Number(b.layers.some((l) => activeLayers.has(l))) - Number(a.layers.some((l) => activeLayers.has(l))),
  );
  return (
    <section className="panel">
      <h2>Data sources</h2>
      <ul className="list credits">
        {sorted.map((s) => {
          const active = s.layers.some((l) => activeLayers.has(l));
          return (
            <li key={s.id} className={active ? "" : "inactive"}>
              <details>
                <summary>
                  <span className={`dot ${active ? "on" : ""}`} />
                  <span>{s.name}</span>
                  {s.commercialUse === false && <span className="badge warn">non-commercial</span>}
                </summary>
                <dl className="kv small">
                  <dt>Licence</dt>
                  <dd>{s.licence}</dd>
                  <dt>Attribution</dt>
                  <dd>{s.attribution}</dd>
                  <dt>Evidence</dt>
                  <dd>{EVIDENCE[s.evidenceType] ?? s.evidenceType}</dd>
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
      <p className="muted small">Filled dot = shown on the map now. Every layer keeps its own licence.</p>
    </section>
  );
}
