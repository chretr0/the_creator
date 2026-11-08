import { describe, expect, it } from "vitest";
import type { Quantity } from "./buildings";
import { averageKw, balance, countByType, fmtSigned, fmtTotal, totalState, uniqueNames } from "./worldTotals";

const q = (value: number | null, missing: string[] = [], unit = "kWh"): Quantity => ({ value, unit, basis: "", missing });

describe("fmtTotal", () => {
  it("moves big totals into readable units", () => {
    expect(fmtTotal(850, "kWh")).toBe("850 kWh");
    expect(fmtTotal(24_000, "kWh")).toBe("24 MWh");
    expect(fmtTotal(3_456_000, "kWh")).toBe("3.46 GWh");
    expect(fmtTotal(2_500_000, "kW")).toBe("2.5 GW");
    expect(fmtTotal(5_000_000, "kg")).toBe("5,000 t");
    expect(fmtTotal(5e9, "kg")).toBe("5 million t");
    expect(fmtTotal(2_500, "m²")).toBe("2,500 m²");
    expect(fmtTotal(45_000, "m²")).toBe("4.5 ha");
    expect(fmtTotal(3_000_000, "m²")).toBe("3 km²");
  });
  it("writes large amounts in words and keeps the currency", () => {
    expect(fmtTotal(1_234_567_890, "USD")).toBe("1.23 billion USD");
    expect(fmtTotal(35, "people")).toBe("35 people");
    expect(fmtTotal(10, "unspecified currency")).toBe("10 (no currency given)");
  });
  it("never shows unknown as zero", () => {
    expect(fmtTotal(null, "kWh")).toBe("unknown");
    expect(fmtTotal(0, "kWh")).toBe("0 kWh");
    expect(fmtTotal(0.000123, "kg")).toBe("0.000123 kg");
  });
  it("signs balances", () => {
    expect(fmtSigned(24_000, "kWh")).toBe("+24 MWh");
    expect(fmtSigned(-300_000, "kWh")).toBe("−300 MWh");
    expect(fmtSigned(0, "kWh")).toBe("0 kWh");
    expect(fmtSigned(null, "kWh")).toBe("unknown");
  });
});

describe("balance", () => {
  it("treats a building that makes nothing as making 0, but keeps unknowns unknown", () => {
    expect(balance(q(1000), q(200))).toBe(800);
    expect(balance(q(null), q(200))).toBe(-200); // not a producer: nothing missing
    expect(balance(q(null, ["output"]), q(200))).toBeNull();
    expect(balance(q(1000), q(null, ["demand"]))).toBeNull();
  });
});

it("averages energy over every hour of the period", () => {
  expect(averageKw(24_000, 1)).toBe(1000);
  expect(averageKw(null, 1)).toBeNull();
  expect(averageKw(10, 0)).toBeNull();
});

it("tells complete, partial, unknown and empty totals apart", () => {
  expect(totalState(q(5))).toBe("complete");
  expect(totalState(q(5, ["x"]))).toBe("partial");
  expect(totalState(q(null, ["x"]))).toBe("unknown");
  expect(totalState(q(null))).toBe("none");
});

it("counts buildings by type, most common first", () => {
  expect(countByType([{ type: "solar" }, { type: "office" }, { type: "office" }])).toEqual([
    { type: "office", count: 2 },
    { type: "solar", count: 1 },
  ]);
  expect(uniqueNames(["A", "B"], undefined, ["B", "C"])).toEqual(["A", "B", "C"]);
});
