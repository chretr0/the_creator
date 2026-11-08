"""Shared contract for building definitions, placement assessment and scenario stress tests.

See CLAUDE.Building-System.md. Mirrored in frontend/src/lib/buildings.ts - change both together.

Conventions
- Every numeric input is optional: ``None`` / absent means *unknown*, never zero. An explicit 0 is
  allowed and means "none".
- All numbers must be finite (NaN / infinity are rejected).
- Units are fixed by field name: kW, kWh, m3, kg, m2, lumens, people, hours.
- Money amounts carry an ISO 4217 currency code on the enclosing ``Costs``; currencies are never
  converted.
- Inputs (stats, parameters, criteria, site, scenario assumptions) are stored; derived results are
  always recomputed and never persisted over inputs.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, field_validator, model_validator

from app.api_base import ApiModel, ParamValue

SCHEMA_VERSION = 1
MODEL_VERSION = "building-model-1"

# Keep in sync with building_templates.TEMPLATES, frontend/src/lib/buildings.ts and the
# project/building_definition type CHECK constraints (db/migrations/V3__more_building_types.sql).
BuildingType = Literal[
    # energy
    "power_station", "solar", "wind_farm", "hydro_plant", "geothermal_plant", "battery_storage", "hydrogen_plant",
    # water
    "water_plant", "wastewater_plant",
    # mining & extraction
    "mine", "quarry", "oil_gas_field",
    # industry & manufacturing
    "factory", "steel_mill", "aluminium_smelter", "cement_plant", "chemical_plant", "oil_refinery",
    "semiconductor_fab",
    # agriculture & food
    "farm", "livestock_farm", "greenhouse", "vertical_farm", "aquaculture", "food_processing",
    # commercial & digital
    "data_centre", "office", "retail", "hotel", "research_lab",
    # housing & public services
    "housing", "hospital", "school", "university", "stadium",
    # transport & logistics
    "airport", "seaport", "warehouse",
    # waste & recycling
    "landfill", "recycling_facility", "waste_to_energy",
    # other
    "custom",
]
# Moon building types, placed only in Moon worlds and never saved as building definitions. Keep in sync
# with shared/moon_buildings.json (same order) and the project type CHECK constraint
# (db/migrations/V4__moon_worlds.sql).
MoonBuildingType = Literal[
    "moon_habitat", "moon_solar_tower", "moon_fission", "moon_storage",
    "moon_ice_mine", "moon_oxygen_plant", "moon_greenhouse", "moon_landing_pad",
]
BuildingCategory = Literal["energy", "water", "extraction", "industry", "agriculture", "commercial", "community",
                           "transport", "waste", "other"]
ProvenanceKind = Literal["user_assumption", "demo_assumption", "cited"]
CheckStatus = Literal["pass", "fail", "unknown"]
AssessmentState = Literal["meets_criteria", "fails_criteria", "insufficient_data"]
Period = Literal["hour", "day", "month", "year"]

# Explicit, displayed prorating assumptions (days per period).
DAYS_PER_PERIOD: dict[str, float] = {"hour": 1 / 24, "day": 1.0, "month": 30.4375, "year": 365.25}

MAX_PERIOD_DAYS = 3660  # ten years


def _finite(v: float | None) -> float | None:
    if v is not None and not math.isfinite(v):
        raise ValueError("must be a finite number")
    return v


def _non_negative(v: float | None) -> float | None:
    _finite(v)
    if v is not None and v < 0:
        raise ValueError("must be zero or positive")
    return v


def _positive(v: float | None) -> float | None:
    _finite(v)
    if v is not None and v <= 0:
        raise ValueError("must be greater than zero")
    return v


def _fraction(v: float | None) -> float | None:
    _finite(v)
    if v is not None and not 0 <= v <= 1:
        raise ValueError("must be between 0 and 1")
    return v


def _hours_per_day(v: float | None) -> float | None:
    _finite(v)
    if v is not None and not 0 <= v <= 24:
        raise ValueError("must be between 0 and 24 hours per day")
    return v


NonNeg = Annotated[float | None, AfterValidator(_non_negative)]
Pos = Annotated[float | None, AfterValidator(_positive)]
Frac = Annotated[float | None, AfterValidator(_fraction)]
HoursPerDay = Annotated[float | None, AfterValidator(_hours_per_day)]
Count = Annotated[int | None, Field(default=None, ge=0, le=10**9)]
# Stored in a PostgreSQL `integer` column, so bounded to int4.
TemplateVersion = Annotated[int | None, Field(default=None, ge=0, le=2**31 - 1)]
TemplateId = Annotated[str | None, Field(default=None, max_length=64)]
Note = Annotated[str | None, Field(default=None, max_length=2000)]  # free-text basis / citation
ShortText = Annotated[str | None, Field(default=None, max_length=200)]


class Provenance(ApiModel):
    kind: ProvenanceKind = "user_assumption"
    note: Note = None  # citation / basis text


# --- building statistics (inputs) -------------------------------------------------------------


class MaterialItem(ApiModel):
    """One named raw material. Mass is always stored in kg (the form may accept tonnes)."""

    id: str = Field(min_length=1, max_length=64)  # stable client-generated identifier
    name: str = Field(min_length=1, max_length=200)
    phase: Literal["construction", "operation"]
    quantity_kg: NonNeg = None  # construction: once per building; operation: per `period`
    period: Period | None = None  # required for operation quantities
    unit_price_per_kg: NonNeg = None  # in Costs.currency; optional
    provenance: Provenance = Provenance()

    @model_validator(mode="after")
    def _operation_needs_period(self):
        if self.phase == "operation" and self.quantity_kg is not None and self.period is None:
            raise ValueError(f"operational material '{self.name}' needs a period for its quantity")
        return self


class EmissionItem(ApiModel):
    """Declared release rate while operating, separated by receiving environment."""

    id: str = Field(min_length=1, max_length=64)
    pollutant: str = Field(min_length=1, max_length=100)
    medium: Literal['air', 'soil', 'freshwater', 'marine', 'climate'] = 'air'
    rate_kg_per_hour: NonNeg = None
    provenance: Provenance = Provenance()

    @model_validator(mode="after")
    def _destination(self):
        from app.pollutants import BY_ID, pollutant_id, release_medium
        key = pollutant_id(self.pollutant)
        if key == 'co2e' and self.medium not in ('air', 'climate'):
            raise ValueError('CO2e is climate accounting; choose a physical pollutant for soil or water')
        self.medium = release_medium(self.pollutant, self.medium)
        # Historical records used unrestricted air-pollutant names. Keep those readable/saveable;
        # the catalogue limits new dropdown choices without invalidating legacy air releases.
        if key in BY_ID and self.medium != 'air' and self.medium not in BY_ID[key]['media']:
            raise ValueError(f'{self.pollutant} is not a supported {self.medium} release')
        return self


class PowerStats(ApiModel):
    average_demand_kw: NonNeg = None  # electricity consumed while operating
    peak_demand_kw: NonNeg = None  # capacity check only, never an energy total
    # Generation (power stations, solar, or any building that declares output)
    average_output_kw: NonNeg = None  # gross average output while operating
    rated_output_kw: NonNeg = None  # nameplate; needs capacity_factor to give energy
    capacity_factor: Frac = None
    technology: ShortText = None  # free-text technology/process description
    provenance: Provenance = Provenance()


class WaterStats(ApiModel):
    input_m3_per_hour: NonNeg = None  # water consumed while operating
    output_m3_per_hour: NonNeg = None  # usable treated/produced output (water plants)
    # Where the intake comes from. Only "fresh" draws on rivers/runoff; "seawater" needs a coastal site;
    # "wastewater" (treated municipal effluent) is estimated from the population within pipeline reach.
    source: Literal["fresh", "seawater", "wastewater"] = "fresh"
    basis: ShortText = None  # water source / process basis, e.g. "brackish groundwater RO"
    provenance: Provenance = Provenance()


class LightStats(ApiModel):
    """Simple proxy: declared upward luminous flux. Not sky brightness or a pollution index."""

    upward_lumens: NonNeg = None
    hours_per_day: HoursPerDay = None
    provenance: Provenance = Provenance()


class WorkerStats(ApiModel):
    capacity: Count = None  # max workers accommodated at one time
    staffing_required: Count = None  # staff needed, when supplied
    provenance: Provenance = Provenance()


class OperatingCost(ApiModel):
    amount: NonNeg = None
    period: Period = "year"
    # "total" = all-inclusive operating cost (resource prices are then NOT added on top);
    # "fixed" = fixed component only (known resource costs are added).
    kind: Literal["total", "fixed"] = "fixed"


class PriceSource(ApiModel):
    """Where a unit price came from when the user did not type it: the location default.

    Set only when the user explicitly chose a cell's average price ("Use location price"). The price
    field then holds exactly ``value``; typing a different price removes the source (user-entered wins).
    The source keeps its own currency (the dataset is in USD) and is never converted.
    """

    kind: Literal["location_default"] = "location_default"
    value: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: Literal["business", "household"] = "business"
    h3_id: str = Field(pattern=r"^[0-9a-f]{15}$")  # resolution-6 cell the price was read at
    price_area: ShortText = None  # e.g. "US-AZ", "NO"
    price_area_name: ShortText = None
    basis: Note = None  # the dataset's basis line: original price, FX, year, publication, tax
    source: ShortText = None  # dataset / layer label, e.g. "PRICE-01 Electricity price (average), Business"

    @field_validator("value")
    @classmethod
    def _finite_value(cls, v):
        return _finite(v)


_PRICE_FIELDS = (("electricity_price_per_kwh", "electricity_price_source", "electricity"),
                 ("water_price_per_m3", "water_price_source", "water"))


class Costs(ApiModel):
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    construction_total: NonNeg = None  # one-time
    price_basis: ShortText = None  # e.g. "2025 prices, vendor quote"
    operating: OperatingCost = OperatingCost()
    electricity_price_per_kwh: NonNeg = None
    water_price_per_m3: NonNeg = None
    # Only when the price is an explicitly chosen location default (absent = typed by the user).
    electricity_price_source: PriceSource | None = None
    water_price_source: PriceSource | None = None
    provenance: Provenance = Provenance()

    @model_validator(mode="after")
    def _sourced_prices_match(self):
        """A location-default price must equal its source value and share the costs' currency.

        No implicit FX conversion: a USD location price is never mixed into EUR (or unspecified) costs.
        """
        for price_field, source_field, name in _PRICE_FIELDS:
            src: PriceSource | None = getattr(self, source_field)
            if src is None:
                continue
            price = getattr(self, price_field)
            if price is None or not math.isclose(price, src.value, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"{name} price differs from its location default; "
                                 "remove the location source or use its value")
            if self.currency != src.currency:
                raise ValueError(f"{name} location price is in {src.currency} but costs are in "
                                 f"{self.currency or 'no currency'}; currencies are never converted")
        return self


class BuildingStats(ApiModel):
    footprint_m2: Pos = None  # occupied ground area (not a greenhouse's floor area, not an H3 cell)
    operating_hours_per_day: HoursPerDay = None  # applies to power, water and emissions
    power: PowerStats = PowerStats()
    water: WaterStats = WaterStats()
    materials: list[MaterialItem] = Field(default_factory=list, max_length=100)
    emissions: list[EmissionItem] = Field(default_factory=list, max_length=100)
    light: LightStats = LightStats()
    workers: WorkerStats = WorkerStats()
    costs: Costs = Costs()
    # Data centres: which electricity/water basis feeds totals. "derived" = IT power x load x PUE
    # (and WUE); "direct" = average_demand_kw / input_m3_per_hour. Never both.
    demand_basis: Literal["direct", "derived"] = "direct"
    footprint_provenance: Provenance = Provenance()


# --- location requirements --------------------------------------------------------------------

CriterionKind = Literal[
    "layer",  # environmental limit on a registered H3 layer slice
    "site_area",  # declared usable area >= footprint
    "power_capacity",  # connected capacity (kW) >= peak (or average) demand
    "energy_budget",  # energy budget (kWh over period) >= demand
    "water_budget",  # water allocation (m3 over period) >= input demand
    "construction_budget",  # max construction cost
    "operating_budget",  # max operating cost over the evaluation period
    "material_budget",  # max kg of a named material (construction + operation over period)
    "staffing",  # staffing_required <= worker capacity
    "light_limit",  # upward_lumens <= max
    "emission_limit",  # pollutant kg over period <= max
]


class Criterion(ApiModel):
    id: str = Field(min_length=1, max_length=64)
    kind: CriterionKind
    required: bool = True
    label: ShortText = None
    # kind == "layer"
    layer_id: str | None = Field(default=None, max_length=64)
    slice_id: str | None = Field(default=None, max_length=64)
    min: float | None = None
    max: float | None = None
    # allowed category values for categorical layers
    classes: list[float] | None = Field(default=None, max_length=100)
    # budgets / limits (units implied by kind: currency, kg, lumens)
    amount: NonNeg = None
    material_name: ShortText = None
    pollutant: str | None = Field(default=None, max_length=100)
    medium: Literal['air', 'soil', 'freshwater', 'marine', 'climate'] = 'air'

    @field_validator("min", "max")
    @classmethod
    def _finite_bounds(cls, v):
        return _finite(v)

    @field_validator("classes")
    @classmethod
    def _finite_classes(cls, v):
        return None if v is None else [_finite(x) for x in v]


# --- placement and site assumptions -----------------------------------------------------------


class SiteAssumptions(ApiModel):
    """Declared for one exact location only; never applied to other candidate sites."""

    usable_area_m2: NonNeg = None
    connected_capacity_kw: NonNeg = None
    energy_budget_kwh_per_day: NonNeg = None
    water_allocation_m3_per_day: NonNeg = None
    note: Note = None


class DefinitionSnapshot(ApiModel):
    """Self-contained copy stored on a placed building."""

    schema_version: int = SCHEMA_VERSION
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)
    template_id: TemplateId = None
    template_version: TemplateVersion = None
    stats: BuildingStats = BuildingStats()
    criteria: list[Criterion] = Field(default_factory=list, max_length=50)


class BuildingDefinitionInput(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    type: BuildingType
    template_id: TemplateId = None
    template_version: TemplateVersion = None
    stats: BuildingStats = BuildingStats()
    parameters: dict[str, ParamValue] = {}
    criteria: list[Criterion] = Field(default_factory=list, max_length=50)


class BuildingDefinitionPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    type: BuildingType | None = None
    # Written only when sent (explicit null clears). Changing `type` without sending them clears
    # both, so a definition never keeps the template of its previous type.
    template_id: TemplateId = None
    template_version: TemplateVersion = None
    stats: BuildingStats | None = None
    parameters: dict[str, ParamValue] | None = None
    criteria: list[Criterion] | None = Field(default=None, max_length=50)


class BuildingDefinition(BuildingDefinitionInput):
    id: UUID
    schema_version: int
    created_at: str
    updated_at: str


# --- templates --------------------------------------------------------------------------------


class TemplateParam(ApiModel):
    key: str
    label: str
    unit: str
    kind: Literal["number", "select"]
    options: list[str] | None = None
    hint: str | None = None


class BuildingTemplate(ApiModel):
    id: str  # == type for predefined templates
    version: int
    type: BuildingType
    label: str
    description: str
    category: BuildingCategory = "other"
    # Which stat sections the form emphasises; every section stays editable for every type.
    produces_power: bool = False
    produces_water: bool = False
    parameters: list[TemplateParam] = []
    # Numeric defaults only with a cited basis or an explicit demo_assumption label. Empty today.
    defaults: BuildingStats = BuildingStats()
    default_provenance: Provenance | None = None
    field_help: dict[str, str] = {}  # stat path -> help text, e.g. "power.averageDemandKw"


# --- presets: real example buildings with cited figures ----------------------------------------


class PresetSource(ApiModel):
    id: str  # short key cited in provenance notes, e.g. "S1"
    title: str
    publisher: str
    url: str
    year: str | None = None  # data year or publication year
    accessed: str | None = None  # ISO date the figure was checked


class ReferenceSite(ApiModel):
    """The real facility the figures describe (shown for context; dropping a preset places a new
    hypothetical building wherever the user chooses)."""

    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, lt=180)
    country: str


class BuildingPreset(ApiModel):
    """A ready-made definition based on one real facility. Every numeric value carries `cited`
    provenance whose note names the source id(s) and the figure or derivation; values the sources
    do not establish are left blank (unknown). Never typical coefficients."""

    id: str
    name: str
    type: BuildingType
    description: str
    headline: str  # short card line, e.g. "290 MW solar PV · Arizona"
    reference_site: ReferenceSite
    stats: BuildingStats
    parameters: dict[str, ParamValue] = {}
    sources: list[PresetSource]
    notes: list[str] = []  # derivations and caveats shown with the preset


# --- scenario assumptions and stress controls -------------------------------------------------


class StressControls(ApiModel):
    water_availability: float = Field(default=1.0, ge=0, le=1)
    power_availability: float = Field(default=1.0, ge=0, le=1)
    operating_demand: float = Field(default=1.0, ge=0, le=100)
    operating_prices: float = Field(default=1.0, ge=0, le=100)


BudgetKind = Literal["power_capacity_kw", "energy_kwh_per_day", "water_m3_per_day"]


class BudgetScope(ApiModel):
    kind: Literal["scenario", "region", "radius"]
    region: Literal["arizona", "uk"] | None = None  # prepared region box
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = None
    radius_km: Pos = None

    @model_validator(mode="after")
    def _complete(self):
        if self.kind == "region" and self.region is None:
            raise ValueError("a region scope needs a region")
        if self.kind == "radius" and None in (self.latitude, self.longitude, self.radius_km):
            raise ValueError("a radius scope needs latitude, longitude and radiusKm")
        if self.longitude is not None:
            _finite(self.longitude)
        return self


class ResourceBudget(ApiModel):
    """A pooled supply shared by every building inside its scope (counted once)."""

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    kind: BudgetKind
    amount: NonNeg = None  # declared external supply; None = unknown
    scope: BudgetScope = BudgetScope(kind="scenario")
    # Placed plants whose *net* output (gross output minus own consumption) is explicitly
    # declared as available to this pool. Nothing is connected automatically.
    contributing_project_ids: list[UUID] = []


def _contributors_counted_once(budgets: list[ResourceBudget] | None) -> None:
    """A plant's net output may feed only one pool of each kind, so it is never allocated twice."""
    first: dict[tuple[str, UUID], ResourceBudget] = {}
    for b in budgets or []:
        for pid in dict.fromkeys(b.contributing_project_ids):  # a repeat within one budget is harmless
            other = first.setdefault((b.kind, pid), b)
            if other is not b:
                raise ValueError(
                    f"building {pid} contributes to two {b.kind} budgets ('{other.label}' and "
                    f"'{b.label}'); its output can only be counted in one of them"
                )


class ScenarioAssumptions(ApiModel):
    schema_version: int = SCHEMA_VERSION
    period_days: float = Field(default=30, gt=0, le=MAX_PERIOD_DAYS)
    budgets: list[ResourceBudget] = Field(default_factory=list, max_length=50)
    stress: StressControls = StressControls()

    @model_validator(mode="after")
    def _no_double_counted_supply(self):
        _contributors_counted_once(self.budgets)
        return self


# --- calculation results ----------------------------------------------------------------------


class Quantity(ApiModel):
    value: float | None  # None = unknown
    unit: str
    basis: str = ""  # human-readable formula / assumption used
    missing: list[str] = []  # inputs that would be needed when value is None or partial


class MaterialTotal(ApiModel):
    name: str
    phase: Literal["construction", "operation"]
    quantity: Quantity


class EmissionTotal(ApiModel):
    pollutant: str
    medium: Literal['air', 'soil', 'freshwater', 'marine', 'climate'] = 'air'
    quantity: Quantity


class CostBreakdown(ApiModel):
    currency: str | None
    construction: Quantity
    operating_fixed: Quantity  # prorated to the period
    electricity: Quantity
    water: Quantity
    materials: Quantity
    operating_known_total: Quantity  # sum of known operating components; partial if missing
    missing: list[str] = []
    operating_cost_kind: Literal["total", "fixed"] = "fixed"
    # Set when the unit price used for that cost line is an explicitly chosen location default.
    electricity_price_source: PriceSource | None = None
    water_price_source: PriceSource | None = None


class BuildingResult(ApiModel):
    period_days: float
    operating_hours: Quantity  # hours over the period
    electricity_demand: Quantity  # kWh
    peak_demand: Quantity  # kW
    electricity_output: Quantity  # kWh, gross
    electricity_net: Quantity  # kWh, output - own demand (only for producers)
    water_demand: Quantity  # m3
    water_output: Quantity  # m3
    water_net: Quantity
    materials: list[MaterialTotal] = []
    emissions: list[EmissionTotal] = []
    light: Quantity  # upward lumens (declared, fixed)
    light_hours: Quantity  # lit hours over the period
    worker_capacity: Quantity
    staffing_required: Quantity
    footprint: Quantity
    costs: CostBreakdown
    demand_basis: Literal["direct", "derived"]


# Checks generated automatically from what the site can provide (app/site_capacity.py).
SiteCheckKind = Literal["site_land", "site_water", "site_power", "site_grid_export", "site_workforce", "site_air",
                        "site_light", "site_material"]


class CheckResult(ApiModel):
    criterion_id: str
    kind: CriterionKind | SiteCheckKind
    label: str
    required: bool
    status: CheckStatus
    actual: float | None = None
    required_value: float | None = None
    unit: str = ""
    period: str | None = None
    source: str = ""  # data source / slice or assumption used
    explanation: str = ""


class SuggestedPreset(ApiModel):
    id: str
    name: str
    capacity: float  # its output (kW or m³/day) or, for consumers, its demand (kW)
    unit: str
    count: int = 1  # how many it would take to cover the shortfall


class SupportSuggestion(ApiModel):
    """A building that could be placed alongside to cover a shortfall the site can't (power, water, export)."""

    resource: Literal["power", "water", "grid_export"]
    shortfall: float
    unit: str
    building_type: BuildingType  # type of the supporting building
    reach_km: float  # it must be placed within this distance (same or neighbouring hexagons)
    rings: int
    title: str
    explanation: str
    presets: list[SuggestedPreset] = []
    generic_name: str
    generic_stats: BuildingStats  # a building of the right size, scaled from a reference preset


class Assessment(ApiModel):
    state: AssessmentState
    checks: list[CheckResult]
    summary: str
    suggestions: list[SupportSuggestion] = []


# --- assessment API ---------------------------------------------------------------------------


class Bounds(ApiModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)


class LatLngIn(ApiModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float

    @field_validator("longitude")
    @classmethod
    def _finite_lon(cls, v):
        return _finite(v)


class AssessmentRequest(ApiModel):
    """Read-only: nothing is saved. Exactly one of location / bounds / region."""

    scenario_id: UUID | None = None
    type: BuildingType
    stats: BuildingStats = BuildingStats()
    parameters: dict[str, ParamValue] = {}
    criteria: list[Criterion] = Field(default_factory=list, max_length=50)
    site: SiteAssumptions = SiteAssumptions()  # only used for an exact location
    location: LatLngIn | None = None
    bounds: Bounds | None = None
    region: Literal["arizona", "uk"] | None = None
    exclude_project_id: UUID | None = None  # the building being moved/edited
    limit: int = Field(default=50, ge=1, le=500)  # candidates listed in detail

    @model_validator(mode="after")
    def _one_target(self):
        if sum(x is not None for x in (self.location, self.bounds, self.region)) != 1:
            raise ValueError("give exactly one of location, bounds or region")
        return self


# --- site suitability (graded, site_suitability.py) -------------------------------------------
# A graded "how ideal is this cell for the building type" from every relevant dataset. It never
# changes the hard assessment state. Types without a profile return None everywhere.

SuitabilityTier = Literal["ideal", "good", "marginal", "unsuitable"]


class SuitabilityFactor(ApiModel):
    """Static description of one factor in a profile."""

    key: str  # e.g. "soil_nitrogen"
    label: str
    group: str  # Soil | Climate | Terrain | Land | Water | Energy | People | Air | Hazards
    unit: str  # display unit of `FactorGrade.value`
    weight: float
    constraint: bool  # unsuitable here makes the whole cell unsuitable
    bands: str  # generated from the envelopes, e.g. "Ideal pH 6.0–7.5 · Good pH 5.5–8.0 · ..."
    layer_id: str | None  # catalogue layer to view the raw data (None for derived-only factors)
    slice_id: str | None
    source: str
    why: str


class SuitabilityProfile(ApiModel):
    id: str  # e.g. "farm:irrigated:cotton"
    label: str
    method: str  # the grading rule, shown verbatim
    factors: list[SuitabilityFactor]


class FactorGrade(ApiModel):
    key: str
    tier: SuitabilityTier | None  # None = no data at this cell
    value: float | None  # in the factor's display unit
    display: str  # "1.8 g/kg" or "no data"
    explanation: str


class Suitability(ApiModel):
    profile: SuitabilityProfile
    tier: SuitabilityTier | None  # None = not enough data to grade
    score: float | None  # 0–3, 2 dp
    coverage: float  # 0–1, share of factor weight with data
    limiting: list[str]  # factor keys graded marginal or unsuitable, worst first, then by weight
    summary: str
    factors: list[FactorGrade]  # same order as profile.factors


class CellState(ApiModel):
    h3_id: str
    state: AssessmentState
    tier: SuitabilityTier | None = None
    grades: str | None = None  # one char per profile factor: '1' ideal … '4' unsuitable, '0' no data


class Candidate(ApiModel):
    h3_id: str
    latitude: float
    longitude: float
    assessment: Assessment
    suitability: Suitability | None = None


PriceOfferStatus = Literal[
    "available",  # no price entered; the cell's price can be applied explicitly
    "entered",  # the user's own price is used (always wins); the location price is for reference
    "applied",  # this location's price is in use (chosen explicitly)
    "applied_elsewhere",  # a location default from another price area / value is in use
    "currency_mismatch",  # costs are in another currency: never converted, so not offered
    "not_used",  # all-inclusive operating cost: unit prices are not added
    "unavailable",  # the dataset has no price for this cell (blank, never assumed)
]


class LocationPriceOffer(ApiModel):
    """The cell's average business price, offered as an explicit, labelled location default."""

    resource: Literal["electricity", "water"]
    unit: str  # e.g. "USD/kWh"
    price: PriceSource | None  # what applying it would store; None when the dataset has no value
    status: PriceOfferStatus
    message: str


class SiteResourcePart(ApiModel):
    label: str
    value: float | None = None
    unit: str = ""
    text: str | None = None


class SiteResource(ApiModel):
    """One resource the site can provide (estimated from prepared data, never typed in)."""

    key: Literal["land", "water", "power", "workforce", "air", "light", "materials"]
    label: str
    unit: str
    available: float | None  # None = unknown here (outside data coverage)
    needed: float | None  # the building's own need, when its specs declare it
    reach: str  # how far around the cell the resource is gathered from
    parts: list[SiteResourcePart] = []
    note: str | None = None
    # Set when available/needed are not a simple "enough or not" (air, light, materials); the UI then
    # shows this instead of comparing numbers. "advisory" = shown for planning, never blocks.
    status: Literal["pass", "fail", "unknown", "none", "advisory"] | None = None
    advisory: bool = False  # raw materials: can be shipped, so never a requirement


class SiteCapacity(ApiModel):
    h3_id: str
    resources: list[SiteResource]
    neighbour_cells: list[str]  # ring-1 cells around the site, for the map
    rings: dict[str, int]  # H3 rings each resource reaches
    note: str


class LocationAssessment(ApiModel):
    latitude: float
    longitude: float
    h3_id: str
    result: BuildingResult
    assessment: Assessment
    site: SiteCapacity | None = None
    utility_prices: list[LocationPriceOffer] = []
    suitability: Suitability | None = None


class AreaAssessment(ApiModel):
    cell_count: int
    counts: dict[AssessmentState, int]
    cells: list[CellState]  # every assessed res-6 cell (state, suitability tier and grades), for the map
    # first `limit` in order: meets, insufficient, fails; then suitability tier (ideal … unsuitable,
    # ungraded last); then h3 id
    candidates: list[Candidate]
    result: BuildingResult  # location-independent calculation
    note: str  # screening caveat
    suitability: SuitabilityProfile | None = None
    tier_counts: dict[str, int] | None = None  # ideal, good, marginal, unsuitable, unknown


class AssessmentResponse(ApiModel):
    model_version: str = MODEL_VERSION
    schema_version: int = SCHEMA_VERSION
    period_days: float
    location: LocationAssessment | None = None
    area: AreaAssessment | None = None


# --- scenario evaluation ----------------------------------------------------------------------


class BudgetResult(ApiModel):
    id: str
    label: str
    kind: BudgetKind
    unit: str
    declared_supply: Quantity  # external amount x availability multiplier (+ contributions)
    demand: Quantity  # summed demand of buildings in scope, counted once
    unmet: Quantity  # max(0, demand - supply)
    project_ids: list[UUID]  # buildings in scope


class BuildingEvaluation(ApiModel):
    project_id: UUID
    name: str
    type: BuildingType
    result: BuildingResult
    assessment: Assessment


class ScenarioTotals(ApiModel):
    electricity_demand: Quantity
    electricity_output: Quantity
    electricity_net: Quantity  # everything generated minus everything used, across the world
    peak_demand: Quantity  # summed peaks: an upper bound (assumes they coincide)
    water_demand: Quantity
    water_output: Quantity
    water_net: Quantity  # everything produced minus everything used, across the world
    construction_cost: list[Quantity]  # one per currency
    operating_cost: list[Quantity]  # one per currency (known part)
    materials: list[MaterialTotal]  # summed by name + phase
    emissions: list[EmissionTotal]  # summed by pollutant, never across pollutants
    light: Quantity
    worker_capacity: Quantity
    staffing_required: Quantity
    footprint: Quantity
    unknown_buildings: dict[str, list[str]] = {}  # metric -> building names with unknown value


class ScenarioResult(ApiModel):
    buildings: list[BuildingEvaluation]
    budgets: list[BudgetResult]
    totals: ScenarioTotals


class EvaluateRequest(ApiModel):
    """Preview overrides for unsaved controls; the scenario's saved values are used otherwise."""

    stress: StressControls | None = None
    period_days: float | None = Field(default=None, gt=0, le=MAX_PERIOD_DAYS)
    budgets: list[ResourceBudget] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _no_double_counted_supply(self):
        _contributors_counted_once(self.budgets)
        return self


class ScenarioEvaluation(ApiModel):
    model_version: str = MODEL_VERSION
    schema_version: int = SCHEMA_VERSION
    scenario_id: UUID
    period_days: float
    stress: StressControls
    inputs_hash: str  # identifies buildings + assumptions + source slices used
    unstressed: ScenarioResult
    stressed: ScenarioResult
    control_notes: dict[str, str]  # control -> why it has / has no calculable effect

