"""Regression tests for persistence / validation fixes: branch contributors, double-counted supply,
definition template fields, non-finite numbers, size limits and definition type on placement.

The API tests write data, so they only run against a disposable *_test database:

    NEWWORLDS_DATABASE_URL=postgresql://newworlds:newworlds@localhost:5433/newworlds_test uv run pytest
"""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.building_models import (
    Criterion,
    EvaluateRequest,
    ScenarioAssumptions,
    WorkerStats,
)
from app.config import settings

needs_test_db = pytest.mark.skipif(
    not settings.database_url.rsplit("/", 1)[-1].endswith("_test"),
    reason="writes data: needs a disposable *_test database (NEWWORLDS_DATABASE_URL)",
)

PHOENIX = (33.45, -112.07)


def _budget(id_, kind, contributors, **kw):
    return {"id": id_, "label": id_, "kind": kind, "amount": 0, "contributingProjectIds": contributors, **kw}


def _post_raw(client, url, text, method="POST"):
    """Send JSON text as-is (the NaN / Infinity tokens Python's json parser accepts)."""
    return client.request(method, url, content=text, headers={"content-type": "application/json"})


@pytest.fixture
def scenario(client):
    s = client.post("/api/scenarios", json={"name": "persistence test"}).json()
    yield s
    client.delete(f"/api/scenarios/{s['id']}")


# --- model-only checks ---------------------------------------------------------------------------


def test_same_plant_in_two_pools_of_one_kind_is_rejected():
    plant = str(uuid4())
    two_energy = [_budget("a", "energy_kwh_per_day", [plant]), _budget("b", "energy_kwh_per_day", [plant])]
    with pytest.raises(ValidationError, match="only be counted in one"):
        ScenarioAssumptions.model_validate({"budgets": two_energy})
    with pytest.raises(ValidationError, match="only be counted in one"):
        EvaluateRequest.model_validate({"budgets": two_energy})
    # Different kinds (energy vs capacity) and a repeat inside one budget are fine.
    ScenarioAssumptions.model_validate({"budgets": [
        _budget("a", "energy_kwh_per_day", [plant, plant]), _budget("b", "power_capacity_kw", [plant]),
    ]})


def test_worker_counts_and_classes_are_bounded_and_finite():
    with pytest.raises(ValidationError):
        WorkerStats.model_validate({"capacity": 10**400})
    assert WorkerStats.model_validate({"capacity": 10**9}).capacity == 10**9
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="finite"):
            Criterion.model_validate({"id": "c", "kind": "layer", "layerId": "worldcover", "classes": [bad]})


# --- API checks ----------------------------------------------------------------------------------


@needs_test_db
def test_branch_keeps_plant_contributions(client, scenario):
    sid = scenario["id"]
    plant = client.post(f"/api/scenarios/{sid}/projects", json={
        "type": "power_station", "name": "Plant", "latitude": PHOENIX[0], "longitude": PHOENIX[1],
        "definition": {"stats": {"operatingHoursPerDay": 24,
                                 "power": {"averageOutputKw": 10, "averageDemandKw": 0}}},
    }).json()
    r = client.patch(f"/api/scenarios/{sid}", json={"assumptions": {
        "budgets": [_budget("pool", "energy_kwh_per_day", [plant["id"]])],
    }})
    assert r.status_code == 200, r.text

    branch = client.post(f"/api/scenarios/{sid}/branch", json={"name": "branch"}).json()
    try:
        new_plant = branch["projects"][0]["id"]
        assert new_plant != plant["id"]
        assert branch["assumptions"]["budgets"][0]["contributingProjectIds"] == [new_plant]

        def supply(scenario_id):
            ev = client.post(f"/api/scenarios/{scenario_id}/evaluate", json={}).json()
            return ev["unstressed"]["budgets"][0]["declaredSupply"]["value"]

        assert supply(sid) == supply(branch["id"]) == 7200  # 10 kW x 24 h x 30 days
        # The parent keeps pointing at its own plant.
        parent = client.get(f"/api/scenarios/{sid}").json()
        assert parent["assumptions"]["budgets"][0]["contributingProjectIds"] == [plant["id"]]
    finally:
        client.delete(f"/api/scenarios/{branch['id']}")


@needs_test_db
def test_double_counted_plant_rejected_by_api(client, scenario):
    sid, plant = scenario["id"], str(uuid4())
    budgets = [_budget("a", "energy_kwh_per_day", [plant]),
               _budget("b", "energy_kwh_per_day", [plant], scope={"kind": "region", "region": "arizona"})]
    r = client.patch(f"/api/scenarios/{sid}", json={"assumptions": {"budgets": budgets}})
    assert r.status_code == 422 and "only be counted in one" in r.text
    r = client.post(f"/api/scenarios/{sid}/evaluate", json={"budgets": budgets})
    assert r.status_code == 422


@needs_test_db
def test_definition_patch_writes_template_fields(client):
    d = client.post("/api/building-definitions", json={
        "name": "DC", "type": "data_centre", "templateId": "data_centre", "templateVersion": 1,
    }).json()
    url = f"/api/building-definitions/{d['id']}"
    try:
        r = client.patch(url, json={"type": "power_station", "templateId": "power_station", "templateVersion": 1})
        assert r.status_code == 200, r.text
        assert (r.json()["type"], r.json()["templateId"], r.json()["templateVersion"]) == (
            "power_station", "power_station", 1)
        # Editing other fields keeps the template.
        assert client.patch(url, json={"name": "Renamed"}).json()["templateId"] == "power_station"
        # A type change without a template clears it rather than leaving a stale one.
        r = client.patch(url, json={"type": "solar"}).json()
        assert (r["type"], r["templateId"], r["templateVersion"]) == ("solar", None, None)
        # Out-of-range template versions are a 422, not a database error.
        assert client.patch(url, json={"templateVersion": 3_000_000_000}).status_code == 422
        r = client.post("/api/building-definitions", json={"name": "x", "type": "custom",
                                                           "templateVersion": 3_000_000_000})
        assert r.status_code == 422
    finally:
        client.delete(url)


@needs_test_db
def test_non_finite_numbers_give_422(client, scenario):
    sid = scenario["id"]
    cases = [
        ("POST", "/api/building-assessments",
         '{"type":"custom","location":{"latitude":NaN,"longitude":0}}'),
        ("POST", "/api/building-definitions", '{"name":"x","type":"custom","stats":{"footprintM2":NaN}}'),
        ("POST", "/api/building-definitions",
         '{"name":"x","type":"custom","criteria":[{"id":"a","kind":"layer","layerId":"worldcover",'
         '"classes":[NaN]}]}'),
        ("POST", "/api/scenarios", '{"name":"x","assumptions":{"periodDays":Infinity}}'),
        ("POST", "/api/scenarios", '{"name":"x","assumptions":{"legacyKey":[1, NaN]}}'),
        ("PATCH", f"/api/scenarios/{sid}", '{"assumptions":{"periodDays":-Infinity}}'),
        ("PATCH", f"/api/scenarios/{sid}", '{"assumptions":{"legacyKey":NaN}}'),
        ("POST", f"/api/scenarios/{sid}/projects",
         '{"type":"custom","latitude":0,"longitude":0,"definition":{"criteria":[{"id":"a","kind":"layer",'
         '"classes":[Infinity]}]}}'),
    ]
    for method, url, text in cases:
        r = _post_raw(client, url, text, method)
        assert r.status_code == 422, (url, text, r.status_code, r.text)
        json.loads(r.text)  # strict JSON body


@needs_test_db
def test_size_limits(client, scenario):
    sid = scenario["id"]
    big = "x" * 1_100_000
    body = {"type": "custom", "latitude": 0, "longitude": 0, "definition": {"description": big}}
    assert client.post(f"/api/scenarios/{sid}/projects", json=body).status_code == 413

    def chunks():  # no Content-Length: the limit still applies
        yield json.dumps(body).encode()

    r = client.post(f"/api/scenarios/{sid}/projects", content=chunks(),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413
    # Under the body limit, the snapshot strings carry the same caps as a saved definition.
    body["definition"]["description"] = "x" * 5001
    assert client.post(f"/api/scenarios/{sid}/projects", json=body).status_code == 422
    body["definition"] = {"stats": {"costs": {"priceBasis": "x" * 201}}}
    assert client.post(f"/api/scenarios/{sid}/projects", json=body).status_code == 422
    assert client.post("/api/scenarios", json={"name": "x" * 201}).status_code == 422


@needs_test_db
def test_placing_from_definition_checks_type(client, scenario):
    sid = scenario["id"]
    d = client.post("/api/building-definitions", json={
        "name": "DC", "type": "data_centre", "templateId": "data_centre",
        "parameters": {"itPowerKw": 5000, "pue": 1.3},
    }).json()
    try:
        place = {"latitude": PHOENIX[0], "longitude": PHOENIX[1], "sourceDefinitionId": d["id"]}
        r = client.post(f"/api/scenarios/{sid}/projects", json={"type": "solar", **place})
        assert r.status_code == 422 and "data_centre" in r.text
        r = client.post(f"/api/scenarios/{sid}/projects", json={"type": "data_centre", **place})
        assert r.status_code == 201, r.text
        assert r.json()["parameters"] == {"itPowerKw": 5000, "pue": 1.3}
    finally:
        client.delete(f"/api/building-definitions/{d['id']}")


def test_invalid_stored_assumptions_keep_valid_parts():
    """A plant listed in two pools of one kind (saved before that rule) must not wipe the scenario."""
    from app.routers.scenarios import scenario_assumptions

    pid = "11111111-1111-1111-1111-111111111111"
    pool = {"kind": "water_m3_per_day", "amount": 20, "scope": {"kind": "scenario"}}
    a = scenario_assumptions({
        "periodDays": 10,
        "stress": {"waterAvailability": 0.5},
        "budgets": [
            {**pool, "id": "a", "label": "A", "contributingProjectIds": [pid]},
            {**pool, "id": "b", "label": "B", "contributingProjectIds": [pid]},
            {"id": "bad", "label": "broken", "kind": "nope"},
        ],
    })
    assert a.period_days == 10 and a.stress.water_availability == 0.5
    assert [b.id for b in a.budgets] == ["a", "b"]
    assert [str(x) for x in a.budgets[0].contributing_project_ids] == [pid]
    assert a.budgets[1].contributing_project_ids == []
