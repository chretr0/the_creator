import { describe, expect, it } from "vitest";
import { MEDIA, POLLUTANTS, pollutantKey, pollutantsFor, releaseMedium } from "./pollutants";
import { criterionToDraft, isAirPollutant, parseCriteria, parseStats, siteNeeds, statsToDraft } from "./buildingForm";

describe("pollutant catalogue and saved forms", () => {
  it("recognises every dropdown label and alias without changing mass bases", () => {
    for (const p of POLLUTANTS) for (const alias of [p.id, p.label, ...p.aliases]) expect(pollutantKey(alias)).toBe(p.id);
    expect(pollutantKey("NOx (as NO2)")).not.toBe("nox");
    for (const medium of Object.keys(MEDIA) as (keyof typeof MEDIA)[]) expect(pollutantsFor(medium).length).toBeGreaterThan(0);
  });
  it("round-trips each pollutant/destination through the building form", () => {
    for (const medium of Object.keys(MEDIA) as (keyof typeof MEDIA)[]) for (const p of pollutantsFor(medium)) {
      const draft = statsToDraft({ operatingHoursPerDay: 24, emissions: [{ id: "e", pollutant: p.label, medium, rateKgPerHour: 10 }] });
      const { stats, errors } = parseStats(draft, []);
      expect(errors).toEqual({});
      expect(stats.emissions?.[0]).toMatchObject({ pollutant: p.label, medium, rateKgPerHour: 10 });
    }
  });
  it("keeps existing CO2e wording while resolving its destination", () => {
    const label = "CO2e (market-based Scope 1+2)";
    const draft = statsToDraft({ emissions: [{ id: "e", pollutant: label, rateKgPerHour: 200 }] });
    expect(draft.emissions[0].medium).toBe("climate");
    expect(parseStats(draft, []).stats.emissions?.[0].pollutant).toBe(label);
    expect(releaseMedium(label)).toBe("climate");
  });
  it("keeps limits tied to the selected receiving environment", () => {
    const draft = criterionToDraft({ id: "c", kind: "emission_limit", required: true, pollutant: "Lead", medium: "soil", amount: 100 });
    expect(parseCriteria([draft]).criteria[0]).toMatchObject({ pollutant: "Lead", medium: "soil", amount: 100 });
  });
  it("detects catalogue air labels and excludes water releases from air checks", () => {
    expect(isAirPollutant("Fine particles (PM2.5)")).toBe(true);
    expect(isAirPollutant("Lead")).toBe(true);
    expect(isAirPollutant("Greenhouse gases (CO₂e)")).toBe(false);
    const stats = { emissions: [{ id: "e", pollutant: "Ammonia (NH₃)", medium: "freshwater" as const, rateKgPerHour: 10 }] };
    expect(siteNeeds(stats, {}, "factory").find((n) => n.key === "air")?.hint).toContain("No local air pollutants");
  });
});

it("does not mistake the phrase CO2 emissions for CO2 equivalents", () => {
  expect(pollutantKey("CO2 emissions")).not.toBe("co2e");
});
