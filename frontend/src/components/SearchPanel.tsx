import { useEffect, useMemo, useState } from "react";
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
  metric: "Largest first",
  company: "Biggest operator",
  nearest: "Nearest",
  newest: "Newest",
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
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [query]);
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
  const currentPage = Math.min(page, Math.max(0, Math.ceil(result.items.length / 5) - 1));
  const metric = METRIC[query.dataset];
  const sorts: Query["sort"][] = ["metric", "company", "nearest", "newest", "name"].filter((s) => {
    if (s === "metric") return !!metric;
    if (s === "company") return query.dataset === "datacenters" || query.dataset === "dams";
    if (s === "newest") return query.dataset === "earthquakes" || query.dataset === "fires";
    return true;
  }) as Query["sort"][];

  return (
    <section className="panel">
      <h2>Search</h2>
      <div className="row">
        <label className="field">
          <span>Find</span>
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
                {available[d] ? "" : " (turn on in Data layers)"}
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
      <details className="section"><summary><span className="section-title">Refine results</span><span className="section-meta">Place, operator & name</span></summary><div className="section-body">
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
          <span>State / region</span>
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
          <span>Operator</span>
          <input value={query.operator ?? ""} onChange={(e) => set({ operator: e.target.value })} placeholder="e.g. Equinix" />
        </label>
        <label className="field">
          <span>Name</span>
          <input value={query.text ?? ""} onChange={(e) => set({ text: e.target.value })} placeholder="Any" />
        </label>
      </div>

      </div></details>
      <h3>
        {result.total.toLocaleString()} result{result.total === 1 ? "" : "s"}
        {metric && result.metric.sum !== null && result.total > 0 && <> · {formatMetric(query.dataset, result.metric.sum)} total</>}
      </h3>
      <ul className="list results">
        {result.items.slice(currentPage * 5, currentPage * 5 + 5).map((r) => (
          <li key={r.key}>
            <button className="link" onClick={() => onPick(r)}>
              <span className="result-title">
                {r.title}
                <span className="muted small" style={{ display: "block" }}>{[r.operator, r.admin1, r.country].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="small right num" style={{ whiteSpace: "nowrap" }}>
                {query.sort === "nearest" && r.distanceKm !== null ? `${Math.round(r.distanceKm)} km` : formatMetric(r.dataset, r.metric)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {result.items.length > 5 && <div className="pagination"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>{currentPage * 5 + 1}–{Math.min(currentPage * 5 + 5, result.items.length)} of {result.items.length}</span><button disabled={(currentPage + 1) * 5 >= result.items.length} onClick={() => setPage(currentPage + 1)}>Next results</button></div>}
      {result.total > result.items.length && <p className="muted small">Showing the first {result.items.length} matches. Refine results to narrow your search.</p>}
    </section>
  );
}
