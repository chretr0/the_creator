"""H3 helpers. Coordinate contract (see CLAUDE.mapping.md section 2):

- persisted locations use named latitude/longitude fields in WGS84 degrees;
- boundaries are returned as GeoJSON-order [longitude, latitude] pairs;
- H3 IDs are always lowercase hex strings.
"""

import re

import h3

from app import bodies
from app.bodies import EARTH, Body

SIMULATION_RESOLUTION = 6
MAX_RESOLUTION = 15


class InvalidCoordinate(ValueError):
    pass


class InvalidCell(ValueError):
    pass


def normalise_longitude(longitude: float) -> float:
    """Map to [-180, 180). In-range values are returned untouched to keep them bit-exact."""
    if -180.0 <= longitude < 180.0:
        return longitude
    normalised = ((longitude + 180.0) % 360.0) - 180.0
    return normalised


def validate_coordinate(latitude: float, longitude: float) -> tuple[float, float]:
    if not (-90.0 <= latitude <= 90.0):
        raise InvalidCoordinate(f"latitude {latitude} outside [-90, 90]")
    if longitude != longitude or abs(longitude) == float("inf"):
        raise InvalidCoordinate("longitude must be finite")
    return latitude, normalise_longitude(longitude)


def simulation_cell(latitude: float, longitude: float) -> str:
    latitude, longitude = validate_coordinate(latitude, longitude)
    return h3.latlng_to_cell(latitude, longitude, SIMULATION_RESOLUTION)


_CELL_ID = re.compile(r"[0-9a-f]{15}")


def validate_cell(h3_id: str) -> str:
    """The stripped, lower-case id of a valid H3 cell; raises InvalidCell for anything else.

    Only the canonical 15-hex-digit form gets as far as h3: its parser is int(s, 16), which also
    takes "0x"/"+"/"_"/leading zeros/full-width digits and raises OverflowError (not ValueError)
    on ids that do not fit 64 bits, e.g. "fffffffffffffffff" or "-1".
    """
    s = h3_id.strip().lower() if isinstance(h3_id, str) else None
    try:
        ok = s is not None and _CELL_ID.fullmatch(s) is not None and h3.is_valid_cell(s)
    except (ValueError, TypeError, OverflowError):
        ok = False
    if not ok:
        raise InvalidCell(f"{s if s is not None else h3_id!r} is not a valid H3 cell")
    return s


def describe_cell(h3_id: str, body: Body | str = EARTH) -> dict:
    """Cell geometry and hierarchy. IDs, centre and boundary are body-independent; lengths and
    areas use the body's radius (Earth: identical to h3's km values)."""
    body = bodies.get(body)
    h3_id = validate_cell(h3_id)
    resolution = h3.get_resolution(h3_id)
    lat, lng = h3.cell_to_latlng(h3_id)
    # h3-py returns (lat, lng) tuples; flip to GeoJSON order and close the ring.
    ring = [[p[1], p[0]] for p in h3.cell_to_boundary(h3_id)]
    ring.append(ring[0])
    neighbours = sorted(c for c in h3.grid_disk(h3_id, 1) if c != h3_id)
    return {
        "h3_id": h3_id,
        "resolution": resolution,
        "is_pentagon": h3.is_pentagon(h3_id),
        "centre": {"latitude": lat, "longitude": lng},
        "boundary": ring,
        "body": body.id,
        "area_km2": bodies.cell_area_km2(h3_id, body),
        "edge_length_km": bodies.edge_length_km(resolution, body),
        "neighbours": neighbours,
        "parent": h3.cell_to_parent(h3_id, resolution - 1) if resolution > 0 else None,
        "simulation_cell": (
            h3.cell_to_parent(h3_id, SIMULATION_RESOLUTION)
            if resolution >= SIMULATION_RESOLUTION
            else None
        ),
    }
