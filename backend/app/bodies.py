"""Planetary bodies sharing the H3 grid (Earth, Moon).

H3 cell IDs are identical on every body: the grid is defined on the unit sphere. Only lengths
(x R) and areas (x R^2) change. Earth uses h3's own authalic radius, so Earth areas and edge
lengths equal h3's "km^2" / "km" values exactly.

All coordinates are planetocentric degrees, longitude positive east, normalised to [-180, 180).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import h3

# h3's EARTH_RADIUS_KM (authalic radius): rads^2 * R**2 reproduces h3.cell_area(..., "km^2") bit for bit.
EARTH_RADIUS_KM = 6371.007180918475
MOON_RADIUS_KM = 1737.4  # IAU_2015:30100 reference sphere (LOLA / LROC / IAU Gazetteer)


@dataclass(frozen=True)
class Body:
    id: str
    name: str
    radius_km: float
    frame: str
    simulation_resolution: int = 6

    def to_api(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "radiusKm": self.radius_km,
            "frame": self.frame,
            "simulationResolution": self.simulation_resolution,
        }


EARTH = Body("earth", "Earth", EARTH_RADIUS_KM, "WGS84 / EPSG:4326")
MOON = Body(
    "moon",
    "Moon",
    MOON_RADIUS_KM,
    "IAU_2015:30100 Moon Mean-Earth, planetocentric, longitude positive east, ±180",
)

BODIES: dict[str, Body] = {b.id: b for b in (EARTH, MOON)}
BODY_IDS: tuple[str, ...] = tuple(BODIES)


class UnknownBody(ValueError):
    pass


def get(body_id: str | Body) -> Body:
    """The registered body for an id (case-insensitive). Raises UnknownBody for anything else."""
    if isinstance(body_id, Body):
        return body_id
    key = body_id.strip().lower() if isinstance(body_id, str) else body_id
    try:
        return BODIES[key]
    except (KeyError, TypeError):
        raise UnknownBody(f"unknown body {body_id!r}; expected one of: {', '.join(BODY_IDS)}") from None


def _normalise_longitude(longitude: float) -> float:
    if -180.0 <= longitude < 180.0:
        return longitude
    return ((longitude + 180.0) % 360.0) - 180.0


def cell_area_km2(h3_id: str, body: Body = EARTH) -> float:
    return h3.cell_area(h3_id, unit="rads^2") * body.radius_km**2


def edge_length_km(resolution: int, body: Body = EARTH) -> float:
    """Average hexagon edge length at a resolution (h3's tabulated Earth value scaled by R / R_earth)."""
    earth_km = h3.average_hexagon_edge_length(resolution, unit="km")
    if body.radius_km == EARTH_RADIUS_KM:
        return earth_km
    return earth_km / EARTH_RADIUS_KM * body.radius_km


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float, body: Body = EARTH) -> float:
    """Great-circle (haversine) distance on the body's sphere."""
    return h3.great_circle_distance((lat1, lon1), (lat2, lon2), unit="rads") * body.radius_km


def geodesic_circle(
    lat: float, lon: float, radius_km: float, body: Body = EARTH, vertices: int = 64
) -> list[list[float]]:
    """Closed [lon, lat] ring of points `radius_km` (great-circle) from the centre.

    `vertices` distinct points, counter-clockwise (bearing decreasing from north), first point
    repeated at the end. Longitudes stay continuous around the centre's longitude (normalised to
    [-180, 180)) rather than being wrapped one by one, as in frontend/src/lib/bodyGeometry.ts
    geodesicCircle: a ring that crosses the antimeridian runs slightly past ±180 and still draws as
    one small shape in deck.gl / MapLibre, where per-vertex wrapping drew a band across the map.

    A circle that contains a pole does not loop around its centre in lon/lat, so it comes back as a
    polar cap instead: `vertices + 1` points of the circle at evenly spaced longitudes from -180 to
    180 (west to east round the north pole, east to west round the south pole), then the two map
    corners on the pole's latitude (±90) and the first point again. That is `vertices + 4`
    positions, still counter-clockwise, every longitude within [-180, 180].

    The radius must be under a quarter of the body's circumference (an angular radius below 90°).
    """
    if vertices < 3:
        raise ValueError("a ring needs at least 3 vertices")
    d = radius_km / body.radius_km  # angular radius
    if not d < math.pi / 2:
        raise ValueError("radius must be under a quarter of the body's circumference")
    phi1, lam1 = math.radians(lat), math.radians(_normalise_longitude(lon))
    if abs(phi1) + d > math.pi / 2:
        return _polar_cap(phi1, lam1, d, vertices)
    sin_phi1, cos_phi1 = math.sin(phi1), math.cos(phi1)
    sin_d, cos_d = math.sin(d), math.cos(d)
    ring: list[list[float]] = []
    for i in range(vertices):
        # Negative bearing step -> counter-clockwise exterior ring (RFC 7946 right-hand rule).
        theta = -2.0 * math.pi * i / vertices
        sin_phi2 = sin_phi1 * cos_d + cos_phi1 * sin_d * math.cos(theta)
        phi2 = math.asin(max(-1.0, min(1.0, sin_phi2)))
        # atan2 offset stays within ±90° of the centre: no pole inside, so no wrap.
        lam2 = lam1 + math.atan2(math.sin(theta) * sin_d * cos_phi1, cos_d - sin_phi1 * sin_phi2)
        ring.append([math.degrees(lam2), math.degrees(phi2)])
    ring.append(list(ring[0]))
    return ring


def _polar_cap(phi1: float, lam1: float, d: float, vertices: int) -> list[list[float]]:
    """geodesic_circle's ring for a circle (angular radius d < 90°) that contains a pole."""
    north = phi1 > 0
    sin_phi1, cos_phi1, cos_d = math.sin(phi1), math.cos(phi1), math.cos(d)
    ring: list[list[float]] = []
    for i in range(vertices + 1):
        lon = -180.0 + 360.0 * i / vertices if north else 180.0 - 360.0 * i / vertices
        # The circle crosses each meridian once. On the great circle through it, the point at
        # "latitude" phi has cos(distance) = sin_phi1 sin(phi) + b cos(phi) = r cos(phi - gamma), so
        # the cap is the arc gamma ± a; its end nearer the equator lies on this meridian.
        b = cos_phi1 * math.cos(math.radians(lon) - lam1)
        r = math.hypot(sin_phi1, b)
        gamma = math.atan2(sin_phi1, b)
        a = math.acos(max(-1.0, min(1.0, cos_d / r)))
        ring.append([lon, math.degrees(gamma - a if north else gamma + a)])
    pole = 90.0 if north else -90.0
    ring += [[ring[-1][0], pole], [ring[0][0], pole], list(ring[0])]
    return ring
