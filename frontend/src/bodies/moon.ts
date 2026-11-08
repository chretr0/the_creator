import type { StyleSpecification } from "maplibre-gl";
import type { Body } from "./types";

/** IAU 2015 mean lunar radius (Moon Mean-Earth frame), used for every Moon length and area. */
export const MOON_RADIUS_KM = 1737.4;

const LROC_WMS = "https://wms.im-ldi.com/";

/**
 * MOON-MAP-01: an LROC Lunaserv WMS layer as Web Mercator tiles (MapLibre fills `{bbox-epsg-3857}`
 * per 256-px tile). `transparent` keeps the areas without data see-through, for overlays such as
 * `luna_nomenclature` or `luna_psr_81s`. The service cuts off at ±85°, like every Web Mercator map.
 */
export function lrocWmsTiles(layer: string, transparent = false): string[] {
  const params = [
    "SERVICE=WMS",
    "REQUEST=GetMap",
    "VERSION=1.1.1",
    `LAYERS=${encodeURIComponent(layer)}`,
    "STYLES=",
    "SRS=EPSG:3857",
    "BBOX={bbox-epsg-3857}",
    "WIDTH=256",
    "HEIGHT=256",
    "FORMAT=image/png",
  ];
  if (transparent) params.push("TRANSPARENT=true");
  return [`${LROC_WMS}?${params.join("&")}`];
}

export const LROC_WAC_ATTRIBUTION = "LROC WAC mosaic: NASA/GSFC/Arizona State University";

/**
 * The WAC global mosaic is 100 m/px: about Web Mercator tile zoom 8.7 at the lunar equator
 * (2π·1737.4 km / 256 px / 2^z). Zoom 9 tiles are sharp; zoom 10 ones are visibly upsampled by the
 * server, so MapLibre over-zooms the zoom 9 tiles instead.
 */
export const LROC_WAC_MAXZOOM = 9;

const MOON_STYLE: StyleSpecification = {
  version: 8,
  name: "Moon (LROC WAC)",
  sources: {
    "lroc-wac": {
      type: "raster",
      tiles: lrocWmsTiles("luna_wac_global"),
      tileSize: 256,
      maxzoom: LROC_WAC_MAXZOOM,
      attribution: LROC_WAC_ATTRIBUTION,
    },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#000000" } },
    { id: "lroc-wac", type: "raster", source: "lroc-wac" },
  ],
};

export const MOON: Body = {
  id: "moon",
  name: "Moon",
  radiusKm: MOON_RADIUS_KM,
  style: MOON_STYLE,
  // The near side (centred on 0°, 0°).
  initialView: { center: [0, 0], zoom: 1.8 },
  themedBasemap: false,
  tilt: false,
  // Res-8 H3 cells (~0.15 km edge) are still ~30 px wide here; the mosaic itself is over-zoomed past ~10.
  maxZoom: 12,
  credits: [{ label: LROC_WAC_ATTRIBUTION, href: "https://lroc.im-ldi.com/" }],
};
