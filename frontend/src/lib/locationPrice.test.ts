import { describe, expect, it } from "vitest";
import type { LocationPriceOffer, PriceSource } from "./buildings";
import { applyLocationPrice, editValue, parseStats, removeLocationPrice, statsToDraft } from "./buildingForm";

const SRC: PriceSource = {
  kind: "location_default",
  value: 0.1245,
  currency: "USD",
  customer: "business",
  h3Id: "8629b6d37ffffff",
  priceArea: "US-AZ",
  priceAreaName: "United States of America · Arizona",
  basis: "USD 0.1245/kWh · 2025 · EIA",
  source: "PRICE-01 Electricity price (average), Business",
};
const OFFER: LocationPriceOffer = { resource: "electricity", unit: "USD/kWh", price: SRC, status: "available", message: "" };

describe("location-default utility prices", () => {
  it("are blank until explicitly applied", () => {
    const { stats } = parseStats(statsToDraft({}), []);
    expect(stats.costs?.electricityPricePerKwh).toBeNull();
    expect(stats.costs?.electricityPriceSource).toBeNull();
  });

  it("apply the price with its source and set a blank currency to USD", () => {
    const d = applyLocationPrice(statsToDraft({}), OFFER);
    const { stats, errors } = parseStats(d, []);
    expect(errors).toEqual({});
    expect(stats.costs?.electricityPricePerKwh).toBe(0.1245);
    expect(stats.costs?.currency).toBe("USD");
    expect(stats.costs?.electricityPriceSource?.priceArea).toBe("US-AZ");
  });

  it("never apply to costs in another currency", () => {
    const d = statsToDraft({ costs: { currency: "EUR" } });
    expect(applyLocationPrice(d, OFFER)).toBe(d);
  });

  it("do not replace a typed price", () => {
    const d = editValue(statsToDraft({ costs: { currency: "USD" } }), "costs.electricityPricePerKwh", "0.3");
    expect(applyLocationPrice(d, OFFER)).toBe(d);
  });

  it("become the user's own price once the price is typed over", () => {
    const d = editValue(applyLocationPrice(statsToDraft({}), OFFER), "costs.electricityPricePerKwh", "0.2");
    const { stats } = parseStats(d, []);
    expect(stats.costs?.electricityPricePerKwh).toBe(0.2);
    expect(stats.costs?.electricityPriceSource).toBeNull();
  });

  it("flag a currency changed after applying instead of mixing currencies", () => {
    const d = editValue(applyLocationPrice(statsToDraft({}), OFFER), "costs.currency", "EUR");
    expect(parseStats(d, []).errors["costs.electricityPricePerKwh"]).toMatch(/never converted/);
  });

  it("round-trip through a saved definition and can be removed", () => {
    const saved = parseStats(applyLocationPrice(statsToDraft({}), OFFER), []).stats;
    const reloaded = statsToDraft(saved);
    expect(reloaded.priceSources.electricity?.value).toBe(0.1245);
    const removed = parseStats(removeLocationPrice(reloaded, "electricity"), []).stats;
    expect(removed.costs?.electricityPricePerKwh).toBeNull();
    expect(removed.costs?.electricityPriceSource).toBeNull();
  });
});
