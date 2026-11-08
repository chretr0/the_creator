/**
 * Lengths and areas on any spherical body. H3 is defined on the unit sphere, so cell IDs are the same
 * on every body: only lengths (×R) and areas (×R²) change. Never use h3's km/m units or MapLibre's
 * metric helpers for a body other than Earth: both assume Earth's radius.
 */
import { cellArea, getHexagonEdgeLengthAvg, UNITS } from "h3-js";

const RAD = Math.PI / 180;

/** The radius h3 uses for its km/m units (its authalic Earth radius). */
const H3_EARTH_RADIUS_KM = 6371.007180918475;

/** MapLibre's tile size: zoom z spans 512·2^z pixels around the equator. */
const TILE_SIZE = 512;

/** Area of an H3 cell on a sphere of `radiusKm`. On Earth (h3's radius) this equals h3's own km². */
export function cellAreaKm2(h3: string, radiusKm: number): number {
  return cellArea(h3, UNITS.rads2) * radiusKm * radiusKm;
}

/** Average hexagon edge length at `resolution` on a sphere of `radiusKm`. */
export function edgeLengthKm(resolution: number, radiusKm: number): number {
  // h3-js only reports average edges in km or m (on its own Earth radius), so rescale to radians first.
  return (getHexagonEdgeLengthAvg(resolution, UNITS.km) / H3_EARTH_RADIUS_KM) * radiusKm;
}

/** Great-circle (haversine) distance between two lat/lon points in degrees. */
export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number, radiusKm: number): number {
  const dLat = (lat2 - lat1) * RAD;
  const dLon = (lon2 - lon1) * RAD;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * radiusKm * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Ground metres per screen pixel in Web Mercator at `latitude` and MapLibre `zoom` (512-px tiles), untilted. */
export function metresPerPixel(latitude: number, zoom: number, radiusKm: number): number {
  return (2 * Math.PI * radiusKm * 1000 * Math.cos(latitude * RAD)) / (TILE_SIZE * 2 ** zoom);
}

/**
 * A circle of `radiusKm` around a point, as a closed [lon, lat] ring (first vertex repeated at the end)
 * wound counter-clockwise, as RFC 7946 asks for exterior rings. Every vertex lies exactly `radiusKm`
 * from the centre along the surface of a sphere of `bodyRadiusKm`.
 *
 * Longitudes stay continuous around the centre's longitude rather than being wrapped, so a ring
 * that crosses the antimeridian may run slightly past ±180 and still draw as one shape. A circle that
 * contains a pole is not a simple polygon in lon/lat; keep radii smaller than the distance to the pole.
 */
export function geodesicCircle(
  lat: number,
  lon: number,
  radiusKm: number,
  bodyRadiusKm: number,
  vertices = 64,
): [number, number][] {
  const n = Math.max(3, Math.round(vertices));
  const delta = radiusKm / bodyRadiusKm;
  const phi1 = lat * RAD;
  const sinPhi1 = Math.sin(phi1);
  const cosPhi1 = Math.cos(phi1);
  const sinDelta = Math.sin(delta);
  const cosDelta = Math.cos(delta);
  const ring: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    // Bearing from north; decreasing goes north → west → south → east (counter-clockwise on a map).
    const theta = (-2 * Math.PI * i) / n;
    const sinPhi2 = sinPhi1 * cosDelta + cosPhi1 * sinDelta * Math.cos(theta);
    const phi2 = Math.asin(Math.max(-1, Math.min(1, sinPhi2)));
    const dLambda = Math.atan2(Math.sin(theta) * sinDelta * cosPhi1, cosDelta - sinPhi1 * sinPhi2);
    ring.push([lon + dLambda / RAD, phi2 / RAD]);
  }
  ring.push([ring[0][0], ring[0][1]]);
  return ring;
}

// MapLibre's ScaleControl rounding (getRoundNum), so a custom scale bar reads like the Earth one.
function roundDecimal(d: number): number {
  const multiplier = Math.pow(10, Math.ceil(-Math.log(d) / Math.LN10));
  return Math.round(d * multiplier) / multiplier;
}

function roundScale(num: number): number {
  const pow10 = Math.pow(10, `${Math.floor(num)}`.length - 1);
  let d = num / pow10;
  d = d >= 10 ? 10 : d >= 5 ? 5 : d >= 3 ? 3 : d >= 2 ? 2 : d >= 1 ? 1 : roundDecimal(d);
  return pow10 * d;
}

/**
 * A metric scale bar at most `maxWidthPx` wide: a round distance and the bar width that spans it,
 * rounded the same way as MapLibre's ScaleControl.
 */
export function scaleBar(metresPerPx: number, maxWidthPx = 100): { widthPx: number; label: string } {
  const maxMetres = metresPerPx * maxWidthPx;
  const [maxDistance, unit] = maxMetres >= 1000 ? [maxMetres / 1000, "km"] : [maxMetres, "m"];
  const distance = roundScale(maxDistance);
  return { widthPx: maxWidthPx * (distance / maxDistance), label: `${distance} ${unit}` };
}
