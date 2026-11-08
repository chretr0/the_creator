"""Placement assessment and scenario evaluation (CLAUDE.Building-System.md sections 7, 8 and 10).

Every criterion becomes one inspectable check per location: ``pass``, ``fail`` or ``unknown`` with
the actual and required values, units, period, source and an explanation. Checks are computed as
numpy status vectors over resolution-6 cells, so the same code path serves a bounded area (screening)
and an exact location (one cell). Pure functions over plain inputs: the routers load the scenario.

Supply accounting (site checks and pooled budgets):
- Site assumptions belong to one exact location and are never applied to candidate cells.
- A pooled ``ResourceBudget`` is shared by every building inside its scope and counted once. The
  remaining supply for a building is ``max(0, supply - demand of the other buildings in scope)``;
  the building being checked (and ``exclude_project_id``) is never counted twice.
- A plant's output joins a pool only via ``contributing_project_ids``; it then contributes its *net*
  output (gross minus own use) and is not also counted as pool demand.
- Supply multipliers (water/power availability) scale declared external supply and site allocations.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

import h3
import numpy as np

from app import building_prices, features, h3store, layers, site_capacity, site_support
from app.pollutants import pollutant_id, release_medium
from app.api_base import ParamValue
from app.building_calc import LocationContext, average_kw, calculate, fmt_num, is_unknown, q
from app.building_models import (
    MODEL_VERSION,
    SCHEMA_VERSION,
    AreaAssessment,
    Assessment,
    AssessmentState,
    BudgetResult,
    BuildingEvaluation,
    BuildingResult,
    BuildingStats,
    Candidate,
    CellState,
    CheckResult,
    Criterion,
    DefinitionSnapshot,
    EmissionTotal,
    LocationAssessment,
    MaterialTotal,
    Quantity,
    ResourceBudget,
    ScenarioAssumptions,
    ScenarioResult,
    ScenarioTotals,
    SiteAssumptions,
    StressControls,
)

PASS, FAIL, UNKNOWN = 0, 1, 2
_STATUS = ("pass", "fail", "unknown")
STATE_RANK: dict[str, int] = {"meets_criteria": 0, "insufficient_data": 1, "fails_criteria": 2}
_STATES: tuple[AssessmentState, ...] = ("meets_criteria", "insufficient_data", "fails_criteria")

MAX_AREA_CELLS = 30_000
EARTH_RADIUS_KM = 6371.0088
RES6_AVG_AREA_KM2 = h3.average_hexagon_area(6, unit="km^2")
GHI_LAYER, GHI_SLICE = "solar_ghi", "clim-ann"
NO_CURRENCY = "unspecified currency"

SCREENING_NOTE = (
    "Each resolution-6 H3 cell (about 36 km²) is checked against what it and its neighbouring cells can "
    "provide: open land, fresh water, grid power and workforce, estimated from prepared data, minus what "
    "buildings already in the scenario use nearby. A cell's state is a screening result, not proof that "
    "every parcel in it is suitable, and says nothing about permission, ownership or a utility connection. "
    "Pick a cell to see the exact location's breakdown before placing."
)


class AreaTooLarge(ValueError):
    pass


@dataclass
class PlacedBuilding:
    id: UUID
    name: str
    type: str
    latitude: float
    longitude: float
    h3_id: str
    snapshot: DefinitionSnapshot
    parameters: dict[str, ParamValue]
    site: SiteAssumptions


@dataclass
class ScenarioContext:
    assumptions: ScenarioAssumptions = field(default_factory=ScenarioAssumptions)
    buildings: list[PlacedBuilding] = field(default_factory=list)

    @property
    def period_days(self) -> float:
        return self.assumptions.period_days


def _layer_num(v: float | None) -> str:
    """Layer values to 6 significant figures (the precision they are compared at and the inspector
    shows), with thousands separators and no scientific notation for ordinary magnitudes."""
    if v is None or v == 0 or not math.isfinite(v) or not 1e-6 <= abs(v) < 1e15:
        return fmt_num(v)
    decimals = max(0, 5 - math.floor(math.log10(abs(v))))
    text = f"{v:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


# --- location context (solar irradiation) -----------------------------------------------------


def _ghi_source() -> tuple[h3store.Source | None, str]:
    layer = layers.BY_ID[GHI_LAYER]
    s = layer.slice(GHI_SLICE)
    period = (layers.layer_meta(layer).get("period") or "").split(";")[0].strip()
    label = f"NASA POWER {layer.name}, {s.label}" + (f" {period}" if period else "") + " [CTX-02], res-6 cell value"
    return layers.source_for(layer, s), label


def location_context(h3_id: str) -> LocationContext:
    src, label = _ghi_source()
    ghi = None
    if src is not None:
        v = float(h3store.lookup(src, h3store.SIM_RES, np.array([int(h3_id, 16)], dtype=np.uint64))[0])
        ghi = float(f"{v:.6g}") if math.isfinite(v) else None
    return LocationContext(h3_id=h3_id, solar_ghi=ghi, solar_source=label)


def building_results(ctx: ScenarioContext, stress: StressControls | None,
                     locs: dict[UUID, LocationContext] | None = None) -> dict[UUID, BuildingResult]:
    locs = locs if locs is not None else {b.id: location_context(b.h3_id) for b in ctx.buildings}
    return {
        b.id: calculate(b.type, b.snapshot.stats, b.parameters, ctx.period_days, stress, locs[b.id])
        for b in ctx.buildings
    }


# --- budget scopes and pools ------------------------------------------------------------------


def _scope_mask(scope, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    if scope.kind == "scenario":
        return np.ones(lats.shape, dtype=bool)
    if scope.kind == "region":
        w, s, e, n = layers.REGION_BOXES[scope.region]
        return (lons >= w) & (lons <= e) & (lats >= s) & (lats <= n)
    la1, lo1 = np.radians(scope.latitude), np.radians(scope.longitude)
    la2, lo2 = np.radians(lats), np.radians(lons)
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.minimum(a, 1.0))) <= scope.radius_km


def _scope_label(scope) -> str:
    if scope.kind == "scenario":
        return "whole scenario"
    if scope.kind == "region":
        return f"prepared region {scope.region}"
    return f"{fmt_num(scope.radius_km)} km around {fmt_num(scope.latitude)}, {fmt_num(scope.longitude)}"


BUDGET_UNITS = {"power_capacity_kw": "kW", "energy_kwh_per_day": "kWh", "water_m3_per_day": "m³"}


def _availability(kind: str, stress: StressControls) -> tuple[float, str]:
    if kind == "water_m3_per_day":
        return stress.water_availability, "water availability"
    return stress.power_availability, "power availability"


def building_demand(kind: str, result: BuildingResult) -> Quantity:
    """A building's demand on a budget of this kind (kW capacity, kWh or m³ over the period)."""
    if kind == "power_capacity_kw":
        if result.peak_demand.value is not None:
            return result.peak_demand
        avg = average_kw(result)
        if avg is not None:
            return q(avg, "kW", "average demand while operating (peak demand not declared)")
        return q(None, "kW", "peak or average demand", result.peak_demand.missing + result.electricity_demand.missing)
    return result.electricity_demand if kind == "energy_kwh_per_day" else result.water_demand


def building_contribution(kind: str, result: BuildingResult, period_days: float) -> Quantity:
    """Net output a declared contributing plant adds to a pool."""
    if kind == "power_capacity_kw":
        net = result.electricity_net
        if net.value is None:
            return q(None, "kW", "net output averaged over the period", net.missing or ["net electricity output"])
        return q(net.value / (period_days * 24), "kW", "net electricity output averaged over all hours of the period")
    net = result.electricity_net if kind == "energy_kwh_per_day" else result.water_net
    if net.value is None:
        return q(None, net.unit, net.basis, net.missing or ["net output"])
    return net


@dataclass
class PoolState:
    budget: ResourceBudget
    unit: str
    supply: Quantity
    demand_by: dict[UUID, Quantity]  # in-scope buildings that are not contributors
    names: dict[UUID, str]
    contributors: set[UUID]
    in_scope: list[UUID]

    def remaining(self, exclude: set[UUID]) -> Quantity:
        """Supply left for one more building after every *other* in-scope building's demand."""
        label = f"{self.budget.label} ({_scope_label(self.budget.scope)})"
        if self.supply.value is None:
            return q(None, self.unit, f"{label}: supply unknown", self.supply.missing or ["pool supply"])
        others = {i: d for i, d in self.demand_by.items() if i not in exclude}
        unknown = [self.names[i] for i, d in others.items() if d.value is None]
        if unknown:
            return q(None, self.unit, f"{label}: other buildings' demand unknown",
                     [f"demand of {n}" for n in unknown])
        used = sum(d.value for d in others.values())
        return q(max(0.0, self.supply.value - used), self.unit,
                 f"{label}: supply {fmt_num(self.supply.value)} − demand of {len(others)} other building(s) "
                 f"{fmt_num(used)} (never below 0)")


def pool_state(budget: ResourceBudget, ctx: ScenarioContext, results: dict[UUID, BuildingResult],
               stress: StressControls) -> PoolState:
    kind, period = budget.kind, ctx.period_days
    unit = BUDGET_UNITS[kind]
    mult, mult_name = _availability(kind, stress)
    per_day = kind != "power_capacity_kw"
    by_id = {b.id: b for b in ctx.buildings}

    parts: list[Quantity] = []
    if budget.amount is None:
        parts.append(q(None, unit, "declared external supply", [f"declared amount of {budget.label}"]))
    else:
        amount = budget.amount * (period if per_day else 1.0) * mult
        basis = f"declared {fmt_num(budget.amount)} {unit}{'/day × ' + fmt_num(period) + ' days' if per_day else ''}"
        parts.append(q(amount, unit, basis + ("" if mult == 1 else f" × {mult_name} {fmt_num(mult)}")))
    contributors = {i for i in budget.contributing_project_ids if i in by_id}
    gone = len(set(budget.contributing_project_ids) - contributors)
    for i in sorted(contributors, key=str):
        c = building_contribution(kind, results[i], period)
        parts.append(q(c.value, unit, f"net output of {by_id[i].name}", c.missing))

    if any(x.value is None for x in parts):
        supply = q(None, unit, "external supply + contributions", [m for x in parts for m in x.missing])
    else:
        supply = q(max(0.0, sum(x.value for x in parts)), unit,
                   " + ".join(x.basis for x in parts) + " (never below 0)")
    if gone:
        supply = supply.model_copy(update={
            "basis": supply.basis + f"; {gone} listed contributing building(s) no longer in this scenario, so not counted"})

    lats = np.array([b.latitude for b in ctx.buildings], dtype=np.float64)
    lons = np.array([b.longitude for b in ctx.buildings], dtype=np.float64)
    mask = _scope_mask(budget.scope, lats, lons) if ctx.buildings else np.zeros(0, bool)
    in_scope = [b.id for b, m in zip(ctx.buildings, mask) if m]
    demand_by = {i: building_demand(kind, results[i]) for i in in_scope if i not in contributors}
    return PoolState(budget, unit, supply, demand_by, {b.id: b.name for b in ctx.buildings}, contributors, in_scope)


def budget_result(pool: PoolState) -> BudgetResult:
    unknown = [pool.names[i] for i, d in pool.demand_by.items() if d.value is None]
    if unknown:
        demand = q(None, pool.unit, "sum of in-scope building demand", [f"demand of {n}" for n in unknown])
    else:
        demand = q(sum(d.value for d in pool.demand_by.values()), pool.unit,
                   f"sum of {len(pool.demand_by)} in-scope building(s), counted once")
    if demand.value is None or pool.supply.value is None:
        unmet = q(None, pool.unit, "max(0, demand − supply)", demand.missing + pool.supply.missing)
    else:
        unmet = q(max(0.0, demand.value - pool.supply.value), pool.unit, "max(0, demand − supply)")
    return BudgetResult(
        id=pool.budget.id, label=pool.budget.label, kind=pool.budget.kind, unit=pool.unit,
        declared_supply=pool.supply, demand=demand, unmet=unmet, project_ids=pool.in_scope,
    )


# --- checks -----------------------------------------------------------------------------------

Builder = Callable[[int], CheckResult]


@dataclass
class CheckVec:
    status: np.ndarray  # int8 per cell
    build: Builder
    required: bool
    sources: tuple[str, ...] = ()  # files ids of data used


def _const(n: int, check: CheckResult) -> CheckVec:
    code = _STATUS.index(check.status)
    return CheckVec(np.full(n, code, dtype=np.int8), lambda _i: check, check.required)


DEFAULT_LABELS = {
    "site_area": "Usable site area ≥ footprint",
    "power_capacity": "Connected power capacity ≥ demand",
    "energy_budget": "Energy budget ≥ electricity demand",
    "water_budget": "Water allocation ≥ water demand",
    "construction_budget": "Construction cost within budget",
    "operating_budget": "Operating cost within budget",
    "material_budget": "Material use within limit",
    "staffing": "Staffing requirement ≤ worker capacity",
    "light_limit": "Upward light ≤ limit",
    "emission_limit": "Emissions within limit",
}


def _check(c: Criterion, status: str, *, label=None, **kw) -> CheckResult:
    return CheckResult(criterion_id=c.id, kind=c.kind, label=c.label or label or DEFAULT_LABELS.get(c.kind, c.kind),
                       required=c.required, status=status, **kw)


def _compare_max(c: Criterion, actual: Quantity, limit: float | None, unit: str, period: str | None,
                 source: str, what: str, partial_ok: bool = True) -> CheckResult:
    """actual <= limit. A known partial actual above the limit already fails (costs only grow)."""
    if limit is None:
        return _check(c, "unknown", actual=actual.value, unit=unit, period=period, source=source,
                      explanation=f"No limit given for {what}.")
    if actual.value is None:
        return _check(c, "unknown", required_value=limit, unit=unit, period=period, source=source,
                      explanation=f"{what} is unknown: missing {', '.join(actual.missing) or 'inputs'}.")
    if actual.value > limit:
        return _check(c, "fail", actual=actual.value, required_value=limit, unit=unit, period=period, source=source,
                      explanation=f"{what} {fmt_num(actual.value)} {unit} exceeds the limit {fmt_num(limit)} {unit}"
                      + (" (known components only)" if actual.missing else "") + ".")
    if actual.missing and partial_ok:
        return _check(c, "unknown", actual=actual.value, required_value=limit, unit=unit, period=period, source=source,
                      explanation=f"Known part of {what} is {fmt_num(actual.value)} {unit} (within {fmt_num(limit)}), but "
                      f"{', '.join(actual.missing)} unknown.")
    return _check(c, "pass", actual=actual.value, required_value=limit, unit=unit, period=period, source=source,
                  explanation=f"{what} {fmt_num(actual.value)} {unit} is within the limit {fmt_num(limit)} {unit}.")


def _definition_check(c: Criterion, stats: BuildingStats, result: BuildingResult) -> CheckResult:
    period = f"{fmt_num(result.period_days)} days"
    src = "building definition (user assumptions)"
    costs = result.costs
    cur = costs.currency or NO_CURRENCY
    if c.kind == "construction_budget":
        return _compare_max(c, costs.construction, c.amount, cur, "one-time", src, "Construction cost")
    if c.kind == "operating_budget":
        return _compare_max(c, costs.operating_known_total, c.amount, cur, period, src, "Operating cost")
    if c.kind == "light_limit":
        return _compare_max(c, result.light, c.amount, "lm", None, src, "Declared upward luminous flux")
    if c.kind in ("material_budget", "emission_limit"):
        name = (c.material_name if c.kind == "material_budget" else c.pollutant) or ""
        items = ([m.quantity for m in result.materials if m.name.strip().lower() == name.strip().lower()]
                 if c.kind == "material_budget" else
                 [e.quantity for e in result.emissions if pollutant_id(e.pollutant) == pollutant_id(name) and e.medium == release_medium(name, c.medium)])
        what = f"{'Use of' if c.kind == 'material_budget' else 'Emissions of'} {name or '(unnamed)'}"
        if not name:
            return _check(c, "unknown", unit="kg", period=period, source=src,
                          explanation=f"No {'material' if c.kind == 'material_budget' else 'pollutant'} named.")
        if not items:
            return _check(c, "unknown", required_value=c.amount, unit="kg", period=period, source=src,
                          explanation=f"{name} is not declared in the building's statistics (unknown, not zero).")
        known_vals = [x.value for x in items if x.value is not None]
        unit = "kgCO₂e" if c.kind == "emission_limit" and release_medium(name, c.medium) == "climate" else "kg"
        total = q(sum(known_vals) if known_vals else None, unit, "", [m for x in items for m in x.missing])
        basis = "construction (once) + operation over the period" if c.kind == "material_budget" else "rate × operating hours"
        return _compare_max(c, total, c.amount, unit, period, f"{src}; {basis}", what)
    if c.kind == "staffing":
        need, cap = result.staffing_required.value, result.worker_capacity.value
        if need is None or cap is None:
            missing = [x for x, v in (("staffing requirement", need), ("worker capacity", cap)) if v is None]
            return _check(c, "unknown", actual=need, required_value=cap, unit="people", source=src,
                          explanation=f"Missing {', '.join(missing)}.")
        ok = need <= cap
        return _check(c, "pass" if ok else "fail", actual=need, required_value=cap, unit="people", source=src,
                      explanation=f"Staffing requirement {fmt_num(need)} {'≤' if ok else '>'} worker capacity {fmt_num(cap)}. "
                      "Does not establish available labour.")
    raise ValueError(c.kind)


def _round_sig(vals: np.ndarray, digits: int = 6) -> np.ndarray:
    """Round to `digits` significant figures, the precision the inspector shows. Layer values are
    stored as float32, so comparing unrounded values would fail a limit copied from the display."""
    out = vals.copy()
    finite = np.isfinite(out) & (out != 0)
    mag = np.floor(np.log10(np.abs(out[finite])))
    scale = 10.0 ** (digits - 1 - mag)
    out[finite] = np.round(out[finite] * scale) / scale
    return out


# Aqueduct basin polygons for exact-point water-stress lookups (the cell layer uses the cell centre).
AQUEDUCT_FEATURES = "aqueduct_baseline"
POINT_IN_BASIN_LAYERS = {"water_stress"}


def _norm_label(s: str) -> str:
    return "".join(ch for ch in s.lower().replace("–", "-") if not ch.isspace())


_BWS_BY_LABEL = {_norm_label(label): float(v) for v, label, _ in layers.AQUEDUCT_BWS}


def _basin_at(slice_id: str, lat: float, lon: float) -> tuple[float, str] | str:
    """Water-stress value of the Aqueduct unit polygon containing the exact point.

    Returns (value, support text), with NaN for 'No Data', or a reason string when no polygon can be
    used (polygons not prepared, or the point lies outside every polygon)."""
    meta = features.layer_meta(AQUEDUCT_FEATURES)
    if meta is None or not features.available(meta):
        return "Aqueduct basin polygons are not prepared on this server"
    shapes = features.load(meta)
    hits = shapes.containing(lon, lat)
    if not hits:
        return "the exact point lies outside every Aqueduct basin polygon"
    props = shapes.features[min(hits)]["properties"]
    label = props.get("bwsLabel") or "No Data"
    cat = _BWS_BY_LABEL.get(_norm_label(label))
    if slice_id == "category":
        value = cat
    else:  # Aqueduct scores 'Arid and low water use' as 5; the polygon file stores no score for it
        value = 5.0 if cat == -1 else props.get("bwsScore")
    support = (f"Aqueduct unit {props.get('id')} ({label}) containing the exact point "
               f"[{AQUEDUCT_FEATURES} polygons, outlines simplified to about 500 m]")
    return (math.nan if value is None else float(value)), support


def _layer_check(c: Criterion, cells: np.ndarray, hexes: Callable[[int], str],
                 point: tuple[float, float] | None = None) -> CheckVec:
    """`point` (lat, lon) is the exact location in location mode; None for area screening."""
    n = len(cells)
    layer = layers.BY_ID.get(c.layer_id or "")
    if layer is None:
        return _const(n, _check(c, "unknown", label=c.layer_id or "Layer limit",
                                explanation=f"Unknown layer {c.layer_id!r}."))
    try:
        s = layer.slice(c.slice_id)
    except KeyError:
        return _const(n, _check(c, "unknown", label=layer.name, explanation=f"{layer.name} has no slice {c.slice_id!r}."))
    label = f"{layer.name} ({s.label})"
    src = layers.source_for(layer, s)
    if src is None:
        return _const(n, _check(c, "unknown", label=label, explanation=f"{label} is not prepared on this server."))

    categorical = layers.is_categorical(layer, s)
    units = layers.slice_units(layer, s)
    period = (layers.layer_meta(layer).get("period") or s.group or "").split(";")[0].strip()[:80] or None
    if categorical and not c.classes:
        return _const(n, _check(c, "unknown", label=label, unit=units, explanation="No allowed classes selected."))
    if not categorical and c.min is None and c.max is None:
        return _const(n, _check(c, "unknown", label=label, unit=units, explanation="No minimum or maximum given."))

    vals = h3store.lookup(src, h3store.SIM_RES, cells).astype(np.float64)
    display = layers.slice_display(layer, s)
    if display == "density":
        areas = np.array([h3.cell_area(hexes(i), unit="km^2") for i in range(n)])
        vals = vals / areas * layer.density_factor
    elif display == "percent":
        vals = vals * 100.0
    vals = _round_sig(vals)

    point_support, cell_note = None, ""  # which spatial support the value comes from
    if layer.id in POINT_IN_BASIN_LAYERS:
        cell_note = " (the Aqueduct basin containing the cell centre)"
        if point is not None:
            basin = _basin_at(s.id, *point)
            if isinstance(basin, str):
                cell_note += f"; point-in-basin check not possible: {basin}"
            else:
                vals[0], point_support = basin

    if categorical:
        ok = np.isin(vals, np.asarray(c.classes, dtype=np.float64))
        names = {float(x["value"]): x["label"] for x in (layer.categories or [])}
        allowed = ", ".join(names.get(float(v), _layer_num(v)) for v in c.classes)
        rule = f"class in {{{allowed}}}"
    else:
        ok = np.ones(n, dtype=bool)
        if c.min is not None:
            ok &= vals >= c.min
        if c.max is not None:
            ok &= vals <= c.max
        names = {}
        rule = " and ".join(x for x in (c.min is not None and f"≥ {_layer_num(c.min)}", c.max is not None and f"≤ {_layer_num(c.max)}") if x)
    nodata = np.isnan(vals)
    status = np.where(nodata, UNKNOWN, np.where(ok, PASS, FAIL)).astype(np.int8)
    required_value = c.max if c.max is not None else c.min
    caveat = f" Limitations: {layer.limitations[0]}" if layer.limitations else ""

    def build(i: int) -> CheckResult:
        h = hexes(i)
        source = (f"{layer.name}, slice {s.label}" + (f" ({period})" if period else "")
                  + f" [{layer.source_id}], " + (point_support or f"value of resolution-6 H3 cell {h}{cell_note}"))
        st = _STATUS[status[i]]
        if st == "unknown":
            return _check(c, st, label=label, required_value=required_value, unit=units, period=period, source=source,
                          explanation="No data for this location (outside the layer's coverage or a no-data value).")
        v = float(vals[i])
        shown = names.get(v, _layer_num(v)) if categorical else f"{_layer_num(v)} {units}"
        return _check(c, st, label=label, actual=v, required_value=required_value, unit=units, period=period,
                      source=source, explanation=f"Value {shown} {'meets' if st == 'pass' else 'does not meet'} "
                      f"the requirement {rule}.{caveat}")

    return CheckVec(status, build, c.required, (src.files_id,))


@dataclass
class _Supply:
    label: str
    value: float | None
    basis: str


def _supply_check(c: Criterion, kind: str, demand: Quantity, site: _Supply | None,
                  pools: list[tuple[np.ndarray, Quantity]], n: int, period: str | None) -> CheckVec:
    """Demand vs the sum of every declared source available at each cell.

    pass if known supply ≥ demand; unknown if not and some source is unknown or none is declared;
    fail otherwise. Remaining pool supply is never negative, so unknown sources can only add.
    """
    known_sum = np.zeros(n)
    any_unknown = np.zeros(n, dtype=bool)
    has_source = np.zeros(n, dtype=bool)
    if site is not None:
        has_source[:] = True
        if site.value is None:
            any_unknown[:] = True
        else:
            known_sum += site.value
    for mask, rem in pools:
        has_source |= mask
        if rem.value is None:
            any_unknown |= mask
        else:
            known_sum += np.where(mask, rem.value, 0.0)

    unit = demand.unit
    if demand.value is None:
        status = np.full(n, UNKNOWN, dtype=np.int8)
    else:
        passed = known_sum >= demand.value
        status = np.where(passed, PASS, np.where(any_unknown | ~has_source, UNKNOWN, FAIL)).astype(np.int8)

    def build(i: int) -> CheckResult:
        parts = []
        if site is not None:
            parts.append(f"site assumption {site.label}: {fmt_num(site.value)} {unit} ({site.basis})")
        parts += [rem.basis + f" = {fmt_num(rem.value)} {unit}" for mask, rem in pools if mask[i]]
        source = "; ".join(parts) or "no declared supply"
        st = _STATUS[status[i]]
        supply = float(known_sum[i])
        if demand.value is None:
            expl = f"Demand is unknown: missing {', '.join(demand.missing) or 'inputs'}."
        elif demand.value == 0:
            expl = "No demand, so no supply is needed."
        elif not parts:
            expl = ("No site assumption or scenario budget covers this location, so supply is unknown. "
                    "Declare a site allocation (exact location) or a scenario budget.")
        elif st == "pass":
            expl = f"Demand {fmt_num(demand.value)} {unit} ≤ available {fmt_num(supply)} {unit}."
        elif st == "fail":
            expl = (f"Demand {fmt_num(demand.value)} {unit} > available {fmt_num(supply)} {unit}; "
                    f"unmet {fmt_num(demand.value - supply)} {unit}.")
        else:
            missing = [m for mask, rem in pools if mask[i] for m in rem.missing]
            expl = (f"Known supply {fmt_num(supply)} {unit} is below demand {fmt_num(demand.value)} {unit} and some supply "
                    f"is unknown ({', '.join(missing) or 'site value'}).")
        return _check(c, st, actual=demand.value, required_value=supply if parts else None, unit=unit,
                      period=period, source=source, explanation=expl + f" Demand basis: {demand.basis}.")

    return CheckVec(status, build, c.required)


SITE_KINDS = {"power_capacity": "power_capacity_kw", "energy_budget": "energy_kwh_per_day", "water_budget": "water_m3_per_day"}


def build_checks(
    criteria: list[Criterion],
    stats: BuildingStats,
    result: BuildingResult,
    cells: np.ndarray,
    lats: Callable[[], np.ndarray],
    lons: Callable[[], np.ndarray],
    hexes: Callable[[int], str],
    site: SiteAssumptions | None,
    pools: list[PoolState],
    stress: StressControls,
    exclude: set[UUID],
    point: tuple[float, float] | None = None,
) -> list[CheckVec]:
    """One CheckVec per criterion over `cells`. `site` and `point` (exact lat, lon) are None in area
    (screening) mode."""
    n = len(cells)
    period_days = result.period_days
    period = f"{fmt_num(period_days)} days"
    out: list[CheckVec] = []
    masks: dict[int, np.ndarray] = {}

    def mask_for(i: int, pool: PoolState) -> np.ndarray:
        if i not in masks:
            masks[i] = _scope_mask(pool.budget.scope, lats(), lons()) if pool.budget.scope.kind != "scenario" \
                else np.ones(n, dtype=bool)
        return masks[i]

    for c in criteria:
        if c.kind == "layer":
            out.append(_layer_check(c, cells, hexes, point))
        elif c.kind == "site_area":
            area = None if site is None else site.usable_area_m2
            fp = result.footprint.value
            if site is None:
                chk = _check(c, "unknown", actual=fp, unit="m²", source="site assumptions (exact location only)",
                             explanation="Usable area is a site-specific assumption and is only evaluated at an "
                             "exact location; an H3 cell's area is not evidence of buildable land.")
            elif fp is None or area is None:
                missing = [x for x, v in (("footprint", fp), ("usable site area", area)) if v is None]
                chk = _check(c, "unknown", actual=fp, required_value=area, unit="m²", source="site assumptions",
                             explanation=f"Missing {', '.join(missing)}.")
            else:
                ok = fp <= area
                chk = _check(c, "pass" if ok else "fail", actual=fp, required_value=area, unit="m²",
                             source="site assumptions (declared usable area)",
                             explanation=f"Footprint {fmt_num(fp)} m² {'≤' if ok else '>'} declared usable area {fmt_num(area)} m².")
            out.append(_const(n, chk))
        elif c.kind in SITE_KINDS:
            kind = SITE_KINDS[c.kind]
            demand = building_demand(kind, result)
            mult, mult_name = _availability(kind, stress)
            note = "" if mult == 1 else f" × {mult_name} {fmt_num(mult)}"
            site_supply = None
            if site is not None:
                if kind == "power_capacity_kw" and site.connected_capacity_kw is not None:
                    site_supply = _Supply("connected capacity", site.connected_capacity_kw * mult,
                                          f"{fmt_num(site.connected_capacity_kw)} kW{note}")
                elif kind == "energy_kwh_per_day" and site.energy_budget_kwh_per_day is not None:
                    site_supply = _Supply("energy budget", site.energy_budget_kwh_per_day * period_days * mult,
                                          f"{fmt_num(site.energy_budget_kwh_per_day)} kWh/day × {fmt_num(period_days)} days{note}")
                elif kind == "water_m3_per_day" and site.water_allocation_m3_per_day is not None:
                    site_supply = _Supply("water allocation", site.water_allocation_m3_per_day * period_days * mult,
                                          f"{fmt_num(site.water_allocation_m3_per_day)} m³/day × {fmt_num(period_days)} days{note}")
            pool_terms = [
                (mask_for(i, p), p.remaining(exclude))
                for i, p in enumerate(pools)
                if p.budget.kind == kind and not (exclude & p.contributors)
            ]
            out.append(_supply_check(c, kind, demand, site_supply, pool_terms, n,
                                     None if kind == "power_capacity_kw" else period))
        else:
            out.append(_const(n, _definition_check(c, stats, result)))
    return out


def overall(statuses: np.ndarray, required: np.ndarray, n: int) -> np.ndarray:
    """State index per cell into _STATES. statuses: [checks, cells]."""
    if not required.any():
        return np.full(n, 1, dtype=np.int8)
    req = statuses[required]
    fail = (req == FAIL).any(axis=0)
    unknown = (req == UNKNOWN).any(axis=0)
    return np.where(fail, 2, np.where(unknown, 1, 0)).astype(np.int8)


NO_REQUIREMENTS = (
    "Nothing to check yet: the building's specs declare no footprint, water, power or staffing, so whether "
    "this site can provide them can't be judged (its usage and costs are still calculated)."
)


def _summary(checks: list[CheckResult], state: str, skipped: list[str] = ()) -> str:
    req = [c for c in checks if c.required]
    nu = sum(c.status == "unknown" for c in req)
    if not req:
        return NO_REQUIREMENTS
    if state == "fails_criteria":
        failed = ", ".join(c.label.lower() for c in req if c.status == "fail")
        text = f"Can't be built here: {failed}" + (f"; {nu} more unknown." if nu else ".")
    elif state == "insufficient_data":
        text = f"Possibly buildable, but {nu} of {len(req)} checks can't be judged with the available data."
    else:
        text = f"Can be built here: the site provides everything its specs need ({len(req)} checks)."
    if skipped:
        text += " Not checked: " + "; ".join(skipped) + "."
    return text


def assessment_at(checks: list[CheckVec], i: int, state_idx: int, skipped: list[str] = (),
                  coastal: bool | None = None) -> Assessment:
    """With `coastal` (from the site data), shortfalls another building could cover get suggestions."""
    results = [c.build(i) for c in checks]
    state = _STATES[state_idx]
    suggestions = site_support.suggestions(results, coastal) if coastal is not None else []
    return Assessment(state=state, checks=results, summary=_summary(results, state, skipped), suggestions=suggestions)


def _site_vecs(btype: str, stats: BuildingStats, result: BuildingResult, cells: np.ndarray, lats: np.ndarray,
               lons: np.ndarray, ctx: ScenarioContext, results: dict[UUID, BuildingResult], exclude: set[UUID],
               stress: StressControls):
    """Automatic checks: what the site (cell + neighbours) provides vs what the building's specs need.

    Other scenario buildings nearby share the same supply (their demand is subtracted, placed plants'
    output added); the building itself and `exclude` are never counted."""
    sd = site_capacity.site_data(cells, lats, lons)
    neighbours = [
        site_capacity.Neighbour(b.id, b.name, int(b.h3_id, 16),
                                site_capacity.demand_of(b.type, b.snapshot.stats, results[b.id]))
        for b in ctx.buildings if b.id not in exclude and b.id in results
    ]
    sh = site_capacity.shared(cells, neighbours)
    demand = site_capacity.demand_of(btype, stats, result)
    checks, skipped, mats = site_capacity.site_checks(btype, demand, sd, sh, stress)
    return [CheckVec(c.status, c.build, c.required) for c in checks], skipped, (sd, sh, demand, mats)


# --- public entry points ----------------------------------------------------------------------


def _scenario_pools(ctx: ScenarioContext, results, stress) -> list[PoolState]:
    return [pool_state(b, ctx, results, stress) for b in ctx.assumptions.budgets]


def assess_point(
    btype: str, stats: BuildingStats, parameters: dict, criteria: list[Criterion], site: SiteAssumptions,
    latitude: float, longitude: float, ctx: ScenarioContext, exclude: set[UUID],
    stress: StressControls | None = None, results: dict[UUID, BuildingResult] | None = None,
    pools: list[PoolState] | None = None, result: BuildingResult | None = None,
) -> tuple[str, BuildingResult, Assessment, list[CheckVec]]:
    stress = stress or StressControls()
    h3_id = h3.latlng_to_cell(latitude, longitude, h3store.SIM_RES)
    if result is None:
        result = calculate(btype, stats, parameters, ctx.period_days, stress, location_context(h3_id))
    results = results if results is not None else building_results(ctx, stress)
    if pools is None:
        pools = _scenario_pools(ctx, results, stress)
    criteria = criteria + implied_criteria(criteria, site, pools, latitude, longitude, exclude)
    cells = np.array([int(h3_id, 16)], dtype=np.uint64)
    lat, lon = np.array([latitude]), np.array([longitude])
    site_vecs, skipped, site_state = _site_vecs(btype, stats, result, cells, lat, lon, ctx, results, exclude, stress)
    checks = site_vecs + build_checks(criteria, stats, result, cells, lambda: lat, lambda: lon,
                                      lambda _i: h3_id, site, pools, stress, exclude, (latitude, longitude))
    statuses = np.array([c.status for c in checks]).reshape(len(checks), 1)
    state = overall(statuses, np.array([c.required for c in checks], dtype=bool), 1)
    sd, sh, demand, mats = site_state
    capacity = site_capacity.capacity_at(sd, sh, 0, stress, demand, btype, mats)
    return h3_id, result, assessment_at(checks, 0, int(state[0]), skipped, bool(sd.coastal[0])), checks, capacity


def assess_location(btype, stats, parameters, criteria, site, latitude, longitude, ctx, exclude) -> LocationAssessment:
    h3_id, result, assessment, _, capacity = assess_point(btype, stats, parameters, criteria, site, latitude,
                                                          longitude, ctx, exclude)
    return LocationAssessment(latitude=latitude, longitude=longitude, h3_id=h3_id, result=result, assessment=assessment,
                              site=capacity, utility_prices=building_prices.location_offers(h3_id, stats.costs))


def _box_area_km2(w: float, s: float, e: float, n: float) -> float:
    width = (e - w) % 360 or (360.0 if e != w else 0.0)
    return EARTH_RADIUS_KM ** 2 * math.radians(width) * abs(math.sin(math.radians(n)) - math.sin(math.radians(s)))


def enumerate_cells(w: float, s: float, e: float, n: float) -> np.ndarray:
    """Sorted unique uint64 res-6 cells whose centres fall in the box (antimeridian-aware)."""
    estimate = _box_area_km2(w, s, e, n) / RES6_AVG_AREA_KM2
    if estimate > MAX_AREA_CELLS * 1.2:
        raise AreaTooLarge(f"the area holds about {int(estimate):,} resolution-6 cells; the limit is "
                           f"{MAX_AREA_CELLS:,}. Narrow the area (zoom in) or choose a prepared region.")
    spans = [(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]
    cells: set[str] = set()
    for a, b in spans:
        x = a
        while x < b:  # chunk wide boxes so polygon edges stay well under 180°
            x2 = min(b, x + 60.0)
            poly = h3.LatLngPoly([(s, x), (s, x2), (n, x2), (n, x)])
            cells.update(h3.polygon_to_cells(poly, h3store.SIM_RES))
            x = x2
    if not cells:  # a box smaller than one cell: use the cell at its centre
        cx = (w + ((e - w) % 360) / 2 + 180) % 360 - 180
        cells.add(h3.latlng_to_cell((s + n) / 2, cx, h3store.SIM_RES))
    if len(cells) > MAX_AREA_CELLS:
        raise AreaTooLarge(f"the area holds {len(cells):,} resolution-6 cells; the limit is {MAX_AREA_CELLS:,}. "
                           "Narrow the area (zoom in) or choose a prepared region.")
    return np.sort(np.array([int(c, 16) for c in cells], dtype=np.uint64))


def assess_area(btype, stats, parameters, criteria, box: tuple[float, float, float, float],
                ctx: ScenarioContext, exclude: set[UUID], limit: int) -> AreaAssessment:
    stress = StressControls()  # assessments are unstressed
    cells = enumerate_cells(*box)
    n = len(cells)
    hex_cache: dict[int, str] = {}

    def hexes(i: int) -> str:
        if i not in hex_cache:
            hex_cache[i] = h3store.cell_hex(cells[i])
        return hex_cache[i]

    centres: list[np.ndarray] = []

    def latlon() -> list[np.ndarray]:
        if not centres:
            pts = np.array([h3.cell_to_latlng(hexes(i)) for i in range(n)], dtype=np.float64).reshape(n, 2)
            centres.extend([pts[:, 0], pts[:, 1]])
        return centres

    result = calculate(btype, stats, parameters, ctx.period_days, stress, None)
    results = building_results(ctx, stress)
    pools = _scenario_pools(ctx, results, stress)
    site_vecs, skipped, site_state = _site_vecs(btype, stats, result, cells, latlon()[0], latlon()[1], ctx, results,
                                                exclude, stress)
    coastal = site_state[0].coastal
    checks = site_vecs + build_checks(criteria, stats, result, cells, lambda: latlon()[0], lambda: latlon()[1],
                                      hexes, None, pools, stress, exclude)
    statuses = np.array([c.status for c in checks]).reshape(len(checks), n)
    states = overall(statuses, np.array([c.required for c in checks], dtype=bool), n)

    order = np.lexsort((cells, states))  # state rank, then H3 id (same-resolution ids sort like their hex)
    candidates = []
    for i in order[:limit]:
        lat, lon = h3.cell_to_latlng(hexes(int(i)))
        candidates.append(Candidate(h3_id=hexes(int(i)), latitude=lat, longitude=lon,
                                    assessment=assessment_at(checks, int(i), int(states[i]), skipped, bool(coastal[i]))))
    counts = {s: int(np.count_nonzero(states == k)) for k, s in enumerate(_STATES)}
    return AreaAssessment(
        cell_count=n,
        counts=counts,
        cells=[CellState(h3_id=hexes(i), state=_STATES[states[i]]) for i in range(n)],
        candidates=candidates,
        result=result,
        note=SCREENING_NOTE + (f" Showing the first {len(candidates)} of {n} cells in order." if n > limit else ""),
    )


# --- scenario evaluation ----------------------------------------------------------------------


def _sum_quantities(items: list[tuple[str, Quantity]], unit: str, label: str) -> tuple[Quantity, list[str]]:
    """Sum of the known values. Returns the total and the names of buildings whose value is unknown or
    only partly known; their missing inputs are carried into the total, so a partial sum never looks
    complete. Nothing known (and something unknown) gives an unknown total, not 0."""
    vals = [x.value for _, x in items if x.value is not None]
    unknown = [name for name, x in items if is_unknown(x)]
    partial = [(name, x) for name, x in items if x.value is not None and x.missing]
    missing = [f"{label} of {n}" for n in unknown] + [f"{label} of {n}: {m}" for n, x in partial for m in x.missing]
    if not vals and unknown:
        return q(None, unit, f"no building has a known {label}", missing), unknown
    incomplete = len(unknown) + len(partial)
    basis = f"sum of {len(vals)} building(s) with known {label}"
    if incomplete:
        basis += f"; {incomplete} unknown or partly known, so partial"
    return q(sum(vals), unit, basis, missing), unknown + [n for n, _ in partial]


def _totals(ctx: ScenarioContext, results: dict[UUID, BuildingResult]) -> ScenarioTotals:
    named = [(b.name or b.type, results[b.id]) for b in ctx.buildings]
    unknown_by: dict[str, list[str]] = {}

    def total(metric: str, get, unit: str, label: str) -> Quantity:
        qty, unknown = _sum_quantities([(n, get(r)) for n, r in named], unit, label)
        if unknown:
            unknown_by[metric] = unknown
        return qty

    def by_currency(metric: str, get, label: str) -> list[Quantity]:
        """One total per declared currency. Costs without a currency are never added to each other:
        two blank currencies are not known to be the same."""
        groups: dict[str, list[tuple[str, Quantity]]] = {}
        blank: list[tuple[str, Quantity]] = []
        for n, r in named:
            if r.costs.currency:
                groups.setdefault(r.costs.currency, []).append((n, get(r)))
            elif not (get(r).value is None and not get(r).missing):  # skip not-applicable costs
                blank.append((n, get(r)))
        mixed = sum(x.value is not None for _, x in blank) > 1
        if blank and not mixed:  # at most one known amount: nothing is mixed
            groups[NO_CURRENCY] = blank
        out = []
        for cur in sorted(groups):
            qty, unknown = _sum_quantities(groups[cur], cur, label)
            if unknown:
                unknown_by.setdefault(metric, []).extend(unknown)
            out.append(qty)
        if mixed:
            names = [n for n, _ in blank]
            out.append(q(None, NO_CURRENCY, f"not summed: {len(blank)} buildings declare no currency, so their "
                         "amounts may be in different currencies (see each building)",
                         [f"currency of {n}" for n in names]))
            unknown_by.setdefault(metric, []).extend(names)
        return out

    mats: dict[tuple[str, str], list[tuple[str, Quantity, str]]] = {}
    ems: dict[tuple[str, str], list[tuple[str, Quantity, str]]] = {}
    for n, r in named:
        for m in r.materials:
            mats.setdefault((m.name.strip().lower(), m.phase), []).append((n, m.quantity, m.name))
        for e in r.emissions:
            ems.setdefault((e.medium, pollutant_id(e.pollutant)), []).append((n, e.quantity, e.pollutant))
    materials = [
        MaterialTotal(name=v[0][2], phase=phase, quantity=_sum_quantities([(n, x) for n, x, _ in v], "kg", name)[0])
        for (name, phase), v in sorted(mats.items())
    ]
    emissions = [
        EmissionTotal(pollutant=v[0][2], medium=medium, quantity=_sum_quantities([(n, x) for n, x, _ in v], v[0][1].unit, key)[0])
        for (medium, key), v in sorted(ems.items())
    ]
    return ScenarioTotals(
        electricity_demand=total("electricityDemand", lambda r: r.electricity_demand, "kWh", "electricity demand"),
        electricity_output=total("electricityOutput", lambda r: r.electricity_output, "kWh", "electricity output"),
        water_demand=total("waterDemand", lambda r: r.water_demand, "m³", "water demand"),
        water_output=total("waterOutput", lambda r: r.water_output, "m³", "water output"),
        construction_cost=by_currency("constructionCost", lambda r: r.costs.construction, "construction cost"),
        operating_cost=by_currency("operatingCost", lambda r: r.costs.operating_known_total, "operating cost"),
        materials=materials,
        emissions=emissions,
        light=total("light", lambda r: r.light, "lm", "upward lumens"),
        worker_capacity=total("workerCapacity", lambda r: r.worker_capacity, "people", "worker capacity"),
        unknown_buildings=unknown_by,
    )


SITE_FIELDS = {"power_capacity": "connected_capacity_kw", "energy_budget": "energy_budget_kwh_per_day",
               "water_budget": "water_allocation_m3_per_day"}


def implied_criteria(criteria: list[Criterion], site: SiteAssumptions, pools: list[PoolState],
                     latitude: float, longitude: float, exclude: set[UUID]) -> list[Criterion]:
    """Checks activated by an explicit declaration at an exact location (spec section 7): a declared
    usable site area, a site supply (connected capacity, energy budget, water allocation) or a scenario
    budget whose scope covers the point. Declaring a limit means the building must fit it, so these
    checks are required. Kinds the definition already checks keep the definition's own settings."""
    declared = {c.kind for c in criteria}
    out = []
    if "site_area" not in declared and site.usable_area_m2 is not None:
        out.append(Criterion(id="site-site_area", kind="site_area", label="Footprint fits declared usable site area"))
    lat, lon = np.array([latitude]), np.array([longitude])
    for kind, budget_kind in SITE_KINDS.items():
        if kind in declared:
            continue
        covered = any(p.budget.kind == budget_kind and not (exclude & p.contributors)
                      and bool(_scope_mask(p.budget.scope, lat, lon)[0]) for p in pools)
        if covered or getattr(site, SITE_FIELDS[kind]) is not None:
            out.append(Criterion(id=f"site-{kind}", kind=kind,
                                 label=DEFAULT_LABELS[kind] + " (declared supply)"))
    return out


def scenario_result(ctx: ScenarioContext, stress: StressControls, locs: dict[UUID, LocationContext]) -> ScenarioResult:
    results = building_results(ctx, stress, locs)
    pools = _scenario_pools(ctx, results, stress)
    buildings = []
    for b in ctx.buildings:
        _, _, assessment, _, _ = assess_point(
            b.type, b.snapshot.stats, b.parameters, b.snapshot.criteria, b.site, b.latitude, b.longitude,
            ctx, {b.id}, stress, results, pools, results[b.id])
        buildings.append(BuildingEvaluation(project_id=b.id, name=b.name, type=b.type, result=results[b.id],
                                            assessment=assessment))
    return ScenarioResult(buildings=buildings, budgets=[budget_result(p) for p in pools], totals=_totals(ctx, results))


def control_notes(ctx: ScenarioContext, stress: StressControls) -> dict[str, str]:
    budgets = ctx.assumptions.budgets
    sites = [b.site for b in ctx.buildings]
    stats = [b.snapshot.stats for b in ctx.buildings]
    pct = lambda m: f"{m * 100:.0f}%"  # noqa: E731

    water_pools = [b for b in budgets if b.kind == "water_m3_per_day"]
    water_sites = [s for s in sites if s.water_allocation_m3_per_day is not None]
    if water_pools or water_sites:
        water = (f"Multiplies declared external water supply ({len(water_pools)} pooled budget(s)) and "
                 f"{len(water_sites)} site allocation(s) by {pct(stress.water_availability)}. Unknown supply "
                 "stays unknown; Aqueduct and satellite observations are unchanged.")
    else:
        water = "No water budget or site water allocation declared — water availability has no calculable effect."

    power_pools = [b for b in budgets if b.kind != "water_m3_per_day"]
    power_sites = [s for s in sites if s.connected_capacity_kw is not None or s.energy_budget_kwh_per_day is not None]
    if power_pools or power_sites:
        power = (f"Multiplies declared external power capacity (kW) and energy (kWh) budgets ({len(power_pools)} "
                 f"pooled, {len(power_sites)} site) by {pct(stress.power_availability)}; capacity and energy are "
                 "checked separately. Contributions from declared plants are their net output, unscaled.")
    else:
        power = "No power capacity or energy budget declared — power availability has no calculable effect."

    has_rates = any(
        s.power.average_demand_kw is not None or s.power.peak_demand_kw is not None
        or s.water.input_m3_per_hour is not None or s.demand_basis == "derived"
        or any(m.phase == "operation" and m.quantity_kg is not None for m in s.materials)
        for s in stats
    )
    fixed = ("Construction materials and cost, footprint, worker capacity, emissions, light output and "
             "generation output are fixed declared values and do not change.")
    if has_rates:
        demand = (f"Multiplies operating electricity (average and peak), water and operational-material demand "
                  f"rates by {pct(stress.operating_demand)}. {fixed}")
    else:
        demand = f"No operating demand rates declared — operating demand has no calculable effect. {fixed}"

    has_prices = any(
        s.costs.operating.kind == "fixed" and (
            s.costs.electricity_price_per_kwh is not None or s.costs.water_price_per_m3 is not None
            or any(m.phase == "operation" and m.unit_price_per_kg is not None for m in s.materials))
        for s in stats
    )
    if has_prices:
        prices = (f"Multiplies electricity, water and operational-material unit prices by "
                  f"{pct(stress.operating_prices)}. Construction cost and fixed or all-inclusive operating "
                  "amounts are unchanged.")
    else:
        prices = ("No unit prices declared on itemised (fixed-kind) operating costs — operating prices have no "
                  "calculable effect.")
    return {"waterAvailability": water, "powerAvailability": power, "operatingDemand": demand,
            "operatingPrices": prices}


def sources_used(ctx: ScenarioContext) -> list[str]:
    """Files ids of every prepared data slice the evaluation reads (for the inputs hash)."""
    ids = set()
    if any(b.type == "solar" for b in ctx.buildings):
        src, _ = _ghi_source()
        if src is not None:
            ids.add(f"{GHI_LAYER}:{src.files_id}:{src.column}")
    for b in ctx.buildings:
        for c in b.snapshot.criteria:
            layer = layers.BY_ID.get(c.layer_id or "") if c.kind == "layer" else None
            if layer is None:
                continue
            try:
                src = layers.source_for(layer, layer.slice(c.slice_id))
            except KeyError:
                continue
            if src is not None:
                ids.add(f"{layer.id}:{src.files_id}:{src.column}")
            meta = features.layer_meta(AQUEDUCT_FEATURES) if layer.id in POINT_IN_BASIN_LAYERS else None
            if meta is not None and features.available(meta):  # point-in-basin polygons
                ids.add(f"{AQUEDUCT_FEATURES}:{features.file_path(meta).stat().st_mtime_ns}")
    return sorted(ids)


def inputs_hash(ctx: ScenarioContext, stress: StressControls) -> str:
    payload = {
        "modelVersion": MODEL_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "assumptions": ctx.assumptions.model_dump(mode="json", by_alias=True),
        "stress": stress.model_dump(mode="json", by_alias=True),
        "buildings": [
            {
                "id": str(b.id), "type": b.type, "latitude": b.latitude, "longitude": b.longitude,
                "definition": b.snapshot.model_dump(mode="json", by_alias=True),
                "parameters": b.parameters, "site": b.site.model_dump(mode="json", by_alias=True),
            }
            for b in ctx.buildings
        ],
        "sources": sources_used(ctx),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def evaluate(ctx: ScenarioContext, stress: StressControls) -> tuple[ScenarioResult, ScenarioResult, dict[str, str]]:
    locs = {b.id: location_context(b.h3_id) for b in ctx.buildings}
    return scenario_result(ctx, StressControls(), locs), scenario_result(ctx, stress, locs), control_notes(ctx, stress)
