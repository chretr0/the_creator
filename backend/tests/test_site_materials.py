"""Raw materials read from the hexagons: advisory only, because materials can be shipped."""

import h3
import numpy as np
import pytest

from app import site_materials as sm
from app.building_assess import ScenarioContext, assess_point
from app.building_models import BuildingStats, SiteAssumptions


@pytest.mark.parametrize("name,keys", [
    ("Concrete", {"aggregate", "limestone"}), ("Structural steel", {"iron"}), ("Rebar", {"iron"}),
    ("Float glass", {"silica"}), ("Copper cable", {"copper"}), ("Aluminium frames", {"aluminium"}),
    ("Plasterboard", {"gypsum"}), ("Bricks", {"clay"}), ("CLT timber", {"timber"}), ("Sand", {"aggregate"}),
])
def test_names_map_to_raw_material_classes(name, keys):
    assert {c.key for c in sm.classes_for(name)} == keys


def test_unmapped_material():
    assert sm.classes_for("Refrigerant R-134a") == []


def test_nearest_within_reach():
    d, w = sm._nearest(np.array([0.0, 10.0]), np.array([0.0, 0.0]), np.array([0.0]), np.array([0.4]), 50.0)
    assert 44 < d[0] < 45 and w[0] == 0 and np.isinf(d[1]) and w[1] == -1


def _have_mrds() -> bool:
    return sm._mrds_index() is not None


@pytest.mark.skipif(not _have_mrds(), reason="prepared MRDS features not available")
def test_real_materials_are_advisory_and_never_block():
    # Phoenix: plenty of sand-and-gravel and copper producers nearby.
    lat, lon = 33.45, -112.07
    s = BuildingStats.model_validate({
        "footprintM2": 1_000,
        "materials": [{"id": "a", "name": "Sand", "phase": "construction", "quantityKg": 1e6},
                      {"id": "b", "name": "Copper", "phase": "construction", "quantityKg": 1e4},
                      {"id": "c", "name": "Widgets", "phase": "construction", "quantityKg": 1}]})
    _, _, a, _, cap = assess_point("custom", s, {}, [], SiteAssumptions(), lat, lon, ScenarioContext(), set())
    mats = {c.label.split(":")[0]: c for c in a.checks if c.kind == "site_material"}
    assert set(mats) == {"Sand", "Copper"} and all(not c.required for c in mats.values())
    assert mats["Sand"].status == "pass" and "producing site" in mats["Sand"].explanation
    assert mats["Copper"].status == "pass"
    assert any("Widgets" in x for x in [a.summary])
    r = next(r for r in cap.resources if r.key == "materials")
    assert r.advisory and r.available == 2 and r.needed == 2
    # Advisory checks never change the overall state
    without = BuildingStats.model_validate({"footprintM2": 1_000})
    _, _, b, _, _ = assess_point("custom", without, {}, [], SiteAssumptions(), lat, lon, ScenarioContext(), set())
    assert a.state == b.state


@pytest.mark.skipif(not _have_mrds(), reason="prepared MRDS features not available")
def test_outside_us_missing_source_is_uncertain_not_shipped():
    cell = int(h3.latlng_to_cell(51.5, -0.12, 6), 16)  # London: MRDS is incomplete outside the US
    av = sm.availability(sm.BY_KEY["aggregate"], np.array([cell], dtype=np.uint64), np.array([51.5]), np.array([-0.12]))
    assert sm.class_status(av)[0] in (sm.PASS, sm.UNKNOWN)
