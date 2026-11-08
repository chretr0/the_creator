#!/usr/bin/env python3
"""Seed showcase demo worlds through the running API (so every building is validated like a user's).

Earth worlds are built from the cited building presets (backend/app/presets/building_presets.json).
A preset used as-is keeps its cited figures. Where a world needs a different size, or a figure the
sources leave unknown, the changed section is relabelled ``demo_assumption`` with a note saying
exactly what was scaled or assumed; nothing is presented as cited that is not. Buildings that are
meant to work together sit in the same or neighbouring H3 cells (so a power station's export or a
water plant's output feeds them in the site checks) and are tied together by declared resource
budgets (CLAUDE.Building-System.md: a plant's net output only counts when it is listed).

Moon worlds use the Moon catalogue (shared/moon_buildings.json); values that differ from its
defaults are explained in the building's description.

Usage (backend running on :8000):
    python3 scripts/seed_demo_worlds.py              # create the worlds that do not exist yet
    python3 scripts/seed_demo_worlds.py --replace    # delete and recreate worlds with these names
    python3 scripts/seed_demo_worlds.py --only "Humber"   # worlds whose name contains this text

Only worlds whose names are listed in WORLDS are ever deleted (and only with --replace).
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

EARTH_RADIUS_KM = 6371.0088
MOON_RADIUS_KM = 1737.4
NOTE_MAX = 2000
DESC_MAX = 5000

# --- geometry ---------------------------------------------------------------------------------


def offset(origin: tuple[float, float], east_km: float, north_km: float, radius_km: float) -> tuple[float, float]:
    """Point `east_km` / `north_km` from `origin` along a great circle (works near the poles too)."""
    lat, lon = origin
    d = math.hypot(east_km, north_km)
    if d == 0:
        return lat, lon
    brg = math.atan2(east_km, north_km)
    p1, l1, delta = math.radians(lat), math.radians(lon), d / radius_km
    p2 = math.asin(math.sin(p1) * math.cos(delta) + math.cos(p1) * math.sin(delta) * math.cos(brg))
    l2 = l1 + math.atan2(math.sin(brg) * math.sin(delta) * math.cos(p1), math.cos(delta) - math.sin(p1) * math.sin(p2))
    lon2 = (math.degrees(l2) + 540) % 360 - 180
    return round(math.degrees(p2), 6), round(lon2, 6)


def earth(origin, east_km=0.0, north_km=0.0):
    return offset(origin, east_km, north_km, EARTH_RADIUS_KM)


def moon(origin, east_km=0.0, north_km=0.0):
    return offset(origin, east_km, north_km, MOON_RADIUS_KM)


# --- building specs ---------------------------------------------------------------------------

# Extensive figures that scale with plant size (camelCase paths inside BuildingStats).
_SCALED = {
    "power": ("averageDemandKw", "peakDemandKw", "averageOutputKw", "ratedOutputKw"),
    "water": ("inputM3PerHour", "outputM3PerHour"),
    "light": ("upwardLumens",),
}
_COUNT = {"workers": ("capacity", "staffingRequired")}


def _clip(text: str, limit: int = NOTE_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


_HEAD = "Demo world assumption: "


def _relabel(section: dict, why: str) -> None:
    """Mark a stats section as a demo assumption, keeping the preset's cited basis after it."""
    prov = section.get("provenance") or {}
    original = prov.get("note") or ""
    if prov.get("kind") == "demo_assumption" and original.startswith(_HEAD):
        note = _HEAD + why + " " + original[len(_HEAD):]  # a second assumption on an already relabelled section
    else:
        note = _HEAD + why + (f" Preset basis ({prov.get('kind', 'cited')}): {original}" if original else "")
    section["provenance"] = {"kind": "demo_assumption", "note": _clip(note)}


def scale_stats(stats: dict, factor: float, preset_name: str) -> dict:
    """Every size-dependent figure × factor; intensive figures (hours, capacity factor, prices) unchanged."""
    s = copy.deepcopy(stats)
    why = f"figures scaled ×{factor:g} from the “{preset_name}” preset (a plant {factor:g} times its size)."

    def mul(v):
        return None if v is None else round(v * factor, 4)

    for sec, keys in _SCALED.items():
        part = s.get(sec) or {}
        if any(part.get(k) not in (None, 0) for k in keys):
            for k in keys:
                part[k] = mul(part.get(k))
            _relabel(part, why)
    for sec, keys in _COUNT.items():
        part = s.get(sec) or {}
        if any(part.get(k) for k in keys):
            for k in keys:
                if part.get(k) is not None:
                    part[k] = max(1, round(part[k] * factor))
            _relabel(part, why)
    if s.get("footprintM2"):
        s["footprintM2"] = mul(s["footprintM2"])
        s["footprintProvenance"] = {"kind": "demo_assumption",
                                    "note": _clip(f"Demo world assumption: {why} Preset basis: "
                                                  f"{(s.get('footprintProvenance') or {}).get('note') or ''}")}
    costs = s.get("costs") or {}
    if costs.get("constructionTotal") is not None or (costs.get("operating") or {}).get("amount") is not None:
        costs["constructionTotal"] = mul(costs.get("constructionTotal"))
        if costs.get("operating"):
            costs["operating"]["amount"] = mul(costs["operating"].get("amount"))
        _relabel(costs, why)
    for m in s.get("materials") or []:
        if m.get("quantityKg") is not None:
            m["quantityKg"] = mul(m["quantityKg"])
            m["provenance"] = {"kind": "demo_assumption", "note": _clip(
                f"Demo world assumption: {why} Preset basis: {(m.get('provenance') or {}).get('note') or ''}")}
    for e in s.get("emissions") or []:
        if e.get("rateKgPerHour") is not None:
            e["rateKgPerHour"] = mul(e["rateKgPerHour"])
            e["provenance"] = {"kind": "demo_assumption", "note": _clip(
                f"Demo world assumption: {why} Preset basis: {(e.get('provenance') or {}).get('note') or ''}")}
    return s


def assume(stats: dict, section: str, values: dict, why: str) -> None:
    """Fill figures the preset leaves unknown (or override them) and say so in that section's provenance."""
    if section == "root":
        stats.update(values)
        if "footprintM2" in values:
            stats["footprintProvenance"] = {"kind": "demo_assumption", "note": _clip(f"Demo world assumption: {why}")}
        return
    part = stats.setdefault(section, {})
    part.update(values)
    _relabel(part, why)


def footprint(m2: float, why: str) -> tuple:
    return ("root", {"footprintM2": float(m2)}, f"footprint {m2 / 10000:g} ha: {why}")


DC_FOOTPRINT = "buildings and yards at ~1.5 kW of average load per m² of occupied ground (hyperscale campus)."
BATTERY_FOOTPRINT = "container rows, inverters, transformers and access roads."
H2_FOOTPRINT = "electrolyser halls, compression, storage and a water-treatment plant."
HOMES_FOOTPRINT = "1.7 ha per 100 homes, the density of the BedZED site itself."
SCHOOL_FOOTPRINT = "the building plus playground and playing field."
HOSPITAL_FOOTPRINT = "the 115,000 m² floor area on about four storeys, plus access."
WTE_FOOTPRINT = "the plant building, waste bunker, ash handling and yard."


class Earth:
    """One Earth building built from a preset (optionally scaled, optionally with assumptions)."""

    def __init__(self, key, preset_id, name, at, story, *, scale=None, params=None, assumptions=(), type_=None):
        self.key, self.preset_id, self.name, self.at, self.story = key, preset_id, name, at, story
        self.scale, self.params, self.assumptions, self.type_ = scale, params, assumptions, type_

    def payload(self, presets: dict, versions: dict) -> dict:
        p = presets[self.preset_id]
        stats = copy.deepcopy(p["stats"])
        if self.scale is not None:
            stats = scale_stats(stats, self.scale, p["name"])
        for section, values, why in self.assumptions:
            assume(stats, section, values, why)
        btype = self.type_ or p["type"]
        basis = f"Based on the “{p['name']}” preset ({p['headline']})"
        basis += f", scaled ×{self.scale:g}." if self.scale is not None else ", cited figures used as published."
        if self.assumptions:
            basis += " Demo assumptions: " + "; ".join(why for _, _, why in self.assumptions)
        params = dict(p.get("parameters") or {})
        if self.params is not None:
            params.update(self.params)
        params = {k: v for k, v in params.items() if v is not None}
        return {
            "type": btype,
            "name": self.name,
            "latitude": self.at[0],
            "longitude": self.at[1],
            "parameters": params,
            "definition": {
                "name": self.name,
                "description": _clip(f"{self.story} {basis}", DESC_MAX),
                "templateId": btype,
                "templateVersion": versions.get(btype, 1),
                "stats": stats,
                "criteria": [],
            },
        }


class Moon:
    def __init__(self, key, type_, name, at, story, **values):
        self.key, self.type_, self.name, self.at, self.story, self.values = key, type_, name, at, story, values

    def payload(self, catalogue: dict, _versions: dict) -> dict:
        defaults = {p["key"]: p["default"] for p in catalogue[self.type_]["params"]}
        values = {**defaults, **self.values}
        return {
            "type": self.type_,
            "name": self.name,
            "latitude": self.at[0],
            "longitude": self.at[1],
            # Unknown (null) values are left out, as the Moon Build form does.
            "parameters": {k: v for k, v in values.items() if v is not None},
            "definition": {"name": self.name, "description": _clip(self.story, DESC_MAX), "templateId": self.type_},
        }


def budget(id_, label, kind, *, contributors=(), amount=0.0, radius=None):
    """A declared pool. `amount` is the external supply per day (0 = none: only the listed plants feed it;
    None would make the whole pool unknown). radius = (centre, km) limits it to buildings within that distance."""
    scope = {"kind": "scenario"}
    if radius is not None:
        (lat, lon), km = radius
        scope = {"kind": "radius", "latitude": lat, "longitude": lon, "radiusKm": km}
    return {"id": id_, "label": label, "kind": kind, "amount": amount, "scope": scope, "contributors": list(contributors)}


# --- Earth world 1: Arizona -------------------------------------------------------------------

PALO_VERDE = (33.3881, -112.8617)
# Clusters are 9+ H3 rings (~55 km) apart from Palo Verde so they don't compete for its commuting workforce.
GILA_BEND = (32.93, -112.68)  # south-east of Gila Bend, beside the Gila River and the 500 kV corridor
NORTH_PHX = (33.78, -112.16)  # TSMC Arizona's site, north Phoenix
WEST_VALLEY = (33.54, -112.19)  # Glendale, in the West Valley
FARMLAND = (33.33, -112.58)  # irrigated farmland south of Buckeye
COPPER_BELT = (31.87, -111.12)  # the copper belt south of Tucson (Green Valley / Sahuarita)

COTTON_HA = 1000
COTTON_IRRIGATION_M = 1.5  # applied water a year: about 5 acre-feet per acre, typical for Arizona cotton
COTTON_M3H = COTTON_HA * 10000 * COTTON_IRRIGATION_M / 8766

RTE = 0.85  # battery round-trip efficiency assumed where the source gives none
H2_KWH_PER_KG = 55.0  # system electricity per kg of hydrogen (stack + balance of plant)
H2_WATER_L_PER_KG = 15.0  # demineralised feedwater incl. treatment reject (9 kg is the stoichiometric minimum)


def hydrogen(scale: float) -> tuple[dict, list]:
    kg_day = 54795 * scale
    kw = kg_day * H2_KWH_PER_KG / 24
    m3h = kg_day * H2_WATER_L_PER_KG / 1000 / 24
    params = {"process": "pem_electrolysis", "electrolyserCapacityKw": round(260000 * scale),
              "hydrogenOutputKgPerDay": round(kg_day)}
    assumptions = [
        ("power", {"averageDemandKw": round(kw, 1), "technology": "PEM electrolysis"},
         f"electricity {H2_KWH_PER_KG:g} kWh per kg of hydrogen (typical whole-system figure) × "
         f"{kg_day:,.0f} kg/day design output ÷ 24 h = {kw:,.0f} kW."),
        ("water", {"inputM3PerHour": round(m3h, 2), "basis": "Demineralised electrolysis feedwater"},
         f"feedwater {H2_WATER_L_PER_KG:g} L per kg of hydrogen (9 L stoichiometric + treatment reject) = "
         f"{m3h:,.1f} m³/h."),
        ("root", {"operatingHoursPerDay": 24}, "runs around the clock on its power purchase agreement."),
    ]
    return params, assumptions


NET_METERED = ("power", {"averageDemandKw": 0.0},
               "own demand 0 because the output figure is metered at the grid connection, i.e. already net of "
               "the plant's own use, so own use is counted once (inside the net figure).")
NET_PUBLISHED = ("power", {"averageDemandKw": 0.0},
                 "own demand 0: own use is taken as already deducted from the published annual generation (the "
                 "source does not say whether it is gross or net), so it is counted once.")


def battery_charging(output_kw: float) -> tuple:
    kw = output_kw / RTE
    return ("power", {"averageDemandKw": round(kw, 1)},
            f"charging demand = average discharge ÷ {RTE:g} round-trip efficiency = {kw:,.0f} kW, so its "
            f"net output is its storage losses (negative).")


H2_AZ_PARAMS, H2_AZ_ASSUME = hydrogen(0.4)

SONORAN = {
    "name": "Arizona: nuclear, solar, chips, copper & cotton (demo)",
    "body": "earth",
    "assumptions": {"periodDays": 30},
    "buildings": [
        Earth("pv", "palo-verde-nuclear", "Nuclear power station", PALO_VERDE,
              "Palo Verde, the anchor of the corridor: 3.7 GW of steady nuclear output, cooled with treated wastewater piped "
              "from Phoenix, so it competes with nobody for desert fresh water."),
        Earth("dc", "meta-prineville-data-centre", "AI data centre", earth(PALO_VERDE, 2.0, 3.0),
              "A hyperscale AI campus built in the hexagon next to the nuclear plant: it takes its ~200 MW straight "
              "from the station's switchyard, so the plant needs less export capacity and the campus needs no new "
              "long-distance line.",
              assumptions=[footprint(131000, DC_FOOTPRINT)]),
        Earth("solar", "agua-caliente-solar", "Solar farm", GILA_BEND,
              "A 290 MW thin-film PV plant near Gila Bend, in the sunniest belt of the Sonoran Desert. With its "
              "battery, its whole net output is sold to the green hydrogen plant in north Phoenix through a virtual power purchase "
              "agreement over the grid."),
        Earth("bess", "hornsdale-power-reserve", "Solar farm battery", earth(GILA_BEND, 2.5, -1.0),
              "A 150 MW / 193.5 MWh battery that shifts midday solar into the evening for the electrolysers.",
              assumptions=[battery_charging(7259.6), footprint(20000, BATTERY_FOOTPRINT)]),
        Earth("h2", "sinopec-kuqa-green-hydrogen", "Green hydrogen plant", earth(NORTH_PHX, -4.5, 1.5),
              "A 104 MW PEM electrolyser making about 22 t of green hydrogen a day in north Phoenix. It sits beside the water "
              "recycling plant because the basin has no unallocated fresh water left, takes its feedwater from it, runs on "
              "the Gila Bend solar farm and battery through a declared PPA, and supplies the chip factory's "
              "process hydrogen.",
              scale=0.4, params=H2_AZ_PARAMS, assumptions=[*H2_AZ_ASSUME, footprint(50000, H2_FOOTPRINT)]),
        Earth("fab", "tsmc-arizona-fab-1", "Computer chip factory", NORTH_PHX,
              "A leading-edge logic chip fab in north Phoenix. Its 18,000 m³ a day of ultrapure-water intake is covered "
              "by the water recycling plant beside it instead of drawing on the Colorado River allocation.",
              assumptions=[("power", {"averageDemandKw": 150000.0},
                            "average demand 150 MW: leading-edge 300 mm logic fabs draw roughly 100–200 MW, and "
                            "TSMC does not publish this site's load.")]),
        Earth("reclaim", "blue-plains-awtp", "Water recycling plant", earth(NORTH_PHX, -2.5, 0.5),
              "Advanced reuse treatment of north-Phoenix sewage (effluent drawn from the metro population within "
              "~64 km). Most of the inflow returns as reclaimed industrial water for the chip factory next door.",
              scale=0.1, params={"treatmentLevel": "advanced_reuse", "designFlowM3PerDay": 145360},
              assumptions=[("water", {"outputM3PerHour": 3000.0,
                                      "basis": "Sewage in; reclaimed industrial water out to the fab"},
                            "reclaimed water output 3,000 m³/h (~78 % of the 3,864 m³/h inflow) delivered for reuse.")]),
        Earth("homes", "bedzed-beddington", "2,500 eco-homes", earth(WEST_VALLEY, -7.0, -1.0),
              "2,500 low-energy homes with rooftop PV in Glendale, for the corridor's workforce.",
              scale=25, params={"form": "mixed", "dwellingCount": 2500},
              assumptions=[footprint(425000, HOMES_FOOTPRINT)]),
        Earth("school", "discovery-elementary-arlington", "Primary school", earth(WEST_VALLEY, -5.0, 3.0),
              "A net-zero primary school serving the new homes.",
              assumptions=[footprint(20000, SCHOOL_FOOTPRINT)]),
        Earth("hospital", "kingston-general-hospital", "Hospital", WEST_VALLEY,
              "A 440-bed teaching hospital for the growing West Valley.",
              assumptions=[footprint(30000, HOSPITAL_FOOTPRINT)]),
        Earth("warehouse", "amazon-jfk8-staten-island", "Delivery warehouse", earth(WEST_VALLEY, 6.0, -4.0),
              "A large parcel fulfilment centre with rooftop solar in Glendale, close to the Loop 101."),
        Earth("farm", "cubbie-station-cotton", "Cotton farm", FARMLAND,
              "1,000 ha of irrigated cotton south of Buckeye. The basin's fresh water is fully allocated, so the "
              "fields are watered with treated sewage water from Phoenix instead of groundwater.",
              scale=COTTON_HA / 22100,
              params={"cropType": "cotton", "irrigation": "furrow_flood", "cultivatedAreaHa": COTTON_HA},
              assumptions=[
                  footprint(COTTON_HA * 10000, "the cultivated fields only."),
                  ("water", {"inputM3PerHour": round(COTTON_M3H, 1), "source": "wastewater",
                             "basis": "Treated sewage effluent from Phoenix, delivered by canal"},
                   f"irrigation {COTTON_IRRIGATION_M:g} m a year (about 5 acre-feet per acre, typical for Arizona "
                   f"cotton) × {COTTON_HA:,} ha = {COTTON_HA * COTTON_IRRIGATION_M * 10000:,.0f} m³ a year, spread "
                   f"over 8,766 h = {COTTON_M3H:,.0f} m³/h, supplied as treated effluent."),
                  ("root", {"operatingHoursPerDay": 24}, "the irrigation total is spread over every hour of the year."),
              ]),
        Earth("mine", "gibraltar-copper-mine", "Copper mine", COPPER_BELT,
              "An open-pit copper mine in the copper belt south of Tucson, producing ~48,000 t of copper a year. It "
              "buys its 49.5 MW from the nuclear power station under a declared contract and takes its make-up "
              "water as treated sewage water from Tucson.",
              assumptions=[
                  footprint(12_000_000, "open pit, waste-rock dumps, mill and tailings (the preset gives no area)."),
                  ("water", {"source": "wastewater",
                             "basis": "Treated effluent piped from Tucson; process water recycled from the tailings pond"},
                   "make-up water taken as treated Tucson effluent instead of groundwater (the basin's fresh water is "
                   "fully allocated); volume as published."),
              ]),
        Earth("wte", "amager-bakke-copenhill-wte", "Waste-burning power plant", earth(WEST_VALLEY, -4.0, -5.0),
              "Burns the West Valley's residual waste instead of landfilling it, and feeds 34 MW net to the local "
              "community supply that the homes, school, hospital and warehouse draw on.",
              assumptions=[footprint(40000, WTE_FOOTPRINT)]),
    ],
    "budgets": [
        budget("pv-switchyard", "Nuclear plant's power for the AI data centre", "power_capacity_kw",
               contributors=["pv"], radius=(PALO_VERDE, 8)),
        budget("gila-ppa", "Solar farm power sold to the hydrogen plant", "energy_kwh_per_day",
               contributors=["solar", "bess"], radius=(earth(NORTH_PHX, -4.5, 1.5), 1)),
        # A treatment plant's sewage intake counts as its own water use, so its net output is negative and it
        # cannot feed a pool; the fab's share is declared as a contract instead (the plant's output also
        # raises the water the site checks find nearby).
        budget("reclaimed", "Recycled water for the chip factory", "water_m3_per_day",
               amount=20000, radius=(NORTH_PHX, 1.5)),
        budget("west-valley", "Waste plant's power for homes, school, hospital and warehouse", "energy_kwh_per_day",
               contributors=["wte"], radius=(WEST_VALLEY, 12)),
        budget("mine-contract", "Nuclear power for the copper mine", "energy_kwh_per_day",
               contributors=["pv"], radius=(COPPER_BELT, 3)),
    ],
}

# --- Earth world 2: Humber, England -----------------------------------------------------------

H2_HUMBER_PARAMS, H2_HUMBER_ASSUME = hydrogen(0.5)

HUMBER = {
    "name": "Humber, England: wind-powered heavy industry (demo)",
    "body": "earth",
    "assumptions": {"periodDays": 30},
    "buildings": [
        Earth("wind", "hornsea-2-offshore-wind", "Offshore wind farm", (53.94, 1.688),
              "Hornsea 2: 1.4 GW of North Sea wind, 89 km offshore. A corporate power purchase agreement sends its output to "
              "the industries on the Humber bank.",
              assumptions=[NET_METERED]),
        Earth("bess", "hornsdale-power-reserve", "Wind farm battery", (53.497, 0.105),
              "A 150 MW battery at the wind farm's Lincolnshire landfall (Horseshoe Point), firming the offshore output.",
              assumptions=[battery_charging(7259.6), footprint(20000, BATTERY_FOOTPRINT)]),
        Earth("h2", "sinopec-kuqa-green-hydrogen", "Green hydrogen plant", (53.655, -0.262),
              "A 130 MW electrolyser at Killingholme making ~27 t of hydrogen a day from offshore wind, piped to the refinery and "
              "steelworks on the same estuary.",
              scale=0.5, params=H2_HUMBER_PARAMS,
              assumptions=[*H2_HUMBER_ASSUME, footprint(60000, H2_FOOTPRINT)]),
        Earth("refinery", "omv-burghausen-refinery", "Oil refinery", (53.637, -0.236),
              "A 79,000 bbl/day refinery that swaps grey hydrogen for the green hydrogen made next door."),
        Earth("port", "port-of-huelva", "Cargo port", (53.628, -0.19),
              "Immingham, the UK's largest port by tonnage: ships in the crude, ores and coal for the cluster and out its fuels."),
        Earth("steel", "voestalpine-linz-steelworks", "Steelworks", (53.585, -0.62),
              "An integrated blast-furnace steelworks at Scunthorpe, the cluster's biggest emitter and the reason for its "
              "hydrogen and wind build-out.",
              scale=0.6, params={"route": "bf_bof", "crudeSteelTPerYear": 3180000}),
        Earth("dc", "meta-prineville-data-centre", "AI data centre", (53.738, -0.24),
              "A 100 MW data centre on the Saltend chemicals park, sited for the wind power landing on the Humber.",
              scale=0.5, assumptions=[footprint(65000, DC_FOOTPRINT)]),
        Earth("wte", "amager-bakke-copenhill-wte", "Waste-burning power plant", (53.728, -0.275),
              "Turns Hull's residual waste into 40 MW of electricity for the shared supply.",
              assumptions=[footprint(40000, WTE_FOOTPRINT)]),
        Earth("hospital", "kingston-general-hospital", "Hospital", (53.744, -0.357),
              "Hull's 440-bed teaching hospital (Hull Royal Infirmary).",
              assumptions=[footprint(30000, HOSPITAL_FOOTPRINT)]),
        Earth("homes", "bedzed-beddington", "1,000 eco-homes", (53.739, -0.318),
              "1,000 low-energy homes on Hull's riverside for cluster workers.",
              scale=10, params={"form": "mixed", "dwellingCount": 1000},
              assumptions=[footprint(170000, HOMES_FOOTPRINT)]),
        Earth("school", "discovery-elementary-arlington", "Primary school", (53.722, -0.433),
              "A net-zero primary school in Hessle, west of Hull.",
              assumptions=[footprint(20000, SCHOOL_FOOTPRINT)]),
    ],
    "budgets": [
        budget("humber-cppa", "Wind, battery and waste power shared by the whole cluster", "energy_kwh_per_day",
               contributors=["wind", "bess", "wte"]),
    ],
}

# --- Earth world 3: Lochaber, Scottish Highlands ----------------------------------------------

FORT_WILLIAM = (56.835, -5.07)
ITAIPU_TO_LOCHABER = 88 / 14000  # Lochaber's ~88 MW scheme vs Itaipu's 14,000 MW

LOCHABER = {
    "name": "Scottish Highlands: hydro-powered aluminium smelter (demo)",
    "body": "earth",
    "assumptions": {"periodDays": 30},
    "buildings": [
        Earth("hydro", "itaipu-hydroelectric", "Hydroelectric power station", earth(FORT_WILLIAM, 2.0, 1.5),
              "Loch Treig water tunnelled through Ben Nevis to a powerhouse above Fort William: 88 MW feeding the "
              "smelter by private wire.",
              scale=ITAIPU_TO_LOCHABER, params={"scheme": "reservoir", "reservoirAreaKm2": 8.5},
              assumptions=[NET_PUBLISHED, footprint(20000, "powerhouse, surge shaft and switchyard (the reservoir "
                                                           "is an existing loch).")]),
        Earth("wind", "hornsea-2-offshore-wind", "Hillside wind farm", earth(FORT_WILLIAM, 9.0, 6.0),
              "A 69 MW onshore wind farm on the hills north-east of the glen, topping up the hydro so the potlines "
              "never starve in a dry spell.",
              scale=0.05, params={"siting": "onshore", "turbineCount": 15, "turbineRatingKw": 4620},
              assumptions=[
                  ("power", {"capacityFactor": 0.32, "averageOutputKw": round(69300 * 0.32, 1)},
                   "onshore capacity factor 0.32 (Highland onshore wind) instead of the offshore 0.441: "
                   "69,300 kW × 0.32."),
                  NET_METERED,
                  ("root", {"footprintM2": 180000.0},
                   "occupied ground 18 ha (turbine bases, crane pads and tracks), not the whole spread of the farm."),
              ]),
        Earth("smelter", "alcoa-fjardaal-aluminium-smelter", "Aluminium smelter", earth(FORT_WILLIAM, 2.5, 1.0),
              "A 46 kt/yr smelter: aluminium is frozen electricity, so it sits where cheap hydro and wind meet.",
              scale=0.13, params={"primaryAluminiumTPerYear": 46150, "potlineCount": 1}),
        Earth("bess", "hornsdale-power-reserve", "Battery", earth(FORT_WILLIAM, -4.0, 1.5),
              "A 30 MW battery that holds the smelter's potlines steady through wind lulls.",
              scale=0.2, params={"energyCapacityKwh": 38700, "powerRatingKw": 30000},
              assumptions=[battery_charging(7259.6 * 0.2), footprint(4000, BATTERY_FOOTPRINT)]),
        Earth("dc", "meta-prineville-data-centre", "Data centre", earth(FORT_WILLIAM, -3.0, 3.0),
              "A 20 MW data centre cooled by Highland air, on the town's share of the glen's renewable power.",
              scale=0.1, assumptions=[footprint(13000, DC_FOOTPRINT)]),
        Earth("salmon", "atlantic-sapphire-miami-bluehouse", "Indoor salmon farm", (56.55, -5.41),
              "A land-based recirculating salmon farm at Port Appin on the open lower Loch Linnhe, drawing seawater from the loch "
              "and shipping fish up to Corpach.",
              scale=0.25, params={"system": "recirculating_ras", "species": "salmon", "productionTPerYear": 386}),
        Earth("port", "port-of-huelva", "Harbour", earth(FORT_WILLIAM, -4.5, 0.5),
              "Corpach, the sea lock at the Caledonian Canal: alumina in, metal and salmon out.",
              scale=0.05, params={"cargoTPerYear": 1515000, "maxDraughtM": 8}),
        Earth("homes", "bedzed-beddington", "300 eco-homes", earth(FORT_WILLIAM, 1.0, 3.5),
              "300 low-energy homes in Fort William for the glen's new workforce.",
              scale=3, params={"form": "mixed", "dwellingCount": 300},
              assumptions=[footprint(51000, HOMES_FOOTPRINT)]),
        Earth("school", "discovery-elementary-arlington", "Primary school", earth(FORT_WILLIAM, -2.0, 4.0),
              "A net-zero primary school in Caol.",
              assumptions=[footprint(20000, SCHOOL_FOOTPRINT)]),
    ],
    "budgets": [
        # Hydro + wind + battery by private wire, topped up by a declared 20 MW grid import.
        budget("glen-supply", "Hydro, wind and battery power (plus 20 MW from the grid)", "energy_kwh_per_day", amount=480000,
               contributors=["hydro", "wind", "bess"], radius=(FORT_WILLIAM, 10)),
    ],
}

# --- Moon world 1: south pole -----------------------------------------------------------------

RIDGE = (-89.45, -137.31)  # the ridge between Shackleton and de Gerlache craters

SHACKLETON = {
    "name": "Moon south pole: self-sufficient base for 8 (demo)",
    "body": "moon",
    "assumptions": {"moonBase": {"transportCase": "central", "nightHours": None}},
    "buildings": [
        Moon("hab1", "moon_habitat", "Crew habitat 1", moon(RIDGE),
             "Four-crew habitat on the sunlit ridge between Shackleton and de Gerlache craters. 60 days of stored oxygen, water and food bridge any gap in "
             "deliveries.", crew=4, reserveDays=60),
        Moon("hab2", "moon_habitat", "Crew habitat 2", moon(RIDGE, 0.25, 0.0),
             "Second four-crew habitat, docked to Crew habitat 1.", crew=4, reserveDays=60),
        Moon("greenhouse", "moon_greenhouse", "Food greenhouse", moon(RIDGE, 0.0, 0.35),
             "750 m² of LED-lit growing area: enough food for all eight crew, and its plants release more oxygen "
             "than they breathe.", areaM2=750),
        *[Moon(f"solar{i}", "moon_solar_tower", f"Solar tower {i}", moon(RIDGE, dx, dy),
               "A 50 kW-class vertical array on the rim (illustrative surveyed sunlit fraction 0.85: ridge points "
               "here are lit 70–90% of the time). Its daytime surplus recharges the fuel cells.",
               ratedKw=50, sunlitFraction=0.85, landedMassT=1.0)
          for i, (dx, dy) in enumerate([(-0.8, -0.3), (-0.5, -0.65), (0.6, -0.5), (1.0, -0.2), (-1.1, 0.1)], 1)],
        Moon("storage", "moon_storage", "Night-time power storage", moon(RIDGE, 0.55, 0.45),
             "14 MWh of regenerative fuel cells: carries the base through the 3–5-day ridge night on top of "
             "the reactors.", capacityKwh=14000, maxOutputKw=120),
        *[Moon(f"fsp{i}", "moon_fission", f"Nuclear reactor {i}", moon(RIDGE, dx, dy),
               "One of four 40 kWe fission units, 2.6 km from the habitats: outside the 1 km radiation keep-out, "
               "inside the base's power network.")
          for i, (dx, dy) in enumerate([(2.6, 1.2), (2.9, 1.2), (2.6, 1.5), (2.9, 1.5)], 1)],
        Moon("ice", "moon_ice_mine", "Water ice mine", moon(RIDGE, 0.0, -4.0),
             "Heats icy regolith from the permanently shadowed slopes towards Shackleton and collects the water: "
             "far more than the habitats' recycling loses."),
        Moon("pad", "moon_landing_pad", "Landing pad", moon(RIDGE, -3.0, 2.0),
             "Sintered landing pad 3 km off the base, outside every building's 2 km plume keep-out."),
    ],
}

# --- Moon world 2: Mare Tranquillitatis ------------------------------------------------------

TRANQ = (6.0, 30.0)

TRANQUILLITATIS = {
    "name": "Moon equator: oxygen factory for rockets (demo)",
    "body": "moon",
    "assumptions": {"moonBase": {"transportCase": "central", "nightHours": None}},
    "buildings": [
        Moon("hab", "moon_habitat", "Crew habitat", moon(TRANQ),
             "Quarters for the four-person plant crew, on Mare Tranquillitatis.", crew=4),
        Moon("lab", "moon_habitat", "Control room & lab", moon(TRANQ, 0.2, 0.15),
             "Control room and sample lab, with bunks for two more.", crew=2, powerKw=15),
        Moon("greenhouse", "moon_greenhouse", "Salad greenhouse", moon(TRANQ, -0.2, 0.3),
             "A small 120 m² greenhouse: fresh food and oxygen, while staple food still comes from Earth.",
             areaM2=120),
        Moon("o2a", "moon_oxygen_plant", "Oxygen factory 1", moon(TRANQ, 1.2, -1.6),
             "Hydrogen reduction of ilmenite-rich mare basalt. 45 kg of oxygen a day, mostly for refuelling "
             "landers at the pad.", oxygenKgPerDay=45),
        Moon("o2b", "moon_oxygen_plant", "Oxygen factory 2", moon(TRANQ, 1.5, -1.6),
             "Second reduction line: together the works make ~90 kg of oxygen a day, 30 times what the crew "
             "breathes.", oxygenKgPerDay=45),
        *[Moon(f"fsp{i}", "moon_fission", f"Nuclear reactor {i}", moon(TRANQ, dx, dy),
               "One of four 40 kWe fission units: steady power through the 14.8-day lunar night, when solar "
               "gives nothing.")
          for i, (dx, dy) in enumerate([(-1.6, -1.2), (-1.9, -1.2), (-1.6, -1.5), (-1.9, -1.5)], 1)],
        *[Moon(f"solar{i}", "moon_solar_tower", f"Solar tower {i}", moon(TRANQ, dx, dy),
               "A 10 kW vertical array: extra daytime power while the Sun is up (half the time at the equator).")
          for i, (dx, dy) in enumerate([(0.6, 0.6), (0.9, 0.6), (1.2, 0.6)], 1)],
        Moon("storage", "moon_storage", "Backup power storage", moon(TRANQ, 0.6, 0.9),
             "Regenerative fuel cells as an emergency reserve."),
        Moon("pad", "moon_landing_pad", "Rocket refuelling pad", moon(TRANQ, 0.0, -4.2),
             "A 100 m pad where landers load liquid oxygen from the works; 2.6 km from the nearest plant, outside "
             "the plume keep-out.", diameterM=100),
    ],
}

WORLDS = [SONORAN, HUMBER, LOCHABER, SHACKLETON, TRANQUILLITATIS]

# --- API --------------------------------------------------------------------------------------


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} failed ({exc.code}): {exc.read().decode()[:2000]}") from None
        return json.loads(raw) if raw else None


def seed(api: Api, world: dict, replace: bool, presets: dict, versions: dict, moon_catalogue: dict) -> str | None:
    existing = [w for w in api.call("GET", f"/api/scenarios?body={world['body']}") if w["name"] == world["name"]]
    if existing and not replace:
        print(f"= {world['name']}: already exists, skipped (use --replace to recreate)")
        return None
    for w in existing:
        api.call("DELETE", f"/api/scenarios/{w['id']}")
        print(f"- {world['name']}: deleted old copy {w['id']}")

    created = api.call("POST", "/api/scenarios", {"name": world["name"], "body": world["body"],
                                                   "assumptions": world.get("assumptions", {})})
    sid = created["id"]
    lookup = moon_catalogue if world["body"] == "moon" else presets
    ids: dict[str, str] = {}
    for b in world["buildings"]:
        project = api.call("POST", f"/api/scenarios/{sid}/projects", b.payload(lookup, versions))
        ids[b.key] = project["id"]
    budgets = [
        {"id": x["id"], "label": x["label"], "kind": x["kind"], "amount": x["amount"], "scope": x["scope"],
         "contributingProjectIds": [ids[k] for k in x["contributors"]]}
        for x in world.get("budgets", [])
    ]
    if budgets:
        api.call("PATCH", f"/api/scenarios/{sid}", {"assumptions": {"budgets": budgets}})
    print(f"+ {world['name']}: {len(ids)} buildings, {len(budgets)} budgets -> {sid}")
    return sid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--replace", action="store_true", help="delete and recreate worlds with the same names")
    ap.add_argument("--only", help="only worlds whose name contains this text")
    args = ap.parse_args()

    api = Api(args.api)
    presets = {p["id"]: p for p in api.call("GET", "/api/building-presets")}
    versions = {t["type"]: t["version"] for t in api.call("GET", "/api/building-templates")}
    catalogue = Path(__file__).resolve().parents[1] / "shared" / "moon_buildings.json"
    moon_catalogue = {b["type"]: b for b in json.loads(catalogue.read_text(encoding="utf-8"))["buildings"]}
    for world in WORLDS:
        if args.only and args.only.lower() not in world["name"].lower():
            continue
        seed(api, world, args.replace, presets, versions, moon_catalogue)
    return 0


if __name__ == "__main__":
    sys.exit(main())
