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


def test_manifest_has_provenance():
    m = json.loads((DIR / "source.json").read_text())
    assert m["licence"] == "ODbL-1.0" and "OpenStreetMap" in m["attribution"]
    assert {layer["id"] for layer in m["layers"]} == {"datacenters", "dams"}
    assert all(layer["stats"]["withConsumption"] == 0 for layer in m["layers"])


@pytest.mark.parametrize("layer", ["datacenters", "dams"])
def test_features_are_honest(layer):
    fc = json.loads((DIR / f"{layer}.geojson").read_text())
    assert fc["features"]
    for f in fc["features"]:
        p = f["properties"]
        # consumption is unknown in this source: null, never zero
        assert p["electricityConsumptionKwhPerYear"] is None and p["waterConsumptionM3PerYear"] is None
        # cell is the res-6 cell of the representative point
        assert p["h3Id"] == h3.latlng_to_cell(p["lat"], p["lon"], 6)
        for r in p["powerRatings"]:
            assert r["kw"] is None or r["kw"] > 0
        # owner is never back-filled from operator
        if p["owner"] is not None:
            assert isinstance(p["owner"], str)
