"""Supporting buildings that could cover a site's shortfall.

Some shortfalls can be fixed by building something else alongside, because placed buildings feed
the same hexagons (site_capacity.shared):

- not enough grid power   → a power station in the same or a neighbouring hexagon (its output is
                            added to the local grid);
- not enough water        → a water plant within the water reach whose intake is not fresh water
                            (seawater on the coast, treated wastewater inland): all of its output is
                            added to the local supply;
- surplus power           → a data centre in the same or a neighbouring hexagon (it uses the output
                            locally). Surplus is an opportunity, never a reason a plant fails.

Land, workforce, air quality and dark sky cannot be supplied by another building: move instead.

Suggestions name real presets big enough to cover the shortfall (or how many it would take) and a
generic building of exactly the right size, scaled from a reference preset (output, footprint,
intake and electricity per unit of output). Scaling is linear and labelled as such.
"""

from __future__ import annotations

import math

from app.building_models import (
    BuildingPreset,
    BuildingStats,
    CheckResult,
    SuggestedPreset,
    SupportSuggestion,
)
from app.building_presets import load_presets
from app.building_templates import POWER_PRODUCERS, WATER_PRODUCERS
from app.site_capacity import RING_GRID, RING_KM, RING_RUNOFF, fmt_kw, fmt_num

# Storage shifts electricity in time; it does not add supply, so it is never suggested as a generator.
GENERATORS = POWER_PRODUCERS - {"battery_storage"}
HEADROOM = 1.1  # size the generic building 10 % above the shortfall (below site_capacity.RESERVE_SHARE)


def _power_out(p: BuildingPreset) -> float | None:
    return p.stats.power.rated_output_kw or p.stats.power.average_output_kw


def _power_in(p: BuildingPreset) -> float | None:
    return p.stats.power.peak_demand_kw or p.stats.power.average_demand_kw


def _water_out(p: BuildingPreset) -> float | None:
    out = p.stats.water.output_m3_per_hour
    return None if not out else out * (p.stats.operating_hours_per_day or 24.0)


def _pick(presets: list[tuple[BuildingPreset, float]], need: float, unit: str) -> list[SuggestedPreset]:
    """Smallest presets that cover the need on their own; else the largest, with how many it takes."""
    enough = sorted([(p, c) for p, c in presets if c >= need], key=lambda x: x[1])[:2]
    if not enough and presets:
        p, c = max(presets, key=lambda x: x[1])
        return [SuggestedPreset(id=p.id, name=p.name, capacity=c, unit=unit, count=math.ceil(need / c))]
    return [SuggestedPreset(id=p.id, name=p.name, capacity=c, unit=unit) for p, c in enough]


def _scaled_footprint(ref: BuildingPreset | None, ref_cap: float | None, cap: float) -> float | None:
    if ref is None or not ref_cap or not ref.stats.footprint_m2:
        return None
    return round(ref.stats.footprint_m2 * cap / ref_cap, -1) or 10.0


def _power_suggestion(short_kw: float, extra_kw: float = 0.0) -> SupportSuggestion:
    """`extra_kw`: electricity of other suggested supporting buildings (e.g. a water plant)."""
    gens = [(p, c) for p in load_presets() if p.type in GENERATORS and (c := _power_out(p))]
    short_kw += extra_kw
    size = math.ceil(short_kw * HEADROOM / 100) * 100  # 0.1 MW steps
    # Gas combined cycle is the reference for a dispatchable plant of any size.
    ref = next((p for p in load_presets() if p.id == "mesquite-generating-station-az"), gens[0][0] if gens else None)
    fp = _scaled_footprint(ref, _power_out(ref) if ref else None, size)
    stats = BuildingStats.model_validate({
        "footprintM2": fp, "operatingHoursPerDay": 24,
        "power": {"ratedOutputKw": size, "averageDemandKw": 0,
                  "technology": "Generic plant sized to cover the shortfall"},
    })
    return SupportSuggestion(
        resource="power", shortfall=short_kw, unit="kW", building_type="power_station",
        reach_km=RING_GRID * RING_KM, rings=RING_GRID,
        title=f"Add a power station of at least {fmt_kw(short_kw)} next to it",
        explanation=(f"The local grid is {fmt_kw(short_kw)} short"
                     + (f" (including {fmt_kw(extra_kw)} for the suggested water plant)" if extra_kw else "")
                     + ". A power station placed in the same or a "
                     f"neighbouring hexagon (within ~{RING_KM:.0f} km) adds its output to this hexagon's grid "
                     "capacity. Its own site needs land and, for thermal plants, cooling water."),
        presets=_pick(gens, short_kw, "kW"),
        generic_name=f"Supporting power station ({fmt_kw(size)})",
        generic_stats=stats,
    )


def _water_suggestion(short_m3: float, coastal: bool) -> SupportSuggestion:
    plants = [(p, c) for p in load_presets() if p.type in WATER_PRODUCERS and (c := _water_out(p))
              and (coastal or p.stats.water.source != "seawater")]
    size = math.ceil(short_m3 * HEADROOM / 100) * 100
    ref = next((p for p in load_presets() if p.type == "water_plant"), None)
    ref_out = _water_out(ref) if ref else None
    source = "seawater" if coastal else "wastewater"
    # Seawater RO recovers ~50 % (the reference preset); effluent reuse with MF/RO ~80 %.
    recovery = 0.5 if coastal else 0.8
    kwh_per_m3 = 3.5 if coastal else 1.0  # SWRO vs advanced effluent treatment, indicative
    stats = BuildingStats.model_validate({
        "footprintM2": _scaled_footprint(ref, ref_out, size), "operatingHoursPerDay": 24,
        "water": {"inputM3PerHour": round(size / recovery / 24, 1), "outputM3PerHour": round(size / 24, 1),
                  "source": source,
                  "basis": "Seawater reverse osmosis" if coastal else "Treated municipal wastewater reuse"},
        "power": {"averageDemandKw": round(size * kwh_per_m3 / 24, 0)},
    })
    what = ("a desalination plant (seawater intake)" if coastal else
            "a wastewater-reuse plant (treated municipal effluent intake)")
    return SupportSuggestion(
        resource="water", shortfall=short_m3, unit="m³/day", building_type="water_plant",
        reach_km=RING_RUNOFF * RING_KM, rings=RING_RUNOFF,
        title=f"Add a water plant of at least {fmt_num(short_m3)} m³/day nearby",
        explanation=(f"Fresh water is {fmt_num(short_m3)} m³/day short. Build {what} within ~"
                     f"{RING_RUNOFF * RING_KM:.0f} km: its whole output is added to this site's supply because its "
                     "intake is not river water. Its own intake, land and electricity are checked where you place it."),
        presets=_pick(plants, short_m3, "m³/day"),
        generic_name=f"Supporting {'desalination' if coastal else 'water-reuse'} plant ({fmt_num(size)} m³/day)",
        generic_stats=stats,
    )


def _export_suggestion(surplus_kw: float) -> SupportSuggestion:
    centres = [(p, c) for p in load_presets() if p.type == "data_centre" and (c := _power_in(p))]
    size = max(1000, math.floor(surplus_kw / 1000) * 1000)  # whole MW, never more than the surplus
    return SupportSuggestion(
        resource="grid_export", shortfall=surplus_kw, unit="kW", building_type="data_centre",
        reach_km=RING_GRID * RING_KM, rings=RING_GRID,
        title=f"Use the {fmt_kw(surplus_kw)} surplus: add a data centre next to it",
        explanation=(f"The grid here can't take {fmt_kw(surplus_kw)} of its output. A data centre in the same or a "
                     f"neighbouring hexagon (within ~{RING_KM:.0f} km) uses that electricity directly, so it needs no "
                     "export room."),
        presets=_pick(centres, surplus_kw, "kW"),
        generic_name=f"Data centre using the surplus ({fmt_kw(size)})",
        generic_stats=BuildingStats.model_validate({
            "operatingHoursPerDay": 24, "power": {"averageDemandKw": size, "peakDemandKw": size}}),
    )


def suggestions(checks: list[CheckResult], coastal: bool) -> list[SupportSuggestion]:
    """Supporting buildings for each failing check that another building can fix."""
    shorts = {}
    for c in checks:
        if c.status == "fail" and c.actual is not None and c.required_value is not None and c.actual > c.required_value:
            shorts[(c.kind, c.label.startswith("Fresh water"))] = c.actual - c.required_value
    out = []
    water = shorts.get(("site_water", True))
    if water:
        out.append(_water_suggestion(water, coastal))
    power = shorts.get(("site_power", False))
    if power:
        # The suggested water plant needs electricity too: cover it with the same power station.
        extra = (out[0].generic_stats.power.average_demand_kw or 0.0) if out else 0.0
        out.insert(0, _power_suggestion(power, extra))
    export = shorts.get(("site_grid_export", False))
    if export:
        out.append(_export_suggestion(export))
    return out
