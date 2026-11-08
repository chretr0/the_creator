import catalogue from "../../../shared/pollutants.json";

export const MEDIA = { air: "Air", soil: "Soil", freshwater: "Rivers & freshwater", marine: "Sea & coastal water", climate: "Climate (CO₂e)" } as const;
export type ReleaseMedium = keyof typeof MEDIA;
export type Pollutant = { id: string; label: string; aliases: string[]; media: string[] };
export const POLLUTANTS: Pollutant[] = catalogue;
export function normalisePollutant(name: string): string {
  return name.toLowerCase().replace(/[₀-₉]/g, (c) => String(c.charCodeAt(0) - "₀".charCodeAt(0))).replace(/ₓ/g, "x").replace(/[^a-z0-9]/g, "");
}
const aliases = new Map(POLLUTANTS.flatMap((p) => [p.id, p.label, ...p.aliases].map((a) => [normalisePollutant(a), p.id])));
export function pollutantKey(name: string): string {
  const key = normalisePollutant(name);
  const text = name.toLowerCase().replace(/[₀-₉]/g, (c) => String(c.charCodeAt(0) - "₀".charCodeAt(0)));
  if (/\bco2\s*(?:e(?:q(?:uivalent)?)?|equivalent)\b|carbon\s*dioxide\s*equivalent/.test(text)) return "co2e";
  if (/scope2|scope12|scope1and2|scope1plus2/.test(key)) return key;
  if (aliases.has(key)) return aliases.get(key)!;
  if (/\bas\b/i.test(name)) return key;
  return aliases.get(normalisePollutant(name.split("(")[0])) ?? key;
}
export function releaseMedium(name: string, medium: ReleaseMedium = "air"): ReleaseMedium {
  return pollutantKey(name) === "co2e" ? "climate" : medium;
}
export function pollutantLabel(key: string, original?: string): string {
  return POLLUTANTS.find((p) => p.id === key)?.label ?? original ?? key;
}
export const pollutantsFor = (medium: ReleaseMedium) => POLLUTANTS.filter((p) => p.media.includes(medium));
