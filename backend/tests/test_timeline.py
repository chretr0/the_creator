from contextlib import contextmanager
from uuid import uuid4

import h3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import timeline
from app.building_assess import PlacedBuilding, ScenarioContext
from app.building_models import BuildingStats, DefinitionSnapshot, ScenarioAssumptions, SiteAssumptions
from app.routers import buildings


def building(stats):
    return PlacedBuilding(id=uuid4(), name="Station", type="power_station", latitude=33.45, longitude=-112.07,
                          h3_id=h3.latlng_to_cell(33.45, -112.07, 6), parameters={}, site=SiteAssumptions(),
                          snapshot=DefinitionSnapshot(name="Station", stats=BuildingStats.model_validate(stats)))


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(timeline, "baseline", lambda cells, _: [12.0] * len(cells))
    monkeypatch.setattr(timeline, "location_context", lambda _: None)
    return ScenarioContext(buildings=[building({"operatingHoursPerDay": 12,
        "emissions": [{"id": "co2", "pollutant": "CO2", "rateKgPerHour": 10}],
        "power": {"averageDemandKw": 2}, "water": {"inputM3PerHour": 3}})],
        assumptions=ScenarioAssumptions.model_validate({"stress": {"operatingDemand": 5}}))


def test_daily_rates_use_declared_hours_and_ignore_legacy_stress(context):
    result = timeline.timeline_inputs(context)
    p = result["projects"][0]
    assert p["emissions"][0]["kgPerDay"] == 120
    assert p["electricityKwhPerDay"] == 24
    assert p["waterM3PerDay"] == 36
    assert len(result["cells"]) == 217 * 7
    assert all(h3.get_resolution(c["h3Id"]) == 7 for c in result["cells"])
    assert result["baseline"]["period"] == "2024"
    assert context.assumptions.stress.operating_demand == 5


def test_unknown_and_zero_emissions_remain_distinct(context):
    context.buildings = [building({"emissions": [{"id": "co2", "pollutant": "CO2", "rateKgPerHour": 10}]}),
                         building({"operatingHoursPerDay": 0, "emissions": [{"id": "co2", "pollutant": "CO2", "rateKgPerHour": 10}]})]
    projects = timeline.timeline_inputs(context)["projects"]
    assert projects[0]["emissions"][0]["kgPerDay"] is None
    assert projects[0]["emissions"][0]["missing"]
    assert projects[1]["emissions"][0]["kgPerDay"] == 0


def test_overlapping_project_domains_are_deduplicated(context):
    context.buildings.append(context.buildings[0])
    assert len(timeline.timeline_inputs(context)["cells"]) == 217 * 7


def test_empty_world(context):
    context.buildings.clear()
    result = timeline.timeline_inputs(context)
    assert result["projects"] == result["cells"] == []


def test_endpoint_returns_serialisable_inputs_without_modifying_database(monkeypatch, context):
    @contextmanager
    def read_transaction():
        yield object()

    monkeypatch.setattr(buildings, "transaction", read_transaction)
    monkeypatch.setattr(buildings, "load_context", lambda conn, scenario_id: context)
    app = FastAPI()
    app.include_router(buildings.router)
    with TestClient(app) as client:
        response = client.get(f"/api/scenarios/{uuid4()}/timeline")
        assert response.status_code == 200
        assert response.json()["projects"][0]["emissions"][0]["kgPerDay"] == 120
        assert client.get("/api/scenarios/not-a-uuid/timeline").status_code == 422
