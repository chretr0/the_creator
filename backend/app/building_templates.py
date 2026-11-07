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


# Type-specific fields for the newer types describe the facility (scale, process, product). They are
# recorded with the building and shown back, but resource use, outputs and costs always come from the
# common statistics: no coefficient is derived from them.
DESCRIPTIVE = "Recorded with the building; not used in calculations."


def _n(key: str, label: str, unit: str, hint: str | None = None) -> TemplateParam:
    return TemplateParam(key=key, label=label, unit=unit, kind="number",
                         hint=f"{hint}. {DESCRIPTIVE}" if hint else DESCRIPTIVE)


def _s(key: str, label: str, options: list[str], hint: str | None = None) -> TemplateParam:
    return TemplateParam(key=key, label=label, unit="", kind="select", options=options,
                         hint=f"{hint}. {DESCRIPTIVE}" if hint else DESCRIPTIVE)


_PCT = "0–100 %"

_WIND_PARAMS = [
    _s("siting", "Siting", ["onshore", "offshore"]),
    _n("turbineCount", "Turbines", "count"),
    _n("turbineRatingKw", "Turbine rating", "kW", "Nameplate rating of one turbine"),
    _n("hubHeightM", "Hub height", "m"),
    _n("rotorDiameterM", "Rotor diameter", "m"),
]
_HYDRO_PARAMS = [
    _s("scheme", "Scheme", ["reservoir", "run_of_river", "pumped_storage"]),
    _n("grossHeadM", "Gross head", "m", "Height difference between intake and tailwater"),
    _n("designFlowM3PerS", "Design flow", "m³/s", "Turbine flow at rated output"),
    _n("reservoirAreaKm2", "Reservoir area", "km²", "Surface area at full supply level"),
    _n("storageEnergyMwh", "Storage energy", "MWh", "Pumped storage: energy stored when full"),
]
_GEOTHERMAL_PARAMS = [
    _s("cycle", "Plant cycle", ["dry_steam", "flash", "binary"]),
    _n("productionWells", "Production wells", "count"),
    _n("reservoirTempC", "Reservoir temperature", "°C"),
    _n("wellDepthM", "Typical well depth", "m"),
]
_BATTERY_PARAMS = [
    _s("chemistry", "Chemistry", ["lithium_ion_lfp", "lithium_ion_nmc", "sodium_ion", "flow", "other"]),
    _n("energyCapacityKwh", "Energy capacity", "kWh", "Usable stored energy when full"),
    _n("powerRatingKw", "Power rating", "kW", "Maximum charge/discharge power"),
    _n("roundTripEfficiency", "Round-trip efficiency", "0–1", "Energy discharged ÷ energy charged"),
]
_HYDROGEN_PARAMS = [
    _s("process", "Process", ["pem_electrolysis", "alkaline_electrolysis", "solid_oxide_electrolysis",
                              "steam_methane_reforming", "smr_with_ccs"]),
    _n("electrolyserCapacityKw", "Electrolyser capacity", "kW"),
    _n("hydrogenOutputKgPerDay", "Hydrogen output", "kg/day"),
]
_WASTEWATER_PARAMS = [
    _s("treatmentLevel", "Treatment level", ["primary", "secondary", "tertiary", "advanced_reuse"]),
    _n("populationEquivalent", "Population equivalent", "PE", "Load served, in population equivalents"),
    _n("designFlowM3PerDay", "Design flow", "m³/day", "Average dry-weather design flow"),
]
_MINE_PARAMS = [
    _s("commodity", "Commodity", ["copper", "gold", "silver", "iron_ore", "coal", "lithium", "nickel", "zinc",
                                  "uranium", "potash", "phosphate", "rare_earths", "bauxite", "diamonds", "other"]),
    _s("miningMethod", "Mining method", ["open_pit", "underground", "strip", "in_situ_leach", "brine_evaporation"]),
    _n("oreThroughputTPerDay", "Ore throughput", "t/day", "Ore mined or processed per day"),
    _n("oreGradePercent", "Ore grade", _PCT, "Average head grade as a percentage of ore mass"),
    _n("productionTPerYear", "Saleable production", "t/yr"),
    _n("mineLifeYears", "Mine life", "years"),
]
_QUARRY_PARAMS = [
    _s("material", "Material", ["limestone", "granite", "basalt", "sandstone", "sand_gravel", "clay", "marble",
                                "gypsum", "other"]),
    _n("extractionTPerYear", "Extraction", "t/yr"),
    _n("pitDepthM", "Pit depth", "m"),
]
_OIL_GAS_PARAMS = [
    _s("product", "Product", ["oil", "gas", "oil_and_gas"]),
    _s("setting", "Setting", ["onshore", "offshore"]),
    _n("wellCount", "Producing wells", "count"),
    _n("oilBblPerDay", "Oil production", "bbl/day"),
    _n("gasM3PerDay", "Gas production", "m³/day"),
]
_FACTORY_PARAMS = [
    _s("sector", "Sector", ["automotive", "electronics", "machinery", "batteries", "textiles", "pharmaceuticals",
                            "plastics", "paper", "glass", "furniture", "aerospace", "general"]),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
    _n("outputUnitsPerYear", "Output", "units/yr", "Finished units produced per year"),
    _n("shiftsPerDay", "Shifts per day", "count"),
]
_STEEL_PARAMS = [
    _s("route", "Process route", ["bf_bof", "eaf", "dri_eaf"],
       "bf_bof = blast furnace + basic oxygen; eaf = electric arc on scrap; dri_eaf = direct reduced iron + EAF"),
    _n("crudeSteelTPerYear", "Crude steel capacity", "t/yr"),
]
_SMELTER_PARAMS = [
    _n("primaryAluminiumTPerYear", "Primary aluminium capacity", "t/yr"),
    _n("potlineCount", "Potlines", "count"),
    _n("lineCurrentKa", "Line current", "kA"),
]
_CEMENT_PARAMS = [
    _s("kilnProcess", "Kiln process", ["dry_precalciner", "dry", "semi_dry", "wet"]),
    _n("clinkerTPerYear", "Clinker capacity", "t/yr"),
    _n("cementTPerYear", "Cement capacity", "t/yr"),
]
_CHEMICAL_PARAMS = [
    _s("primaryProduct", "Primary product", ["ammonia", "fertiliser", "methanol", "ethylene", "propylene",
                                             "chlorine_alkali", "polymers", "sulphuric_acid", "pharmaceutical_api",
                                             "specialty", "other"]),
    _n("outputTPerYear", "Output", "t/yr"),
]
_REFINERY_PARAMS = [
    _n("crudeCapacityBblPerDay", "Crude distillation capacity", "bbl/day"),
    _n("nelsonComplexityIndex", "Nelson complexity index", "index"),
]
_FAB_PARAMS = [
    _s("waferSizeMm", "Wafer size", ["150", "200", "300"]),
    _n("waferStartsPerMonth", "Wafer starts", "wafers/month"),
    _n("processNodeNm", "Leading process node", "nm"),
    _n("cleanroomAreaM2", "Cleanroom area", "m²"),
]
_FARM_PARAMS = [
    _s("cropType", "Main crop", ["wheat", "maize", "rice", "soybean", "barley", "cotton", "sugarcane", "potatoes",
                                 "vegetables", "fruit_orchard", "vineyard", "nuts", "alfalfa_hay", "mixed", "other"]),
    _s("irrigation", "Irrigation", ["rainfed", "centre_pivot", "sprinkler", "drip", "furrow_flood"]),
    _n("cultivatedAreaHa", "Cultivated area", "ha", "Separate from the occupied footprint in m²"),
    _n("yieldTPerHa", "Yield", "t/ha/yr"),
]
_LIVESTOCK_PARAMS = [
    _s("species", "Livestock", ["dairy_cattle", "beef_cattle", "pigs", "poultry_layers", "poultry_broilers",
                                "sheep_goats", "mixed"]),
    _s("housing", "Housing system", ["housed", "feedlot", "pasture", "mixed"]),
    _n("headCount", "Animals", "head", "Average standing herd or flock"),
    _n("grazingAreaHa", "Grazing area", "ha"),
]
_VERTICAL_FARM_PARAMS = [
    _n("growingAreaM2", "Growing area", "m²", "Total cultivated shelf area over all tiers"),
    _n("tierCount", "Growing tiers", "count"),
    _n("cropOutputKgPerYear", "Crop output", "kg/yr"),
]
_AQUACULTURE_PARAMS = [
    _s("system", "System", ["marine_net_pen", "freshwater_pond", "recirculating_ras", "flow_through",
                            "shellfish_longline"]),
    _s("species", "Species", ["salmon", "trout", "shrimp", "tilapia", "carp", "catfish", "oysters_mussels",
                              "seaweed", "other"]),
    _n("productionTPerYear", "Production", "t/yr"),
    _n("waterAreaM2", "Water surface area", "m²"),
]
_FOOD_PARAMS = [
    _s("product", "Product", ["dairy", "meat_poultry", "beverages", "brewing_distilling", "bakery",
                              "grain_milling", "sugar", "fruit_vegetables", "edible_oils", "confectionery", "other"]),
    _n("rawInputTPerYear", "Raw material input", "t/yr"),
    _n("outputTPerYear", "Product output", "t/yr"),
]
_OFFICE_PARAMS = [
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
    _n("floorCount", "Floors", "count"),
    _n("heightM", "Height", "m"),
]
_RETAIL_PARAMS = [
    _s("format", "Format", ["shopping_centre", "supermarket", "hypermarket", "retail_park", "high_street",
                            "outlet", "department_store"]),
    _n("grossLeasableAreaM2", "Gross leasable area", "m²"),
    _n("parkingSpaces", "Parking spaces", "count"),
]
_HOTEL_PARAMS = [
    _n("roomCount", "Rooms", "count"),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
    _n("starRating", "Star rating", "1–5"),
]
_LAB_PARAMS = [
    _s("biosafetyLevel", "Highest biosafety level", ["none", "bsl1", "bsl2", "bsl3", "bsl4"]),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
    _n("labAreaM2", "Laboratory area", "m²"),
]
_HOUSING_PARAMS = [
    _s("form", "Housing form", ["detached", "semi_detached", "terraced", "low_rise_apartments",
                                "high_rise_apartments", "mixed"]),
    _n("dwellingCount", "Dwellings", "count"),
    _n("residentCapacity", "Residents", "people", "Residents housed. Worker capacity stays the on-site staff"),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
]
_HOSPITAL_PARAMS = [
    _s("level", "Level of care", ["community", "general", "tertiary_teaching", "specialist"]),
    _n("bedCount", "Beds", "count"),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
]
_SCHOOL_PARAMS = [
    _s("level", "Level", ["primary", "secondary", "all_through", "special"]),
    _n("studentCapacity", "Student places", "pupils"),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
]
_UNIVERSITY_PARAMS = [
    _n("studentCount", "Students", "people", "Enrolled students (headcount)"),
    _n("campusAreaHa", "Campus area", "ha"),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
]
_STADIUM_PARAMS = [
    _s("roof", "Roof", ["open", "partial", "retractable", "enclosed"]),
    _n("seatCapacity", "Seats", "count"),
    _n("eventsPerYear", "Events", "per year"),
]
_AIRPORT_PARAMS = [
    _n("runwayCount", "Runways", "count"),
    _n("longestRunwayM", "Longest runway", "m"),
    _n("passengersPerYear", "Passengers", "per year"),
    _n("cargoTPerYear", "Cargo", "t/yr"),
]
_SEAPORT_PARAMS = [
    _n("berthCount", "Berths", "count"),
    _n("containerTeuPerYear", "Container throughput", "TEU/yr"),
    _n("cargoTPerYear", "Total cargo", "t/yr"),
    _n("maxDraughtM", "Maximum draught", "m"),
]
_WAREHOUSE_PARAMS = [
    _s("temperature", "Temperature regime", ["ambient", "chilled", "frozen", "mixed"]),
    _n("grossFloorAreaM2", "Gross floor area", "m²"),
    _n("clearHeightM", "Clear height", "m"),
    _n("dockDoors", "Loading docks", "count"),
]
_LANDFILL_PARAMS = [
    _s("gasManagement", "Landfill gas", ["none", "flaring", "energy_recovery"]),
    _n("wasteAcceptedTPerYear", "Waste accepted", "t/yr"),
    _n("permittedCapacityM3", "Permitted void capacity", "m³"),
]
_RECYCLING_PARAMS = [
    _s("material", "Main stream", ["mixed_dry_recyclables", "paper_card", "plastics", "metals", "glass",
                                   "e_waste", "construction_demolition", "organics_compost", "textiles", "batteries"]),
    _n("throughputTPerYear", "Throughput", "t/yr"),
]
_WTE_PARAMS = [
    _s("technology", "Technology", ["moving_grate", "fluidised_bed", "gasification", "anaerobic_digestion"]),
    _s("mode", "Mode", ["electricity_only", "combined_heat_power"]),
    _n("wasteThroughputTPerYear", "Waste throughput", "t/yr"),
]


def _t(type_: str, label: str, category: str, description: str, *, power=False, water=False, params=(),
       help_=None):
    if params and any(p.hint and p.hint.endswith(DESCRIPTIVE) for p in params):
        description += " Type-specific fields describe the facility; resource use comes from the common statistics."
    return BuildingTemplate(
        id=type_,
        version=TEMPLATE_VERSION,
        type=type_,
        label=label,
        category=category,
        description=description,
        produces_power=power,
        produces_water=water,
        parameters=list(params),
        field_help={**COMMON_HELP, **(help_ or {})},
    )


_GEN_HELP = {"power.technology": "Generation technology. Descriptive only: no coefficients are inferred from it."}

TEMPLATES: list[BuildingTemplate] = [
    # --- energy --------------------------------------------------------------------------------
    _t(
        "power_station",
        "Power station",
        "energy",
        "Generates electricity. Enter output (average, or rated with a capacity factor) separately from "
        "the station's own electricity and water use, and describe the technology. No generic thermal "
        "or renewable coefficients are assumed.",
        power=True,
        help_={"power.technology": "Generation technology, e.g. 'single-axis PV', 'gas CCGT'. Descriptive "
               "only: no coefficients are inferred from it."},
    ),
    _t(
        "solar",
        "Solar generation",
        "energy",
        "Photovoltaic generation. Give an output assumption (average, or rated with a capacity factor), "
        "or peak capacity and performance ratio to use NASA POWER irradiation at the placed location.",
        power=True,
        params=_SOLAR_PARAMS,
    ),
    _t("wind_farm", "Wind farm", "energy",
       "Wind turbines onshore or offshore. Enter output as average kW, or rated kW with a capacity factor; "
       "turbine count × rating is not converted into generated energy.", power=True, params=_WIND_PARAMS,
       help_=_GEN_HELP),
    _t("hydro_plant", "Hydroelectric plant", "energy",
       "Reservoir, run-of-river or pumped-storage hydropower. Enter output as average kW, or rated kW with a "
       "capacity factor. Water passing through turbines is not consumption; enter only water actually consumed "
       "(e.g. reservoir evaporation) as water input.", power=True, params=_HYDRO_PARAMS, help_=_GEN_HELP),
    _t("geothermal_plant", "Geothermal plant", "energy",
       "Electricity from geothermal steam or brine. Enter output, own electricity use and cooling-water make-up "
       "separately.", power=True, params=_GEOTHERMAL_PARAMS, help_=_GEN_HELP),
    _t("battery_storage", "Battery storage", "energy",
       "Grid battery. Average output is the average discharge and average demand the average charging power, "
       "so the net output over the period shows the round-trip losses. It stores electricity; it does not "
       "generate it.", power=True, params=_BATTERY_PARAMS,
       help_={"power.averageOutputKw": "Average discharge power over operating hours, in kW.",
              "power.averageDemandKw": "Average charging power (plus auxiliary load) over operating hours, in kW."}),
    _t("hydrogen_plant", "Hydrogen plant", "energy",
       "Produces hydrogen, usually by electrolysis (large electricity and purified-water demand) or by steam "
       "methane reforming. Enter electricity and water demand directly; hydrogen output is recorded in the "
       "type-specific fields.", params=_HYDROGEN_PARAMS),
    # --- water ---------------------------------------------------------------------------------
    _t(
        "water_plant",
        "Water plant",
        "water",
        "Treats or produces water. Enter usable output separately from water input and electricity "
        "demand, and state the water/process basis. No generic treatment or desalination coefficients "
        "are assumed.",
        water=True,
        help_={"water.basis": "Source water and process, e.g. 'seawater RO', 'river abstraction, "
               "conventional treatment'. Descriptive only."},
    ),
    _t("wastewater_plant", "Wastewater treatment", "water",
       "Treats municipal or industrial sewage. Water input is the sewage treated (source: wastewater, so it draws "
       "no river water); water output is the treated effluent made available for reuse, if any.",
       water=True, params=_WASTEWATER_PARAMS,
       help_={"water.outputM3PerHour": "Treated effluent delivered for reuse, in m³/hour. Leave blank if it is "
              "only discharged to a river or the sea."}),
    # --- mining & extraction -------------------------------------------------------------------
    _t("mine", "Mine", "extraction",
       "Open-pit, underground or solution mine with its processing plant. Enter process water, electricity, "
       "diesel and reagents (as operational materials) and dust emissions you know; the commodity and grade "
       "are descriptive.", params=_MINE_PARAMS),
    _t("quarry", "Quarry", "extraction",
       "Aggregate, dimension-stone or industrial-mineral quarry. Dust and blasting emissions go under emissions; "
       "extracted tonnage is descriptive.", params=_QUARRY_PARAMS),
    _t("oil_gas_field", "Oil & gas field", "extraction",
       "Production wells with their gathering and processing facilities. Enter flaring and venting as emissions "
       "per pollutant; production volumes are descriptive.", params=_OIL_GAS_PARAMS),
    # --- industry & manufacturing --------------------------------------------------------------
    _t("factory", "Factory", "industry",
       "General manufacturing or assembly plant. Pick the sector and enter the plant's electricity, water and "
       "material flows.", params=_FACTORY_PARAMS),
    _t("steel_mill", "Steel mill", "industry",
       "Integrated (blast furnace) or electric-arc steelmaking. Iron ore, coking coal and scrap are operational "
       "materials; the process route does not set any coefficient.", params=_STEEL_PARAMS),
    _t("aluminium_smelter", "Aluminium smelter", "industry",
       "Primary aluminium by electrolysis: a very large, continuous electricity user. Alumina, carbon anodes and "
       "other inputs are operational materials.", params=_SMELTER_PARAMS),
    _t("cement_plant", "Cement plant", "industry",
       "Clinker kiln and cement grinding. Limestone, clay and kiln fuel are operational materials; CO₂, NOx, "
       "SO₂ and dust go under emissions.", params=_CEMENT_PARAMS),
    _t("chemical_plant", "Chemical plant", "industry",
       "Chemical or fertiliser production (ammonia, methanol, olefins, chlor-alkali …). Feedstocks are "
       "operational materials.", params=_CHEMICAL_PARAMS),
    _t("oil_refinery", "Oil refinery", "industry",
       "Crude-oil refinery. Crude intake can be entered as an operational material in kg; capacity in barrels "
       "per day and complexity are descriptive.", params=_REFINERY_PARAMS),
    _t("semiconductor_fab", "Semiconductor fab", "industry",
       "Wafer fabrication plant: continuous cleanroom operation with high electricity and ultrapure-water "
       "demand.", params=_FAB_PARAMS),
    # --- agriculture & food --------------------------------------------------------------------
    _t("farm", "Crop farm", "agriculture",
       "Arable land, orchards or vineyards. Irrigation water goes in water input (m³/hour while irrigating, with "
       "operating hours); fertiliser, seed and diesel are operational materials.", params=_FARM_PARAMS),
    _t("livestock_farm", "Livestock farm", "agriculture",
       "Dairy, beef, pig, poultry or sheep farm. Drinking and washing water go in water input; feed is an "
       "operational material; ammonia and methane go under emissions.", params=_LIVESTOCK_PARAMS),
    _t(
        "greenhouse",
        "Greenhouse",
        "agriculture",
        "Controlled-environment growing. The existing floor-area and heat fields are kept; occupied "
        "footprint is entered separately.",
        params=_GREENHOUSE_PARAMS,
    ),
    _t("vertical_farm", "Vertical farm", "agriculture",
       "Indoor, multi-tier growing under LED lighting: electricity-intensive, low water use.",
       params=_VERTICAL_FARM_PARAMS),
    _t("aquaculture", "Aquaculture", "agriculture",
       "Fish, shellfish or seaweed farming in sea pens, ponds or recirculating tanks. Feed is an operational "
       "material.", params=_AQUACULTURE_PARAMS),
    _t("food_processing", "Food processing plant", "agriculture",
       "Dairy, meat, beverage, milling or other food and drink manufacturing. Raw produce is an operational "
       "material.", params=_FOOD_PARAMS),
    # --- commercial & digital ------------------------------------------------------------------
    _t(
        "data_centre",
        "Data centre",
        "commercial",
        "Computing facility. Electricity and water can be entered directly or derived from IT power, "
        "load fraction, PUE and WUE (choose one basis).",
        params=_DATA_CENTRE_PARAMS,
    ),
    _t("office", "Office building", "commercial",
       "Offices. Worker capacity is the number of occupants it can accommodate at once.", params=_OFFICE_PARAMS),
    _t("retail", "Retail centre", "commercial",
       "Shopping centre, supermarket or retail park.", params=_RETAIL_PARAMS),
    _t("hotel", "Hotel", "commercial",
       "Hotel or resort. Guests are not workers: worker capacity is staff.", params=_HOTEL_PARAMS),
    _t("research_lab", "Research laboratory", "commercial",
       "Laboratory building or research campus; labs usually run continuous ventilation.", params=_LAB_PARAMS),
    # --- housing & public services -------------------------------------------------------------
    _t("housing", "Housing", "community",
       "Homes and apartments. Residents are recorded separately from worker capacity (on-site staff).",
       params=_HOUSING_PARAMS),
    _t("hospital", "Hospital", "community",
       "Hospital or medical centre: continuous operation with high electricity, heat and water use.",
       params=_HOSPITAL_PARAMS),
    _t("school", "School", "community", "Primary or secondary school. Pupils are not workers.",
       params=_SCHOOL_PARAMS),
    _t("university", "University campus", "community",
       "University or college campus with teaching, research and residential buildings.",
       params=_UNIVERSITY_PARAMS),
    _t("stadium", "Stadium & arena", "community",
       "Sports stadium or arena. Floodlighting is a major upward-light source; enter it under light.",
       params=_STADIUM_PARAMS),
    # --- transport & logistics -----------------------------------------------------------------
    _t("airport", "Airport", "transport",
       "Passenger and cargo airport (terminals, airfield lighting, ground operations). Aircraft fuel is not "
       "counted unless you add it as an operational material.", params=_AIRPORT_PARAMS),
    _t("seaport", "Seaport", "transport",
       "Container, bulk or passenger port with its cranes, yards and shore power.", params=_SEAPORT_PARAMS),
    _t("warehouse", "Warehouse & logistics", "transport",
       "Distribution centre or cold store.", params=_WAREHOUSE_PARAMS),
    # --- waste & recycling ---------------------------------------------------------------------
    _t("landfill", "Landfill", "waste",
       "Engineered landfill. Landfill-gas methane goes under emissions; flaring or energy recovery is "
       "descriptive unless you enter output on a separate waste-to-energy building.", params=_LANDFILL_PARAMS),
    _t("recycling_facility", "Recycling facility", "waste",
       "Materials-recovery, sorting, reprocessing or composting facility.", params=_RECYCLING_PARAMS),
    _t("waste_to_energy", "Waste-to-energy plant", "waste",
       "Burns or digests waste to generate electricity (and heat). Enter output as for a power station; waste "
       "accepted is an operational material or the descriptive throughput.", power=True, params=_WTE_PARAMS,
       help_=_GEN_HELP),
    # --- other ---------------------------------------------------------------------------------
    _t(
        "custom",
        "Custom building",
        "other",
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

# Descriptive parameters of the newer types: non-negative numbers, with these narrower ranges.
_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "oreGradePercent": (0, 100),
    "roundTripEfficiency": (0, 1),
    "starRating": (1, 5),
    "shiftsPerDay": (0, 4),
    "reservoirTempC": (-273.15, None),
}
_LEGACY = set(NUMERIC_PARAMS) | {"power_station", "water_plant", "custom"}
for _tpl in TEMPLATES:
    if _tpl.id in _LEGACY:
        continue
    for _p in _tpl.parameters:
        if _p.kind == "number":
            NUMERIC_PARAMS.setdefault(_tpl.id, {})[_p.key] = _BOUNDS.get(_p.key, (0, None))
        else:
            SELECT_PARAMS.setdefault(_tpl.id, {})[_p.key] = tuple(_p.options or ())

POWER_PRODUCERS = frozenset(t.type for t in TEMPLATES if t.produces_power)
WATER_PRODUCERS = frozenset(t.type for t in TEMPLATES if t.produces_water)
