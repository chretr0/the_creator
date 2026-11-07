"""Prepared infrastructure layers: provenance and semantics. No database needed."""

import json
import sys
from pathlib import Path

import h3
import pytest

from app.config import settings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_infrastructure import parse_kw  # noqa: E402

DIR = Path(settings.prepared_data_dir) / "infrastructure"
pytestmark = pytest.mark.skipif(not (DIR / "source.json").exists(), reason="infrastructure data not prepared")


def test_parse_kw():
    assert parse_kw("77.4MW") == 77400.0
    assert parse_kw("575 kW") == 575.0
    assert parse_kw("1,8 MW") == 1800.0
    assert parse_kw("small_installation") is None
    assert parse_kw("substation") is None
    assert parse_kw(None) is None


def _manifest() -> dict:
    return json.loads((DIR / "source.json").read_text())


def _layer(layer_id: str) -> list[dict]:
    entry = next((x for x in _manifest()["layers"] if x["id"] == layer_id), None)
    if entry is None or not (DIR / entry["file"]).exists():
        pytest.skip(f"{layer_id} not prepared")
    return json.loads((DIR / entry["file"]).read_text())["features"]


def test_manifest_has_provenance_per_source():
    m = _manifest()
    assert {"datacenters", "dams"} <= {layer["id"] for layer in m["layers"]}
    for layer in m["layers"]:
        src = m["sources"][layer["source"]]
        assert src["licence"] and src["attribution"] and src["limitations"]
        assert layer["stats"]["withConsumption"] == 0
        assert layer["scope"] in ("global", "regions")
    assert "OpenStreetMap" in m["sources"]["INFRA-OSM-GEV"]["attribution"]


def test_simplify_keeps_ends_and_drops_collinear_points():
    from prepare_infrastructure import simplify

    line = [(0.0, 0.0), (0.5, 0.00001), (1.0, 0.0), (1.0, 1.0)]
    assert simplify(line, 0.001) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


@pytest.mark.parametrize("layer", ["datacenters", "dams", "power_plants", "substations", "transmission_lines", "airports", "ports"])
def test_features_are_honest(layer):
    features = _layer(layer)
    assert features
    for f in features:
        p = f["properties"]
        assert p["layer"] == layer
        # consumption is unknown in these sources: null or absent, never zero
        assert p.get("electricityConsumptionKwhPerYear") is None and p.get("waterConsumptionM3PerYear") is None
        # cell is the res-6 cell of the representative point
        assert p["h3Id"] == h3.latlng_to_cell(p["lat"], p["lon"], 6)
        for r in p.get("powerRatings", []):
            assert r["kw"] is None or r["kw"] > 0
        # owner is never back-filled from operator
        assert "owner" in p and "operator" in p
        if p["owner"] is not None:
            assert isinstance(p["owner"], str)


def test_power_plants_keep_capacity_and_flag_estimates():
    for f in _layer("power_plants"):
        p = f["properties"]
        assert p["capacityMw"] > 0
        assert p["operator"] is None  # the source reports owners only
        g = p.get("generation")
        if g:
            assert g["gwh"] >= 0 and isinstance(g["estimated"], bool) and 2013 <= g["year"] <= 2019


def test_grid_is_high_voltage_and_regional():
    m = _manifest()
    for layer in ("substations", "transmission_lines"):
        entry = next(x for x in m["layers"] if x["id"] == layer)
        assert entry["scope"] == "regions" and entry["minVoltageKv"] == 66
        for f in _layer(layer):
            p = f["properties"]
            assert p["voltageKv"][0] >= 66 and p["voltageKv"] == sorted(p["voltageKv"], reverse=True)
            assert p["region"] in entry["regions"]
            assert p["osmUrl"].startswith("https://www.openstreetmap.org/")
    for f in _layer("transmission_lines"):
        assert f["geometry"]["type"] == "LineString" and len(f["geometry"]["coordinates"]) >= 2


def test_airports_are_large_or_medium():
    kinds = {f["properties"]["kind"] for f in _layer("airports")}
    assert kinds <= {"Large airport", "Medium airport"}


def test_api_lists_availability_and_serves_layers(client):
    m = client.get("/api/infrastructure").json()
    assert all("available" in layer for layer in m["layers"])
    for layer in m["layers"]:
        r = client.get(f"/api/infrastructure/{layer['id']}")
        assert r.status_code == (200 if layer["available"] else 503)
    assert client.get("/api/infrastructure/nope").status_code == 404
    credits = {s["id"]: s["layers"] for s in client.get("/api/sources").json()}
    assert credits["INFRA-OSM-GEV"] == ["datacenters", "dams"]
