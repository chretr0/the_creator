import { useMemo } from "react";
import { formatKw } from "../lib/infrastructure";
import { DATASET_LABEL, METRIC, runQuery, type Dataset, type Query, type QueryRecord } from "../lib/query";

type Props = {
  records: QueryRecord[];
  available: Record<Dataset, boolean>;
  query: Query;
  onQuery: (q: Query) => void;
  near: { lat: number; lon: number } | null;
  onPick: (r: QueryRecord) => void;
};

const SORT_LABEL: Record<Query["sort"], string> = {
  metric: "Largest value first",
  company: "Most-mapped operator first",
  nearest: "Nearest to map centre",
  newest: "Newest first",
  name: "Name",
};

function formatMetric(dataset: Dataset, v: number | null): string {
  if (v === null) return "—";
  const m = METRIC[dataset];
  if (!m) return "—";
  if (m.unit === "kW") return formatKw(v);
  if (dataset === "earthquakes") return `M${v.toFixed(1)}`;
  return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${m.unit}`;
}

export default function SearchPanel({ records, available, query, onQuery, near, onPick }: Props) {
  const set = (patch: Partial<Query>) => onQuery({ ...query, ...patch });
  const inDataset = useMemo(() => records.filter((r) => r.dataset === query.dataset), [records, query.dataset]);
  const countries = useMemo(
    () => [...new Set(inDataset.map((r) => r.country).filter((c): c is string => !!c))].sort(),
    [inDataset],
  );
  const admin1s = useMemo(
    () =>
      query.country
        ? [...new Set(inDataset.filter((r) => r.country === query.country).map((r) => r.admin1).filter((a): a is string => !!a))].sort()
        : [],
    [inDataset, query.country],
  );
  const result = useMemo(() => runQuery(records, { ...query, near, limit: 30 }), [records, query, near]);
  const metric = METRIC[query.dataset];
  const sorts: Query["sort"][] = ["metric", "company", "nearest", "newest", "name"].filter((s) => {
    if (s === "metric") return !!metric;
    if (s === "company") return query.dataset === "datacenters" || query.dataset === "dams";
    if (s === "newest") return query.dataset === "earthquakes" || query.dataset === "fires";
    return true;
  }) as Query["sort"][];

  return (
    <section className="panel">
      <h2>Search & rank</h2>
      <div className="row">
        <label className="field">
          <span>Dataset</span>
          <select
            value={query.dataset}
            onChange={(e) => {
              const dataset = e.target.value as Dataset;
              onQuery({ ...query, dataset, country: null, admin1: null, sort: METRIC[dataset] ? "metric" : "name" });
            }}
          >
            {(Object.keys(DATASET_LABEL) as Dataset[]).map((d) => (
              <option key={d} value={d} disabled={!available[d]}>
                {DATASET_LABEL[d]}
                {available[d] ? "" : " (turn layer on)"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Sort</span>
          <select value={sorts.includes(query.sort) ? query.sort : sorts[0]} onChange={(e) => set({ sort: e.target.value as Query["sort"] })}>
            {sorts.map((s) => (
              <option key={s} value={s}>
                {SORT_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <label className="field">
          <span>Country</span>
          <select value={query.country ?? ""} onChange={(e) => set({ country: e.target.value || null, admin1: null })}>
            <option value="">Anywhere</option>
            {countries.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>State / province</span>
          <select value={query.admin1 ?? ""} disabled={!query.country} onChange={(e) => set({ admin1: e.target.value || null })}>
            <option value="">All</option>
            {admin1s.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <label className="field">
          <span>Operator / owner contains</span>
          <input value={query.operator ?? ""} onChange={(e) => set({ operator: e.target.value })} placeholder="e.g. Equinix" />
        </label>
        <label className="field">
          <span>Name contains</span>
          <input value={query.text ?? ""} onChange={(e) => set({ text: e.target.value })} />
        </label>
      </div>

      <p className="small">
        <strong>{result.total.toLocaleString()}</strong> match
        {metric && result.total > 0 && (
          <>
            {" "}
            · {result.metric.withValue} with a {metric.label.toLowerCase()}
            {result.metric.sum !== null && <> · tagged total {formatMetric(query.dataset, result.metric.sum)}</>}
            {result.metric.max !== null && <> · max {formatMetric(query.dataset, result.metric.max)}</>}
          </>
        )}
      </p>
      {result.operators.length > 0 && (
        <p className="muted small">Top operators: {result.operators.map((o) => `${o.name} (${o.count})`).join(", ")}</p>
      )}

      <ul className="list results">
        {result.items.map((r) => (
          <li key={r.key}>
            <button className="link" onClick={() => onPick(r)}>
              <span className="result-title">
                {r.title}
                <span className="muted small"> {[r.operator, r.admin1, r.country].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="small right mono">
                {query.sort === "nearest" && r.distanceKm !== null ? `${Math.round(r.distanceKm)} km` : formatMetric(r.dataset, r.metric)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="muted small">
        Ranks only by the criteria above, over what is loaded. Unknown values sort last, not as zero. Sums
        cover only the records that carry a value. Not a siting recommendation.
      </p>
    </section>
  );
}
