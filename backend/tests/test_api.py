"""Integration tests: require the docker Postgres (docker compose up -d db flyway)."""

import h3


def test_cell_lookup(client):
    r = client.get("/api/cells/locate", params={"latitude": 51.5074, "longitude": -0.1278})
    assert r.status_code == 200
    body = r.json()
    assert body["resolution"] == 6 and body["h3Id"] == h3.latlng_to_cell(51.5074, -0.1278, 6)
    assert client.get(f"/api/cells/{body['h3Id']}").json()["h3Id"] == body["h3Id"]
    assert client.get("/api/cells/zzz").status_code == 404


def test_scenario_project_round_trip_and_branch(client):
    s = client.post("/api/scenarios", json={"name": "test scenario"}).json()
    lat, lng = 53.48095123456789, -2.23743987654321
    p = client.post(
        f"/api/scenarios/{s['id']}/projects",
        json={"type": "data_centre", "latitude": lat, "longitude": lng, "parameters": {"itPowerKw": 5000}},
    ).json()
    assert p["latitude"] == lat and p["longitude"] == lng  # exact round trip
    assert p["h3Resolution"] == 6

    moved = client.patch(f"/api/projects/{p['id']}", json={"latitude": -33.87, "longitude": 151.21}).json()
    assert moved["h3Id"] != p["h3Id"]

    reloaded = client.get(f"/api/scenarios/{s['id']}").json()
    assert reloaded["projects"][0]["latitude"] == -33.87
    assert reloaded["projects"][0]["parameters"] == {"itPowerKw": 5000}

    b = client.post(f"/api/scenarios/{s['id']}/branch", json={"name": "branch"}).json()
    assert b["parentScenarioId"] == s["id"]
    assert len(b["projects"]) == 1 and b["projects"][0]["id"] != p["id"]
    assert b["projects"][0]["h3Id"] == moved["h3Id"]

    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/scenarios/{s['id']}").json()["projects"] == []
    assert len(client.get(f"/api/scenarios/{b['id']}").json()["projects"]) == 1  # branch unaffected

    for sid in (b["id"], s["id"]):
        assert client.delete(f"/api/scenarios/{sid}").status_code == 204


def test_bad_latitude_rejected(client):
    s = client.post("/api/scenarios", json={"name": "bad"}).json()
    r = client.post(f"/api/scenarios/{s['id']}/projects", json={"type": "solar", "latitude": 95, "longitude": 0})
    assert r.status_code == 422
    client.delete(f"/api/scenarios/{s['id']}")
