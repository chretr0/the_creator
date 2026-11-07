"""Building-system API tests. They write data, so they only run against a disposable database whose
name ends in `_test`:

    NEWWORLDS_DATABASE_URL=postgresql://newworlds:newworlds@localhost:5433/newworlds_test uv run pytest
"""

import time

import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(
    not settings.database_url.rsplit("/", 1)[-1].endswith("_test"),
    reason="building API tests need a disposable *_test database (NEWWORLDS_DATABASE_URL)",
)

PHOENIX = (33.44838123456789, -112.07403987654321)

STATS = {
    "footprintM2": 2000,
    "operatingHoursPerDay": 8,
    "power": {"averageDemandKw": 100},
    "water": {"inputM3PerHour": 2},
    "costs": {"currency": "USD", "constructionTotal": 1000},
}


@pytest.fixture
def scenario(client):
    s = client.post("/api/scenarios", json={"name": "building test"}).json()
    yield s
    client.delete(f"/api/scenarios/{s['id']}")


def _place(client, sid, **kw):
    body = {"type": "custom", "name": "B", "latitude": PHOENIX[0], "longitude": PHOENIX[1], **kw}
    r = client.post(f"/api/scenarios/{sid}/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_templates(client):
    ts = client.get("/api/building-templates").json()
    ids = [t["id"] for t in ts]
    assert ids == ["power_station", "water_plant", "data_centre", "solar", "greenhouse", "custom"]
    by = {t["id"]: t for t in ts}
    assert by["power_station"]["producesPower"] and by["water_plant"]["producesWater"]
    assert [p["key"] for p in by["solar"]["parameters"]] == ["capacityKwp", "landAreaM2", "performanceRatio"]
    assert "pue" in [p["key"] for p in by["data_centre"]["parameters"]]
    for t in ts:  # no numeric defaults anywhere
        assert t["defaults"]["power"]["averageDemandKw"] is None and t["defaults"]["footprintM2"] is None
        assert "power.averageDemandKw" in t["fieldHelp"]


def test_definition_crud_and_snapshot_independence(client, scenario):
    d = client.post("/api/building-definitions", json={
        "name": "Pump house", "description": "Small pumping station", "type": "custom",
        "templateId": "custom", "stats": STATS,
        "criteria": [{"id": "c1", "kind": "construction_budget", "amount": 5000}],
    })
    assert d.status_code == 201, d.text
    d = d.json()
    assert client.get(f"/api/building-definitions/{d['id']}").json()["stats"]["power"]["averageDemandKw"] == 100
    assert d["id"] in [x["id"] for x in client.get("/api/building-definitions").json()]

    # Place from the saved definition (server snapshots it).
    p = _place(client, scenario["id"], sourceDefinitionId=d["id"])
    assert p["definition"]["name"] == "Pump house"
    assert p["definition"]["stats"]["power"]["averageDemandKw"] == 100
    assert p["sourceDefinitionId"] == d["id"]

    # Editing the definition changes future placements only.
    patched = client.patch(f"/api/building-definitions/{d['id']}", json={
        "name": "Bigger pump house", "stats": {**STATS, "power": {"averageDemandKw": 999}}}).json()
    assert patched["stats"]["power"]["averageDemandKw"] == 999 and patched["description"] == "Small pumping station"
    reloaded = client.get(f"/api/scenarios/{scenario['id']}").json()["projects"][0]
    assert reloaded["definition"]["stats"]["power"]["averageDemandKw"] == 100
    assert reloaded["definition"]["name"] == "Pump house"

    # Deleting it keeps the snapshot and clears the link.
    assert client.delete(f"/api/building-definitions/{d['id']}").status_code == 204
    assert client.get(f"/api/building-definitions/{d['id']}").status_code == 404
    reloaded = client.get(f"/api/scenarios/{scenario['id']}").json()["projects"][0]
    assert reloaded["sourceDefinitionId"] is None
    assert reloaded["definition"]["stats"]["power"]["averageDemandKw"] == 100


def test_invalid_inputs_rejected(client, scenario):
    bad = {"name": "x", "type": "data_centre", "parameters": {"pue": 0.5}}
    assert client.post("/api/building-definitions", json=bad).status_code == 422
    bad_stats = {"name": "x", "type": "custom", "stats": {"operatingHoursPerDay": 30}}
    assert client.post("/api/building-definitions", json=bad_stats).status_code == 422
    r = client.post(f"/api/scenarios/{scenario['id']}/projects", json={
        "type": "custom", "latitude": 1, "longitude": 1, "definition": {"stats": {"footprintM2": -5}}})
    assert r.status_code == 422


def test_legacy_project_adapter(client, scenario):
    p = _place(client, scenario["id"], type="data_centre", name="Old DC", parameters={"itPowerKw": 5000})
    assert p["definition"] == {
        **p["definition"], "name": "Old DC", "description": "", "templateId": "data_centre", "criteria": []}
    assert p["definition"]["stats"]["power"]["averageDemandKw"] is None  # never a template default
    assert p["parameters"] == {"itPowerKw": 5000}
    assert p["site"]["usableAreaM2"] is None and p["sourceDefinitionId"] is None


def test_branch_copies_snapshot_site_and_assumptions(client, scenario):
    sid = scenario["id"]
    client.patch(f"/api/scenarios/{sid}", json={"assumptions": {
        "periodDays": 10, "stress": {"waterAvailability": 0.5}, "legacyNote": "keep me"}})
    p = _place(client, sid, definition={"name": "W", "stats": STATS}, site={"waterAllocationM3PerDay": 20})
    b = client.post(f"/api/scenarios/{sid}/branch", json={"name": "branch"}).json()
    try:
        bp = b["projects"][0]
        assert bp["definition"] == p["definition"] and bp["site"] == p["site"]
        assert b["assumptions"]["periodDays"] == 10 and b["assumptions"]["stress"]["waterAvailability"] == 0.5
        assert b["assumptions"]["legacyNote"] == "keep me"

        client.patch(f"/api/projects/{bp['id']}", json={
            "definition": {"name": "W2", "stats": {**STATS, "footprintM2": 1}}, "site": {}})
        client.patch(f"/api/scenarios/{b['id']}", json={"assumptions": {"stress": {"waterAvailability": 1}}})
        orig = client.get(f"/api/scenarios/{sid}").json()
        assert orig["projects"][0]["definition"]["stats"]["footprintM2"] == 2000
        assert orig["projects"][0]["site"]["waterAllocationM3PerDay"] == 20
        assert orig["assumptions"]["stress"]["waterAvailability"] == 0.5
        assert orig["assumptions"]["periodDays"] == 10  # partial PATCH on the branch did not touch this
    finally:
        client.delete(f"/api/scenarios/{b['id']}")


def test_assumption_defaults_and_validation(client, scenario):
    a = client.get(f"/api/scenarios/{scenario['id']}").json()["assumptions"]
    assert a["periodDays"] == 30 and a["budgets"] == []
    assert a["stress"] == {"waterAvailability": 1, "powerAvailability": 1, "operatingDemand": 1, "operatingPrices": 1}
    r = client.patch(f"/api/scenarios/{scenario['id']}", json={"assumptions": {"stress": {"waterAvailability": 2}}})
    assert r.status_code == 422
    r = client.patch(f"/api/scenarios/{scenario['id']}", json={"assumptions": {"periodDays": -1}})
    assert r.status_code == 422


def test_move_preserves_snapshot_and_exact_coordinates(client, scenario):
    p = _place(client, scenario["id"], definition={"name": "M", "stats": STATS}, site={"usableAreaM2": 5000})
    renamed = client.patch(f"/api/projects/{p['id']}", json={"name": "Renamed"}).json()
    assert (renamed["latitude"], renamed["longitude"]) == PHOENIX
    lat, lon = 51.50740123456789, -0.12780987654321
    moved = client.patch(f"/api/projects/{p['id']}", json={"latitude": lat, "longitude": lon}).json()
    assert (moved["latitude"], moved["longitude"]) == (lat, lon) and moved["h3Id"] != p["h3Id"]
    reloaded = client.get(f"/api/scenarios/{scenario['id']}").json()["projects"][0]
    assert (reloaded["latitude"], reloaded["longitude"]) == (lat, lon)
    assert reloaded["definition"] == p["definition"] and reloaded["site"] == p["site"]
    assert reloaded["name"] == "Renamed"


def test_evaluate_with_stress(client, scenario):
    sid = scenario["id"]
    client.patch(f"/api/scenarios/{sid}", json={"assumptions": {"periodDays": 10, "budgets": [
        {"id": "pool", "label": "Town water", "kind": "water_m3_per_day", "amount": 20}]}})
    p = _place(client, sid, definition={"name": "W", "stats": STATS, "criteria": [
        {"id": "w", "kind": "water_budget"}]})

    ev = client.post(f"/api/scenarios/{sid}/evaluate", json={"stress": {"waterAvailability": 0.5}})
    assert ev.status_code == 200, ev.text
    ev = ev.json()
    un, st = ev["unstressed"], ev["stressed"]
    assert un["buildings"][0]["result"]["electricityDemand"]["value"] == 8000
    assert un["budgets"][0]["declaredSupply"]["value"] == 200 and un["budgets"][0]["unmet"]["value"] == 0
    assert st["budgets"][0]["declaredSupply"]["value"] == 100 and st["budgets"][0]["unmet"]["value"] == 60
    assert un["buildings"][0]["assessment"]["state"] == "meets_criteria"
    assert st["buildings"][0]["assessment"]["state"] == "fails_criteria"
    assert un["budgets"][0]["projectIds"] == [p["id"]]
    assert "powerAvailability" in ev["controlNotes"] and "no calculable effect" in ev["controlNotes"]["powerAvailability"]
    assert len(ev["inputsHash"]) == 64

    # Saved controls are used without a body; neutral = identical results.
    plain = client.post(f"/api/scenarios/{sid}/evaluate").json()
    assert plain["stress"]["waterAvailability"] == 1
    assert plain["stressed"]["budgets"] == plain["unstressed"]["budgets"]
    assert plain["inputsHash"] != ev["inputsHash"]


def test_evaluate_shows_site_supply_and_shortfall_per_building(client, scenario):
    """Spec fixture with a site allocation and no supply criterion: the check is still reported."""
    sid = scenario["id"]
    client.patch(f"/api/scenarios/{sid}", json={"assumptions": {"periodDays": 10}})
    _place(client, sid, definition={"name": "W", "stats": STATS}, site={"waterAllocationM3PerDay": 20})
    ev = client.post(f"/api/scenarios/{sid}/evaluate", json={"stress": {"waterAvailability": 0.5}}).json()
    checks = {k: [c for c in ev[k]["buildings"][0]["assessment"]["checks"] if c["kind"] == "water_budget"]
              for k in ("unstressed", "stressed")}
    [un], [st] = checks["unstressed"], checks["stressed"]
    assert (un["status"], un["actual"], un["requiredValue"], un["unit"]) == ("pass", 160, 200, "m³")
    assert (st["status"], st["actual"], st["requiredValue"]) == ("fail", 160, 100)
    assert "unmet 60" in st["explanation"]
    # The declared site allocation activates a required check, so stress changes the building's state.
    assert un["required"] is True
    assert ev["unstressed"]["buildings"][0]["assessment"]["state"] == "meets_criteria"
    assert ev["stressed"]["buildings"][0]["assessment"]["state"] == "fails_criteria"


DC_STATS = {"footprintM2": 9290, "operatingHoursPerDay": 24,
            "power": {"averageDemandKw": 20000, "peakDemandKw": 30000}, "water": {"inputM3PerHour": 85}}


def test_building_without_requirements_explains_what_to_add(client, scenario):
    """All statistics filled but no requirements and no site supply: usage is still calculated and the
    summary says what to add instead of implying missing map data."""
    r = client.post("/api/building-assessments", json={
        "scenarioId": scenario["id"], "type": "data_centre", "stats": DC_STATS,
        "location": {"latitude": 33.33, "longitude": -112.26}}).json()["location"]
    assert r["assessment"]["state"] == "insufficient_data" and r["assessment"]["checks"] == []
    assert "no required location requirements" in r["assessment"]["summary"]
    assert r["result"]["electricityDemand"]["value"] == 20000 * 24 * 30


def test_declared_site_assumptions_are_checked_at_exact_location(client, scenario):
    """Reported case: a data centre with no requirements but declared site supply that it exceeds must
    fail, not say 'more information needed'."""
    site = {"usableAreaM2": 1000, "connectedCapacityKw": 100, "energyBudgetKwhPerDay": 100,
            "waterAllocationM3PerDay": 2000}
    r = client.post("/api/building-assessments", json={
        "scenarioId": scenario["id"], "type": "data_centre", "stats": DC_STATS, "site": site,
        "location": {"latitude": 33.33, "longitude": -112.26}}).json()["location"]
    a = r["assessment"]
    assert a["state"] == "fails_criteria"
    got = {c["kind"]: (c["status"], c["required"]) for c in a["checks"]}
    assert got == {"site_area": ("fail", True), "power_capacity": ("fail", True),
                   "energy_budget": ("fail", True), "water_budget": ("fail", True)}

    # Generous declarations pass; the placed building's evaluation agrees with the preview.
    ok = {"usableAreaM2": 20000, "connectedCapacityKw": 40000, "energyBudgetKwhPerDay": 500000,
          "waterAllocationM3PerDay": 3000}
    p = _place(client, scenario["id"], type="data_centre", definition={"name": "DC", "stats": DC_STATS}, site=ok)
    ev = client.post(f"/api/scenarios/{scenario['id']}/evaluate", json={}).json()
    b = next(x for x in ev["unstressed"]["buildings"] if x["projectId"] == p["id"])
    assert b["assessment"]["state"] == "meets_criteria"
    assert all(c["required"] and c["status"] == "pass" for c in b["assessment"]["checks"])


def test_location_assessment_excludes_moved_building(client, scenario):
    sid = scenario["id"]
    client.patch(f"/api/scenarios/{sid}", json={"assumptions": {"periodDays": 10, "budgets": [
        {"id": "pool", "label": "Town water", "kind": "water_m3_per_day", "amount": 20}]}})
    p = _place(client, sid, definition={"name": "W", "stats": STATS})
    body = {"scenarioId": sid, "type": "custom", "stats": STATS,
            "criteria": [{"id": "w", "kind": "water_budget"}],
            "location": {"latitude": PHOENIX[0], "longitude": PHOENIX[1]}}
    other = client.post("/api/building-assessments", json=body).json()
    assert other["location"]["assessment"]["checks"][0]["status"] == "fail"  # 160 vs 200 - 160 remaining
    same = client.post("/api/building-assessments", json={**body, "excludeProjectId": p["id"]}).json()
    assert same["location"]["assessment"]["checks"][0]["status"] == "pass"
    assert same["periodDays"] == 10 and same["modelVersion"]


def test_area_assessment_region_fast_and_bounded(client):
    body = {"type": "custom", "stats": STATS, "region": "arizona", "limit": 20, "criteria": [
        {"id": "ghi", "kind": "layer", "layerId": "solar_ghi", "sliceId": "clim-ann", "min": 5.5},
        {"id": "cb", "kind": "construction_budget", "amount": 5000},
    ]}
    t = time.perf_counter()
    r = client.post("/api/building-assessments", json=body)
    elapsed = time.perf_counter() - t
    assert r.status_code == 200, r.text
    area = r.json()["area"]
    assert elapsed < 2.0
    assert area["cellCount"] == len(area["cells"]) > 1000
    assert sum(area["counts"].values()) == area["cellCount"]
    assert len(area["candidates"]) == 20
    rank = {"meets_criteria": 0, "insufficient_data": 1, "fails_criteria": 2}
    keys = [(rank[c["assessment"]["state"]], c["h3Id"]) for c in area["candidates"]]
    assert keys == sorted(keys)
    check = area["candidates"][0]["assessment"]["checks"][0]
    assert check["unit"] == "kWh/m²/day" and "resolution-6 H3 cell" in check["source"]


def test_oversized_bounds_rejected(client):
    body = {"type": "custom", "stats": STATS, "bounds": {"west": -120, "south": 20, "east": -80, "north": 50}}
    r = client.post("/api/building-assessments", json=body)
    assert r.status_code == 422 and "Narrow the area" in r.json()["detail"]
    one_target = {"type": "custom", "region": "uk", "location": {"latitude": 1, "longitude": 1}}
    assert client.post("/api/building-assessments", json=one_target).status_code == 422


def test_location_assessment_offers_business_price_explicitly(client, scenario):
    """The cell's business price is offered, not filled in; applying it persists its source."""
    req = {"scenarioId": scenario["id"], "type": "custom", "stats": {**STATS, "costs": {"currency": "USD"}},
           "location": {"latitude": PHOENIX[0], "longitude": PHOENIX[1]}}
    loc = client.post("/api/building-assessments", json=req).json()["location"]
    elec, water = loc["utilityPrices"]
    assert elec["resource"] == "electricity" and elec["status"] == "available" and elec["unit"] == "USD/kWh"
    assert water["status"] == "unavailable" and water["price"] is None
    assert loc["result"]["costs"]["electricity"]["value"] is None  # not applied: unknown

    price = elec["price"]
    applied = {"currency": "USD", "electricityPricePerKwh": price["value"], "electricityPriceSource": price}
    req["stats"] = {**STATS, "costs": applied}
    loc = client.post("/api/building-assessments", json=req).json()["location"]
    assert loc["utilityPrices"][0]["status"] == "applied"
    cost = loc["result"]["costs"]["electricity"]
    assert cost["value"] == pytest.approx(8000 * 3 * price["value"])  # default period is 30 days
    assert "location default" in cost["basis"] and "PRICE-01" in cost["basis"]

    p = _place(client, scenario["id"], definition={"name": "P", "stats": req["stats"]})
    got = client.get(f"/api/scenarios/{scenario['id']}").json()["projects"][0]
    assert got["id"] == p["id"]
    assert got["definition"]["stats"]["costs"]["electricityPriceSource"]["priceArea"] == "US-AZ"


def test_location_price_never_mixed_with_other_currency(client, scenario):
    loc = client.post("/api/building-assessments", json={
        "type": "custom", "stats": {**STATS, "costs": {"currency": "EUR"}},
        "location": {"latitude": PHOENIX[0], "longitude": PHOENIX[1]}}).json()["location"]
    assert loc["utilityPrices"][0]["status"] == "currency_mismatch"
    src = loc["utilityPrices"][0]["price"]
    r = client.post("/api/building-assessments", json={
        "type": "custom", "stats": {"costs": {"currency": "EUR", "electricityPricePerKwh": src["value"],
                                              "electricityPriceSource": src}},
        "location": {"latitude": PHOENIX[0], "longitude": PHOENIX[1]}})
    assert r.status_code == 422 and "never converted" in r.text
