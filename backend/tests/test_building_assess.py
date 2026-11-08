"""Pure assessment and scenario-evaluation tests (no database). Numbers are test inputs, not
template defaults."""

import uuid

import numpy as np
import pytest

from app import site_capacity
from app import features, h3store, layers
from app.building_assess import (
    PlacedBuilding,
    ScenarioContext,
    _layer_check,
    _round_sig,
    _totals,
    assess_point,
    building_results,
    evaluate,
)
from app.building_calc import LocationContext
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
FIXTURE = {"operatingHoursPerDay": 8, "power": {"averageDemandKw": 100}, "water": {"inputM3PerHour": 2}}


def stats(**kw) -> BuildingStats:
    return BuildingStats.model_validate(kw)


def place(name: str, s: BuildingStats, criteria=(), site=None, lat=LAT, lon=LON) -> PlacedBuilding:
    snap = DefinitionSnapshot(name=name, stats=s, criteria=list(criteria))
    return PlacedBuilding(uuid.uuid4(), name, "custom", lat, lon, "8629b0c07ffffff", snap, {},
                          site or SiteAssumptions())


def totals(*buildings: PlacedBuilding, period_days=10):
    ctx = ScenarioContext(assumptions=ScenarioAssumptions(period_days=period_days), buildings=list(buildings))
    locs = {b.id: LocationContext(b.h3_id, None) for b in buildings}
    return _totals(ctx, building_results(ctx, StressControls(), locs))


# --- scenario totals --------------------------------------------------------------------------


def test_partial_operating_cost_total_keeps_missing_components():
    fixed = {"currency": "USD", "operating": {"amount": 365.25, "period": "year", "kind": "fixed"}}
    a = place("A", stats(operatingHoursPerDay=8, power={"averageDemandKw": 100}, costs=fixed))
    b = place("B", stats(costs=fixed))
    [op] = totals(a, b).operating_cost
    assert op.value == pytest.approx(20) and op.unit == "USD"
    assert "operating cost of A: electricity price per kWh" in op.missing
    assert "partial" in op.basis


def test_total_is_unknown_not_zero_when_nothing_is_known():
    t = totals(place("C", stats()), place("D", stats()))
    assert t.electricity_demand.value is None
    assert t.electricity_demand.missing == ["electricity demand of C", "electricity demand of D"]
    assert t.unknown_buildings["electricityDemand"] == ["C", "D"]
    assert all(x.value is None for x in t.construction_cost)
    # Known zeros still add up to a known zero.
    z = totals(place("Z", stats(operatingHoursPerDay=8, power={"averageDemandKw": 0})))
    assert z.electricity_demand.value == 0 and not z.electricity_demand.missing


def test_world_balance_is_generated_minus_used_across_all_buildings():
    plant = place("Plant", stats(operatingHoursPerDay=24, power={"averageOutputKw": 1000, "averageDemandKw": 50},
                               water={"inputM3PerHour": 1, "outputM3PerHour": 5}))
    office = place("Office", stats(operatingHoursPerDay=10, power={"averageDemandKw": 100}, water={"inputM3PerHour": 2}))
    t = totals(plant, office, period_days=1)
    assert t.electricity_output.value == pytest.approx(24_000)
    assert t.electricity_demand.value == pytest.approx(24 * 50 + 10 * 100)
    assert t.electricity_net.value == pytest.approx(24_000 - 2_200) and not t.electricity_net.missing
    assert t.water_net.value == pytest.approx(24 * 5 - (24 * 1 + 10 * 2))
    # Nothing generates power: the balance is minus what is used, not unknown.
    only_use = totals(office, period_days=1)
    assert only_use.electricity_output.value == 0
    assert only_use.electricity_net.value == pytest.approx(-1_000)


def test_world_balance_is_partial_or_unknown_with_the_inputs_it_lacks():
    known = place("Known", stats(operatingHoursPerDay=24, power={"averageDemandKw": 10}))
    blank = place("Blank", stats())
    partial = totals(known, blank, period_days=1).electricity_net
    assert partial.value == pytest.approx(-240)
    assert "electricity demand of Blank" in partial.missing and "partial" in partial.basis
    unknown = totals(blank, period_days=1).electricity_net
    assert unknown.value is None and unknown.missing == ["electricity demand of Blank"]


def test_footprint_staff_and_peak_totals():
    a = place("A", stats(footprintM2=2_000, workers={"staffingRequired": 30}, power={"peakDemandKw": 400}))
    b = place("B", stats(footprintM2=500, workers={"staffingRequired": 5}))
    t = totals(a, b)
    assert (t.footprint.value, t.footprint.unit) == (2_500, "m²") and not t.footprint.missing
    assert (t.staffing_required.value, t.staffing_required.unit) == (35, "people")
    assert t.peak_demand.value == 400 and t.peak_demand.missing == ["peak demand of B"]
    assert "upper bound" in t.peak_demand.basis
    assert t.unknown_buildings["peakDemand"] == ["B"]


def test_costs_without_currency_are_not_summed_together():
    a = place("A", stats(costs={"constructionTotal": 1_000_000}))
    b = place("B", stats(costs={"constructionTotal": 500_000}))
    usd = place("U", stats(costs={"currency": "USD", "constructionTotal": 10}))
    t = totals(a, b, usd)
    by_unit = {x.unit: x for x in t.construction_cost}
    assert by_unit["USD"].value == 10
    blank = by_unit["unspecified currency"]
    assert blank.value is None and blank.missing == ["currency of A", "currency of B"]
    assert set(t.unknown_buildings["constructionCost"]) == {"A", "B"}
    # A single building without a currency mixes nothing: its own amount is shown.
    [one] = totals(a).construction_cost
    assert (one.value, one.unit) == (1_000_000, "unspecified currency")


def test_explanations_use_readable_numbers():
    s = stats(costs={"currency": "USD", "constructionTotal": 1_000_000})
    crit = [Criterion(id="c", kind="construction_budget", amount=2_000_000)]
    _, _, a, *_ = assess_point("custom", s, {}, crit, SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    assert "1,000,000 USD" in a.checks[0].explanation and "e+06" not in a.checks[0].explanation


# --- supply checks ----------------------------------------------------------------------------


def test_zero_demand_without_supply_passes_with_matching_explanation():
    s = stats(operatingHoursPerDay=24, water={"inputM3PerHour": 0})
    crit = [Criterion(id="w", kind="water_budget")]
    _, _, a, *_ = assess_point("custom", s, {}, crit, SiteAssumptions(), LAT, LON, ScenarioContext(), set())
    c = a.checks[0]
    assert c.status == "pass" and "No demand" in c.explanation and "unknown" not in c.explanation


def _supply_check(result, kind="water_budget"):
    [c] = [c for c in result.buildings[0].assessment.checks if c.kind == kind]
    return c


@pytest.mark.parametrize("declared", [False, True])
def test_evaluation_shows_site_supply_and_shortfall_per_building(declared):
    """Spec fixture: 20 m³/day × 10 days = 200 m³ vs 160 m³ demand; water availability 0.5 → 100 m³."""
    crit = [Criterion(id="w", kind="water_budget")] if declared else []
    b = place("W", stats(**FIXTURE), crit, SiteAssumptions(water_allocation_m3_per_day=20))
    ctx = ScenarioContext(assumptions=ScenarioAssumptions(period_days=10), buildings=[b])
    unstressed, stressed, _ = evaluate(ctx, StressControls(water_availability=0.5))

    un, st = _supply_check(unstressed), _supply_check(stressed)
    assert (un.status, un.actual, un.required_value, un.unit) == ("pass", 160, 200, "m³")
    assert (st.status, st.actual, st.required_value) == ("fail", 160, 100)
    assert "unmet 60" in st.explanation and "water availability 0.5" in st.source
    # A declared site allocation activates a required check whether or not the definition lists one.
    assert un.required is True
    assert unstressed.buildings[0].assessment.state == "meets_criteria"
    assert stressed.buildings[0].assessment.state == "fails_criteria"
    # No power source declared, so no power check is added.
    assert not [c for c in unstressed.buildings[0].assessment.checks if c.kind in ("power_capacity", "energy_budget")]


def test_evaluation_adds_pool_supply_check_for_covered_buildings():
    b = place("W", stats(**FIXTURE))
    pool = ResourceBudget(id="p", label="Town water", kind="water_m3_per_day", amount=20)
    ctx = ScenarioContext(assumptions=ScenarioAssumptions(period_days=10, budgets=[pool]), buildings=[b])
    unstressed, stressed, _ = evaluate(ctx, StressControls(water_availability=0.5))
    assert (_supply_check(unstressed).status, _supply_check(unstressed).required_value) == ("pass", 200)
    assert (_supply_check(stressed).status, _supply_check(stressed).required_value) == ("fail", 100)


# --- layer checks -----------------------------------------------------------------------------


def test_round_sig_matches_display_precision():
    v = np.array([np.float32(0.1) * 100.0, 0.0760456123, np.nan, 0.0, -1234567.89])
    r = _round_sig(v)
    assert r[0] == 10.0 and r[1] == 0.0760456 and np.isnan(r[2]) and r[3] == 0 and r[4] == -1234570.0


def _have_water_stress() -> bool:
    layer = layers.BY_ID["water_stress"]
    meta = features.layer_meta("aqueduct_baseline")
    return (layers.source_for(layer, layer.slice("score")) is not None
            and meta is not None and features.available(meta))


@pytest.mark.skipif(not _have_water_stress(), reason="prepared Aqueduct data not available")
def test_water_stress_uses_point_in_basin_at_exact_location():
    # Real prepared data: the cell centre lies in a 'Low' basin, the point in an 'Extremely High' one.
    lat, lon, cell = 34.20812, -113.01106, "8629b636fffffff"
    cells = np.array([int(cell, 16)], dtype=np.uint64)
    crit = Criterion.model_validate({"id": "ws", "kind": "layer", "layerId": "water_stress", "sliceId": "score", "max": 2})

    screening = _layer_check(crit, cells, lambda _i: cell).build(0)
    assert screening.status == "pass" and "containing the cell centre" in screening.source

    exact = _layer_check(crit, cells, lambda _i: cell, (lat, lon)).build(0)
    assert exact.status == "fail" and exact.actual == 5
    assert "containing the exact point" in exact.source and "aqueduct_baseline" in exact.source

    cat = Criterion.model_validate({"id": "wc", "kind": "layer", "layerId": "water_stress", "sliceId": "category",
                                   "classes": [0, 1]})
    assert _layer_check(cat, cells, lambda _i: cell, (lat, lon)).build(0).status == "fail"


@pytest.mark.skipif(not _have_water_stress(), reason="prepared Aqueduct data not available")
def test_water_stress_falls_back_to_cell_value_without_polygon(monkeypatch):
    monkeypatch.setattr(features, "layer_meta", lambda _id: None)
    cell = "8629b636fffffff"
    crit = Criterion.model_validate({"id": "ws", "kind": "layer", "layerId": "water_stress", "sliceId": "score", "max": 2})
    c = _layer_check(crit, np.array([int(cell, 16)], dtype=np.uint64), lambda _i: cell, (34.20812, -113.01106)).build(0)
    assert c.status == "pass" and "point-in-basin check not possible" in c.source


def test_layer_threshold_equal_to_displayed_value_passes():
    layer = layers.BY_ID["solar_ghi"]
    src = layers.source_for(layer, layer.slice("clim-ann"))
    if src is None:
        pytest.skip("prepared solar data not available")
    cell = "8629b0c07ffffff"
    cells = np.array([int(cell, 16)], dtype=np.uint64)
    ghi = {"id": "g", "kind": "layer", "layerId": "solar_ghi", "sliceId": "clim-ann"}
    shown = _layer_check(Criterion.model_validate({**ghi, "min": 0}), cells, lambda _i: cell).build(0).actual
    raw = float(h3store.lookup(src, h3store.SIM_RES, cells)[0])
    for bound in ({"min": shown}, {"max": shown}):
        c = Criterion.model_validate({**ghi, **bound})
        assert _layer_check(c, cells, lambda _i: cell).build(0).status == "pass", (raw, shown)


def test_emission_totals_keep_media_separate_and_combine_aliases():
    a = place('A', stats(operatingHoursPerDay=24, emissions=[
        {'id': 'a', 'pollutant': 'Pb', 'rateKgPerHour': 1},
        {'id': 's', 'pollutant': 'Lead', 'medium': 'soil', 'rateKgPerHour': 10},
        {'id': 'c', 'pollutant': 'CO2e (Scope 1+2)', 'rateKgPerHour': 200}]))
    b = place('B', stats(operatingHoursPerDay=12, emissions=[
        {'id': 'b', 'pollutant': 'Lead', 'medium': 'air', 'rateKgPerHour': 2}]))
    emissions = totals(a, b, period_days=1).emissions
    assert {e.medium: (e.quantity.value, e.quantity.unit) for e in emissions} == {
        'air': (48, 'kg'), 'soil': (240, 'kg'), 'climate': (4800, 'kgCO₂e')}
