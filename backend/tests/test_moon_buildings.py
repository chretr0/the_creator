"""Moon building catalogue (shared/moon_buildings.json) and Moon parameter validation. No database."""

import math
import typing

import pytest
from pydantic import ValidationError

from app import moon_buildings
from app.building_calc import CalcInputError
from app.building_models import BuildingType, MoonBuildingType
from app.models import ProjectCreate, ProjectType, ScenarioCreate
from app.moon_buildings import MOON_TYPES, PARAMS, defaults, validate_parameters
from app.routers.scenarios import snapshot_of

SPECS = [(t, spec) for t in MOON_TYPES for spec in PARAMS[t].values()]


def test_catalogue_matches_literal_in_order():
    assert MOON_TYPES == typing.get_args(MoonBuildingType)
    assert len(MOON_TYPES) == 8 and all(t.startswith("moon_") for t in MOON_TYPES)


def test_project_type_is_earth_then_moon_without_overlap():
    earth = typing.get_args(BuildingType)
    assert typing.get_args(ProjectType) == earth + MOON_TYPES
    assert not set(earth) & set(MOON_TYPES)


@pytest.mark.parametrize("btype", MOON_TYPES)
def test_param_keys_are_unique(btype):
    keys = [p["key"] for p in moon_buildings.BY_TYPE[btype]["params"]]
    assert keys and len(keys) == len(set(keys))


@pytest.mark.parametrize(("btype", "spec"), SPECS, ids=[f"{t}.{s['key']}" for t, s in SPECS])
def test_every_default_is_within_its_bounds(btype, spec):
    lo, hi, default = spec["min"], spec["max"], spec["default"]
    assert isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo <= hi
    if default is not None:
        assert lo <= default <= hi
        if spec.get("integer"):
            assert float(default).is_integer()


@pytest.mark.parametrize("btype", MOON_TYPES)
def test_catalogue_defaults_validate(btype):
    validate_parameters(btype, defaults(btype))
    validate_parameters(btype, {})  # absent = unknown
    validate_parameters(btype, {key: None for key in PARAMS[btype]})  # null = unknown


def test_null_defaults_stay_unknown():
    assert defaults("moon_storage")["landedMassT"] is None
    assert defaults("moon_habitat") == {"crew": 4, "powerKw": 15, "waterRecoveryPct": 90, "oxygenRecoveryPct": 40,
                                        "reserveDays": 30, "landedMassT": 12}


def _problems(btype, parameters) -> str:
    with pytest.raises(CalcInputError) as exc:
        validate_parameters(btype, parameters)
    return str(exc.value)


def test_out_of_range_messages():
    assert _problems("moon_habitat", {"crew": 0}) == "crew must be at least 1"
    assert _problems("moon_habitat", {"crew": 51}) == "crew must be at most 50"
    assert _problems("moon_storage", {"capacityKwh": 1_000_001}) == "capacityKwh must be at most 1,000,000"
    assert _problems("moon_landing_pad", {"diameterM": 4.5}) == "diameterM must be at least 5"
    # Bounds are inclusive.
    validate_parameters("moon_habitat", {"crew": 1, "waterRecoveryPct": 99})
    validate_parameters("moon_habitat", {"crew": 50, "waterRecoveryPct": 0})


def test_integer_params_must_be_whole():
    assert _problems("moon_habitat", {"crew": 4.5}) == "crew must be a whole number"
    assert _problems("moon_habitat", {"reserveDays": 0.1}) == "reserveDays must be a whole number"
    validate_parameters("moon_habitat", {"crew": 4.0, "reserveDays": 7})
    validate_parameters("moon_habitat", {"powerKw": 15.5})  # not an integer param


def test_messages_are_sorted_and_deduplicated():
    msg = _problems("moon_habitat", {"crew": math.nan, "powerKw": -1, "landedMassT": 1001})
    assert msg == "crew must be finite; landedMassT must be at most 1,000; powerKw must be at least 0"


@pytest.mark.parametrize("bad", ["4", "", True, [1]])
def test_known_params_must_be_numbers(bad):
    assert _problems("moon_habitat", {"crew": bad}) == "crew must be a number or null"


def test_huge_ints_are_out_of_range():
    assert _problems("moon_habitat", {"crew": 10**400}) == "crew is out of range"


def test_extra_keys_preserved_but_non_finite_rejected():
    validate_parameters("moon_fission", {"outputKw": 40, "note": "hello", "flag": True, "extra": 1e9})
    for bad in (math.inf, -math.inf, math.nan):
        assert _problems("moon_fission", {"extra": bad}) == "extra must be finite"


def test_earth_type_is_not_a_moon_type():
    assert not moon_buildings.is_moon_type("solar")
    with pytest.raises(CalcInputError, match="not a Moon building type"):
        validate_parameters("solar", {})


def test_moon_project_round_trips_through_models():
    p = ProjectCreate.model_validate({
        "type": "moon_storage", "name": "Night store", "latitude": -89.5, "longitude": 0,
        "parameters": {"capacityKwh": 2000, "maxOutputKw": 10, "landedMassT": None},
        "definition": {"name": "Night store", "templateId": "moon_storage"},
    })
    assert p.parameters["landedMassT"] is None
    assert p.definition.template_id == "moon_storage"
    # Legacy rows (no definition) adapt with the Moon type as the template id.
    snap = snapshot_of({"name": "Hab", "type": "moon_habitat", "definition": None})
    assert snap.template_id == "moon_habitat" and snap.name == "Hab"


def test_scenario_body_defaults_to_earth_and_rejects_unknown():
    assert ScenarioCreate.model_validate({"name": "x"}).body == "earth"
    assert ScenarioCreate.model_validate({"name": "x", "body": "moon"}).body == "moon"
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate({"name": "x", "body": "mars"})
