import { EARTH } from "./earth";
import { MOON } from "./moon";
import type { Body, BodyId } from "./types";

export type { Body, BodyId } from "./types";

export const BODIES: Record<BodyId, Body> = { earth: EARTH, moon: MOON };

/** In display order (the body switch shows them left to right). */
export const BODY_IDS: BodyId[] = ["earth", "moon"];

export function isBodyId(x: unknown): x is BodyId {
  return typeof x === "string" && (BODY_IDS as string[]).includes(x);
}
