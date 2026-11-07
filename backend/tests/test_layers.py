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


def test_profile_rejects_finer_than_resolution_6():
    assert client.get(f"/api/cells/{h3.latlng_to_cell(*PHOENIX, 7)}/profile").status_code == 422


@pytest.mark.parametrize("res", [0, 2, 4, 5])
def test_descendant_range_brackets_exactly_the_children(res):
    cell = h3.latlng_to_cell(*PHOENIX, res)
    lo, hi = h3store.descendant_range(int(cell, 16))
    children = sorted(int(c, 16) for c in h3.cell_to_children(cell, 6))
    assert lo <= children[0] and hi >= children[-1]
    # neighbouring resolution-6 cells just outside the parent fall outside the range
    ring = {c for child in h3.cell_to_children(cell, 6) for c in h3.grid_disk(child, 1)}
    outside = [int(c, 16) for c in ring if h3.cell_to_parent(c, res) != cell]
    assert outside and not any(lo <= c <= hi for c in outside)


@needs_power
@pytest.mark.parametrize("res", [3, 5])
def test_coarse_profile_matches_map_colour(res):
    """A zoomed-out hexagon's profile equals the value the map colours it by."""
    cell = h3.latlng_to_cell(*PHOENIX, res)
    r = client.get(f"/api/cells/{cell}/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["resolution"] == res and body["simulationCells"] == h3.cell_to_children_size(cell, 6)
    ghi = next(layer for layer in body["layers"] if layer["layer"] == "solar_ghi")
    ann = next(v for v in ghi["values"] if v["slice"] == "clim-ann")
    shown = client.post("/api/layers/solar_ghi/values", json={"slice": "clim-ann", "cells": [cell]}).json()["values"][0]
    assert ann["display"] == pytest.approx(shown, rel=1e-3)
    assert 0 < ann["cellsWithData"] <= body["simulationCells"]


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


needs_water_stress = pytest.mark.skipif(
    not (PREPARED / "layers" / "water_stress_baseline" / "arizona.parquet").exists(), reason="water stress not prepared"
)
LONDON = (51.5072, -0.1276)


def _layer_in_profile(cell: str, layer_id: str) -> dict | None:
    body = client.get(f"/api/cells/{cell}/profile").json()
    return next((layer for layer in body["layers"] if layer["layer"] == layer_id), None)


@needs_water_stress
@pytest.mark.parametrize(("point", "score", "label"), [(PHOENIX, 5.0, "Extremely High"), (LONDON, 3.39, "High")])
def test_water_stress_basin_values(point, score, label):
    """Each cell takes its basin's Aqueduct score unchanged (checked against data/STATUS.md)."""
    ws = _layer_in_profile(h3.latlng_to_cell(*point, 6), "water_stress")
    values = {v["slice"]: v for v in ws["values"]}
    assert values["score"]["value"] == pytest.approx(score, abs=0.01)
    assert values["category"]["categorical"] and not values["score"]["categorical"]
    assert next(a["value"] for a in ws["attributes"] if a["key"] == "bws_label").startswith(label)
    src = ws["source"]
    assert src["licence"] == "CC BY 4.0" and src["attribution"] and src["period"] and src["evidenceType"]


@needs_water_stress
def test_water_stress_no_data_basin_is_null_not_zero():
    import pyarrow.parquet as pq

    t = pq.read_table(PREPARED / "layers" / "water_stress_baseline" / "uk.parquet", columns=["h3", "bws_label"])
    labels = t.column("bws_label").to_pylist()
    cell = format(t.column("h3")[labels.index("No Data")].as_py(), "x")
    r = client.post("/api/layers/water_stress/values", json={"slice": "score", "cells": [cell]})
    assert r.json()["values"] == [None]
    ws = _layer_in_profile(cell, "water_stress")
    assert all(v["value"] is None for v in ws["values"])
    assert any(a["value"] == "No Data" for a in ws["attributes"])


@needs_water_stress
def test_water_stress_coarse_cell_uses_most_common_class():
    cell = h3.latlng_to_cell(*PHOENIX, 3)
    shown = client.post("/api/layers/water_stress/values", json={"slice": "score", "cells": [cell]}).json()["values"][0]
    children = sorted(h3.cell_to_children(cell, 6))
    child_scores = client.post("/api/layers/water_stress/values", json={"slice": "score", "cells": children}).json()
    assert any(v is not None and v == pytest.approx(shown, rel=1e-3) for v in child_scores["values"])  # never a blend
    ws = _layer_in_profile(cell, "water_stress")
    assert next(v for v in ws["values"] if v["slice"] == "score")["display"] == pytest.approx(shown, rel=1e-3)


def test_profile_outside_regions_has_no_regional_layers():
    body = client.get(f"/api/cells/{h3.latlng_to_cell(48.85, 2.35, 6)}/profile").json()  # Paris
    assert body["region"] is None
    assert not any(layer["coverage"] == "regions" for layer in body["layers"])


def test_region_files_map_to_regions():
    assert layers._region_of(Path("layers/water_stress_baseline/uk.parquet")) == "uk"
    assert layers.region_at(*PHOENIX) == "arizona" and layers.region_at(48.85, 2.35) is None
