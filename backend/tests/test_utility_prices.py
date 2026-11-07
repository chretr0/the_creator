"""Average electricity and water price layers (scripts/prepare_utility_prices.py). Skip when not prepared."""

import csv
from pathlib import Path

import h3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import layers
from app.config import settings
from app.routers import layers as layers_router

PREPARED = Path(settings.prepared_data_dir)
AREAS = PREPARED / "utility_prices" / "areas.csv"

app = FastAPI()
app.include_router(layers_router.router)
client = TestClient(app)

needs_prices = pytest.mark.skipif(
    not (PREPARED / layers.PRICES_FILE).exists() or not AREAS.exists(), reason="utility prices not prepared"
)

PHOENIX = (33.4484, -112.0740)
LONDON = (51.5, -0.12)
MONTREAL = (45.5, -73.57)
OCEAN = (0.0, -30.0)


def _areas() -> dict[tuple[str, str], dict]:
    with AREAS.open(newline="", encoding="utf-8") as f:
        return {(r["code"], r["metric"]): r for r in csv.DictReader(f)}


def _values(layer: str, slice_id: str, points) -> list:
    cells = [h3.latlng_to_cell(lat, lon, 6) for lat, lon in points]
    r = client.post(f"/api/layers/{layer}/values", json={"slice": slice_id, "cells": cells})
    assert r.status_code == 200
    return r.json()["values"]


def test_price_layers_registered_with_units():
    for layer_id, units in (("electricity_price", "USD/kWh"), ("water_price", "USD/m³")):
        layer = layers.BY_ID[layer_id]
        assert layer.category == "Prices" and layer.agg == "mean"
        assert [s.id for s in layer.slices] == ["household", "business"]
        assert all(layers.slice_units(layer, s) == units for s in layer.slices)


@needs_prices
def test_state_price_beats_country_and_matches_areas_table():
    areas = _areas()
    az = float(areas[("US-AZ", "elec_household")]["usd"])
    gb = float(areas[("GB", "elec_household")]["usd"])
    phoenix, london, ocean = _values("electricity_price", "household", [PHOENIX, LONDON, OCEAN])
    assert phoenix == pytest.approx(az, rel=1e-4)
    assert london == pytest.approx(gb, rel=1e-4)
    assert ocean is None  # open sea is unknown, never zero


@needs_prices
def test_province_falls_back_to_country_when_it_has_no_price():
    areas = _areas()
    assert ("CA-QC", "water_household") not in areas
    (montreal,) = _values("water_price", "household", [MONTREAL])
    assert montreal == pytest.approx(float(areas[("CA", "water_household")]["usd"]), rel=1e-4)


@needs_prices
def test_profile_shows_price_area_and_basis():
    cell = h3.latlng_to_cell(*MONTREAL, 6)
    profile = client.get(f"/api/cells/{cell}/profile").json()
    elec = next(layer for layer in profile["layers"] if layer["layer"] == "electricity_price")
    attrs = {a["key"]: a["value"] for a in elec["attributes"]}
    assert attrs["price_area_name"] == "Canada · Québec"
    assert "USD" in attrs["elec_household_basis"] and "CAD" in attrs["elec_household_basis"]
    assert elec["source"]["sourceId"] == "PRICE-01"


@needs_prices
def test_coarse_hexagon_is_mean_of_priced_cells():
    coarse = h3.latlng_to_cell(*LONDON, 3)
    profile = client.get(f"/api/cells/{coarse}/profile").json()
    elec = next(layer for layer in profile["layers"] if layer["layer"] == "electricity_price")
    household = next(v for v in elec["values"] if v["slice"] == "household")
    assert household["cellsWithData"] > 0
    assert household["value"] == pytest.approx(float(_areas()[("GB", "elec_household")]["usd"]), rel=1e-3)
