import math

import h3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import LinearRing, Point, Polygon

from app import bodies, geo
from app.bodies import EARTH, MOON
from app.routers import bodies as bodies_router
from app.routers import cells as cells_router

SCALE = MOON.radius_km / EARTH.radius_km

CELLS = (
    [h3.latlng_to_cell(51.5074, -0.1278, r) for r in range(16)]
    + [h3.latlng_to_cell(-16.5, 179.999, r) for r in (0, 3, 6, 9)]
    + [h3.latlng_to_cell(0.674, 23.473, r) for r in (2, 6, 10)]
    + list(h3.get_pentagons(0))[:3]
    + list(h3.get_pentagons(6))[:3]
)


@pytest.fixture(scope="module")
def api():
    """Just the bodies and cells routers: no database needed."""
    app = FastAPI()
    app.include_router(bodies_router.router)
    app.include_router(cells_router.router)
    with TestClient(app) as c:
        yield c


def test_registry():
    assert bodies.get("earth") is EARTH
    assert bodies.get(" Moon ") is MOON
    assert bodies.get(MOON) is MOON
    assert EARTH.radius_km == 6371.007180918475
    assert MOON.radius_km == 1737.4
    assert EARTH.simulation_resolution == MOON.simulation_resolution == geo.SIMULATION_RESOLUTION


@pytest.mark.parametrize("bad", ["mars", "", None, 3])
def test_unknown_body_raises(bad):
    with pytest.raises(bodies.UnknownBody):
        bodies.get(bad)


@pytest.mark.parametrize("cell", CELLS)
def test_earth_area_is_bit_identical_to_h3_km2(cell):
    assert bodies.cell_area_km2(cell, EARTH) == h3.cell_area(cell, unit="km^2")
    assert geo.describe_cell(cell)["area_km2"] == h3.cell_area(cell, unit="km^2")


@pytest.mark.parametrize("cell", CELLS)
def test_moon_area_scales_with_radius_squared(cell):
    assert bodies.cell_area_km2(cell, MOON) == pytest.approx(h3.cell_area(cell, unit="km^2") * SCALE**2, rel=1e-12)


@pytest.mark.parametrize("res", range(16))
def test_edge_length(res):
    assert bodies.edge_length_km(res, EARTH) == h3.average_hexagon_edge_length(res, unit="km")
    assert bodies.edge_length_km(res, MOON) == pytest.approx(h3.average_hexagon_edge_length(res, unit="km") * SCALE, rel=1e-12)


def test_distance_km():
    a, b = (51.5074, -0.1278), (-33.8688, 151.2093)
    assert bodies.distance_km(*a, *b, EARTH) == pytest.approx(h3.great_circle_distance(a, b, unit="km"), rel=1e-12)
    assert bodies.distance_km(*a, *b, MOON) == pytest.approx(h3.great_circle_distance(a, b, unit="km") * SCALE, rel=1e-12)
    # A quarter of a great circle on the Moon.
    assert bodies.distance_km(0, 0, 0, 90, MOON) == pytest.approx(MOON.radius_km * 3.141592653589793 / 2)


@pytest.mark.parametrize(
    "lat,lon,radius_km",
    [(0.674, 23.473, 2.0), (-89.5, 0.0, 10.0), (-45.4, 179.999, 0.5), (60.0, -179.9, 50.0)],
)
def test_geodesic_circle(lat, lon, radius_km):
    ring = bodies.geodesic_circle(lat, lon, radius_km, MOON, vertices=64)
    assert len(ring) == 65 and ring[0] == ring[-1]
    for vlon, vlat in ring:
        # Continuous around the centre (may run just past ±180), never wrapped vertex by vertex.
        assert abs(vlon - lon) < 90.0 and -90.0 <= vlat <= 90.0
        assert bodies.distance_km(lat, lon, vlat, vlon, MOON) == pytest.approx(radius_km, rel=1e-9)


def test_geodesic_circle_is_counter_clockwise():
    assert LinearRing(bodies.geodesic_circle(10.0, 20.0, 5.0, MOON)).is_ccw


def test_geodesic_circle_in_range_is_unchanged():
    """Rings that stay inside [-180, 180) are exactly what the per-vertex wrap used to give."""
    ring = bodies.geodesic_circle(0.67408, 23.47297, 2.0, MOON)
    assert all(-180.0 <= vlon < 180.0 for vlon, _ in ring)
    assert ring[16] == pytest.approx([23.47297 - 2.0 / MOON.radius_km * 57.29577951308232 / math.cos(math.radians(0.67408)), 0.67408], abs=1e-6)


@pytest.mark.parametrize(
    "lat,lon,radius_km",
    [(-45.39, 179.95, 2.0), (0.0, 179.99, 2.0), (10.0, -179.999, 5.0), (60.0, 180.0, 50.0), (-30.0, -180.0, 3.0)],
)
def test_geodesic_circle_across_the_antimeridian_is_one_small_shape(lat, lon, radius_km):
    ring = bodies.geodesic_circle(lat, lon, radius_km, MOON)
    lons = [vlon for vlon, _ in ring]
    assert max(lons) > 180.0 or min(lons) < -180.0  # it really does cross ±180
    assert max(lons) - min(lons) < 180.0  # not a band across the whole map
    centre_lon = geo.normalise_longitude(lon)  # the ring is continuous around the normalised centre
    polygon = Polygon(ring)
    assert polygon.is_valid and LinearRing(ring).is_ccw
    assert polygon.contains(Point(centre_lon, lat))
    assert not polygon.contains(Point(centre_lon - 180.0, lat))
    for vlon, vlat in ring:
        assert bodies.distance_km(lat, lon, vlat, vlon, MOON) == pytest.approx(radius_km, rel=1e-9)


@pytest.mark.parametrize(
    "lat,lon,radius_km",
    [(89.99, 0.0, 2.0), (89.99, 179.95, 2.0), (-89.99, 45.0, 2.0), (90.0, 0.0, 5.0), (-90.0, 12.0, 5.0), (-80.0, -60.0, 400.0)],
)
def test_geodesic_circle_around_a_pole_is_a_polar_cap(lat, lon, radius_km):
    vertices = 64
    ring = bodies.geodesic_circle(lat, lon, radius_km, MOON, vertices)
    pole = 90.0 if lat > 0 else -90.0
    assert ring[0] == ring[-1] and len(ring) == vertices + 4
    assert min(vlon for vlon, _ in ring) == -180.0 and max(vlon for vlon, _ in ring) == 180.0
    assert ring[-3:-1] == ([[180.0, pole], [-180.0, pole]] if pole > 0 else [[-180.0, pole], [180.0, pole]])
    for vlon, vlat in ring[: vertices + 1]:  # the circle itself, west to east (north) or east to west (south)
        assert bodies.distance_km(lat, lon, vlat, vlon, MOON) == pytest.approx(radius_km, rel=1e-9, abs=1e-9)
    polygon = Polygon(ring)
    assert polygon.is_valid and LinearRing(ring).is_ccw
    assert polygon.covers(Point(lon, pole))  # the pole: on the cap's top/bottom edge
    for plon in (-179.9, -90.0, 0.0, 90.0, 179.9):  # just off the pole at any longitude
        assert polygon.contains(Point(plon, pole - math.copysign(0.001, pole)))
    if abs(lat) < 90.0:
        assert polygon.contains(Point(lon, lat))
    assert not polygon.contains(Point(lon, 0.0))


def test_geodesic_circle_rejects_a_hemisphere_or_more():
    with pytest.raises(ValueError):
        bodies.geodesic_circle(0.0, 0.0, MOON.radius_km * math.pi / 2, MOON)


def test_describe_cell_body_fields():
    cell = h3.latlng_to_cell(0.674, 23.473, 6)
    earth, moon = geo.describe_cell(cell), geo.describe_cell(cell, "moon")
    assert earth["body"] == "earth" and moon["body"] == "moon"
    assert earth["edge_length_km"] == h3.average_hexagon_edge_length(6, unit="km")
    assert moon["area_km2"] == pytest.approx(earth["area_km2"] * SCALE**2)
    assert moon["boundary"] == earth["boundary"] and moon["neighbours"] == earth["neighbours"]


def test_bodies_endpoint(api):
    r = api.get("/api/bodies")
    assert r.status_code == 200
    assert r.json() == [
        {"id": "earth", "name": "Earth", "radiusKm": 6371.007180918475, "frame": EARTH.frame, "simulationResolution": 6},
        {"id": "moon", "name": "Moon", "radiusKm": 1737.4, "frame": MOON.frame, "simulationResolution": 6},
    ]


def test_cell_endpoint_default_is_earth(api):
    cell = h3.latlng_to_cell(51.5074, -0.1278, 6)
    data = api.get(f"/api/cells/{cell}").json()
    assert data["body"] == "earth"
    assert data["areaKm2"] == h3.cell_area(cell, unit="km^2")
    assert data["edgeLengthKm"] == h3.average_hexagon_edge_length(6, unit="km")
    assert api.get(f"/api/cells/{cell}?body=earth").json() == data


def test_cell_endpoints_on_the_moon(api):
    cell = h3.latlng_to_cell(0.674, 23.473, 6)
    data = api.get(f"/api/cells/{cell}?body=moon").json()
    assert data["body"] == "moon"
    assert data["areaKm2"] == pytest.approx(h3.cell_area(cell, unit="km^2") * SCALE**2)
    assert data["edgeLengthKm"] == pytest.approx(h3.average_hexagon_edge_length(6, unit="km") * SCALE)
    located = api.get("/api/cells/locate", params={"latitude": 0.674, "longitude": 23.473, "body": "moon"}).json()
    assert located == data


@pytest.mark.parametrize("bad", ["not-a-cell", "fffffffffffffffff", "-1", "1" * 28])
@pytest.mark.parametrize("body", ["earth", "moon"])
def test_invalid_cell_is_404(api, bad, body):
    # h3 raises OverflowError (not ValueError) on the last three: they used to be a 500.
    assert api.get(f"/api/cells/{bad}?body={body}").status_code == 404


def test_unknown_body_is_422(api):
    cell = h3.latlng_to_cell(0.674, 23.473, 6)
    r = api.get(f"/api/cells/{cell}?body=pluto")
    assert r.status_code == 422 and "pluto" in r.json()["detail"]
    r = api.get("/api/cells/locate", params={"latitude": 0, "longitude": 0, "body": "pluto"})
    assert r.status_code == 422


def test_routers_are_wired_into_the_app(client):
    assert [b["id"] for b in client.get("/api/bodies").json()] == ["earth", "moon"]
    assert client.get("/api/moon/sources").status_code == 200
