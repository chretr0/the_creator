import { describe, expect, it } from "vitest";
import { cellSetKey, EMPTY_CACHE, IDLE_STATUS, LOADING_STATUS, mergeCellValues, planValuesRequest, type CellCache } from "./h3Cache";

const cache = (layerId: string, entries: [string, number | null][], served: [string, number][] = []): CellCache => ({
  layerId,
  values: new Map(entries),
  served: new Map(served),
});

describe("cellSetKey", () => {
  it("changes when cells between the first and the last change (same count)", () => {
    // The old key was `${length}:${first}:${last}`, identical for these two views.
    const before = ["861a00007ffffff", "861a0000fffffff", "861a00017ffffff", "861a0001fffffff"];
    const after = ["861a00007ffffff", "861a00027ffffff", "861a0002fffffff", "861a0001fffffff"];
    expect(cellSetKey(before)).not.toBe(cellSetKey(after));
  });

  it("is stable for the same cells and empty for no cells", () => {
    const cells = ["861a00007ffffff", "861a0000fffffff"];
    expect(cellSetKey(cells)).toBe(cellSetKey([...cells]));
    expect(cellSetKey([])).toBe("");
  });

  it("does not run ids together", () => {
    expect(cellSetKey(["ab", "c"])).not.toBe(cellSetKey(["a", "bc"]));
  });
});

describe("planValuesRequest", () => {
  it("requests only uncached cells of the active layer and shows loading", () => {
    const plan = planValuesRequest("elevation", ["a", "b", "c"], cache("elevation", [["a", 1], ["b", null]]));
    expect(plan.missing).toEqual(["c"]);
    expect(plan.status).toBe(LOADING_STATUS);
  });

  it("is idle for a fully cached view, so a stale 'Loading…' or error is cleared", () => {
    const plan = planValuesRequest("elevation", ["a", "b"], cache("elevation", [["a", 1], ["b", null]]));
    expect(plan.missing).toEqual([]);
    expect(plan.status).toBe(IDLE_STATUS);
    expect(plan.status).toEqual({ loading: false, error: null, notPrepared: false });
  });

  it("is idle without an active layer", () => {
    expect(planValuesRequest(null, ["a"], EMPTY_CACHE)).toEqual({ missing: [], status: IDLE_STATUS });
  });

  it("ignores another layer's cache", () => {
    expect(planValuesRequest("slope", ["a", "b"], cache("elevation", [["a", 1]])).missing).toEqual(["a", "b"]);
  });
});

describe("mergeCellValues", () => {
  it("adds the requested cells, keeping null for missing or non-finite values", () => {
    const next = mergeCellValues(
      cache("elevation", [["a", 5]], [["a", 4]]),
      "elevation",
      ["b", "c", "d"],
      { values: { b: -120, c: null, d: Number.NaN }, servedResolution: { b: 4 } },
      ["a", "b", "c", "d"],
    );
    expect([...next.values]).toEqual([
      ["a", 5],
      ["b", -120],
      ["c", null],
      ["d", null],
    ]);
    expect(next.served.get("b")).toBe(4);
    expect(next.served.get("c")).toBeUndefined();
  });

  it("keeps a zero value as 0, not null", () => {
    const next = mergeCellValues(EMPTY_CACHE, "elevation", ["a"], { values: { a: 0 }, servedResolution: {} }, ["a"]);
    expect(next.values.get("a")).toBe(0);
  });

  it("keeps the on-screen cells when the full cache starts afresh", () => {
    // Cache at its cap: on screen are x (cached) and y (just requested); z is off screen.
    const full = cache("elevation", [["x", 10], ["z", 30]], [["x", 5], ["z", 5]]);
    const next = mergeCellValues(full, "elevation", ["y"], { values: { y: 20 }, servedResolution: { y: 5 } }, ["x", "y"], 2);
    expect(next.values.get("x")).toBe(10);
    expect(next.served.get("x")).toBe(5);
    expect(next.values.get("y")).toBe(20);
    expect(next.values.has("z")).toBe(false);
    expect(next.values.size).toBe(2);
  });

  it("drops another layer's values", () => {
    const next = mergeCellValues(cache("slope", [["a", 3]]), "elevation", ["b"], { values: { b: 1 }, servedResolution: {} }, ["a", "b"]);
    expect(next.layerId).toBe("elevation");
    expect(next.values.has("a")).toBe(false);
    expect(next.values.get("b")).toBe(1);
  });
});
