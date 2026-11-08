"""Moon routes against a tiny fixture dataset (never the real data/prepared/moon)."""

import json

import h3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import bodies, moon_reference
from app.bodies import EARTH, MOON
from app.config import settings
from app.routers import moon as moon_router

APOLLO_11 = (0.67408, 23.47297)  # (lat, lon)
SURVEYOR_5 = (1.455, 23.1943)
RANGER_7 = (-10.634, -20.6771)


def _point(lat, lon):
    return {"type": "Point", "coordinates": [lon, lat]}


def _feature(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def _site(sid, name, latlon, kind, heritage):
    return _feature(
        _point(*latlon) if latlon else None,
        id=sid, name=name, mission=name, kind=kind, date="1969-07-20" if sid == "apollo-11" else None,
        dateNote=None, elevationM=None, uncertainty=None, heritage=heritage,
        evidenceType="reported_record", sourceId="MOON-SITE-01",
    )


SOURCES = {
    "MOON-SITE-01": {"id": "MOON-SITE-01", "name": "LROC landed objects", "provider": "LROC / ASU",
                     "licence": "U.S. public domain", "attribution": "NASA/GSFC/ASU", "evidenceType": "reported_record",
                     "url": "https://example.test/sites", "retrievedAt": "2026-11-08", "limitations": ["positions ±10 m"],
                     "commercialUse": True},
    "MOON-PLACE-01": {"id": "MOON-PLACE-01", "name": "IAU Gazetteer (Moon)", "provider": "IAU / USGS",
                      "licence": "public domain", "attribution": "IAU WGPSN / USGS", "evidenceType": "reference",
                      "url": "https://planetarynames.wr.usgs.gov/", "retrievedAt": "2026-11-08", "limitations": [],
                      "commercialUse": True},
    "MOON-PLACE-02": {"id": "MOON-PLACE-02", "name": "Mare outlines", "provider": "USGS", "licence": "public domain",
                      "attribution": "USGS", "evidenceType": "reference", "url": None, "retrievedAt": None,
                      "limitations": [], "commercialUse": True},
    "MOON-SITE-02": {"id": "MOON-SITE-02", "name": "Planned missions", "provider": "NASA", "licence": "public domain",
                     "attribution": "NASA", "evidenceType": "planned", "url": None, "retrievedAt": "2026-11-08",
                     "limitations": ["dates slip"], "commercialUse": True},
    "MOON-SITE-06": {"id": "MOON-SITE-06", "name": "NASA 2011 heritage recommendations Rev A", "provider": "NASA",
                     "licence": "U.S. public domain", "attribution": "NASA", "evidenceType": "rule", "url": None,
                     "retrievedAt": "2026-11-08", "limitations": [], "commercialUse": True},
}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """Write a minimal data/prepared/moon tree and point settings at it."""
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    moon_reference.reset()
    root = tmp_path / "moon"
    for sub in ("sites", "places", "regions", "missions", "h3"):
        (root / sub).mkdir(parents=True)

    sites = {"type": "FeatureCollection", "features": [
        _site("apollo-11", "Apollo 11 LM descent stage", APOLLO_11, "crewed_landing", "landing"),
        _site("surveyor-5", "Surveyor 5", SURVEYOR_5, "soft_landing", None),
        _site("ranger-7", "Ranger 7", RANGER_7, "impact", "impact"),
        _site("lost-probe", "Unlocated probe", None, "impact", "impact"),  # no geometry: skipped
    ]}
    places = [
        {"id": "5675", "name": "Statio Tranquillitatis", "type": "Statio", "diameterKm": None,
         "lat": 0.67409, "lon": 23.47298, "quad": "LAC-60", "approved": "1976", "origin": None, "link": None},
        {"id": "4009", "name": "Moltke", "type": "Crater, craters", "diameterKm": 6.5,
         "lat": -0.6, "lon": 24.2, "quad": "LAC-79", "approved": "1935", "origin": None, "link": None},
        {"id": "3691", "name": "Mare Tranquillitatis", "type": "Mare, maria", "diameterKm": 875.7,
         "lat": 8.35, "lon": 30.83, "quad": None, "approved": "1935", "origin": None, "link": None},
    ]
    mare = {"type": "FeatureCollection", "features": [_feature(
        {"type": "Polygon", "coordinates": [[[15, -5], [40, -5], [40, 20], [15, 20], [15, -5]]]},
        id="mare-tranquillitatis", name="Mare Tranquillitatis",
    )]}
    missions = {"type": "FeatureCollection", "features": [_feature(
        None, id="clps-x", name="CLPS X", kind="planned_mission", mission="CLPS X", target="Somewhere",
        date="Q1 2027", asOf="2026-11-08", evidenceType="planned", approximate=True, note=None, sourceId="MOON-SITE-02",
    )]}
    (root / "sites" / "anthropogenic_objects.geojson").write_text(json.dumps(sites))
    (root / "places" / "gazetteer.json").write_text(json.dumps(places))
    (root / "regions" / "mare.geojson").write_text(json.dumps(mare))
    (root / "missions" / "planned.geojson").write_text(json.dumps(missions))
    (root / "source.json").write_text(json.dumps({
        "body": "moon", "generatedAt": "2026-11-08T00:00:00Z", "sources": SOURCES,
        "layers": [
            {"id": "moon_sites", "file": "sites/anthropogenic_objects.geojson", "source": "MOON-SITE-01", "count": 3},
            {"id": "moon_places", "file": "places/gazetteer.json", "source": "MOON-PLACE-01", "count": 3},
            {"id": "moon_mare", "file": "regions/mare.geojson", "source": "MOON-PLACE-02", "count": 1},
            {"id": "moon_missions", "file": "missions/planned.geojson", "source": "MOON-SITE-02", "count": 1},
        ],
    }))
    (root / "h3" / "layers.json").write_text(json.dumps({
        "layers": [{"id": "elevation", "name": "Elevation (LOLA)", "unit": "m", "sourceId": "MOON-TOPO-02",
                    "evidenceType": "orbital_retrieval", "maxResolution": 5}],
        "sources": {"MOON-TOPO-02": {"id": "MOON-TOPO-02", "name": "LOLA DEM", "provider": "NASA GSFC",
                                     "licence": "U.S. public domain", "attribution": "NASA/GSFC LOLA",
                                     "evidenceType": "orbital_retrieval", "url": None, "retrievedAt": "2026-11-08",
                                     "limitations": [], "commercialUse": True}},
    }))
    yield root
    moon_reference.reset()


@pytest.fixture
def unprepared(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "prepared_data_dir", str(tmp_path))
    moon_reference.reset()
    yield tmp_path
    moon_reference.reset()


@pytest.fixture(scope="module")
def api():
    """Only the Moon router: no database needed."""
    app = FastAPI()
    app.include_router(moon_router.router)
    with TestClient(app) as c:
        yield c


# -- manifest and files ------------------------------------------------------------------------


def test_manifest_503_when_not_prepared(api, unprepared):
    for path in ("/api/moon", "/api/moon/keepout", "/api/moon/layers/moon_sites",
                 f"/api/moon/cells/{h3.latlng_to_cell(0, 0, 6)}/context"):
        r = api.get(path)
        assert r.status_code == 503, path
        assert "scripts/moon/prepare_moon_reference.py" in r.json()["detail"]


def test_manifest_marks_available_layers(api, prepared):
    (prepared / "missions" / "planned.geojson").unlink()
    m = api.get("/api/moon").json()
    assert m["body"] == "moon" and "MOON-SITE-06" in m["sources"]
    available = {layer["id"]: layer["available"] for layer in m["layers"]}
    assert available == {"moon_sites": True, "moon_places": True, "moon_mare": True, "moon_missions": False}
    assert api.get("/api/moon/layers/moon_missions").status_code == 503


def test_layer_files(api, prepared):
    r = api.get("/api/moon/layers/moon_sites")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")
    assert len(r.json()["features"]) == 4
    r = api.get("/api/moon/layers/moon_places")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.json()[0]["name"] == "Statio Tranquillitatis"
    assert api.get("/api/moon/layers/nope").status_code == 404


def test_layer_file_outside_the_moon_dir_is_never_served(api, prepared):
    (prepared.parent / "secret.json").write_text("{}")
    m = json.loads((prepared / "source.json").read_text())
    m["layers"].append({"id": "escape", "file": "../secret.json", "source": "X", "count": 0})
    (prepared / "source.json").write_text(json.dumps(m))
    assert api.get("/api/moon/layers/escape").status_code == 503
    assert {layer["id"]: layer["available"] for layer in api.get("/api/moon").json()["layers"]}["escape"] is False


# -- keep-out rings ----------------------------------------------------------------------------


def test_keepout_rings(api, prepared):
    fc = api.get("/api/moon/keepout").json()
    assert fc["type"] == "FeatureCollection"
    by_site = {f["properties"]["siteId"]: f for f in fc["features"]}
    assert set(by_site) == {"apollo-11", "ranger-7"}  # surveyor-5 has no heritage; lost-probe no position
    expected = {"apollo-11": (APOLLO_11, 2000.0, "heritage_landing"), "ranger-7": (RANGER_7, 500.0, "heritage_impact")}
    for site_id, ((lat, lon), radius_m, rule) in expected.items():
        f = by_site[site_id]
        p = f["properties"]
        assert p == {"id": f"keepout-{site_id}", "siteId": site_id, "siteName": p["siteName"], "radiusM": radius_m,
                     "rule": rule, "sourceId": "MOON-SITE-06", "evidenceType": "rule"}
        ring = f["geometry"]["coordinates"][0]
        assert f["geometry"]["type"] == "Polygon" and len(ring) == 65 and ring[0] == ring[-1]
        for vlon, vlat in ring:
            assert -180 <= vlon < 180
            # Measured on the Moon sphere: within 1 % of the rule radius.
            assert bodies.distance_km(lat, lon, vlat, vlon, MOON) * 1000 == pytest.approx(radius_m, rel=0.01)


def test_cache_follows_file_changes(api, prepared):
    assert len(api.get("/api/moon/keepout").json()["features"]) == 2
    path = prepared / "sites" / "anthropogenic_objects.geojson"
    fc = json.loads(path.read_text())
    fc["features"].append(_site("apollo-12", "Apollo 12 LM", (-3.01239, -23.42157), "crewed_landing", "landing"))
    path.write_text(json.dumps(fc))
    assert len(api.get("/api/moon/keepout").json()["features"]) == 3


# -- cell context ------------------------------------------------------------------------------


def test_context_at_apollo_11(api, prepared):
    cell = h3.latlng_to_cell(*APOLLO_11, 9)
    lat, lon = h3.cell_to_latlng(cell)
    ctx = api.get(f"/api/moon/cells/{cell}/context").json()
    assert ctx["h3Id"] == cell and ctx["body"] == "moon"
    assert ctx["centre"] == {"latitude": lat, "longitude": lon}

    places = ctx["nearestPlaces"]
    assert [p["name"] for p in places] == ["Statio Tranquillitatis", "Moltke", "Mare Tranquillitatis"]
    for p in places:
        moon_km = bodies.distance_km(lat, lon, p["latitude"], p["longitude"], MOON)
        assert p["distanceKm"] == pytest.approx(moon_km, abs=1e-3)
        # The Moon distance, not Earth's: 1737.4 / 6371.007 of the Earth figure.
        earth_km = bodies.distance_km(lat, lon, p["latitude"], p["longitude"], EARTH)
        assert p["distanceKm"] == pytest.approx(earth_km * MOON.radius_km / EARTH.radius_km, rel=1e-4, abs=1e-3)
    statio, moltke, mare = places
    assert statio["diameterKm"] is None and statio["within"] is False  # unknown diameter: never "within"
    assert moltke["diameterKm"] == 6.5 and moltke["within"] is False and 40 < moltke["distanceKm"] < 50
    assert mare["within"] is True and mare["quad"] is None

    sites = ctx["nearbySites"]
    assert [s["id"] for s in sites] == ["apollo-11", "surveyor-5"]  # ranger-7 is > 150 km away
    assert sites[0]["distanceKm"] < 0.1
    assert sites[1]["distanceKm"] == pytest.approx(bodies.distance_km(lat, lon, *SURVEYOR_5, MOON), abs=1e-3)
    assert {"name", "mission", "kind", "date"} <= set(sites[0])

    assert [k["siteId"] for k in ctx["keepout"]] == ["apollo-11"]
    k = ctx["keepout"][0]
    assert k["rule"] == "heritage_landing" and k["radiusM"] == 2000.0 and k["distanceKm"] < 2.0

    assert ctx["mare"] == {"id": "mare-tranquillitatis", "name": "Mare Tranquillitatis"}
    assert ctx["quad"] == "LAC-60"


def test_context_keepout_edge(api, prepared):
    """A cell centre ~1.5 km from Apollo 11 is inside the 2 km ring; ~3 km away is outside."""
    def cell_at(km_north):
        dlat = km_north / MOON.radius_km * 57.29577951308232
        return h3.latlng_to_cell(APOLLO_11[0] + dlat, APOLLO_11[1], 12)

    inside = api.get(f"/api/moon/cells/{cell_at(1.5)}/context").json()["keepout"]
    outside = api.get(f"/api/moon/cells/{cell_at(3.0)}/context").json()["keepout"]
    assert [k["siteId"] for k in inside] == ["apollo-11"] and 1.4 < inside[0]["distanceKm"] < 1.6
    assert outside == []


def test_context_far_from_everything(api, prepared):
    cell = h3.latlng_to_cell(-60.0, 150.0, 6)
    ctx = api.get(f"/api/moon/cells/{cell}/context").json()
    assert ctx["nearbySites"] == [] and ctx["keepout"] == [] and ctx["mare"] is None
    assert len(ctx["nearestPlaces"]) == 3 and all(p["within"] is False for p in ctx["nearestPlaces"])
    assert ctx["quad"] in {"LAC-60", "LAC-79"}


@pytest.mark.parametrize("bad", ["not-a-cell", "fffffffffffffffff", "-1", "1" * 28])
def test_context_invalid_cell_404(api, prepared, bad):
    # h3 raises OverflowError (not ValueError) on the last three: they used to be a 500.
    assert api.get(f"/api/moon/cells/{bad}/context").status_code == 404


def test_context_survives_missing_layers(api, prepared):
    (prepared / "regions" / "mare.geojson").unlink()
    (prepared / "places" / "gazetteer.json").unlink()
    ctx = api.get(f"/api/moon/cells/{h3.latlng_to_cell(*APOLLO_11, 9)}/context").json()
    assert ctx["mare"] is None and ctx["quad"] is None and ctx["nearestPlaces"] == []
    assert [k["siteId"] for k in ctx["keepout"]] == ["apollo-11"]


# -- sources -----------------------------------------------------------------------------------


def test_sources(api, prepared):
    items = api.get("/api/moon/sources").json()
    by_id = {s["id"]: s for s in items}
    assert len(by_id) == len(items)  # no duplicates
    assert by_id["MOON-SITE-01"]["layers"] == ["moon_sites"]
    # From source.json (not the fallback), also credited for the WMS name labels.
    assert by_id["MOON-PLACE-01"]["layers"] == ["moon_places", "moon_overlays"]
    assert by_id["MOON-PLACE-01"]["name"] == "IAU Gazetteer (Moon)"
    assert by_id["MOON-SITE-06"]["layers"] == ["moon_keepout"]
    assert by_id["MOON-TOPO-02"]["layers"] == ["h3:elevation"]
    wms = by_id["MOON-MAP-01"]
    assert wms["provider"] == "LROC / IM-LDI (Arizona State University)"
    assert wms["licence"] == "U.S. public domain (NASA); credit requested"
    assert wms["attribution"] == "NASA/GSFC/Arizona State University"
    assert wms["evidenceType"] == "satellite_imagery" and wms["url"] == "https://wms.im-ldi.com/"
    assert wms["layers"] == ["moon_basemap", "moon_overlays"]
    keys = {"id", "name", "provider", "licence", "attribution", "evidenceType", "retrievedAt", "url", "layers",
            "limitations", "commercialUse"}
    assert all(keys <= set(s) for s in items)


def test_sources_without_prepared_data(api, unprepared):
    r = api.get("/api/moon/sources")
    assert r.status_code == 200
    assert {s["id"] for s in r.json()} == {"MOON-MAP-01", "MOON-PLACE-01"}
