"""H3 helpers. Coordinate contract (see CLAUDE.mapping.md section 2):

- persisted locations use named latitude/longitude fields in WGS84 degrees;
- boundaries are returned as GeoJSON-order [longitude, latitude] pairs;
- H3 IDs are always lowercase hex strings.
"""

import h3

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


def validate_cell(h3_id: str) -> str:
    h3_id = h3_id.strip().lower()
    if not h3.is_valid_cell(h3_id):
        raise InvalidCell(f"{h3_id!r} is not a valid H3 cell")
    return h3_id


def describe_cell(h3_id: str) -> dict:
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
        "area_km2": h3.cell_area(h3_id, unit="km^2"),
        "neighbours": neighbours,
        "parent": h3.cell_to_parent(h3_id, resolution - 1) if resolution > 0 else None,
        "simulation_cell": (
            h3.cell_to_parent(h3_id, SIMULATION_RESOLUTION)
            if resolution >= SIMULATION_RESOLUTION
            else None
        ),
    }
