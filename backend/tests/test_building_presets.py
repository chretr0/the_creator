"""Real example buildings (app/presets/building_presets.json): schema, citations and calculability."""

from __future__ import annotations

import json
import math
import re
import typing

import h3
import pytest

from app.building_calc import LocationContext, calculate, validate_parameters
from app.building_models import BuildingPreset, BuildingType
from app.building_presets import PRESETS_PATH, load_presets

PRESETS = load_presets()
IDS = [p.id for p in PRESETS]
SOURCE_REF = re.compile(r"\bS\d+\b")

# Stat sections and the provenance that covers their numbers.
SECTIONS = ("power", "water", "light", "workers", "costs")


def _numbers(obj, path: str = "") -> list[tuple[str, float]]:
    """Every non-null number under `obj` (alias keys), skipping provenance blocks."""
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [(path, obj)]
    if isinstance(obj, dict):
        return [n for k, v in obj.items() if k != "provenance" for n in _numbers(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [n for i, v in enumerate(obj) for n in _numbers(v, f"{path}[{i}]")]
    return []


def _cited_problem(provenance: dict, source_ids: set[str]) -> str | None:
    if provenance.get("kind") != "cited":
        return f"provenance kind is {provenance.get('kind')!r}, not 'cited'"
    refs = set(SOURCE_REF.findall(provenance.get("note") or ""))
    if not refs:
        return "provenance note names no source id"
    if not refs & source_ids:
        return f"provenance note cites {sorted(refs)}, none of which is a listed source"
    return None


def _stats(preset: BuildingPreset) -> dict:
    return preset.stats.model_dump(mode="json", by_alias=True)


def test_file_is_a_json_array_of_unique_presets():
    raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and raw
    assert len(IDS) == len(raw) == len(set(IDS))
    assert load_presets() is PRESETS  # cached


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_preset_validates_and_type_is_known(preset: BuildingPreset):
    BuildingPreset.model_validate(preset.model_dump(mode="json", by_alias=True))
    assert preset.type in typing.get_args(BuildingType)
    assert preset.name.strip() and preset.headline.strip() and preset.description.strip()


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_sources_have_https_urls_and_unique_ids(preset: BuildingPreset):
    assert preset.sources
    ids = [s.id for s in preset.sources]
    assert len(ids) == len(set(ids))
    for s in preset.sources:
        assert s.url.startswith("https://"), s.id
        assert s.title.strip() and s.publisher.strip()


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_every_source_reference_resolves(preset: BuildingPreset):
    source_ids = {s.id for s in preset.sources}
    stats = _stats(preset)
    texts = list(preset.notes) + [stats["footprintProvenance"].get("note") or ""]
    texts += [stats[s]["provenance"].get("note") or "" for s in SECTIONS]
    texts += [i["provenance"].get("note") or "" for i in stats["materials"] + stats["emissions"]]
    unknown = {ref for t in texts for ref in SOURCE_REF.findall(t)} - source_ids
    assert not unknown, f"notes cite sources that are not listed: {sorted(unknown)}"


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_every_number_is_cited(preset: BuildingPreset):
    source_ids = {s.id for s in preset.sources}
    stats = _stats(preset)
    problems = []

    def check(numbers: list[tuple[str, float]], provenance: dict) -> None:
        if numbers and (p := _cited_problem(provenance, source_ids)):
            problems.append(f"{', '.join(path for path, _ in numbers)}: {p}")

    check(_numbers({"footprintM2": stats["footprintM2"]}), stats["footprintProvenance"])
    for section in SECTIONS:
        check(_numbers(stats[section], section), stats[section]["provenance"])
    for kind in ("materials", "emissions"):
        for i, item in enumerate(stats[kind]):
            check(_numbers(item, f"{kind}[{i}]"), item["provenance"])

    # Parameters have no provenance block: each numeric one must be named, with its value, in a note
    # that cites a listed source.
    cited_texts = [n for n in preset.notes if SOURCE_REF.findall(n)]
    cited_texts += [stats["footprintProvenance"].get("note") or ""]
    cited_texts += [stats[s]["provenance"].get("note") or "" for s in SECTIONS]
    for key, value in preset.parameters.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        shown = f"{int(value):,}" if float(value).is_integer() else str(value)
        as_number = re.compile(rf"(?<![\d,.]){re.escape(shown)}(?![\d,]|\.\d)")
        if not any(key in t and as_number.search(t) and set(SOURCE_REF.findall(t)) & source_ids
                   for t in cited_texts):
            problems.append(f"parameters.{key}: value {shown} not given in any note that cites a listed source")

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_reference_site_is_a_real_coordinate(preset: BuildingPreset):
    site = preset.reference_site
    assert -90 <= site.latitude <= 90 and -180 <= site.longitude < 180
    assert not (site.latitude == 0 and site.longitude == 0)
    assert site.name.strip() and site.country.strip()


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_parameters_are_valid(preset: BuildingPreset):
    validate_parameters(preset.type, preset.parameters)


def _all_finite(obj) -> bool:
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_finite(v) for v in obj)
    return True


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
@pytest.mark.parametrize("with_location", [False, True], ids=["no-location", "location"])
def test_calculates_without_error(preset: BuildingPreset, with_location: bool):
    location = None
    if with_location:
        site = preset.reference_site
        location = LocationContext(h3_id=h3.latlng_to_cell(site.latitude, site.longitude, 6), solar_ghi=5.5,
                                   solar_source="test climatology")
    result = calculate(preset.type, preset.stats, preset.parameters, 30, location=location)
    assert result.period_days == 30
    assert _all_finite(result.model_dump(mode="python"))


def test_presets_route(client):
    r = client.get("/api/building-presets")
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body] == IDS
    first = body[0]
    assert {"referenceSite", "headline", "sources", "stats", "parameters", "notes"} <= first.keys()
    assert "footprintProvenance" in first["stats"]
