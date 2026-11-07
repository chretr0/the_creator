"""Supporting buildings suggested for shortfalls another building can cover."""

from app import site_support
from app.building_models import CheckResult
from app.building_presets import load_presets


def ck(kind, label, need, avail, status="fail"):
    return CheckResult(criterion_id=kind, kind=kind, label=label, required=True, status=status,
                       actual=need, required_value=avail, unit="")


def test_power_and_water_shortfalls_suggest_plants_sized_together():
    out = site_support.suggestions([ck("site_power", "Grid power available", 60_000, 0),
                                    ck("site_water", "Fresh water available", 9_600, 590)], coastal=False)
    power, water = out
    assert power.resource == "power" and power.building_type == "power_station" and power.rings == 1
    assert water.resource == "water" and water.generic_stats.water.source == "wastewater"
    plant_kw = water.generic_stats.power.average_demand_kw
    assert power.shortfall == 60_000 + plant_kw  # the station also feeds the suggested water plant
    assert power.generic_stats.power.rated_output_kw >= power.shortfall
    assert all(p.capacity >= power.shortfall for p in power.presets)  # presets that cover it alone


def test_coastal_water_suggests_desalination_and_seawater_presets():
    (water,) = site_support.suggestions([ck("site_water", "Fresh water available", 1_000_000, 0)], coastal=True)
    assert water.generic_stats.water.source == "seawater"
    assert water.presets and water.presets[0].count > 1  # Carlsbad alone is too small: how many it takes


def test_inland_water_never_suggests_a_seawater_preset():
    (water,) = site_support.suggestions([ck("site_water", "Fresh water available", 1_000, 0)], coastal=False)
    assert all(p.id != "carlsbad-desalination-plant" for p in water.presets)


def test_surplus_output_suggests_a_data_centre_and_nothing_for_land_or_staff():
    out = site_support.suggestions([ck("site_grid_export", "Grid connection for output", 200_000, 50_000),
                                    ck("site_land", "Open land", 10, 1), ck("site_workforce", "Local workforce", 10, 1),
                                    ck("site_power", "Grid power available", 10, 100, status="pass")], coastal=False)
    assert [s.resource for s in out] == ["grid_export"]
    (surplus,) = out
    assert surplus.building_type == "data_centre" and "surplus" in surplus.title
    presets = {p.id: p for p in load_presets()}
    assert surplus.presets and all(presets[p.id].type == "data_centre" for p in surplus.presets)
    # The generic data centre never uses more than the surplus.
    assert surplus.generic_stats.power.average_demand_kw <= surplus.shortfall
