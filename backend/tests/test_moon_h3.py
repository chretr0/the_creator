"""Moon H3 layer store and /api/moon/h3 routes, on a small synthetic layer (no database needed).

The last test checks the real LOLA elevation layer and skips when it has not been prepared.
"""

from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import moon_h3
from app.config import settings
from app.routers import moon_layers

TYCHO = (-43.31, -11.36)
IMBRIUM = (33.0, -16.0)

app = FastAPI()
app.include_router(moon_layers.router)
client = TestClient(app)

A5 = h3.latlng_to_cell(*TYCHO, 5)
B5 = h3.latlng_to_cell(*IMBRIUM, 5)  # stored as NaN
ABSENT5 = h3.latlng_to_cell(0.0, 0.0, 5)  # no row at all


def _write_layer(root: Path, *, with_parquet: bool = True) -> None:
    d = root / "moon" / "h3"
    d.mkdir(parents=True, exist_ok=True)
    rows = [(A5, 5, -1759.25, 6), (B5, 5, float("nan"), 0)]
    rows += [(h3.cell_to_parent(A5, r), r, -1000.0 - r, 10 * (6 - r)) for r in range(5)]
    rows.sort(key=lambda row: int(row[0], 16))
    if with_parquet:
        table = pa.table(
            {
                "h3": pa.array([int(r[0], 16) for r in rows], type=pa.uint64()),
                "res": pa.array([r[1] for r in rows], type=pa.uint8()),
                "value": pa.array([r[2] for r in rows], type=pa.float32()),
                "count": pa.array([r[3] for r in rows], type=pa.uint32()),
            }
        )
        pq.write_table(table, d / "elevation.parquet")
    catalogue = {
        "layers": [
            {
                "id": "elevation",
                "name": "Elevation (LOLA)",
                "unit": "m",
                "description": "synthetic",
                "sourceId": "MOON-TOPO-02",
                "evidenceType": "orbital_retrieval",
                "maxResolution": 5,
                "nativeResolutionKm": 1.9,
                "aggregation": "mean",
                "range": [-5000, 6000],
                "palette": "terrain",
                "limitations": ["synthetic"],
            }
        ],
        "sources": {"MOON-TOPO-02": {"id": "MOON-TOPO-02", "name": "LOLA"}},
    }
    (d / "layers.json").write_text(json.dumps(catalogue))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    moon_h3.reset()
    _write_layer(tmp_path)
    yield tmp_path
    moon_h3.reset()


@pytest.fixture
def empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    moon_h3.reset()
    yield tmp_path
    moon_h3.reset()


def test_list_empty_when_not_prepared(empty):
    r = client.get("/api/moon/h3")
    assert r.status_code == 200
    assert r.json() == []


def test_list_layers(prepared):
    r = client.get("/api/moon/h3")
    assert r.status_code == 200
    (layer,) = r.json()
    assert layer["id"] == "elevation" and layer["maxResolution"] == 5 and layer["unit"] == "m"
    assert layer["available"] is True


def test_values_at_stored_resolutions(prepared):
    parent3 = h3.cell_to_parent(A5, 3)
    r = client.post("/api/moon/h3/elevation", json={"cells": [A5, parent3]})
    assert r.status_code == 200
    body = r.json()
    assert body["layerId"] == "elevation" and body["unit"] == "m"
    assert body["values"] == {A5: -1759.25, parent3: -1003.0}
    assert body["servedResolution"] == {A5: 5, parent3: 3}


def test_finer_cells_resolve_to_max_resolution_ancestor(prepared):
    child6 = h3.cell_to_center_child(A5, 6)
    child9 = h3.cell_to_children(A5, 9)[17]
    r = client.post("/api/moon/h3/elevation", json={"cells": [child6, child9]})
    assert r.status_code == 200
    body = r.json()
    assert body["values"] == {child6: -1759.25, child9: -1759.25}
    assert body["servedResolution"] == {child6: 5, child9: 5}


def test_missing_and_nan_are_null_never_zero(prepared):
    nan6 = h3.cell_to_center_child(B5, 6)
    r = client.post("/api/moon/h3/elevation", json={"cells": [ABSENT5, B5, nan6]})
    assert r.status_code == 200
    assert r.json()["values"] == {ABSENT5: None, B5: None, nan6: None}


def test_empty_request(prepared):
    r = client.post("/api/moon/h3/elevation", json={"cells": []})
    assert r.status_code == 200
    assert r.json()["values"] == {} and r.json()["servedResolution"] == {}


@pytest.mark.parametrize(
    "bad",
    [
        "zzz", "", "8f2830828052d2", "123", h3.latlng_to_cell(0, 0, 5)[:-1] + "x",
        # h3 raises OverflowError on these (not ValueError): they were a 500.
        "fffffffffffffffff", "-1", "1" * 28,
        # int(s, 16) syntax h3 accepts; not a canonical id, so it must not be echoed back as one.
        "0x" + h3.latlng_to_cell(0, 0, 5),
    ],
)
def test_bad_cell_is_422(prepared, bad):
    r = client.post("/api/moon/h3/elevation", json={"cells": [A5, bad]})
    assert r.status_code == 422


def test_unknown_layer_is_404(prepared):
    r = client.post("/api/moon/h3/nope", json={"cells": [A5]})
    assert r.status_code == 404


def test_size_limit(prepared):
    cells = list(h3.cell_to_children(h3.cell_to_parent(A5, 0), 6))[: moon_h3.MAX_CELLS + 1]
    assert len(cells) == moon_h3.MAX_CELLS + 1
    r = client.post("/api/moon/h3/elevation", json={"cells": cells})
    assert r.status_code == 422
    r = client.post("/api/moon/h3/elevation", json={"cells": cells[: moon_h3.MAX_CELLS]})
    assert r.status_code == 200
    assert len(r.json()["values"]) == moon_h3.MAX_CELLS


def test_listed_but_missing_parquet_is_503(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    moon_h3.reset()
    _write_layer(tmp_path, with_parquet=False)
    try:
        assert client.get("/api/moon/h3").json()[0]["available"] is False
        assert client.post("/api/moon/h3/elevation", json={"cells": [A5]}).status_code == 503
    finally:
        moon_h3.reset()


def test_store_is_lazy_and_reset_reloads(prepared, monkeypatch, tmp_path_factory):
    assert moon_h3.values("elevation", [A5])["values"][A5] == -1759.25
    other = tmp_path_factory.mktemp("other")
    monkeypatch.setattr(settings, "prepared_data_dir", str(other))
    moon_h3.reset()
    assert moon_h3.list_layers() == []
    with pytest.raises(moon_h3.UnknownLayer):
        moon_h3.values("elevation", [A5])


REAL = Path(settings.prepared_data_dir) / "moon" / "h3" / "elevation.parquet"


@pytest.mark.skipif(not REAL.exists(), reason="LOLA elevation layer not prepared")
def test_real_lola_layer_sanity():
    moon_h3.reset()
    try:
        centre = h3.latlng_to_cell(-43.31, -10.67, 5)  # Tycho floor beside the central peak
        rim = h3.latlng_to_cell(-41.90, -11.36, 5)
        imbrium = h3.latlng_to_cell(*IMBRIUM, 5)
        engelhardt = h3.latlng_to_cell(5.7, -159.0, 5)
        v = moon_h3.values("elevation", [centre, rim, imbrium, engelhardt])["values"]
        assert v[centre] < v[rim] - 2000
        assert -4000 < v[imbrium] < -2000
        assert v[engelhardt] > 8000
        layer = moon_h3.layer("elevation")
        assert layer["maxResolution"] == 5 and layer["range"][0] < 0 < layer["range"][1]
        vals = np.asarray(moon_h3._table(layer).vals)
        assert not np.isnan(vals).any()
        assert -9200 < float(vals.min()) < -8000 and 10000 < float(vals.max()) < 10800
    finally:
        moon_h3.reset()
