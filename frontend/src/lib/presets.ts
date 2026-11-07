/**
 * Real example buildings (GET /api/building-presets) -> Build-tab form state. Pure, so it is tested
 * without the UI. A preset is not a template: the draft uses the type's own template, and its cited
 * provenance is kept per section until the user edits that section.
 */
import type { BuildingPreset, BuildingType } from "./buildings";
import { statsToDraft, type StatsDraft } from "./buildingForm";

export type PresetForm = {
  type: BuildingType;
  name: string;
  description: string;
  stats: StatsDraft;
};

export function presetToForm(preset: BuildingPreset): PresetForm {
  return {
    type: preset.type,
    name: preset.name,
    description: preset.description,
    stats: { ...statsToDraft(preset.stats, preset.parameters), basedOn: preset.name },
  };
}

/** "Hoover Dam, United States". */
export function presetPlace(preset: Pick<BuildingPreset, "referenceSite">): string {
  const { name, country } = preset.referenceSite;
  return country ? `${name}, ${country}` : name;
}

export const sourceCount = (n: number) => `${n} source${n === 1 ? "" : "s"}`;

