"""Location-default utility prices for the building system.

The ``electricity_price`` / ``water_price`` layers hold one average price per area (country, or US/CA/AU
state for electricity) in USD. A building's unit prices stay blank unless the user enters them; this
module only *offers* the cell's business price as an explicit, labelled location default
(CLAUDE.Building-System.md: blank means unknown, no implicit FX conversion, every value shows its source).

- A user-entered price (no ``*_price_source``) always wins; the location price is then reference only.
- The offer is never applicable when the costs are in another currency: USD is never converted.
- A blank dataset value stays blank: nothing is offered, nothing is assumed.
"""

from __future__ import annotations

import math

from app import h3store, layers
from app.building_calc import fmt_num
from app.building_models import Costs, LocationPriceOffer, PriceSource

DATASET_CURRENCY = "USD"  # prepare_utility_prices.py converts every price to USD
CUSTOMER = "business"

# resource -> (layer id, value column, basis column, price field, source field, price unit)
_RESOURCES = {
    "electricity": ("electricity_price", "elec_business", "elec_business_basis",
                    "electricity_price_per_kwh", "electricity_price_source", "kWh"),
    "water": ("water_price", "water_business", "water_business_basis",
              "water_price_per_m3", "water_price_source", "m³"),
}


def _sig6(v: float) -> float:
    """Prices are stored as float32; read them back at the precision they were published with."""
    return float(f"{v:.6g}")


def cell_prices(h3_id: str) -> dict[str, PriceSource | None]:
    """The cell's average business electricity and water price, or None where the dataset is blank."""
    out: dict[str, PriceSource | None] = {}
    cell = h3store.cell_int(h3_id)
    for resource, (layer_id, col, basis_col, *_rest) in _RESOURCES.items():
        layer = layers.BY_ID.get(layer_id)
        s = layer.slice(CUSTOMER) if layer else None
        files = tuple(layers.slice_files(s)) if s else ()
        if not files:
            out[resource] = None
            continue
        got = h3store.point_values(files, layer.key_column, [col, basis_col, "price_area", "price_area_name"], cell)
        v = got.get(col)
        if v is None or not math.isfinite(float(v)) or float(v) < 0:
            out[resource] = None
            continue
        area, area_name = got.get("price_area"), got.get("price_area_name")
        if resource == "water" and area_name:
            # Water prices are national: the state part of a US/CA/AU electricity area does not apply.
            area_name = area_name.split(" · ")[0]
            area = area.split("-")[0] if area else area
        out[resource] = PriceSource(
            value=_sig6(float(v)),
            currency=DATASET_CURRENCY,
            customer=CUSTOMER,
            h3_id=h3_id,
            price_area=area,
            price_area_name=area_name,
            basis=got.get(basis_col),
            source=f"{layer.source_id} {layer.name}, {s.label}",
        )
    return out


def _same_price(a: PriceSource, b: PriceSource) -> bool:
    return (a.currency == b.currency and a.customer == b.customer and a.price_area == b.price_area
            and math.isclose(a.value, b.value, rel_tol=1e-9, abs_tol=1e-12))


def offer(resource: str, here: PriceSource | None, costs: Costs) -> LocationPriceOffer:
    _layer, _col, _basis, price_field, source_field, price_unit = _RESOURCES[resource]
    entered = getattr(costs, price_field)
    applied: PriceSource | None = getattr(costs, source_field)
    unit = f"{DATASET_CURRENCY}/{price_unit}"
    here_text = f"{DATASET_CURRENCY} {fmt_num(here.value)}/{price_unit}" if here else ""

    def make(status, message):
        return LocationPriceOffer(resource=resource, unit=unit, price=here, status=status, message=message)

    if entered is not None and applied is None:
        ref = f" This location's average {CUSTOMER} price is {here_text} (reference only)." if here else ""
        return make("entered", f"Your entered {resource} price is used.{ref}")
    if applied is not None:
        area = applied.price_area_name or applied.price_area or applied.h3_id
        if here is not None and _same_price(applied, here):
            return make("applied", f"Using this location's average {CUSTOMER} {resource} price, {here_text} "
                                   f"({here.price_area_name or here.price_area}).")
        now = (f" This location's price is {here_text}." if here
               else f" This location has no {CUSTOMER} {resource} price in the dataset.")
        return make("applied_elsewhere", f"The {resource} price in use is the location default for {area} "
                                         f"({applied.currency} {fmt_num(applied.value)}/{price_unit}).{now}")
    if costs.operating.kind == "total":
        return make("not_used", "The operating cost is all-inclusive, so unit prices are not added.")
    if here is None:
        return make("unavailable", f"No average {CUSTOMER} {resource} price for this location in the dataset; "
                                   "the price stays blank (unknown) unless you enter one.")
    if costs.currency is not None and costs.currency != here.currency:
        return make("currency_mismatch", f"This location's average {CUSTOMER} price is {here_text}, but this "
                                         f"building's costs are in {costs.currency}. Currencies are never converted: "
                                         f"enter a {costs.currency} price yourself or switch the costs to "
                                         f"{here.currency}.")
    extra = "" if costs.currency else f" Applying it also sets the cost currency to {here.currency}."
    return make("available", f"No {resource} price entered. This location's average {CUSTOMER} price is "
                             f"{here_text} ({here.price_area_name or here.price_area}).{extra}")


def location_offers(h3_id: str, costs: Costs) -> list[LocationPriceOffer]:
    here = cell_prices(h3_id)
    return [offer(r, here[r], costs) for r in _RESOURCES]

