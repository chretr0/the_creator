import h3
import pytest

from app import geo


@pytest.mark.parametrize(
    "lat,lng",
    [
        (51.5074, -0.1278),  # London, negative longitude
        (-33.8688, 151.2093),  # Sydney, southern hemisphere
        (64.1466, -21.9426),  # Reykjavik
        (-16.5, 179.999),  # just west of the antimeridian
        (-16.5, -179.999),  # just east of the antimeridian
        (89.9, 0.0),  # near the north pole
        (-89.9, 45.0),  # near the south pole
    ],
)
def test_simulation_cell_is_resolution_6_and_contains_point(lat, lng):
    cell = geo.simulation_cell(lat, lng)
    assert h3.get_resolution(cell) == 6
    assert h3.latlng_to_cell(lat, lng, 6) == cell
    assert cell == cell.lower() and len(cell) == 15


def test_antimeridian_sides_are_different_cells():
    assert geo.simulation_cell(-16.5, 179.999) != geo.simulation_cell(-16.5, -179.999)


def test_longitude_normalisation():
    assert geo.normalise_longitude(180.0) == -180.0
    assert geo.normalise_longitude(190.0) == pytest.approx(-170.0)
    assert geo.normalise_longitude(-190.0) == pytest.approx(170.0)
    exact = -0.12780000000000001
    assert geo.normalise_longitude(exact) is exact or geo.normalise_longitude(exact) == exact


def test_invalid_latitude_rejected():
    with pytest.raises(geo.InvalidCoordinate):
        geo.validate_coordinate(91, 0)


def test_describe_cell_boundary_is_closed_lng_lat_ring():
    info = geo.describe_cell(h3.latlng_to_cell(51.5074, -0.1278, 6))
    ring = info["boundary"]
    assert ring[0] == ring[-1]
    lng, lat = ring[0]
    assert -1 < lng < 1 and 51 < lat < 52  # GeoJSON order
    assert info["simulation_cell"] == info["h3_id"]
    assert len(info["neighbours"]) == 6


def test_pentagon_neighbourhood():
    pentagon = next(c for c in h3.get_pentagons(6))
    info = geo.describe_cell(pentagon)
    assert info["is_pentagon"]
    assert len(info["neighbours"]) == 5


def test_invalid_cell_rejected():
    with pytest.raises(geo.InvalidCell):
        geo.describe_cell("not-a-cell")


VALID = "8a2a1072b59ffff"


@pytest.mark.parametrize(
    "bad",
    [
        "fffffffffffffffff",  # 17 hex digits: does not fit 64 bits (h3 raised OverflowError)
        "1" * 28,
        "-1",  # negative (h3 raised OverflowError)
        "0x" + VALID,  # int(s, 16) syntax that h3 accepts but is not an H3 id
        VALID[:4] + "_" + VALID[4:],
        "+" + VALID,
        "0" + VALID,
        "\uff18" + VALID[1:],  # full-width digit
        "",
        "   ",
        "not-a-cell",
        VALID[:-1] + "x",
        "8f2830828052d2",  # 14 digits
    ],
)
def test_validate_cell_rejects_anything_but_a_cell_id(bad):
    with pytest.raises(geo.InvalidCell):
        geo.validate_cell(bad)


@pytest.mark.parametrize("bad", [None, 3, b"8a2a1072b59ffff"])
def test_validate_cell_rejects_non_strings(bad):
    with pytest.raises(geo.InvalidCell):
        geo.validate_cell(bad)


def test_validate_cell_strips_and_lowercases():
    assert geo.validate_cell(VALID) == VALID
    assert geo.validate_cell(" 8A2A1072B59FFFF\n") == VALID

