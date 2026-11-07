"""H3 layer store, layer API and feature API. Data-dependent tests skip when files are not prepared."""

from pathlib import Path

import h3
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import features, h3store, layers
from app.config import settings
from app.routers import features as features_router
from app.routers import layers as layers_router

PREPARED = Path(settings.prepared_data_dir)
PHOENIX = (33.4484, -112.0740)

app = FastAPI()
app.include_router(layers_router.router)
app.include_router(features_router.router)
client = TestClient(app)

needs_power = pytest.mark.skipif(
    not (PREPARED / "power_ALLSKY_SFC_SW_DWN_climatology_h3r6.parquet").exists(), reason="POWER layer not prepared"
)
needs_features = pytest.mark.skipif(not (PREPARED / "features" / "manifest.json").exists(), reason="features not prepared")


@pytest.mark.parametrize("res", range(6))
def test_parent_index_matches_h3(res):
    cells = [h3.latlng_to_cell(lat, lon, 6) for lat, lon in [PHOENIX, (51.5, -0.12), (-33.9, 151.2), (89.9, 0.0)]]
    got = h3store.parent_index(np.array([int(c, 16) for c in cells], dtype=np.uint64), res)
    assert [format(int(x), "x") for x in got] == [h3.cell_to_parent(c, res) for c in cells]


def test_aggregate_mean_sum_mode_skip_missing():
    children = sorted(h3.cell_to_children(h3.latlng_to_cell(*PHOENIX, 5), 6))
    keys = np.array([int(c, 16) for c in children], dtype=np.uint64)
    vals = np.array([1, 1, 2, np.nan, 3, 3, 3], dtype=np.float32)
    for agg, expected in [("mean", 13 / 6), ("sum", 13.0), ("mode", 3.0)]:
        k, v, n = h3store._aggregate(keys, vals, 5, agg)
        assert len(k) == 1 and n[0] == 6
        assert v[0] == pytest.approx(expected)


def test_catalogue_lists_every_layer():
    r = client.get("/api/layers")
    assert r.status_code == 200
    ids = {layer["id"] for layer in r.json()}
    assert {"solar_ghi", "population_ghsl", "soil_phh2o", "elevation", "land_cover"} <= ids
    for layer in r.json():
        assert layer["slices"] and all("units" in s for s in layer["slices"])


@needs_power
def test_values_aligned_with_request_and_known_point():
    cell = h3.latlng_to_cell(*PHOENIX, 6)
    ocean = h3.latlng_to_cell(0.0, -30.0, 6)
    r = client.post("/api/layers/solar_ghi/values", json={"slice": "clim-ann", "cells": [cell, ocean]})
    assert r.status_code == 200
    body = r.json()
    assert body["resolution"] == 6 and len(body["values"]) == 2
    assert body["values"][0] == pytest.approx(5.848, abs=0.01)  # NASA POWER API check in data/STATUS.md
    assert body["units"] == "kWh/m²/day"


@needs_power
def test_values_reject_mixed_resolutions():
    a = h3.latlng_to_cell(*PHOENIX, 6)
    b = h3.latlng_to_cell(*PHOENIX, 5)
    assert client.post("/api/layers/solar_ghi/values", json={"cells": [a, b]}).status_code == 422


@needs_power
def test_profile_has_monthly_series():
    r = client.get(f"/api/cells/{h3.latlng_to_cell(*PHOENIX, 6)}/profile")
    assert r.status_code == 200
    ghi = next(layer for layer in r.json()["layers"] if layer["layer"] == "solar_ghi")
    assert len([v for v in ghi["values"] if v["slice"].startswith("clim-") and v["slice"] != "clim-ann"]) == 12


def test_profile_requires_resolution_6():
    assert client.get(f"/api/cells/{h3.latlng_to_cell(*PHOENIX, 4)}/profile").status_code == 422


def test_unknown_layer_404():
    assert client.post("/api/layers/nope/values", json={"cells": []}).status_code == 404


def test_scrub_removes_nan():
    assert features._scrub({"a": float("nan"), "b": [1.0, float("nan"), "x"]}) == {"a": None, "b": [1.0, "x"]}


@needs_features
def test_feature_bbox_query_and_cell_context():
    m = features.manifest()
    points = [layer for layer in m["layers"] if layer["geometry"] == "point" and features.available(layer)]
    if not points:
        pytest.skip("no point layers")
    layer = points[0]
    w, s, e, n = layer["bbox"]
    r = client.get(f"/api/features/{layer['id']}", params={"west": w, "south": s, "east": e, "north": n, "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection" and len(body["features"]) <= 50
    assert body["truncated"] == (body["matched"] > len(body["features"]))
    r = client.get(f"/api/cells/{h3.latlng_to_cell(*PHOENIX, 6)}/features")
    assert r.status_code == 200


def test_layer_files_expand_regions():
    s = layers.BY_ID["elevation"].slices[0]
    assert all(p.name.startswith("dem_") for p in layers.slice_files(s))
