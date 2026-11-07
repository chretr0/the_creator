"""Boundaries, region lookup, cables manifest, Overpass parsing and the source registry. No network."""

import json
from pathlib import Path

import pytest

from app import regions
from app.config import settings
from app.routers.power import box, parse_kv, parse_kw
from app.routers.sources import sources

BOUNDARIES = Path(settings.prepared_data_dir) / "boundaries" / "source.json"
CABLES = Path(settings.prepared_data_dir) / "cables" / "source.json"
needs_boundaries = pytest.mark.skipif(not BOUNDARIES.exists(), reason="boundaries not prepared")


@needs_boundaries
@pytest.mark.parametrize(
    ("lat", "lon", "country", "admin1", "county"),
    [
        (48.8566, 2.3522, "France", "Paris", None),
        (33.4484, -112.0740, "United States of America", "Arizona", "Maricopa County"),
        (51.5074, -0.1278, "United Kingdom", None, None),
    ],
)
def test_locate(lat, lon, country, admin1, county):
    r = regions.locate(lon, lat)
    assert r["country"]["name"] == country
    if admin1:
        assert r["admin1"]["name"] == admin1
    assert (r.get("county") or {}).get("name") == county


@needs_boundaries
def test_open_sea_is_unknown_not_a_country():
    r = regions.locate(-30.0, 0.0)  # mid-Atlantic
    assert r["country"] is None and r["admin1"] is None


@needs_boundaries
def test_one_country_per_point():
    """Constituent countries (England, Wales…) are dropped so they can't shadow the UK."""
    fc = json.loads((BOUNDARIES.parent / "countries.geojson").read_text())
    names = {f["properties"]["name"] for f in fc["features"]}
    assert "United Kingdom" in names and "England" not in names and "Wales" not in names


@pytest.mark.skipif(not CABLES.exists(), reason="cables not prepared")
def test_cables_carry_non_commercial_licence():
    m = json.loads(CABLES.read_text())
    assert m["licence"] == "CC BY-NC-SA 3.0" and m["commercialUse"] is False
    assert "TeleGeography" in m["attribution"]


def test_overpass_tag_parsing():
    assert parse_kw("1006 MW") == 1_006_000.0
    assert parse_kw("yes") is None
    assert parse_kv("400000;132000") == [400.0, 132.0]
    assert parse_kv("medium") == []
    s, w, n, e = box(33.45, -112.07, 10)
    assert s < 33.45 < n and w < -112.07 < e
    assert round(n - s, 2) == round(20 / 111.32, 2)


def test_source_registry_has_licence_and_attribution():
    out = sources()
    assert out, "no sources registered"
    for s in out:
        assert s["licence"] and s["attribution"] and s["evidenceType"] and s["layers"]
