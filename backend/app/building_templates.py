"""Predefined building templates (CLAUDE.Building-System.md section 4).

Templates are forms: field names, units and help text. They carry no numeric defaults, because the
repository has no cited source for typical coefficients and the spec forbids plausible-looking
placeholders. Every value a user enters is a ``user_assumption``.

The type-specific ``parameters`` lists are the legacy scalar fields from
frontend/src/lib/projectTypes.ts, kept so existing projects keep their meaning.
"""

from __future__ import annotations

from app.building_models import BuildingTemplate, TemplateParam

TEMPLATE_VERSION = 1

# Help text for the common statistics, keyed by camelCase stat path (as the form sends them).
COMMON_HELP: dict[str, str] = {
    "footprintM2": "Occupied ground area in m². Not a greenhouse's floor area and not the H3 cell area; "
    "an H3 cell is not evidence of vacant or buildable land.",
    "operatingHoursPerDay": "Hours per day the building operates (0–24). Electricity, water and emissions "
    "rates are multiplied by these hours over the scenario period. Blank = unknown.",
    "power.averageDemandKw": "Average electricity drawn while operating, in kW. Energy over the period = "
    "this × operating hours.",
    "power.peakDemandKw": "Highest expected draw in kW. Used only for connected-capacity checks, never "
    "as an energy total.",
    "power.averageOutputKw": "Average gross electricity output while operating, in kW (before the "
    "building's own consumption).",
    "power.ratedOutputKw": "Nameplate output in kW. Needs a capacity factor before it can give energy.",
    "power.capacityFactor": "Fraction (0–1) of rated output delivered on average while operating. "
    "Required with rated output; there is no default.",
    "power.technology": "Free-text description of the technology or process. No coefficients are "
    "inferred from it.",
    "water.inputM3PerHour": "Water consumed while operating, in m³/hour.",
    "water.outputM3PerHour": "Usable treated or produced water while operating, in m³/hour. A treatment "
    "capacity is not a water abstraction allocation.",
    "water.basis": "Water source and process, e.g. 'brackish groundwater, reverse osmosis'.",
    "materials": "Named raw materials in kg (tonnes × 1000). Construction quantities count once per "
    "building; operational quantities need a period (per hour/day/month/year).",
    "emissions": "Emission rate per named pollutant in kg/hour while operating. Reported separately per "
    "pollutant; never converted into a concentration change.",
    "light.upwardLumens": "Declared upward luminous flux in lumens: a simple emitted-light proxy, not "
    "predicted sky brightness or a measured light-pollution index.",
    "light.hoursPerDay": "Hours per day the declared lighting is on.",
    "workers.capacity": "Maximum number of workers the building can accommodate at one time. Does not "
    "establish available labour or jobs created.",
    "workers.staffingRequired": "Number of staff the building needs, if known.",
    "costs.currency": "ISO 4217 code (e.g. USD, GBP). Amounts in different currencies are never converted "
    "or added together.",
    "costs.constructionTotal": "One-time construction cost, counted once per building.",
    "costs.priceBasis": "Price year and source, e.g. '2025 prices, vendor quote'.",
    "costs.operating.amount": "Operating cost per the selected period; prorated to the scenario period "
    "with 30.4375 days/month and 365.25 days/year.",
    "costs.operating.kind": "'total' = all-inclusive (resource prices are not added on top); 'fixed' = "
    "fixed component only (known electricity, water and material costs are added).",
    "costs.electricityPricePerKwh": "Unit price of consumed electricity, per kWh.",
    "costs.waterPricePerM3": "Unit price of consumed water, per m³.",
    "demandBasis": "Data centres: 'derived' computes electricity from IT power × load fraction × PUE and "
    "water from WUE; 'direct' uses average demand and water input. Never both.",
}

_DATA_CENTRE_PARAMS = [
    TemplateParam(key="itPowerKw", label="IT power", unit="kW", kind="number",
                  hint="IT equipment power at full load"),
    TemplateParam(key="loadFraction", label="Load fraction", unit="0–1", kind="number",
                  hint="Average fraction of IT power in use"),
    TemplateParam(key="pue", label="PUE", unit="ratio", kind="number",
                  hint="facility energy ÷ IT energy (at least 1)"),
    TemplateParam(key="wueLPerKwh", label="WUE", unit="L/kWh", kind="number",
                  hint="Litres of water per kWh on the selected basis"),
    TemplateParam(key="wueBasis", label="WUE basis", unit="", kind="select",
                  options=["it_energy", "facility_energy"],
                  hint="Whether WUE is per kWh of IT energy or of total facility energy"),
    TemplateParam(key="heatRecoveryFraction", label="Heat recovery fraction", unit="0–1", kind="number"),
]

_SOLAR_PARAMS = [
    TemplateParam(key="capacityKwp", label="Peak capacity", unit="kWp", kind="number",
                  hint="DC peak capacity under standard test conditions; not a constant output in kW"),
    TemplateParam(key="landAreaM2", label="Occupied land", unit="m²", kind="number"),
    TemplateParam(key="performanceRatio", label="Performance ratio", unit="0–1", kind="number",
                  hint="Energy delivered ÷ (kWp × irradiation in kWh/m²); with kWp and a location, "
                  "energy = kWp × NASA POWER daily irradiation × PR"),
]

_GREENHOUSE_PARAMS = [
    TemplateParam(key="floorAreaM2", label="Floor area", unit="m²", kind="number",
                  hint="Growing floor area; separate from the occupied footprint"),
    TemplateParam(key="heatDemandKwhPerYear", label="Heat demand", unit="kWh/yr", kind="number"),
    TemplateParam(key="minSupplyTempC", label="Min. supply temperature", unit="°C", kind="number"),
]


def _t(type_: str, label: str, description: str, *, power=False, water=False, params=(), help_=None):
    return BuildingTemplate(
        id=type_,
        version=TEMPLATE_VERSION,
        type=type_,
        label=label,
        description=description,
        produces_power=power,
        produces_water=water,
        parameters=list(params),
        field_help={**COMMON_HELP, **(help_ or {})},
    )


TEMPLATES: list[BuildingTemplate] = [
    _t(
        "power_station",
        "Power station",
        "Generates electricity. Enter output (average, or rated with a capacity factor) separately from "
        "the station's own electricity and water use, and describe the technology. No generic thermal "
        "or renewable coefficients are assumed.",
        power=True,
        help_={"power.technology": "Generation technology, e.g. 'single-axis PV', 'gas CCGT'. Descriptive "
               "only: no coefficients are inferred from it."},
    ),
    _t(
        "water_plant",
        "Water plant",
        "Treats or produces water. Enter usable output separately from water input and electricity "
        "demand, and state the water/process basis. No generic treatment or desalination coefficients "
        "are assumed.",
        water=True,
        help_={"water.basis": "Source water and process, e.g. 'seawater RO', 'river abstraction, "
               "conventional treatment'. Descriptive only."},
    ),
    _t(
        "data_centre",
        "Data centre",
        "Computing facility. Electricity and water can be entered directly or derived from IT power, "
        "load fraction, PUE and WUE (choose one basis).",
        params=_DATA_CENTRE_PARAMS,
    ),
    _t(
        "solar",
        "Solar generation",
        "Photovoltaic generation. Give an output assumption (average, or rated with a capacity factor), "
        "or peak capacity and performance ratio to use NASA POWER irradiation at the placed location.",
        power=True,
        params=_SOLAR_PARAMS,
    ),
    _t(
        "greenhouse",
        "Greenhouse",
        "Controlled-environment growing. The existing floor-area and heat fields are kept; occupied "
        "footprint is entered separately.",
        params=_GREENHOUSE_PARAMS,
    ),
    _t(
        "custom",
        "Custom building",
        "Any other building: describe it and enter the statistics you know. Blank fields stay unknown.",
        power=False,
        water=False,
    ),
]

BY_ID = {t.id: t for t in TEMPLATES}

# Inclusive numeric bounds for the legacy scalar parameters: key -> (min, max); None = unbounded.
NUMERIC_PARAMS: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "data_centre": {
        "itPowerKw": (0, None),
        "loadFraction": (0, 1),
        "pue": (1, None),
        "wueLPerKwh": (0, None),
        "heatRecoveryFraction": (0, 1),
    },
    "solar": {"capacityKwp": (0, None), "landAreaM2": (0, None), "performanceRatio": (0, 1)},
    "greenhouse": {"floorAreaM2": (0, None), "heatDemandKwhPerYear": (0, None), "minSupplyTempC": (-273.15, None)},
}
SELECT_PARAMS: dict[str, dict[str, tuple[str, ...]]] = {
    "data_centre": {"wueBasis": ("it_energy", "facility_energy")},
}
