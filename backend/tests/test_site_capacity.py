"""Automatic site checks: what a hexagon and its neighbours provide vs what the building's specs need."""

import uuid

import h3
import numpy as np
import pytest

from app import site_capacity as sc
from app.building_assess import PlacedBuilding, ScenarioContext, assess_point
from app.building_calc import calculate
from app.building_models import BuildingStats, DefinitionSnapshot, SiteAssumptions, StressControls

LAT, LON = 33.4, -112.0
CELL = int(h3.latlng_to_cell(LAT, LON, 6), 16)


def stats(**kw) -> BuildingStats:
    return BuildingStats.model_validate(kw)


def fake_site(**kw) -> sc.SiteData:
    one = lambda v: np.array([v], dtype=np.float64)  # noqa: E731
    base = dict(
        cells=np.array([CELL], dtype=np.uint64), lats=one(LAT), lons=one(LON),
        cell_m2=one(36e6), open_frac=one(0.5), slope=one(2.0), slope_factor=one(1.0),
        land_cell_m2=one(18e6), land_ring_m2=one(100e6),
        river_m3_day=one(100_000.0), runoff_m3_day=one(5_000.0), stress_cat=one(0.0), headroom=one(0.3),
        water_m3_day=one(30_000.0), coastal=np.array([False]),
        grid_kv=one(132.0), grid_sub_kv=one(np.nan), grid_has_data=np.array([True]), settled=np.array([True]), grid_kw=one(100_000.0),
        population=one(200_000.0), workforce=one(2_000.0),
    )
    base.update({k: (v if isinstance(v, np.ndarray) else one(v)) for k, v in kw.items()})
    return sc.SiteData(**base)


def run(btype: str, s: BuildingStats, site: sc.SiteData, neighbours=(), stress=None):
    stress = stress or StressControls()
    result = calculate(btype, s, {}, 30, stress, None)
    demand = sc.demand_of(btype, s, result)
    checks, skipped, _ = sc.site_checks(btype, demand, site, sc.shared(site.cells, list(neighbours)), stress)
    return {c.kind: c.build(0) for c in checks}, skipped


CONSUMER = stats(footprintM2=50_000, operatingHoursPerDay=24, power={"peakDemandKw": 20_000},
                 water={"inputM3PerHour": 100}, workers={"staffingRequired": 150})


def test_everything_fits():
    checks, skipped = run("custom", CONSUMER, fake_site())
    assert {k: c.status for k, c in checks.items()} == {
        "site_land": "pass", "site_water": "pass", "site_power": "pass", "site_workforce": "pass"}
    assert skipped == []


def test_each_check_explains_its_own_need():
    """Regression: explanation builders must not pick up another resource's need."""
    checks, _ = run("custom", CONSUMER, fake_site())
    assert checks["site_water"].actual == 2_400 and "2,400 m³/day" in checks["site_water"].explanation
    assert checks["site_power"].actual == 20_000 and "20 MW" in checks["site_power"].explanation
    assert checks["site_workforce"].actual == 150
    assert checks["site_land"].actual == 50_000


def test_shortfalls_fail_with_amount_short():
    site = fake_site(water_m3_day=1_000.0, grid_kw=5_000.0, grid_kv=np.nan, workforce=50.0, land_cell_m2=10_000.0,
                     land_ring_m2=20_000.0)
    checks, _ = run("custom", CONSUMER, site)
    assert all(c.status == "fail" for c in checks.values())
    assert "short by 1,400 m³/day" in checks["site_water"].explanation
    assert "short by 15 MW" in checks["site_power"].explanation


def test_large_footprint_can_spill_into_neighbours():
    checks, _ = run("custom", CONSUMER, fake_site(land_cell_m2=10_000.0, land_ring_m2=80_000.0))
    assert checks["site_land"].status == "pass" and "neighbouring cells" in checks["site_land"].explanation


def test_outside_coverage_is_unknown_not_fail():
    nan = np.nan
    site = fake_site(open_frac=nan, land_cell_m2=nan, land_ring_m2=nan, water_m3_day=nan, headroom=nan,
                     grid_kw=nan, grid_has_data=np.array([False]), workforce=nan, population=nan)
    checks, _ = run("custom", CONSUMER, site)
    assert {c.status for c in checks.values()} == {"unknown"}


def test_undeclared_needs_are_not_checked_but_footprint_always_is():
    checks, skipped = run("custom", stats(), fake_site())
    assert list(checks) == ["site_land"] and checks["site_land"].status == "unknown"
    assert any("water" in s for s in skipped) and any("workforce" in s for s in skipped)


def test_producer_checks_export_not_draw():
    plant = stats(footprintM2=1_000_000, operatingHoursPerDay=24, power={"ratedOutputKw": 500_000, "averageDemandKw": 0})
    checks, _ = run("power_station", plant, fake_site())
    assert "site_power" not in checks
    surplus = checks["site_grid_export"]
    assert surplus.status == "fail"  # 132 kV ≈ 100 MW < 500 MW
    assert not surplus.required and "surplus" in surplus.explanation  # surplus output never fails the plant
    checks, _ = run("power_station", plant, fake_site(grid_kv=400.0, grid_kw=1_000_000.0))
    assert checks["site_grid_export"].status == "pass"


def test_coastal_sites_supply_seawater_to_plants_only():
    thirsty = stats(footprintM2=1_000, operatingHoursPerDay=24, water={"inputM3PerHour": 10_000})
    site = fake_site(coastal=np.array([True]), water_m3_day=100.0)
    assert run("water_plant", thirsty, site)[0]["site_water"].status == "pass"
    assert run("custom", thirsty, site)[0]["site_water"].status == "fail"


def test_water_availability_stress_scales_supply():
    checks, _ = run("custom", CONSUMER, fake_site(water_m3_day=3_000.0),
                    stress=StressControls(water_availability=0.5))
    assert checks["site_water"].status == "fail" and "water availability 0.5" in checks["site_water"].explanation


def test_neighbours_share_supply_and_plants_add_to_it():
    dc = stats(footprintM2=10_000, operatingHoursPerDay=24, power={"peakDemandKw": 90_000})
    hog = sc.Neighbour(uuid.uuid4(), "Other DC", CELL, sc.Demand(None, None, 50_000, None, None, None))
    checks, _ = run("custom", dc, fake_site(), [hog])
    assert checks["site_power"].status == "fail" and "Other DC" in checks["site_power"].explanation
    plant = sc.Neighbour(uuid.uuid4(), "Gas plant", CELL, sc.Demand(None, None, 0, 60_000, None, None))
    checks, _ = run("custom", dc, fake_site(), [hog, plant])
    assert checks["site_power"].status == "pass"


def test_grid_capacity_classes():
    kv = np.array([np.nan, 0.4, 11, 33, 66, 132, 275, 400])
    assert list(sc.grid_capacity_kw(kv)[1:]) == [1_000, 5_000, 15_000, 40_000, 100_000, 500_000, 1_500_000]
    assert np.isnan(sc.grid_capacity_kw(kv)[0])
    # An extra-high-voltage substation is a multi-GW hub
    assert sc.grid_capacity_kw(np.array([500.0]), sc.SUBSTATION_CLASSES)[0] == 5_000_000


# --- real prepared data (skipped where it isn't prepared) -------------------------------------


def _have_arizona() -> bool:
    return sc._layer_src("land_cover", "crop") is not None


@pytest.mark.skipif(not _have_arizona(), reason="prepared Arizona land cover not available")
def test_real_location_reports_site_capacity_and_shared_use():
    s = stats(footprintM2=50_000, operatingHoursPerDay=24, workers={"staffingRequired": 100})
    _, _, a, _, cap = assess_point("custom", s, {}, [], SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    assert [c.kind for c in a.checks] == ["site_land", "site_workforce"]
    assert {r.key for r in cap.resources} == {"land", "water", "power", "workforce", "air", "light"}
    assert len(cap.neighbour_cells) == 6
    workers_alone = next(r for r in cap.resources if r.key == "workforce").available

    other = PlacedBuilding(uuid.uuid4(), "Factory", "custom", LAT, LON, h3.latlng_to_cell(LAT, LON, 6),
                           DefinitionSnapshot(stats=s), {}, SiteAssumptions())
    ctx = ScenarioContext(buildings=[other])
    _, _, _, _, cap2 = assess_point("custom", s, {}, [], SiteAssumptions(), LAT, LON, ctx, set())
    assert next(r for r in cap2.resources if r.key == "workforce").available == workers_alone - 100
    # Re-assessing the factory itself never counts it twice
    _, _, _, _, cap3 = assess_point("custom", s, {}, [], SiteAssumptions(), LAT, LON, ctx, {other.id})
    assert next(r for r in cap3.resources if r.key == "workforce").available == workers_alone


# --- power stations alongside, air quality, dark sky ------------------------------------------


def test_power_station_alongside_boosts_grid_both_ways():
    """A consumer next to a placed power station gets its output; the station needs no export room
    for what nearby consumers use."""
    dc = stats(footprintM2=10_000, operatingHoursPerDay=24, power={"peakDemandKw": 150_000})
    weak = fake_site(grid_kw=100_000.0)
    assert run("custom", dc, weak)[0]["site_power"].status == "fail"
    plant = sc.Neighbour(uuid.uuid4(), "Gas plant", CELL, sc.Demand(None, None, 0, 80_000, None, None))
    checks, _ = run("custom", dc, weak, [plant])
    assert checks["site_power"].status == "pass" and "80 MW from power stations placed nearby" in checks["site_power"].explanation

    station = stats(footprintM2=100_000, operatingHoursPerDay=24, power={"ratedOutputKw": 150_000, "averageDemandKw": 0})
    assert run("power_station", station, weak)[0]["site_grid_export"].status == "fail"
    consumer = sc.Neighbour(uuid.uuid4(), "Data centre", CELL, sc.Demand(None, None, 60_000, None, None, None))
    checks, _ = run("power_station", station, weak, [consumer])
    assert checks["site_grid_export"].status == "pass"
    assert "use 60 MW of it locally" in checks["site_grid_export"].explanation


def test_air_quality_only_for_local_pollutants():
    clean = fake_site(pm25=6.0, pm10=12.0, no2col=40.0, so2col=5.0)
    dirty = fake_site(pm25=12.4)
    ghg = stats(footprintM2=1_000, emissions=[{"id": "c", "pollutant": "CO2", "rateKgPerHour": 1000}])
    assert "site_air" not in run("custom", ghg, dirty)[0]
    nox = stats(footprintM2=1_000, emissions=[{"id": "n", "pollutant": "NOx", "rateKgPerHour": 25}])
    assert run("custom", nox, clean)[0]["site_air"].status == "pass"  # Phoenix ≈ US → 9 µg/m³
    c = run("custom", nox, dirty)[0]["site_air"]
    assert c.status == "fail" and c.required_value == 9.0 and "offsets" in c.explanation
    assert run("custom", nox, fake_site())[0]["site_air"].status == "unknown"  # no CAMS data


@pytest.mark.parametrize("name,expected", [("NOx", True), ("PM2.5", True), ("SO₂", True), ("CO", True),
                                           ("CO2", False), ("CO2e (Scope 1)", False), ("CH4", False), ("VOCs", True)])
def test_air_pollutant_names(name, expected):
    assert sc.is_air_pollutant(name) is expected


def test_light_zones_and_dark_sky_check():
    z = sc.light_zone(np.array([2.0, 50.0, 800.0, 5_000.0, np.nan]), np.array([0.0, 0.0, 0.0, 0.0, np.nan]))
    assert list(z[:4]) == [1, 2, 3, 4] and np.isnan(z[4])
    lit = stats(footprintM2=1_000, light={"upwardLumens": 50_000})
    assert run("custom", lit, fake_site(zone=1.0, density=2.0, built_share=0.0))[0]["site_light"].status == "fail"
    c = run("custom", lit, fake_site(zone=3.0, density=800.0, built_share=0.08))[0]["site_light"]
    assert c.status == "pass" and "E3 suburban" in c.explanation
    assert "site_light" not in run("custom", stats(footprintM2=1_000, light={"upwardLumens": 0}), fake_site(zone=1.0))[0]


# --- relaxed limits, water intake sources, supporting buildings -------------------------------


def test_air_margin_lets_borderline_sites_pass_with_a_warning():
    nox = stats(footprintM2=1_000, emissions=[{"id": "n", "pollutant": "NOx", "rateKgPerHour": 25}])
    c = run("custom", nox, fake_site(pm25=10.9))[0]["site_air"]  # Mesquite's site vs the US 9 µg/m³
    assert c.status == "pass" and "screening margin" in c.explanation
    assert run("custom", nox, fake_site(pm25=11.5))[0]["site_air"].status == "fail"  # > 9 × 1.25


def test_seawater_intake_needs_a_coast():
    desal = stats(footprintM2=1_000, operatingHoursPerDay=24, water={"inputM3PerHour": 100, "source": "seawater"})
    assert run("custom", desal, fake_site(coastal=np.array([True])))[0]["site_water"].status == "pass"
    c = run("custom", desal, fake_site())[0]["site_water"]
    assert c.status == "fail" and "no coast" in c.explanation


def test_wastewater_intake_uses_effluent_not_rivers():
    pv = stats(footprintM2=1_000, operatingHoursPerDay=24, water={"inputM3PerHour": 10_000, "source": "wastewater"})
    site = fake_site(water_m3_day=0.0)
    site._effluent = np.array([300_000.0])
    c = run("custom", pv, site)[0]["site_water"]
    assert c.status == "pass" and c.label == "Treated wastewater available"
    site._effluent = np.array([100_000.0])
    assert run("custom", pv, site)[0]["site_water"].status == "fail"


def test_non_fresh_water_plant_adds_its_whole_output_and_draws_no_fresh_water():
    plant = stats(operatingHoursPerDay=24, water={"inputM3PerHour": 200, "outputM3PerHour": 100, "source": "seawater"})
    d = sc.demand_of("water_plant", plant, calculate("water_plant", plant, {}, 30, StressControls(), None))
    assert d.water_out_m3_day == 2_400 and d.fresh_m3_day == 0
    sh = sc.shared(np.array([CELL], dtype=np.uint64), [sc.Neighbour(uuid.uuid4(), "Desal", CELL, d)])
    assert sh.water_added[0] == 2_400 and sh.water_used[0] == 0


def test_plant_may_hold_back_reserve_instead_of_exporting():
    station = stats(footprintM2=1_000, operatingHoursPerDay=24, power={"ratedOutputKw": 110_000, "averageDemandKw": 0})
    weak = fake_site(grid_kw=0.0, grid_kv=np.nan, settled=np.array([False]))
    user = sc.Neighbour(uuid.uuid4(), "DC", CELL, sc.Demand(None, None, 100_000, None, None, None))
    c = run("power_station", station, weak, [user])[0]["site_grid_export"]
    assert c.status == "pass" and "operating reserve" in c.explanation
    small = sc.Neighbour(uuid.uuid4(), "DC", CELL, sc.Demand(None, None, 50_000, None, None, None))
    assert run("power_station", station, weak, [small])[0]["site_grid_export"].status == "fail"
