/**
 * Map layers that only shade the ground (the hexagon grid, screening cells, the timeline overlay).
 * A click on one falls through to whatever record lies under or near the cursor, and never selects
 * the layer itself.
 */
export const BACKGROUND_LAYER_IDS: readonly string[] = ["grid", "assessment-cells", "timeline-impact"];

/** True for a built-in background layer or one of the map's `extra` ones (e.g. the Moon's keep-out rings). */
export function isBackgroundLayer(id: string | undefined, extra: readonly string[] = []): boolean {
  return id !== undefined && (BACKGROUND_LAYER_IDS.includes(id) || extra.includes(id));
}
