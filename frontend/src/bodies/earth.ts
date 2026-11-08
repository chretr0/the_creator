import type { Body } from "./types";

/** H3's authalic Earth radius, so areas from `radiusKm` equal h3's own km² exactly. */
export const EARTH_RADIUS_KM = 6371.007180918475;

export const EARTH: Body = {
  id: "earth",
  name: "Earth",
  radiusKm: EARTH_RADIUS_KM,
  // OpenFreeMap basemap (OSM data).
  style: "https://tiles.openfreemap.org/styles/liberty",
  initialView: { center: [10, 30], zoom: 1.6 },
  themedBasemap: true,
  tilt: true,
  // MapLibre's default, so the Earth map zooms exactly as before.
  maxZoom: 22,
  credits: [
    { label: "OpenFreeMap", href: "https://openfreemap.org" },
    { label: "© OpenMapTiles", href: "https://www.openmaptiles.org/" },
    { label: "OpenStreetMap", href: "https://www.openstreetmap.org/copyright" },
  ],
};
