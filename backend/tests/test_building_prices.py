"""Location-default utility prices in the building system (no database).

The cell's average business price is only ever *offered*: unit prices stay blank until the user
explicitly applies it, a typed price always wins, and USD is never mixed with another currency.
Numbers are test inputs, not template defaults.
"""

import h3
import pytest
from pydantic import ValidationError

from app import layers
from app.building_calc import calculate
from app.building_models import BuildingStats, Costs, PriceSource
from app.building_prices import cell_prices, location_offers, offer

PHOENIX = (33.44838, -112.07404)  # US-AZ: business electricity, no business water
FIXTURE = {"operatingHoursPerDay": 8, "power": {"averageDemandKw": 100}, "water": {"inputM3PerHour": 2}}
H3 = h3.latlng_to_cell(*PHOENIX, 6)


def src(value=0.12, currency="USD", area="US-AZ", name="Arizona", h3_id=H3) -> PriceSource:
    return PriceSource(value=value, currency=currency, h3_id=h3_id, price_area=area, price_area_name=name,
                       basis="USD 0.12/kWh · 2025 · test basis", source="PRICE-01 test")


def costs(**kw) -> Costs:
    return Costs.model_validate(kw)


# --- the offer -------------------------------------------------------------------------------


def test_blank_price_is_offered_not_filled_in():
    o = offer("electricity", src(), costs(currency="USD"))
    assert o.status == "available" and o.price.value == 0.12 and o.unit == "USD/kWh"
    assert "Arizona" in o.message


def test_blank_currency_offer_says_it_sets_usd():
    o = offer("electricity", src(), costs())
    assert o.status == "available" and "sets the cost currency to USD" in o.message


def test_entered_price_always_wins():
    o = offer("electricity", src(), costs(currency="USD", electricity_price_per_kwh=0.30))
    assert o.status == "entered" and "reference only" in o.message
    # also when the building's currency differs: the user's own price is simply used
    assert offer("electricity", src(), costs(currency="EUR", electricity_price_per_kwh=0.2)).status == "entered"


def test_non_usd_costs_are_never_offered_a_usd_price():
    o = offer("electricity", src(), costs(currency="EUR"))
    assert o.status == "currency_mismatch" and "never converted" in o.message
    assert o.price is not None  # shown for reference, but not applicable


def test_missing_dataset_value_stays_unknown():
    o = offer("water", None, costs(currency="USD"))
    assert o.status == "unavailable" and o.price is None and "blank" in o.message


def test_applied_here_and_elsewhere():
    applied = costs(currency="USD", electricity_price_per_kwh=0.12, electricity_price_source=src())
    assert offer("electricity", src(), applied).status == "applied"
    other = offer("electricity", src(value=0.2, area="US-CA", name="California"), applied)
    assert other.status == "applied_elsewhere" and "Arizona" in other.message and "0.2" in other.message
    assert offer("electricity", None, applied).status == "applied_elsewhere"


def test_all_inclusive_operating_cost_does_not_use_unit_prices():
    c = costs(currency="USD", operating={"amount": 100, "period": "year", "kind": "total"})
    assert offer("electricity", src(), c).status == "not_used"


# --- the stored source: validation ----------------------------------------------------------


def test_source_must_share_the_cost_currency():
    with pytest.raises(ValidationError, match="never converted"):
        costs(currency="EUR", electricity_price_per_kwh=0.12, electricity_price_source=src())
    with pytest.raises(ValidationError, match="no currency"):
        costs(electricity_price_per_kwh=0.12, electricity_price_source=src())


def test_source_must_match_the_price_it_labels():
    with pytest.raises(ValidationError, match="differs from its location default"):
        costs(currency="USD", electricity_price_per_kwh=0.5, electricity_price_source=src())
    with pytest.raises(ValidationError, match="differs from its location default"):
        costs(currency="USD", water_price_source=src(value=1.5))


def test_source_round_trips_camel_case():
    c = costs(currency="USD", electricityPricePerKwh=0.12, electricityPriceSource=src().model_dump(by_alias=True))
    assert c.electricity_price_source.price_area == "US-AZ"
    assert c.model_dump(by_alias=True)["electricityPriceSource"]["h3Id"] == H3


# --- the calculation ---------------------------------------------------------------------------


def test_applied_location_price_is_costed_and_labelled():
    s = BuildingStats.model_validate({**FIXTURE, "costs": {
        "currency": "USD", "electricityPricePerKwh": 0.12, "electricityPriceSource": src().model_dump(by_alias=True)}})
    r = calculate("custom", s, {}, 10)
    assert r.electricity_demand.value == 8000
    assert r.costs.electricity.value == pytest.approx(960) and r.costs.electricity.unit == "USD"
    basis = r.costs.electricity.basis
    assert "location default: USD 0.12/kWh" in basis and "Arizona" in basis and "PRICE-01" in basis
    assert r.costs.electricity_price_source.price_area == "US-AZ" and r.costs.water_price_source is None
    # water was not applied: still unknown, never zero
    assert r.costs.water.value is None and "water price per m³" in r.costs.water.missing


def test_typed_price_has_no_location_label():
    s = BuildingStats.model_validate({**FIXTURE, "costs": {"currency": "USD", "electricityPricePerKwh": 0.12}})
    assert "location default" not in calculate("custom", s, {}, 10).costs.electricity.basis


def test_blank_prices_stay_unknown_without_explicit_choice():
    s = BuildingStats.model_validate({**FIXTURE, "costs": {"currency": "USD"}})
    r = calculate("custom", s, {}, 10)
    assert r.costs.electricity.value is None and r.costs.water.value is None


# --- prepared data -----------------------------------------------------------------------------

needs_prices = pytest.mark.skipif(
    not layers.slice_files(layers.BY_ID["electricity_price"].slice("business")),
    reason="utility_prices_h3r6.parquet not prepared",
)


@needs_prices
def test_cell_prices_read_business_usd_with_basis():
    p = cell_prices(H3)
    e = p["electricity"]
    assert e is not None and e.currency == "USD" and e.customer == "business"
    assert e.price_area == "US-AZ" and e.h3_id == H3 and e.basis and "PRICE-01" in e.source
    assert e.value == float(f"{e.value:.6g}")  # float32 noise removed
    assert p["water"] is None  # no business water price for the US: blank, never zero or household


@needs_prices
def test_water_area_is_national():
    """Electricity is priced per US state, water per country: the water source names the country only."""
    cell = h3.latlng_to_cell(-12.05, -77.04, 6)  # Lima: business water reported for Peru
    w = cell_prices(cell)["water"]
    if w is None:
        pytest.skip("no business water price for Peru in this data build")
    assert " · " not in (w.price_area_name or "") and "-" not in (w.price_area or "")


@needs_prices
def test_open_sea_has_no_offer():
    offers = location_offers(h3.latlng_to_cell(-30.0, -140.0, 6), Costs())
    assert [o.status for o in offers] == ["unavailable", "unavailable"]
