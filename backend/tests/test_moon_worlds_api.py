"""Moon worlds through the API: the scenario body filter, placing Moon buildings, world/type family checks,
branching and the Earth-only endpoints.

These tests write data, so they only run against a disposable *_test database:

    NEWWORLDS_DATABASE_URL=postgresql://newworlds:newworlds@localhost:5433/newworlds_test uv run pytest
"""

from uuid import uuid4

import pytest

from app.config import settings
from app.moon_buildings import MOON_TYPES, PARAMS, defaults

needs_test_db = pytest.mark.skipif(
    not settings.database_url.rsplit("/", 1)[-1].endswith("_test"),
    reason="writes data: needs a disposable *_test database (NEWWORLDS_DATABASE_URL)",
)

pytestmark = needs_test_db

SHACKLETON = (-89.45, 129.78)  # lunar south pole
PHOENIX = (33.45, -112.07)


@pytest.fixture
def make_world(client):
    """Create worlds (scenarios) and delete every one of them, and their projects, afterwards."""
    created: list[str] = []

    def make(name: str, **body) -> dict:
        r = client.post("/api/scenarios", json={"name": name, **body})
        assert r.status_code == 201, r.text
        created.append(r.json()["id"])
        return r.json()

    make.track = created.append
    yield make
    for sid in reversed(created):
        client.delete(f"/api/scenarios/{sid}")
    for sid in created:
        assert client.get(f"/api/scenarios/{sid}").status_code == 404


def _place(client, sid: str, btype: str, *, at=SHACKLETON, **extra):
    return client.post(f"/api/scenarios/{sid}/projects",
                       json={"type": btype, "latitude": at[0], "longitude": at[1], **extra})


def _ids(client, **params) -> set[str]:
    r = client.get("/api/scenarios", params=params)
    assert r.status_code == 200, r.text
    return {s["id"] for s in r.json()}


def test_body_filter_both_ways(client, make_world):
    earth = make_world("earth world")
    moon = make_world("moon world", body="moon")
    assert (earth["body"], moon["body"]) == ("earth", "moon")

    # The Earth app sends no parameter and never sees Moon worlds.
    default_ids = _ids(client)
    assert earth["id"] in default_ids and moon["id"] not in default_ids
    assert _ids(client, body="earth") == default_ids
    moon_ids = _ids(client, body="moon")
    assert moon["id"] in moon_ids and earth["id"] not in moon_ids

    summaries = client.get("/api/scenarios", params={"body": "moon"}).json()
    assert {s["body"] for s in summaries} == {"moon"}
    assert client.get("/api/scenarios", params={"body": "mars"}).status_code == 422
    assert client.post("/api/scenarios", json={"name": "x", "body": "mars"}).status_code == 422
    assert client.get(f"/api/scenarios/{moon['id']}").json()["body"] == "moon"


def test_place_every_moon_type_with_catalogue_defaults(client, make_world):
    sid = make_world("moon base", body="moon")["id"]
    placed = {}
    for btype in MOON_TYPES:
        params = defaults(btype)
        r = _place(client, sid, btype, name=f"My {btype}", parameters=params,
                   definition={"name": f"My {btype}", "templateId": btype})
        assert r.status_code == 201, (btype, r.text)
        p = r.json()
        assert p["type"] == btype and p["parameters"] == params
        assert (p["definition"]["name"], p["definition"]["templateId"]) == (f"My {btype}", btype)
        assert p["sourceDefinitionId"] is None
        placed[p["id"]] = p

    # Unknown values stay null after a reload (never zero).
    scenario = client.get(f"/api/scenarios/{sid}").json()
    assert scenario["body"] == "moon"
    assert {p["id"]: p for p in scenario["projects"]} == placed
    storage = next(p for p in scenario["projects"] if p["type"] == "moon_storage")
    assert storage["parameters"]["landedMassT"] is None
    summary = next(s for s in client.get("/api/scenarios", params={"body": "moon"}).json() if s["id"] == sid)
    assert summary["projectCount"] == len(MOON_TYPES)

    # No definition at all: the legacy adapter uses the Moon type as the template id.
    r = _place(client, sid, "moon_landing_pad", name="Pad")
    assert r.status_code == 201, r.text
    assert (r.json()["definition"]["templateId"], r.json()["parameters"]) == ("moon_landing_pad", {})

    # PATCH and DELETE work as on Earth.
    hab = next(p for p in placed.values() if p["type"] == "moon_habitat")
    r = client.patch(f"/api/projects/{hab['id']}",
                     json={"name": "Renamed", "parameters": {**hab["parameters"], "crew": 6, "landedMassT": None}})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["parameters"]["crew"], r.json()["parameters"]["landedMassT"]) == (
        "Renamed", 6, None)
    assert client.delete(f"/api/projects/{hab['id']}").status_code == 204
    assert len(client.get(f"/api/scenarios/{sid}").json()["projects"]) == len(MOON_TYPES)


def test_out_of_range_and_non_integer_parameters_are_422(client, make_world):
    sid = make_world("moon checks", body="moon")["id"]
    cases = [
        ({"crew": 0}, "crew must be at least 1"),
        ({"crew": 4.5}, "crew must be a whole number"),
        ({"waterRecoveryPct": 100}, "waterRecoveryPct must be at most 99"),
        ({"powerKw": "lots"}, "powerKw must be a number or null"),
    ]
    for params, msg in cases:
        r = _place(client, sid, "moon_habitat", parameters=params)
        assert r.status_code == 422 and msg in r.json()["detail"], (params, r.text)

    ok = _place(client, sid, "moon_habitat", parameters=defaults("moon_habitat"))
    assert ok.status_code == 201, ok.text
    r = client.patch(f"/api/projects/{ok.json()['id']}", json={"parameters": {"reserveDays": 2.5}})
    assert r.status_code == 422 and "reserveDays must be a whole number" in r.json()["detail"]
    # Unknown extra keys are kept.
    r = client.patch(f"/api/projects/{ok.json()['id']}", json={"parameters": {"crew": 2, "note": "pilot crew"}})
    assert r.status_code == 200 and r.json()["parameters"] == {"crew": 2, "note": "pilot crew"}


def test_non_finite_moon_parameters_are_422(client, make_world):
    sid = make_world("moon nan", body="moon")["id"]
    for value in ("NaN", "Infinity"):
        text = ('{"type":"moon_fission","latitude":0,"longitude":0,"parameters":{"extra":%s}}' % value)
        r = client.post(f"/api/scenarios/{sid}/projects", content=text,
                        headers={"content-type": "application/json"})
        assert r.status_code == 422 and "extra must be finite" in r.text, r.text


def test_type_family_must_match_the_world(client, make_world):
    moon = make_world("moon family", body="moon")["id"]
    earth = make_world("earth family")["id"]

    # Create: an Earth type on the Moon and a Moon type on Earth.
    r = _place(client, moon, "solar", parameters={"capacityKwp": 100})
    assert r.status_code == 422 and "Moon world" in r.json()["detail"] and "'solar'" in r.json()["detail"]
    r = _place(client, earth, "moon_habitat", at=PHOENIX, parameters=defaults("moon_habitat"))
    assert r.status_code == 422 and "only be placed in a Moon world" in r.json()["detail"]

    # PATCH: changing type across families is rejected both ways; same-family changes still work.
    hab = _place(client, moon, "moon_habitat", parameters=defaults("moon_habitat")).json()
    r = client.patch(f"/api/projects/{hab['id']}", json={"type": "solar", "parameters": {}})
    assert r.status_code == 422 and "Moon world" in r.json()["detail"]
    r = client.patch(f"/api/projects/{hab['id']}",
                     json={"type": "moon_fission", "parameters": defaults("moon_fission")})
    assert r.status_code == 200 and r.json()["type"] == "moon_fission"

    dc = _place(client, earth, "data_centre", at=PHOENIX, parameters={"itPowerKw": 5000}).json()
    r = client.patch(f"/api/projects/{dc['id']}", json={"type": "moon_storage", "parameters": {}})
    assert r.status_code == 422 and "only be placed in a Moon world" in r.json()["detail"]
    assert client.get(f"/api/scenarios/{earth}").json()["projects"][0]["type"] == "data_centre"

    # Earth types keep their rule that unknown = absent key, never null.
    r = _place(client, earth, "solar", at=PHOENIX, parameters={"capacityKwp": None})
    assert r.status_code == 422 and "capacityKwp must not be null" in r.json()["detail"]


def test_source_definition_is_unsupported_for_moon_types(client, make_world):
    sid = make_world("moon definitions", body="moon")["id"]
    r = _place(client, sid, "moon_greenhouse", sourceDefinitionId=str(uuid4()))
    assert r.status_code == 422 and "not supported for Moon building types" in r.json()["detail"]
    pad = _place(client, sid, "moon_landing_pad").json()
    r = client.patch(f"/api/projects/{pad['id']}", json={"sourceDefinitionId": str(uuid4())})
    assert r.status_code == 422 and "not supported for Moon building types" in r.json()["detail"]
    # Moon types cannot be saved as definitions either.
    r = client.post("/api/building-definitions", json={"name": "x", "type": "moon_habitat"})
    assert r.status_code == 422


def test_branch_keeps_body_and_copies_moon_buildings(client, make_world):
    parent = make_world("moon parent", body="moon")
    sid = parent["id"]
    for btype in ("moon_habitat", "moon_storage"):
        assert _place(client, sid, btype, parameters=defaults(btype),
                      definition={"name": btype, "templateId": btype}).status_code == 201

    r = client.post(f"/api/scenarios/{sid}/branch", json={"name": "moon branch"})
    assert r.status_code == 201, r.text
    branch = r.json()
    make_world.track(branch["id"])
    assert branch["body"] == "moon" and branch["parentScenarioId"] == sid

    def strip(projects):  # copies share one created_at, so the branch's order is not the parent's
        return sorted(((p["type"], p["parameters"], p["definition"], p["h3Id"]) for p in projects),
                      key=lambda t: t[0])

    parent_projects = client.get(f"/api/scenarios/{sid}").json()["projects"]
    assert strip(branch["projects"]) == strip(parent_projects)
    assert not {p["id"] for p in branch["projects"]} & {p["id"] for p in parent_projects}
    assert branch["id"] in _ids(client, body="moon") and branch["id"] not in _ids(client)

    # Earth branches stay on Earth.
    earth = make_world("earth parent")
    eb = client.post(f"/api/scenarios/{earth['id']}/branch", json={"name": "earth branch"}).json()
    make_world.track(eb["id"])
    assert eb["body"] == "earth"


def test_earth_only_endpoints_refuse_a_moon_world(client, make_world):
    sid = make_world("moon earth-only", body="moon")["id"]
    assert _place(client, sid, "moon_solar_tower", parameters=defaults("moon_solar_tower")).status_code == 201
    responses = [
        client.get(f"/api/scenarios/{sid}/timeline"),
        client.post(f"/api/scenarios/{sid}/evaluate", json={}),
        client.post("/api/building-assessments", json={
            "type": "solar", "scenarioId": sid, "location": {"latitude": PHOENIX[0], "longitude": PHOENIX[1]},
        }),
    ]
    for r in responses:
        assert r.status_code == 422 and "is a Moon world" in r.json()["detail"], (r.request.url, r.text)
    # Unknown scenarios are still a 404.
    assert client.get(f"/api/scenarios/{uuid4()}/timeline").status_code == 404


def test_every_moon_param_bound_is_enforced_by_the_api(client, make_world):
    """One request per type with every known param just above its maximum."""
    sid = make_world("moon bounds", body="moon")["id"]
    for btype in MOON_TYPES:
        over = {key: spec["max"] + 1 for key, spec in PARAMS[btype].items()}
        r = _place(client, sid, btype, parameters=over)
        assert r.status_code == 422, (btype, r.text)
        assert all(f"{key} must be at most" in r.json()["detail"] for key in over), r.text
    assert client.get(f"/api/scenarios/{sid}").json()["projects"] == []
