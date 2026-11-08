import json
import h3
import pytest
from pydantic import ValidationError
from app import timeline_environment as environment
from app.building_models import BuildingStats, EmissionItem, Criterion, ScenarioAssumptions, SiteAssumptions
from app.building_calc import calculate
from app.building_assess import assess_point, ScenarioContext
from app.pollutants import CATALOGUE, pollutant_id


def test_catalogue_aliases_and_mass_bases():
    assert len(CATALOGUE) >= 35
    for row in CATALOGUE:
        for name in [row['id'], row['label'], *row['aliases']]:
            assert pollutant_id(name) == row['id']
    assert pollutant_id('CO2e (market-based Scope 1+2)') == 'co2e'
    assert pollutant_id('PFCs (as CO2e)') == 'co2e'
    assert pollutant_id('CO₂') == 'co2'
    assert pollutant_id('NOx (as NO2)') != 'nox'
    assert pollutant_id('CO2 (Scope 2)') != 'co2'


def test_legacy_defaults_and_new_destinations_round_trip():
    old = EmissionItem.model_validate({'id': 'a', 'pollutant': 'CO2e (market-based Scope 1+2)', 'rateKgPerHour': 200})
    assert old.medium == 'climate'
    assert EmissionItem.model_validate(old.model_dump(by_alias=True)) == old
    assert EmissionItem(id='b', pollutant='PM10').medium == 'air'
    for medium in ['air', 'soil', 'freshwater', 'marine']:
        item = EmissionItem(id='x', pollutant='Lead', medium=medium, rate_kg_per_hour=1)
        assert EmissionItem.model_validate(item.model_dump(by_alias=True)).medium == medium
    for pollutant, medium in [('CO2e', 'soil'), ('PM10', 'marine')]:
        with pytest.raises(ValidationError):
            EmissionItem(id='x', pollutant=pollutant, medium=medium)


def test_calculator_keeps_media_and_co2e_units():
    stats = BuildingStats.model_validate({'operatingHoursPerDay': 24, 'emissions': [
        {'id': 'c', 'pollutant': 'CO2e (market-based Scope 1+2)', 'rateKgPerHour': 200},
        {'id': 'a', 'pollutant': 'Lead', 'rateKgPerHour': 1},
        {'id': 's', 'pollutant': 'Lead', 'medium': 'soil', 'rateKgPerHour': 10}]})
    assert [(e.medium, e.quantity.value, e.quantity.unit) for e in calculate('custom', stats, {}, 30).emissions] == [
        ('climate', 144000, 'kgCO₂e'), ('air', 720, 'kg'), ('soil', 7200, 'kg')]


def test_emission_criteria_match_alias_and_destination(monkeypatch):
    from app import site_capacity
    monkeypatch.setattr(site_capacity, 'site_checks', lambda *a, **k: ([], [], site_capacity.Materials([], [])))
    stats = BuildingStats.model_validate({'operatingHoursPerDay': 24, 'emissions': [
        {'id': 'a', 'pollutant': 'Pb', 'rateKgPerHour': 1},
        {'id': 's', 'pollutant': 'Lead', 'medium': 'soil', 'rateKgPerHour': 10}]})
    _, _, assessment, *_ = assess_point('custom', stats, {}, [Criterion(id='c', kind='emission_limit', pollutant='Lead', medium='soil', amount=300)],
        SiteAssumptions(), 33.45, -112.07, ScenarioContext(assumptions=ScenarioAssumptions(period_days=1)), set(), None)
    assert assessment.checks[0].actual == 240
    assert assessment.checks[0].status == 'pass'


def test_river_follows_downstream_topology_and_preserves_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(environment.settings, 'prepared_data_dir', str(tmp_path))
    folder = tmp_path / 'features'
    folder.mkdir()
    # Reversed first geometry: NEXT_DOWN, not vertex order, establishes downstream east.
    rows = [{'type': 'Feature', 'properties': {'hyrivId': i, 'nextDown': n, 'disAvCms': flow},
             'geometry': {'type': 'LineString', 'coordinates': coords}}
            for i, n, flow, coords in [(1, 2, 10, [[.1, 0], [0, 0]]), (2, 0, 20, [[.1, 0], [.2, 0]])]]
    (folder / 'hydrorivers.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': rows}))
    result = environment.river_release(.05, .001)
    assert result['distanceKm'] < 1 and result['cells']
    assert all(h3.cell_to_latlng(c['h3Id'])[1] >= .04 for c in result['cells'])
    assert {c['flowM3PerSecond'] for c in result['cells']} == {10, 20}
    assert max(c['distanceM'] for c in result['cells']) > 10000
    assert environment.river_release(20, 20)['cells'] == []


def test_surface_and_marine_source_do_not_invent_inland_outfalls(tmp_path, monkeypatch):
    monkeypatch.setattr(environment.settings, 'prepared_data_dir', str(tmp_path))
    folder = tmp_path / 'boundaries'
    folder.mkdir()
    (folder / 'countries.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}))
    cells = [{'latitude': .5, 'longitude': .5}, {'latitude': .5, 'longitude': -.02}]
    environment.surfaces(cells)
    assert [c['surface'] for c in cells] == ['land', 'marine']
    assert environment.marine_release(.01, .5, cells)['longitude'] == -.02
    assert environment.marine_release(.8, .5, cells)['latitude'] is None


def test_all_dropdown_choices_are_valid_stored_releases():
    for p in CATALOGUE:
        for medium in p['media']:
            item = EmissionItem(id='e', pollutant=p['label'], medium=medium, rate_kg_per_hour=1)
            assert EmissionItem.model_validate(item.model_dump(by_alias=True)).medium == medium


def test_air_site_checks_recognise_catalogue_and_exclude_water():
    from app.site_capacity import is_air_pollutant
    assert is_air_pollutant('Fine particles (PM2.5)')
    assert is_air_pollutant('Lead')
    assert not is_air_pollutant('Greenhouse gases (CO₂e)')


def test_terminal_river_can_use_upstream_topology(tmp_path, monkeypatch):
    monkeypatch.setattr(environment.settings, 'prepared_data_dir', str(tmp_path))
    folder = tmp_path / 'features'; folder.mkdir()
    rows = [{'type': 'Feature', 'properties': {'hyrivId': i, 'nextDown': n, 'disAvCms': 5},
             'geometry': {'type': 'LineString', 'coordinates': coords}}
            for i, n, coords in [(1, 2, [[0, 0], [.1, 0]]), (2, None, [[.2, 0], [.1, 0]])]]
    (folder / 'hydrorivers.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': rows}))
    route = environment.river_release(.15, .001)
    assert route['cells']
    assert all(h3.cell_to_latlng(c['h3Id'])[1] >= .14 for c in route['cells'])
    assert environment.river_release(.21, .001)['cells'] # Snapped to the terminal outlet, no segment remaining.


def test_legacy_air_names_remain_readable_and_co2_emissions_is_not_co2e():
    item = EmissionItem(id='e', pollutant='Copper')
    assert EmissionItem.model_validate(item.model_dump(by_alias=True)).medium == 'air'
    assert pollutant_id('CO2 emissions') != 'co2e'
