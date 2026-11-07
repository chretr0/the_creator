"""Deterministic building calculations (CLAUDE.Building-System.md sections 5, 6 and 10).

The single source of truth for previews, candidate assessment, saved buildings and stress tests.
Pure functions: no database, no network. Unknown inputs give ``Quantity(value=None, missing=[...])``
and never zero; independent results are still returned. Every returned number is finite.

Stress multipliers handled here (supply multipliers only touch budgets, see building_assess):
- ``operating_demand`` multiplies operating demand *rates*: electricity (average and peak), water
  input and operational materials. Emissions, light, construction, footprint, workers and outputs
  are fixed declared values.
- "Per hour" demand rates (electricity, water, emissions, operational materials) count operating
  hours; a fixed operating cost per hour counts calendar hours (the building costs money while idle).
- ``operating_prices`` multiplies unit prices (electricity, water, operational materials); never
  construction cost or the fixed/total operating amount.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.api_base import ParamValue
from app.building_models import (
    DAYS_PER_PERIOD,
    MAX_PERIOD_DAYS,
    BuildingResult,
    BuildingStats,
    CostBreakdown,
    EmissionTotal,
    MaterialTotal,
    PriceSource,
    Quantity,
    StressControls,
)
from app.building_templates import NUMERIC_PARAMS, SELECT_PARAMS

KWH, KW, M3, KG, HOURS = "kWh", "kW", "m³", "kg", "h"
STC_IRRADIANCE_KW_PER_M2 = 1.0  # standard test conditions: kWp is defined at 1 kW/m²


class CalcInputError(ValueError):
    """Input that cannot be stored or calculated (e.g. out-of-range parameter)."""


@dataclass(frozen=True)
class LocationContext:
    """Location-dependent inputs for one exact location / H3 cell."""

    h3_id: str
    solar_ghi: float | None  # kWh/m²/day, NASA POWER all-sky annual-mean climatology at the cell
    solar_source: str = ""


# --- helpers ----------------------------------------------------------------------------------


def fmt_num(v: float | None) -> str:
    """Readable number for explanations: ``1,000,000``, ``0.25``, ``365.25``, ``0.04167``.

    Thousands separators, at most 4 decimal places (4 significant digits below 1), trailing zeros
    dropped, no scientific notation except for extreme magnitudes. ``None`` reads as "unknown".
    """
    if v is None:
        return "unknown"
    try:
        v = float(v)
    except OverflowError:
        return "out of range"
    if not math.isfinite(v):
        return str(v)
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1e15 or a < 1e-6:
        return f"{v:.4g}"
    decimals = 4 if a >= 1 else 3 - math.floor(math.log10(a))
    text = f"{v:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "0") else text


def q(value: float | None, unit: str, basis: str = "", missing: list[str] | None = None) -> Quantity:
    missing = list(missing or [])
    if value is not None:
        try:
            value = float(value)
        except OverflowError:  # an int too large for a float
            value = math.inf
        if not math.isfinite(value):
            return Quantity(value=None, unit=unit, basis=basis, missing=missing + ["result out of numeric range"])
        if value == 0:
            value = 0.0  # no negative zero
    return Quantity(value=value, unit=unit, basis=basis, missing=missing)


def known(x: Quantity) -> bool:
    return x.value is not None


def is_unknown(x: Quantity) -> bool:
    """Unknown = no value *and* something is missing (vs. not applicable: no value, nothing missing)."""
    return x.value is None and bool(x.missing)


def _mult_note(m: float, what: str) -> str:
    return "" if m == 1 else f" × {what} multiplier {fmt_num(m)}"


def param_number(btype: str, parameters: dict[str, ParamValue], key: str) -> tuple[float | None, str | None]:
    """(value, problem). Absent = (None, None). Invalid values are reported, never coerced."""
    if key not in parameters or parameters[key] is None or parameters[key] == "":
        return None, None
    v = parameters[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, f"{key} must be a number"
    try:
        v = float(v)
    except OverflowError:  # an int too large for a float: a clear 422, not a 500
        return None, f"{key} is out of range"
    if not math.isfinite(v):
        return None, f"{key} must be finite"
    lo, hi = NUMERIC_PARAMS.get(btype, {}).get(key, (None, None))
    if lo is not None and v < lo:
        return None, f"{key} must be at least {fmt_num(lo)}"
    if hi is not None and v > hi:
        return None, f"{key} must be at most {fmt_num(hi)}"
    return v, None


def validate_parameters(btype: str, parameters: dict[str, ParamValue]) -> None:
    """Reject invalid known parameters before saving. Unknown extra keys are preserved as-is."""
    problems = []
    for key in NUMERIC_PARAMS.get(btype, {}):
        _, err = param_number(btype, parameters, key)
        if err:
            problems.append(err)
    for key, options in SELECT_PARAMS.get(btype, {}).items():
        v = parameters.get(key)
        if v not in (None, "") and v not in options:
            problems.append(f"{key} must be one of {', '.join(options)}")
    for key, v in parameters.items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"{key} must be finite")
    if problems:
        raise CalcInputError("; ".join(sorted(set(problems))))


# --- electricity / water ----------------------------------------------------------------------


@dataclass
class _Derived:
    """Data-centre intermediates. IT energy does not need PUE, so each keeps its own missing list."""

    it_kwh: float | None = None
    facility_kwh: float | None = None
    it_missing: tuple[str, ...] = ()
    facility_missing: tuple[str, ...] = ()


def _electricity(btype, stats: BuildingStats, params, hours: float | None, d: float):
    """(energy kWh, peak kW, derived intermediates)."""
    pw = stats.power
    if stats.demand_basis == "derived":
        if btype != "data_centre":
            msg = "derived demand basis is only defined for data centres (choose direct)"
            return (q(None, KWH, "derived basis", [msg]), q(None, KW, "derived basis", [msg]),
                    _Derived(it_missing=(msg,), facility_missing=(msg,)))
        vals, errs = {}, {}
        for key in ("itPowerKw", "loadFraction", "pue"):
            vals[key], err = param_number(btype, params, key)
            errs[key] = err or key
        base = "derived: IT power × load fraction × operating hours × PUE" + _mult_note(d, "operating-demand")
        if pw.peak_demand_kw is not None:
            peak = q(pw.peak_demand_kw * d, KW, "declared peak demand" + _mult_note(d, "operating-demand"))
        elif vals["itPowerKw"] is not None and vals["pue"] is not None:
            peak = q(vals["itPowerKw"] * vals["pue"] * d, KW,
                     "derived: IT power × PUE (peak not declared)" + _mult_note(d, "operating-demand"))
        else:
            peak = q(None, KW, "derived: IT power × PUE", [k for k in ("itPowerKw", "pue") if vals[k] is None])
        it_missing = [errs[k] for k in ("itPowerKw", "loadFraction") if vals[k] is None]
        if hours is None:
            it_missing.append("operating hours per day")
        facility_missing = it_missing + ([errs["pue"]] if vals["pue"] is None else [])
        it_kwh = None if it_missing else vals["itPowerKw"] * vals["loadFraction"] * hours * d
        facility = None if facility_missing else it_kwh * vals["pue"]
        derived = _Derived(it_kwh, facility, tuple(it_missing), tuple(facility_missing))
        return q(facility, KWH, base, facility_missing), peak, derived

    basis = "average demand × operating hours" + _mult_note(d, "operating-demand")
    missing = []
    if pw.average_demand_kw is None:
        missing.append("average electricity demand (kW)")
    if hours is None:
        missing.append("operating hours per day")
    energy = q(None if missing else pw.average_demand_kw * hours * d, KWH, basis, missing)
    if pw.peak_demand_kw is not None:
        peak = q(pw.peak_demand_kw * d, KW, "declared peak demand" + _mult_note(d, "operating-demand"))
    else:
        peak = q(None, KW, "declared peak demand", ["peak demand (kW)"])
    return energy, peak, _Derived()


def _water_demand(btype, stats: BuildingStats, params, hours: float | None, d: float, derived: _Derived) -> Quantity:
    if stats.demand_basis == "derived" and btype == "data_centre":
        wue, err = param_number(btype, params, "wueLPerKwh")
        wue_basis = params.get("wueBasis")
        # Only the inputs of the selected energy basis matter (IT energy does not need PUE).
        missing = list(derived.facility_missing if wue_basis == "facility_energy" else derived.it_missing)
        if wue is None:
            missing.append(err or "wueLPerKwh")
        if wue_basis not in ("it_energy", "facility_energy"):
            missing.append("wueBasis (it_energy or facility_energy)")
        label = "IT" if wue_basis == "it_energy" else "facility"
        basis = f"derived: WUE (L/kWh) × {label} energy ÷ 1000 L/m³" + _mult_note(d, "operating-demand")
        if missing:
            return q(None, M3, basis, sorted(set(missing)))
        energy = derived.it_kwh if wue_basis == "it_energy" else derived.facility_kwh
        return q(wue * energy / 1000.0, M3, basis)
    if stats.demand_basis == "derived":
        return q(None, M3, "derived basis", ["derived demand basis is only defined for data centres (choose direct)"])

    missing = []
    if stats.water.input_m3_per_hour is None:
        missing.append("water input (m³/hour)")
    if hours is None:
        missing.append("operating hours per day")
    basis = "water input rate × operating hours" + _mult_note(d, "operating-demand")
    return q(None if missing else stats.water.input_m3_per_hour * hours * d, M3, basis, missing)


def _power_output(btype, stats: BuildingStats, params, hours, period_days, location: LocationContext | None):
    """(gross kWh, producer?)."""
    pw = stats.power
    if pw.average_output_kw is not None:
        missing = [] if hours is not None else ["operating hours per day"]
        return q(None if missing else pw.average_output_kw * hours, KWH,
                 "declared average output × operating hours", missing), True
    if pw.rated_output_kw is not None:
        missing = []
        if pw.capacity_factor is None:
            missing.append("capacity factor (rated output alone does not give energy)")
        if hours is None:
            missing.append("operating hours per day")
        value = None if missing else pw.rated_output_kw * pw.capacity_factor * hours
        return q(value, KWH, "rated output × capacity factor × operating hours", missing), True
    if btype == "solar":
        kwp, err1 = param_number(btype, params, "capacityKwp")
        pr, err2 = param_number(btype, params, "performanceRatio")
        basis = (f"PV model: peak capacity (kWp) × daily irradiation (kWh/m²/day) ÷ "
                 f"{fmt_num(STC_IRRADIANCE_KW_PER_M2)} kW/m² (STC) × performance ratio × "
                 f"{fmt_num(period_days)} days; "
                 "kWp is not treated as constant output")
        missing = []
        if kwp is None:
            missing.append(err1 or "capacityKwp (or an output assumption)")
        if pr is None:
            missing.append(err2 or "performanceRatio")
        if location is None:
            missing.append("exact location (for NASA POWER irradiation)")
        elif location.solar_ghi is None:
            missing.append(f"solar irradiation at cell {location.h3_id} (no data)")
        else:
            basis += f"; irradiation {fmt_num(location.solar_ghi)} kWh/m²/day from {location.solar_source}"
        if missing:
            return q(None, KWH, basis, missing), True
        return q(kwp * location.solar_ghi / STC_IRRADIANCE_KW_PER_M2 * pr * period_days, KWH, basis), True
    if btype == "power_station":
        return q(None, KWH, "power station output", ["average output (kW), or rated output and capacity factor"]), True
    return q(None, KWH, "no electricity output declared"), False


def _water_output(btype, stats: BuildingStats, hours):
    w = stats.water
    if w.output_m3_per_hour is not None:
        missing = [] if hours is not None else ["operating hours per day"]
        basis = "declared usable output rate × operating hours" + (f" ({w.basis})" if w.basis else "")
        return q(None if missing else w.output_m3_per_hour * hours, M3, basis, missing), True
    if btype == "water_plant":
        return q(None, M3, "water plant output", ["usable water output (m³/hour)"]), True
    return q(None, M3, "no water output declared"), False


def _net(output: Quantity, demand: Quantity, producer: bool, unit: str, what: str) -> Quantity:
    if not producer:
        return q(None, unit, f"not a {what} producer")
    basis = f"gross output − own {what} demand (own use counted once)"
    missing = output.missing + demand.missing
    if output.value is None or demand.value is None:
        return q(None, unit, basis, missing or ["output or own demand"])
    return q(output.value - demand.value, unit, basis)


# --- materials / emissions / costs ------------------------------------------------------------


def _materials(stats: BuildingStats, period_days: float, hours: float | None, d: float) -> list[MaterialTotal]:
    """Operational 'per hour' rates use operating hours (like electricity, water and emissions);
    day/month/year rates are prorated over calendar days."""
    demand_note = _mult_note(d, "operating-demand")
    out = []
    for m in stats.materials:
        if m.phase == "construction":
            qty = q(m.quantity_kg, KG, "construction quantity, counted once per building",
                    [] if m.quantity_kg is not None else [f"quantity of {m.name}"])
        else:
            if m.quantity_kg is None:
                qty = q(None, KG, "operational rate × period", [f"quantity of {m.name}"])
            elif m.period == "hour":
                basis = f"{fmt_num(m.quantity_kg)} kg per operating hour × operating hours" + demand_note
                if hours is None:
                    qty = q(None, KG, basis, ["operating hours per day"])
                else:
                    qty = q(m.quantity_kg * hours * d, KG,
                            f"{fmt_num(m.quantity_kg)} kg per operating hour × {fmt_num(hours)} operating hours"
                            + demand_note)
            else:
                per = DAYS_PER_PERIOD[m.period]
                qty = q(m.quantity_kg * period_days / per * d, KG,
                        f"{fmt_num(m.quantity_kg)} kg per {m.period} × {fmt_num(period_days)} days "
                        f"÷ {fmt_num(per)} days/{m.period}" + demand_note)
        out.append(MaterialTotal(name=m.name, phase=m.phase, quantity=qty))
    return out


def _emissions(stats: BuildingStats, hours: float | None) -> list[EmissionTotal]:
    out = []
    for e in stats.emissions:
        missing = []
        if e.rate_kg_per_hour is None:
            missing.append(f"{e.pollutant} emission rate (kg/hour)")
        if hours is None:
            missing.append("operating hours per day")
        value = None if missing else e.rate_kg_per_hour * hours
        out.append(EmissionTotal(pollutant=e.pollutant, quantity=q(
            value, KG, "emission rate × operating hours (fixed: not changed by demand stress)", missing)))
    return out


def price_source_label(src: PriceSource, price_unit: str) -> str:
    """One line naming a location-default price, its currency and where it came from."""
    area = src.price_area_name or src.price_area or f"cell {src.h3_id}"
    text = (f"location default: {src.currency} {fmt_num(src.value)}/{price_unit}, average {src.customer} price "
            f"for {area}")
    if src.source:
        text += f" [{src.source}]"
    if src.basis:
        text += f"; basis: {src.basis}"
    return text


def _resource_cost(qty: Quantity, price: float | None, unit: str, name: str, price_unit: str, p: float,
                   source: PriceSource | None = None) -> Quantity:
    basis = f"{name} × unit price per {price_unit}" + _mult_note(p, "operating-price")
    if source is not None and price is not None:
        basis += f" ({price_source_label(source, price_unit)})"
    if qty.value is None:
        if not qty.missing:
            return q(None, unit, f"no {name} declared")
        return q(None, unit, basis, [f"{name} quantity"])
    if qty.value == 0:
        return q(0.0, unit, f"no {name} consumed")
    if price is None:
        return q(None, unit, basis, [f"{name} price per {price_unit}"])
    return q(qty.value * price * p, unit, basis)


def _sum_known(parts: list[Quantity], unit: str, basis: str) -> Quantity:
    vals = [x.value for x in parts if x.value is not None]
    missing = [m for x in parts for m in x.missing]
    return q(sum(vals) if vals else None, unit, basis, missing)


def _costs(stats: BuildingStats, period_days, electricity: Quantity, water: Quantity,
           materials: list[MaterialTotal], p: float) -> CostBreakdown:
    c = stats.costs
    unit = c.currency or "unspecified currency"
    price_basis = f" ({c.price_basis})" if c.price_basis else ""
    construction = q(c.construction_total, unit, "one-time construction total, counted once per building; "
                     "construction material quantities are not costed separately" + price_basis,
                     [] if c.construction_total is not None else ["construction cost"])
    op = c.operating
    per = DAYS_PER_PERIOD[op.period]
    label = "all-inclusive operating cost" if op.kind == "total" else "fixed operating cost"
    if op.amount is None:
        fixed = q(None, unit, label, [label])
    else:
        if op.period == "hour":  # a running cost of the building: every calendar hour, not operating hours
            how = f"{fmt_num(op.amount)} per calendar hour × 24 h/day × {fmt_num(period_days)} days"
        else:
            how = (f"{fmt_num(op.amount)} per {op.period} × {fmt_num(period_days)} days "
                   f"÷ {fmt_num(per)} days/{op.period}")
        fixed = q(op.amount * period_days / per, unit, f"{label} {how} (prorated; not changed by price stress)")

    if op.kind == "total":
        included = "included in the all-inclusive operating total; not added again"
        elec_cost = q(None, unit, included)
        water_cost = q(None, unit, included)
        mat_cost = q(None, unit, included)
        total = q(fixed.value, unit, "all-inclusive operating total (resource costs not added on top)", fixed.missing)
    else:
        elec_cost = _resource_cost(electricity, c.electricity_price_per_kwh, unit, "electricity", "kWh", p,
                                   c.electricity_price_source)
        water_cost = _resource_cost(water, c.water_price_per_m3, unit, "water", "m³", p, c.water_price_source)
        op_items = [(stats.materials[i], t) for i, t in enumerate(materials) if t.phase == "operation"]
        if not op_items:
            mat_cost = q(None, unit, "no operational materials declared")
        else:
            mat_cost = _sum_known(
                [_resource_cost(t.quantity, m.unit_price_per_kg, unit, m.name, "kg", p) for m, t in op_items],
                unit, "operational materials × unit price per kg" + _mult_note(p, "operating-price"))
        total = _sum_known([fixed, elec_cost, water_cost, mat_cost], unit,
                           "known operating components: fixed + electricity + water + operational materials")
        if total.missing:
            total.basis += " (partial: some components unknown)"

    missing = construction.missing + total.missing
    if c.currency is None and any(x.value for x in (construction, total)):
        missing.append("currency")
    return CostBreakdown(
        currency=c.currency,
        construction=construction,
        operating_fixed=fixed,
        electricity=elec_cost,
        water=water_cost,
        materials=mat_cost,
        operating_known_total=total,
        missing=list(dict.fromkeys(missing)),
        operating_cost_kind=op.kind,
        electricity_price_source=c.electricity_price_source if op.kind == "fixed" else None,
        water_price_source=c.water_price_source if op.kind == "fixed" else None,
    )


# --- entry point ------------------------------------------------------------------------------


def calculate(
    btype: str,
    stats: BuildingStats,
    parameters: dict[str, ParamValue] | None,
    period_days: float,
    stress: StressControls | None = None,
    location: LocationContext | None = None,
) -> BuildingResult:
    if not (math.isfinite(period_days) and 0 < period_days <= MAX_PERIOD_DAYS):
        raise CalcInputError(f"period must be between 0 and {MAX_PERIOD_DAYS} days")
    params = parameters or {}
    stress = stress or StressControls()
    d, p = stress.operating_demand, stress.operating_prices

    hpd = stats.operating_hours_per_day
    hours_v = None if hpd is None else hpd * period_days
    hours = q(hours_v, HOURS, f"{fmt_num(hpd)} h/day × {fmt_num(period_days)} days" if hpd is not None else "operating hours",
              [] if hpd is not None else ["operating hours per day"])

    electricity, peak, derived = _electricity(btype, stats, params, hours_v, d)
    water = _water_demand(btype, stats, params, hours_v, d, derived)
    e_out, power_producer = _power_output(btype, stats, params, hours_v, period_days, location)
    w_out, water_producer = _water_output(btype, stats, hours_v)
    materials = _materials(stats, period_days, hours_v, d)

    light = stats.light
    w = stats.workers
    return BuildingResult(
        period_days=period_days,
        operating_hours=hours,
        electricity_demand=electricity,
        peak_demand=peak,
        electricity_output=e_out,
        electricity_net=_net(e_out, electricity, power_producer, KWH, "electricity"),
        water_demand=water,
        water_output=w_out,
        water_net=_net(w_out, water, water_producer, M3, "water"),
        materials=materials,
        emissions=_emissions(stats, hours_v),
        light=q(light.upward_lumens, "lm", "declared upward luminous flux (proxy; fixed, not sky brightness)",
                [] if light.upward_lumens is not None else ["upward lumens"]),
        light_hours=q(None if light.hours_per_day is None else light.hours_per_day * period_days, HOURS,
                      "lit hours per day × period days", [] if light.hours_per_day is not None else ["lighting hours per day"]),
        worker_capacity=q(w.capacity, "people", "declared maximum workers at one time (fixed)",
                          [] if w.capacity is not None else ["worker capacity"]),
        staffing_required=q(w.staffing_required, "people", "declared staffing requirement",
                            [] if w.staffing_required is not None else ["staffing requirement"]),
        footprint=q(stats.footprint_m2, "m²", "declared occupied ground area (fixed)",
                    [] if stats.footprint_m2 is not None else ["footprint (m²)"]),
        costs=_costs(stats, period_days, electricity, water, materials, p),
        demand_basis=stats.demand_basis,
    )


def average_kw(result: BuildingResult) -> float | None:
    """Average electricity demand while operating (kWh / operating hours)."""
    e, h = result.electricity_demand.value, result.operating_hours.value
    if e is None or h is None or h <= 0:
        return None
    return e / h
