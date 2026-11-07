"""Predefined building templates: one per BuildingType, valid fields, and calculation wiring."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from app import site_capacity, site_support
from app.building_calc import CalcInputError, calculate, validate_parameters
from app.building_models import BuildingCategory, BuildingStats, BuildingType
from app.building_templates import (
    BY_ID,
    DESCRIPTIVE,
    NUMERIC_PARAMS,
    POWER_PRODUCERS,
    SELECT_PARAMS,
    TEMPLATES,
    WATER_PRODUCERS,
)

TYPES = typing.get_args(BuildingType)
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def test_one_template_per_type_in_literal_order():
    assert [t.id for t in TEMPLATES] == list(TYPES)
    assert all(t.type == t.id for t in TEMPLATES)
    assert len(TYPES) >= 40


def test_categories_are_known_and_each_used():
    cats = set(typing.get_args(BuildingCategory))
    assert {t.category for t in TEMPLATES} == cats
    assert BY_ID["custom"].category == "other" and BY_ID["mine"].category == "extraction"


def test_original_types_keep_their_fields():
    assert [p.key for p in BY_ID["solar"].parameters] == ["capacityKwp", "landAreaM2", "performanceRatio"]
    assert "pue" in [p.key for p in BY_ID["data_centre"].parameters]
    assert [p.key for p in BY_ID["greenhouse"].parameters] == ["floorAreaM2", "heatDemandKwhPerYear", "minSupplyTempC"]
    assert {"power_station", "solar"} <= POWER_PRODUCERS and "water_plant" in WATER_PRODUCERS


@pytest.mark.parametrize("template", TEMPLATES, ids=[t.id for t in TEMPLATES])
def test_template_parameters_are_validated(template):
    keys = [p.key for p in template.parameters]
    assert len(keys) == len(set(keys))
    for p in template.parameters:
        if p.kind == "number":
            assert p.key in NUMERIC_PARAMS.get(template.id, {}), p.key
        else:
            assert p.options and tuple(p.options) == SELECT_PARAMS[template.id][p.key]
    # No numeric defaults anywhere: every value is a user assumption until cited.
    assert template.defaults == BuildingStats()
    assert "power.averageDemandKw" in template.field_help


@pytest.mark.parametrize("template", [t for t in TEMPLATES if t.id not in {"data_centre", "solar", "greenhouse"}],
                         ids=lambda t: t.id)
def test_new_type_parameters_are_descriptive_and_bounded(template):
    for p in template.parameters:
        assert p.hint and p.hint.endswith(DESCRIPTIVE)
        if p.kind == "number":
            lo, _ = NUMERIC_PARAMS[template.id][p.key]
            with pytest.raises(CalcInputError):
                validate_parameters(template.id, {p.key: lo - 1})
        else:
            with pytest.raises(CalcInputError):
                validate_parameters(template.id, {p.key: "not-an-option"})
            validate_parameters(template.id, {p.key: p.options[0]})


def test_descriptive_parameters_do_not_change_results():
    stats = BuildingStats.model_validate({"operatingHoursPerDay": 24, "power": {"averageDemandKw": 1000}})
    plain = calculate("mine", stats, {}, 30)
    described = calculate("mine", stats, {"commodity": "copper", "oreThroughputTPerDay": 50_000}, 30)
    assert plain.model_dump() == described.model_dump()
    assert plain.electricity_demand.value == 1000 * 24 * 30


@pytest.mark.parametrize("btype", sorted(POWER_PRODUCERS - {"solar"}))
def test_power_producers_ask_for_output(btype):
    r = calculate(btype, BuildingStats.model_validate({"operatingHoursPerDay": 24}), {}, 30)
    assert r.electricity_output.value is None and r.electricity_output.missing
    r = calculate(btype, BuildingStats.model_validate(
        {"operatingHoursPerDay": 24, "power": {"averageOutputKw": 100, "averageDemandKw": 10}}), {}, 30)
    assert r.electricity_net.value == pytest.approx((100 - 10) * 24 * 30)


@pytest.mark.parametrize("btype", sorted(WATER_PRODUCERS))
def test_water_producers_ask_for_output(btype):
    r = calculate(btype, BuildingStats.model_validate({"operatingHoursPerDay": 24}), {}, 30)
    assert r.water_output.value is None and r.water_output.missing


def test_consumers_report_no_output():
    r = calculate("office", BuildingStats.model_validate({"operatingHoursPerDay": 10}), {}, 30)
    assert r.electricity_output.value is None and not r.electricity_output.missing


def test_support_sets_cover_types_consistently():
    assert "battery_storage" not in site_support.GENERATORS  # storage adds no supply
    assert site_support.GENERATORS <= POWER_PRODUCERS
    assert site_capacity.SEAWATER_TYPES <= set(TYPES)


def test_latest_migration_allows_every_type():
    latest = max(MIGRATIONS.glob("V*__*.sql"), key=lambda p: int(re.match(r"V(\d+)", p.name).group(1)))
    sql = latest.read_text()
    for table in ("project", "building_definition"):
        block = re.search(rf"ADD CONSTRAINT {table}_type_check\s+CHECK \(type IN \((.*?)\)\);", sql, re.S)
        assert block, f"{latest.name} does not reset {table}_type_check"
        assert re.findall(r"'([a-z_]+)'", block.group(1)) == list(TYPES)
