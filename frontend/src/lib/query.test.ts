import { describe, expect, it } from "vitest";
import { haversineKm, runQuery, type QueryRecord } from "./query";
import { parseCoordinates, searchLocal, type SearchEntry } from "./context";

const rec = (o: Partial<QueryRecord> & { key: string }): QueryRecord => ({
  dataset: "datacenters",
  title: o.key,
  lon: 0,
  lat: 0,
  country: null,
  admin1: null,
  operator: null,
  owner: null,
  metric: null,
  time: null,
  companyCount: null,
  ref: null,
  ...o,
});

const records = [
  rec({ key: "a", country: "France", operator: "Equinix", metric: 16000, lat: 48.85, lon: 2.35 }),
  rec({ key: "b", country: "France", operator: "Digital Realty", metric: null, lat: 43.3, lon: 5.37 }),
  rec({ key: "c", country: "Germany", operator: "Equinix", metric: 77400, lat: 50.11, lon: 8.68 }),
  rec({ key: "d", dataset: "dams", country: "France", metric: 5000 }),
];

describe("runQuery", () => {
  it("filters by dataset and region", () => {
    const r = runQuery(records, { dataset: "datacenters", country: "France", sort: "name" });
    expect(r.items.map((i) => i.key)).toEqual(["a", "b"]);
    expect(r.total).toBe(2);
  });

  it("ranks by metric with unknown values last, never as zero", () => {
    const r = runQuery(records, { dataset: "datacenters", sort: "metric" });
    expect(r.items.map((i) => i.key)).toEqual(["c", "a", "b"]);
    expect(r.metric).toEqual({ withValue: 2, sum: 93400, max: 77400 });
  });

  it("matches operator or owner text and counts operators", () => {
    const r = runQuery(records, { dataset: "datacenters", operator: "equi", sort: "name" });
    expect(r.total).toBe(2);
    expect(r.operators).toEqual([{ name: "Equinix", count: 2 }]);
  });

  it("sorts by distance from a point", () => {
    const r = runQuery(records, { dataset: "datacenters", sort: "nearest", near: { lat: 50, lon: 8 } });
    expect(r.items[0].key).toBe("c");
    expect(r.items[0].distanceKm).toBeLessThan(60);
  });
});

describe("haversineKm", () => {
  it("is about 344 km London–Paris", () => {
    expect(haversineKm({ lat: 51.5074, lon: -0.1278 }, { lat: 48.8566, lon: 2.3522 })).toBeCloseTo(343.5, 0);
  });
});

describe("place search", () => {
  const index: SearchEntry[] = [
    { id: "country:FRA", name: "France", level: "country", country: "France", state: null, bbox: [-5, 41, 10, 51], label: [2, 46] },
    { id: "admin1:US-AZ", name: "Arizona", level: "admin1", country: "United States of America", state: null, bbox: [-115, 31, -109, 37], label: [-111.7, 34.3] },
    { id: "us_county:04013", name: "Maricopa County", level: "us_county", country: "United States of America", state: "Arizona", bbox: [-113, 32.5, -111, 34], label: [-112.5, 33.3] },
  ];
  it("finds local regions by prefix", () => {
    expect(searchLocal(index, "mari").map((h) => h.key)).toEqual(["us_county:04013"]);
    expect(searchLocal(index, "fr")[0].label).toBe("France");
  });
  it("parses latitude-first coordinates", () => {
    expect(parseCoordinates("33.45, -112.07")).toMatchObject({ lat: 33.45, lon: -112.07 });
    expect(parseCoordinates("200, 1")).toBeNull();
    expect(parseCoordinates("Phoenix")).toBeNull();
  });
});
