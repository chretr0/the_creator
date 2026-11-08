import type { StyleSpecification } from "maplibre-gl";

/** A celestial body the app can map. Earth and Moon share the H3 grid; only lengths (×R) and areas (×R²) differ. */
export type BodyId = "earth" | "moon";

export type Body = {
  id: BodyId;
  /** Display name, e.g. "Earth" or "Moon". */
  name: string;
  /** Mean (authalic) radius used for every length and area on this body. */
  radiusKm: number;
  /** MapLibre basemap: a style URL or an inline style. */
  style: string | StyleSpecification;
  initialView: { center: [number, number]; zoom: number };
  /** Day/night repaint of the basemap (Earth's vector basemap only). */
  themedBasemap: boolean;
  /** 3D tilt and building volumes are available. */
  tilt: boolean;
  maxZoom: number;
  credits: { label: string; href?: string }[];
};
