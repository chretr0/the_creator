"""Pure calculation and assessment tests (no database). Fixtures from CLAUDE.Building-System.md §13;
the numbers are test inputs, not template defaults."""

import math
import uuid

import pytest
from pydantic import ValidationError

from app import site_capacity
from app.building_assess import PlacedBuilding, ScenarioContext, assess_point, budget_result, building_results, pool_state
from app.building_calc import (
    CalcInputError,
    LocationContext,
    calculate,
    fmt_num,
    param_number,
    q,
    validate_parameters,
)
from app.building_models import (
    BuildingStats,
    Criterion,
    DefinitionSnapshot,
    ResourceBudget,
    ScenarioAssumptions,
    SiteAssumptions,
    StressControls,
)

LAT, LON = 33.4, -112.0  # Phoenix area (inside the Arizona prepared region)


@pytest.fixture(autouse=True)
def _no_site_checks(monkeypatch):
    """These tests cover declared criteria and budgets; automatic site checks are tested in test_site_capacity.py."""
    monkeypatch.setattr(site_capacity, "site_checks", lambda *a, **k: ([], [], site_capacity.Materials([], [])))


def stats(**kw) -> BuildingStats:
    return BuildingStats.model_validate(kw)


FIXTURE = {"operatingHoursPerDay": 8, "power": {"averageDemandKw": 100}, "water": {"inputM3PerHour": 2}}


def test_spec_fixture_energy_and_water():
    r = calculate("custom", stats(**FIXTURE), {}, 10)
    assert r.operating_hours.value == 80
    assert r.electricity_demand.value == 8000 and r.electricity_demand.unit == "kWh"
    assert r.water_demand.value == 160
    assert r.period_days == 10


def _water_check(stress=None):
    crit = [Criterion(id="w", kind="water_budget")]
    ctx = ScenarioContext(assumptions=ScenarioAssumptions(period_days=10))
    site = SiteAssumptions(water_allocation_m3_per_day=20)
    _, _, a, *_ = assess_point("custom", stats(**FIXTURE), {}, crit, site, LAT, LON, ctx, set(), stress)
    return a


def test_water_allocation_pass_stress_and_reset():
    a = _water_check()
    assert a.state == "meets_criteria"
    c = a.checks[0]
    assert (c.status, c.actual, c.required_value, c.unit) == ("pass", 160, 200, "m³")

    stressed = _water_check(StressControls(water_availability=0.5))
    c = stressed.checks[0]
    assert stressed.state == "fails_criteria"
    assert (c.status, c.actual, c.required_value) == ("fail", 160, 100)
    assert "unmet 60" in c.explanation

    assert _water_check(StressControls()).checks[0].status == "pass"  # reset = neutral


def test_pooled_budget_unmet_and_counted_once():
    a, b = uuid.uuid4(), uuid.uuid4()
    snap = DefinitionSnapshot(stats=stats(**FIXTURE))
    ctx = ScenarioContext(
        assumptions=ScenarioAssumptions(
            period_days=10,
            budgets=[ResourceBudget(id="pool", label="Town water", kind="water_m3_per_day", amount=20)],
        ),
        buildings=[PlacedBuilding(a, "A", "custom", LAT, LON, "8629b0c07ffffff", snap, {}, SiteAssumptions())],
    )
    for stress, supply, unmet in ((StressControls(), 200, 0), (StressControls(water_availability=0.5), 100, 60)):
        results = building_results(ctx, stress, {a: LocationContext("8629b0c07ffffff", None)})
        br = budget_result(pool_state(ctx.assumptions.budgets[0], ctx, results, stress))
        assert (br.declared_supply.value, br.demand.value, br.unmet.value) == (supply, 160, unmet)
    # A second identical building in scope: the pool is shared, not duplicated.
    ctx.buildings.append(PlacedBuilding(b, "B", "custom", LAT, LON, "8629b0c07ffffff", snap, {}, SiteAssumptions()))
    results = building_results(ctx, StressControls(), {i: LocationContext("8629b0c07ffffff", None) for i in (a, b)})
    pool = pool_state(ctx.assumptions.budgets[0], ctx, results, StressControls())
    br = budget_result(pool)
    assert (br.declared_supply.value, br.demand.value, br.unmet.value) == (200, 320, 120)
    # Reassessing A excludes A itself: remaining = 200 - B's 160.
    assert pool.remaining({a}).value == 40


def test_construction_counted_once_and_independent_of_period():
    s = stats(
        operatingHoursPerDay=10,
        materials=[
            {"id": "s", "name": "Steel", "phase": "construction", "quantityKg": 5000},
            {"id": "c", "name": "Chlorine", "phase": "operation", "quantityKg": 365.25, "period": "year"},
        ],
        costs={"currency": "USD", "constructionTotal": 1_000_000},
    )
    r10, r20 = calculate("custom", s, {}, 10), calculate("custom", s, {}, 20)
    for r in (r10, r20):
        assert r.materials[0].quantity.value == 5000
        assert r.costs.construction.value == 1_000_000
    assert r10.materials[1].quantity.value == pytest.approx(10)
    assert r20.materials[1].quantity.value == pytest.approx(20)
    # Demand stress does not touch construction quantities.
    rs = calculate("custom", s, {}, 10, StressControls(operating_demand=2))
    assert rs.materials[0].quantity.value == 5000 and rs.materials[1].quantity.value == pytest.approx(20)


def test_unknown_vs_zero():
    blank = calculate("custom", stats(operatingHoursPerDay=8), {}, 10)
    assert blank.electricity_demand.value is None and blank.electricity_demand.missing
    zero = calculate("custom", stats(operatingHoursPerDay=8, power={"averageDemandKw": 0}), {}, 10)
    assert zero.electricity_demand.value == 0 and not zero.electricity_demand.missing
    no_hours = calculate("custom", stats(power={"averageDemandKw": 100}), {}, 10)
    assert no_hours.electricity_demand.value is None
    assert "operating hours per day" in no_hours.electricity_demand.missing


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1])
def test_nan_inf_negative_rejected(bad):
    with pytest.raises(ValidationError):
        stats(power={"averageDemandKw": bad})
    with pytest.raises(ValidationError):
        StressControls(water_availability=bad if bad != -1 else 1.5)


def test_hours_capped_and_capacity_factor_bounded():
    with pytest.raises(ValidationError):
        stats(operatingHoursPerDay=25)
    with pytest.raises(ValidationError):
        stats(power={"capacityFactor": 1.2})


def test_emissions_per_pollutant_and_fixed_under_demand_stress():
    s = stats(operatingHoursPerDay=8, emissions=[
        {"id": "1", "pollutant": "NOx", "rateKgPerHour": 0.5},
        {"id": "2", "pollutant": "SO2", "rateKgPerHour": 0.1},
    ], light={"upwardLumens": 1000})
    r = calculate("custom", s, {}, 10, StressControls(operating_demand=3))
    assert [(e.pollutant, e.quantity.value) for e in r.emissions] == [("NOx", 40), ("SO2", pytest.approx(8))]
    assert r.light.value == 1000


def test_total_operating_cost_not_double_counted():
    base = {"operatingHoursPerDay": 8, "power": {"averageDemandKw": 100}, "water": {"inputM3PerHour": 0}}
    total = calculate("custom", stats(**base, costs={
        "currency": "EUR", "operating": {"amount": 365.25, "period": "year", "kind": "total"},
        "electricityPricePerKwh": 0.2}), {}, 10)
    assert total.costs.operating_known_total.value == pytest.approx(10)
    assert total.costs.electricity.value is None
    fixed = calculate("custom", stats(**base, costs={
        "currency": "EUR", "operating": {"amount": 365.25, "period": "year", "kind": "fixed"},
        "electricityPricePerKwh": 0.2}), {}, 10)
    assert fixed.costs.electricity.value == pytest.approx(1600)
    assert fixed.costs.operating_known_total.value == pytest.approx(1610)
    assert not fixed.costs.operating_known_total.missing
    # Price stress multiplies unit prices only, never construction or the fixed amount.
    stressed = calculate("custom", stats(**base, costs={
        "currency": "EUR", "constructionTotal": 50, "operating": {"amount": 365.25, "period": "year"},
        "electricityPricePerKwh": 0.2}), {}, 10, StressControls(operating_prices=2))
    assert stressed.costs.electricity.value == pytest.approx(3200)
    assert stressed.costs.operating_fixed.value == pytest.approx(10)
    assert stressed.costs.construction.value == 50


def test_missing_price_gives_partial_cost_not_zero():
    r = calculate("custom", stats(operatingHoursPerDay=8, power={"averageDemandKw": 100}, costs={
        "currency": "GBP", "operating": {"amount": 100, "period": "day"}}), {}, 10)
    assert r.costs.operating_known_total.value == 1000
    assert any("electricity price" in m for m in r.costs.operating_known_total.missing)
    none = calculate("custom", stats(), {}, 10)
    assert none.costs.operating_known_total.value is None


def test_data_centre_derived_formula():
    params = {"itPowerKw": 1000, "loadFraction": 0.5, "pue": 1.2, "wueLPerKwh": 2, "wueBasis": "it_energy"}
    s = stats(operatingHoursPerDay=24, demandBasis="derived", power={"averageDemandKw": 999999})
    r = calculate("data_centre", s, params, 10)
    it_kwh = 1000 * 0.5 * 240
    assert r.electricity_demand.value == pytest.approx(it_kwh * 1.2)  # never adds the direct 999999 kW
    assert r.water_demand.value == pytest.approx(2 * it_kwh / 1000)
    assert r.peak_demand.value == pytest.approx(1200)
    r2 = calculate("data_centre", s, {**params, "wueBasis": "facility_energy"}, 10)
    assert r2.water_demand.value == pytest.approx(2 * it_kwh * 1.2 / 1000)
    missing = calculate("data_centre", s, {"itPowerKw": 1000}, 10)
    assert missing.electricity_demand.value is None
    assert {"loadFraction", "pue"} <= set(missing.electricity_demand.missing)


def test_rated_output_without_capacity_factor_is_unknown():
    s = stats(operatingHoursPerDay=24, power={"ratedOutputKw": 5000, "averageDemandKw": 100})
    r = calculate("power_station", s, {}, 10)
    assert r.electricity_output.value is None
    assert any("capacity factor" in m for m in r.electricity_output.missing)
    s2 = stats(operatingHoursPerDay=24, power={"ratedOutputKw": 5000, "capacityFactor": 0.5, "averageDemandKw": 100})
    r2 = calculate("power_station", s2, {}, 10)
    assert r2.electricity_output.value == 5000 * 0.5 * 240
    assert r2.electricity_net.value == 5000 * 0.5 * 240 - 100 * 240


def test_water_plant_net_output():
    s = stats(operatingHoursPerDay=10, water={"inputM3PerHour": 12, "outputM3PerHour": 10}, power={"averageDemandKw": 50})
    r = calculate("water_plant", s, {}, 10)
    assert (r.water_output.value, r.water_demand.value, r.water_net.value) == (1000, 1200, -200)
    assert r.electricity_demand.value == 5000


def test_solar_kwp_model_needs_location():
    params = {"capacityKwp": 1000, "performanceRatio": 0.8}
    assert calculate("solar", stats(), params, 10).electricity_output.value is None
    r = calculate("solar", stats(), params, 10, location=LocationContext("x", 6.0, "test"))
    assert r.electricity_output.value == pytest.approx(1000 * 6.0 * 0.8 * 10)
    assert "kWp is not treated as constant output" in r.electricity_output.basis


def test_empty_criteria_is_insufficient():
    _, _, a, *_ = assess_point("custom", stats(**FIXTURE), {}, [], SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    assert a.state == "insufficient_data" and a.checks == []


def test_fail_and_unknown_both_visible():
    crit = [Criterion(id="c", kind="construction_budget", amount=100),
            Criterion(id="s", kind="staffing")]
    s = stats(costs={"currency": "USD", "constructionTotal": 500})
    _, _, a, *_ = assess_point("custom", s, {}, crit, SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    assert a.state == "fails_criteria"
    assert [c.status for c in a.checks] == ["fail", "unknown"]
    assert "1 more unknown" in a.summary


def test_optional_checks_do_not_decide_state():
    crit = [Criterion(id="c", kind="construction_budget", amount=100, required=False)]
    s = stats(costs={"currency": "USD", "constructionTotal": 500})
    _, _, a, *_ = assess_point("custom", s, {}, crit, SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    assert a.state == "insufficient_data" and a.checks[0].status == "fail"


def test_results_are_json_safe():
    huge = stats(operatingHoursPerDay=24, power={"averageDemandKw": 1e308})
    r = calculate("custom", huge, {}, 3000)
    assert r.electricity_demand.value is None  # overflow is reported, never inf
    r.model_dump_json()


def test_data_centre_it_energy_water_does_not_need_pue():
    s = stats(operatingHoursPerDay=24, demandBasis="derived")
    params = {"itPowerKw": 1000, "loadFraction": 0.5, "wueLPerKwh": 1.8, "wueBasis": "it_energy"}
    r = calculate("data_centre", s, params, 10)
    assert r.electricity_demand.value is None and r.electricity_demand.missing == ["pue"]
    assert r.water_demand.value == pytest.approx(216) and not r.water_demand.missing
    facility = calculate("data_centre", s, {**params, "wueBasis": "facility_energy"}, 10)
    assert facility.water_demand.value is None and facility.water_demand.missing == ["pue"]


def test_huge_integers_are_input_errors_not_crashes():
    assert param_number("data_centre", {"itPowerKw": 10**400}, "itPowerKw") == (None, "itPowerKw is out of range")
    with pytest.raises(CalcInputError, match="out of range"):
        validate_parameters("data_centre", {"itPowerKw": 10**400})
    big = q(10**400, "people")  # e.g. a worker count, should one ever pass model validation
    assert big.value is None and big.missing == ["result out of numeric range"]


def test_operational_materials_priced_per_item_even_with_duplicate_ids():
    s = stats(materials=[
        {"id": "m", "name": "Lime", "phase": "operation", "quantityKg": 10, "period": "day", "unitPricePerKg": 100},
        {"id": "m", "name": "Sand", "phase": "operation", "quantityKg": 10, "period": "day", "unitPricePerKg": 1},
    ], costs={"currency": "USD"})
    assert calculate("custom", s, {}, 1).costs.materials.value == pytest.approx(1010)


def test_hourly_material_rate_uses_operating_hours():
    mat = {"id": "m", "name": "Lime", "phase": "operation", "quantityKg": 10, "period": "hour"}
    s = stats(operatingHoursPerDay=8, materials=[mat], emissions=[{"id": "e", "pollutant": "NOx", "rateKgPerHour": 10}])
    r = calculate("custom", s, {}, 1)
    assert r.materials[0].quantity.value == pytest.approx(80) == r.emissions[0].quantity.value
    assert "operating hour" in r.materials[0].quantity.basis
    no_hours = calculate("custom", stats(materials=[mat]), {}, 1).materials[0].quantity
    assert no_hours.value is None and no_hours.missing == ["operating hours per day"]
    # A fixed operating cost per hour is a calendar-time cost, and its basis says so.
    hourly_cost = stats(operatingHoursPerDay=8, costs={"operating": {"amount": 1, "period": "hour"}})
    cost = calculate("custom", hourly_cost, {}, 1)
    assert cost.costs.operating_fixed.value == pytest.approx(24)
    assert "calendar hour" in cost.costs.operating_fixed.basis


@pytest.mark.parametrize("value, text", [
    (1_000_000, "1,000,000"), (0.25, "0.25"), (365.25, "365.25"), (1 / 24, "0.04167"), (30.4375, "30.4375"),
    (1234.56789, "1,234.5679"), (-2500.5, "-2,500.5"), (0, "0"), (-0.0, "0"), (None, "unknown"), (1e20, "1e+20"),
])
def test_fmt_num_is_readable(value, text):
    assert fmt_num(value) == text


def test_basis_strings_avoid_scientific_notation():
    s = stats(materials=[{"id": "m", "name": "Salt", "phase": "operation", "quantityKg": 1_000_000, "period": "year"}])
    basis = calculate("custom", s, {}, 30).materials[0].quantity.basis
    assert "1,000,000 kg per year" in basis and "e+" not in basis
