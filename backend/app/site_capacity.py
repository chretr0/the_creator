"""What a site can provide, estimated from prepared data (no user input).

A *site* is the resolution-6 H3 cell a building is placed in plus the rings of neighbouring cells
that can reasonably serve it. Each resource has its own reach:

=============  =====  =====================================================================
Resource       Rings  Estimate
=============  =====  =====================================================================
Land           0 (1)  Open land in the cell: cell area × share of WorldCover shrub, grass,
                      crop, bare and moss/lichen × a slope factor (DEM mean slope; 1 at ≤ 5°,
                      0 at ≥ 15°). A footprint larger than the cell may spill into ring 1.
Water          1–2    Renewable fresh water = max(largest HydroRIVERS mean discharge crossing
                      rings 0–1, local runoff max(0, P − E) from ERA5-Land over rings 0–2),
                      × the share Aqueduct baseline water stress leaves unallocated.
                      Coastal sites additionally offer seawater to SEAWATER_TYPES (thermal
                      power, water plants, heavy industry, hydrogen, aquaculture: cooling,
                      desalination or marine intake).
Grid power     1      Indicative connectable capacity from the highest-voltage OSM line or
                      substation in rings 0–1; a settled area implies at least a local
                      distribution network.
                      A building whose intake is seawater needs a coastal site; one on treated
                      wastewater draws on effluent from the population within ~64 km (rings
                      0–10, a long effluent pipeline: Palo Verde's runs ~58 km from Phoenix).
Workforce      8      1 % of the GHSL population within ~50 km, a typical maximum daily commute
                      (≈ 50 % in the labour force, of which one new employer can recruit ~2 %).
Air quality    0      Headroom under the national annual PM2.5 standard: CAMS 2024 mean at the
                      cell vs the standard of the country it lies in, with a 25 % screening
                      margin for the coarse (~80 km) reanalysis: borderline cells pass with a
                      warning, clear exceedances fail. Checked when the specs
                      declare emissions of a local air pollutant (PM, NOx, SO2, CO, VOC, NH3);
                      greenhouse gases are not a local air-quality limit.
Dark sky       1      ILP GN01 lighting environmental zone (E1 natural … E4 urban) from GHSL
                      population density over rings 0–1 and built-up share of the cell. Any
                      upward light fails in E1 (its upward-light-ratio limit is 0 %).
Raw materials  n/a    Advisory only (site_materials.py): nearest producing source hexagon of each
                      declared material within its haul distance. Materials can be shipped, so
                      this never blocks a site.
=============  =====  =====================================================================

Buildings already placed in the scenario share these resources: their demand inside the same reach
is subtracted, and a placed power station or water plant adds its net output. A power station's
output therefore raises the grid capacity of its own and neighbouring hexagons, and consumers next to
a power station absorb part of its output locally, so it needs less room to export. The stress
controls' water/power availability multipliers scale the natural supply.

These are screening estimates (``modelled_estimate``) with every input and coefficient shown in the
check explanation. They are not a water licence, a grid connection offer, land ownership or planning
permission. All functions are vectorised over many centre cells so the same code serves a bounded
area and one exact location.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import h3
import h3.api.numpy_int as h3n
import numpy as np

from app import features, h3store, layers, regions, site_materials
from app.building_calc import fmt_num as _fmt_exact
from app.building_models import (
    BuildingResult,
    BuildingStats,
    CheckResult,
    SiteCapacity,
    SiteResource,
    SiteResourcePart,
    StressControls,
)

# --- coefficients (shown to the user in every explanation) ------------------------------------

RING_LAND, RING_RIVER, RING_RUNOFF, RING_GRID, RING_WORK, RING_EFFLUENT = 1, 1, 2, 1, 8, 10
# Treated municipal effluent returned per resident (m³/day). US domestic wastewater is ~0.3–0.4,
# the UK ~0.15; 0.2 is a conservative screening value.
EFFLUENT_M3_PER_PERSON = 0.2
RING_KM = 6.4  # res-6 centre-to-centre spacing, for "within ~N km" labels

OPEN_LAND = ("frac_shrub", "frac_grass", "frac_crop", "frac_bare", "frac_moss")
SLOPE_FULL, SLOPE_NONE = 5.0, 15.0

# Share of renewable supply still allocatable, by Aqueduct baseline water-stress category
# (withdrawals ÷ renewable supply). 40 % withdrawal is Aqueduct's "high stress" line; headroom is
# what is left below it, smaller for basins that are already stressed.
WATER_HEADROOM = {0.0: 0.30, 1.0: 0.20, 2.0: 0.10, 3.0: 0.02, 4.0: 0.005, -1.0: 0.05}
WATER_STRESS_NAMES = {v: label for v, label, _ in layers.AQUEDUCT_BWS}
# Types whose water intake can be seawater on a coast (once-through/tower cooling, desalination
# pre-treatment, marine pens). Any other type needs fresh water or treated wastewater.
SEAWATER_TYPES = {"power_station", "geothermal_plant", "waste_to_energy", "hydrogen_plant", "water_plant",
                  "steel_mill", "chemical_plant", "oil_refinery", "aquaculture"}

# Indicative capacity a new connection can take at a given voltage (kW). Order-of-magnitude planning
# values, not a network study. A substation gathers several circuits, so it can take more than a
# single line of the same voltage (an extra-high-voltage switchyard is a multi-GW hub).
GRID_CLASSES = [(345.0, 1_500_000.0), (220.0, 500_000.0), (110.0, 100_000.0), (60.0, 40_000.0),
                (30.0, 15_000.0), (10.0, 5_000.0), (0.0, 1_000.0)]
SUBSTATION_CLASSES = [(345.0, 5_000_000.0), (220.0, 1_000_000.0), (110.0, 200_000.0), (60.0, 60_000.0),
                      (30.0, 20_000.0), (10.0, 5_000.0), (0.0, 1_000.0)]
DISTRIBUTION_KW = 5_000.0
RESERVE_SHARE = 0.15  # share of a plant's output it may hold back (not export) as operating reserve  # a settled area has at least a local distribution network
SETTLED_POP, SETTLED_BUILT = 2_000.0, 0.05

LABOUR_SHARE, RECRUIT_SHARE = 0.5, 0.02

# Annual-mean PM2.5 standards (µg/m³) by ISO-3 country; anything else uses WHO interim target 4.
_EU = ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"]
PM25_STANDARDS: dict[str, tuple[float, str]] = {
    "USA": (9.0, "US EPA primary annual PM2.5 NAAQS (2024)"),
    "GBR": (20.0, "UK annual limit value, Air Quality Standards Regulations 2010"),
    **{iso: (25.0, "EU annual limit value, Directive 2008/50/EC (10 µg/m³ from 2030)") for iso in _EU},
}
PM25_DEFAULT = (10.0, "WHO 2021 air quality guidelines, interim target 4 (no national standard on file)")
AIR_MARGIN = 1.25  # CAMS is a ~80 km reanalysis (high over deserts): fail only clearly above the standard
# Local air pollutants (normalised names). CO₂, CO₂e, CH₄ and N₂O are greenhouse gases, not local limits.
AIR_PREFIXES = ("pm", "particulate", "nox", "no2", "nitrogenoxide", "nitrogendioxide", "so2", "sox", "sulphurdioxide",
                "sulfurdioxide", "voc", "nmvoc", "nh3", "ammonia", "carbonmonoxide", "dust", "smoke")
AIR_EXACT = ("co",)

# ILP GN01:2021 lighting environmental zones. Thresholds are implementation defaults:
# (zone, label, upward-light-ratio limit %, min people/km² over rings 0–1, min built-up share of the cell)
LIGHT_ZONES = [
    (4, "E4 urban", 15.0, 3_000.0, 0.20),
    (3, "E3 suburban", 5.0, 500.0, 0.05),
    (2, "E2 rural", 2.5, 5.0, 0.002),
    (1, "E1 natural (dark)", 0.0, 0.0, 0.0),
]
ZONE_NAMES = {z: (label, ulr) for z, label, ulr, _, _ in LIGHT_ZONES}


def is_air_pollutant(name: str) -> bool:
    n = "".join(ch for ch in name.lower().replace("₂", "2").replace("ₓ", "x").replace("₃", "3") if ch.isalnum())
    if n.startswith(("co2", "ch4", "n2o", "ghg", "carbondioxide", "methane")):
        return False
    return n in AIR_EXACT or n.startswith(AIR_PREFIXES)


def light_zone(density: np.ndarray, built: np.ndarray) -> np.ndarray:
    """ILP zone number per cell (NaN when neither density nor built-up share is known)."""
    out = np.full(density.shape, np.nan)
    d, b = np.nan_to_num(density, nan=-1.0), np.nan_to_num(built, nan=-1.0)
    known = ~(np.isnan(density) & np.isnan(built))
    for z, _, _, min_d, min_b in reversed(LIGHT_ZONES):
        out = np.where(known & ((d >= min_d) | (b >= min_b)), float(z), out)
    return out

MODELLED = "modelled estimate from prepared data"


def fmt_num(v) -> str:
    """Estimates are rough: show 3 significant figures (2,400 m³/day, 4.28 million m²)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return _fmt_exact(v)
    v = float(v)
    if v == 0:
        return "0"
    digits = 3 - 1 - math.floor(math.log10(abs(v)))
    r = round(v, digits)
    if abs(r) >= 1e6:
        return f"{r / 1e6:,.3g} million"
    return _fmt_exact(int(r) if digits <= 0 else r)


def fmt_kw(v) -> str:
    """Power with a readable unit: 850 kW, 60 MW, 1,000 MW."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return f"{_fmt_exact(v)} kW"
    return f"{fmt_num(v)} kW" if abs(v) < 1000 else f"{fmt_num(v / 1000)} MW"


# --- data access ------------------------------------------------------------------------------


def _layer_src(layer_id: str, slice_id: str) -> h3store.Source | None:
    layer = layers.BY_ID.get(layer_id)
    if layer is None:
        return None
    try:
        return layers.source_for(layer, layer.slice(slice_id))
    except KeyError:
        return None


def _file_src(pattern: str, column: str) -> h3store.Source | None:
    root = Path(layers.settings.prepared_data_dir)
    files = tuple(p for p in (root / pattern.format(region=r) for r in layers.REGIONS) if p.exists())
    return h3store.Source(files, "h3", column, "mean") if files else None


def _lookup(src: h3store.Source | None, cells: np.ndarray) -> np.ndarray:
    if src is None or len(cells) == 0:
        return np.full(cells.shape, np.nan)
    return h3store.lookup(src, h3store.SIM_RES, cells).astype(np.float64)


def _in_regions(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    ok = np.zeros(lats.shape, dtype=bool)
    for w, s, e, n in layers.REGION_BOXES.values():
        ok |= (lons >= w) & (lons <= e) & (lats >= s) & (lats <= n)
    return ok


def _in_regions_with(lats: np.ndarray, lons: np.ndarray, pattern: str) -> np.ndarray:
    """Cells inside a prepared region whose own file exists (a region without the file is unknown)."""
    root = Path(layers.settings.prepared_data_dir)
    ok = np.zeros(lats.shape, dtype=bool)
    for r, (w, s, e, n) in layers.REGION_BOXES.items():
        if (root / pattern.format(region=r)).exists():
            ok |= (lons >= w) & (lons <= e) & (lats >= s) & (lats <= n)
    return ok


@dataclass
class Disk:
    """Rings 0..k around each centre cell, flattened, with reduceat offsets."""

    flat: np.ndarray
    starts: np.ndarray

    def sum(self, vals: np.ndarray) -> np.ndarray:
        return np.add.reduceat(np.nan_to_num(vals), self.starts) if len(self.flat) else np.zeros(0)

    def max(self, vals: np.ndarray) -> np.ndarray:
        if not len(self.flat):
            return np.zeros(0)
        out = np.maximum.reduceat(np.where(np.isnan(vals), -np.inf, vals), self.starts)
        return np.where(np.isinf(out), np.nan, out)

    def any(self, mask: np.ndarray) -> np.ndarray:
        return np.logical_or.reduceat(mask, self.starts) if len(self.flat) else np.zeros(0, dtype=bool)


def disk(cells: np.ndarray, k: int) -> Disk:
    if k == 0:
        return Disk(cells, np.arange(len(cells)))
    parts = [h3n.grid_disk(int(c), k) for c in cells]
    lengths = np.array([len(p) for p in parts])
    starts = np.concatenate([[0], np.cumsum(lengths)[:-1]]).astype(np.intp)
    flat = np.concatenate(parts).astype(np.uint64) if parts else np.zeros(0, dtype=np.uint64)
    return Disk(flat, starts)


@lru_cache(maxsize=2)
def _river_index(path: str, _mtime: float) -> tuple[np.ndarray, np.ndarray]:
    """Sorted res-6 cells crossed by a HydroRIVERS reach, with the largest mean discharge (m³/s)."""
    meta = features.layer_meta("hydrorivers")
    shapes = features.load(meta)
    best: dict[int, float] = {}
    for f in shapes.features:
        q = (f.get("properties") or {}).get("disAvCms")
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if q is None or len(coords) < 2:
            continue
        for (lon1, lat1), (lon2, lat2) in pairwise(coords):
            dist = math.hypot((lon2 - lon1) * 111 * math.cos(math.radians(lat1)), (lat2 - lat1) * 111)
            steps = max(1, int(dist / 0.5))
            for s in range(steps + 1):
                t = s / steps
                c = h3n.latlng_to_cell(lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t, 6)
                if q > best.get(c, -1.0):
                    best[c] = float(q)
    keys = np.array(sorted(best), dtype=np.uint64)
    return keys, np.array([best[int(k)] for k in keys], dtype=np.float64)


def _river_lookup(cells: np.ndarray) -> np.ndarray | None:
    meta = features.layer_meta("hydrorivers")
    if meta is None or not features.available(meta):
        return None
    p = features.file_path(meta)
    keys, vals = _river_index(str(p), p.stat().st_mtime)
    out = np.full(cells.shape, np.nan)
    if len(keys) and len(cells):
        idx = np.minimum(np.searchsorted(keys, cells), len(keys) - 1)
        hit = keys[idx] == cells
        out[hit] = vals[idx[hit]]
    return out


def _cell_area_m2(cells: np.ndarray) -> np.ndarray:
    return np.array([h3.cell_area(h3store.cell_hex(c), unit="m^2") for c in cells])


# --- natural supply per centre cell -----------------------------------------------------------


@dataclass
class SiteData:
    """Natural (pre-scenario) supply per centre cell. NaN = unknown (outside data coverage)."""

    cells: np.ndarray
    lats: np.ndarray
    lons: np.ndarray
    # land
    cell_m2: np.ndarray
    open_frac: np.ndarray
    slope: np.ndarray
    slope_factor: np.ndarray
    land_cell_m2: np.ndarray
    land_ring_m2: np.ndarray
    # water
    river_m3_day: np.ndarray
    runoff_m3_day: np.ndarray
    stress_cat: np.ndarray
    headroom: np.ndarray
    water_m3_day: np.ndarray
    coastal: np.ndarray
    # grid
    grid_kv: np.ndarray  # highest mapped voltage (line or substation)
    grid_sub_kv: np.ndarray  # highest substation voltage
    grid_has_data: np.ndarray
    settled: np.ndarray
    grid_kw: np.ndarray
    # people
    population: np.ndarray
    workforce: np.ndarray
    # air quality (CAMS 2024 annual means at the cell; NaN = outside the prepared regions)
    pm25: np.ndarray | None = None
    pm10: np.ndarray | None = None
    no2col: np.ndarray | None = None
    so2col: np.ndarray | None = None
    # dark sky
    density: np.ndarray | None = None  # people/km² over rings 0–1
    built_share: np.ndarray | None = None  # GHSL built-up m² ÷ cell area
    zone: np.ndarray | None = None  # ILP lighting zone 1–4

    def __post_init__(self):
        n = len(self.cells)
        for f in ("pm25", "pm10", "no2col", "so2col", "density", "built_share", "zone"):
            if getattr(self, f) is None:
                setattr(self, f, np.full(n, np.nan))


def grid_capacity_kw(kv: np.ndarray, classes=GRID_CLASSES) -> np.ndarray:
    out = np.full(kv.shape, np.nan)
    for threshold, kw in reversed(classes):
        out = np.where(kv >= threshold, kw, out)
    return out


def site_data(cells: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> SiteData:
    n = len(cells)
    cell_m2 = _cell_area_m2(cells)

    # Land: open-land share in the cell and in rings 0..1
    open_parts = [_lookup(_layer_src("land_cover", c.removeprefix("frac_")), cells) for c in OPEN_LAND]
    open_frac = np.sum(open_parts, axis=0) if n else np.zeros(0)  # NaN where WorldCover has no cell
    slope = _lookup(_layer_src("elevation", "slope"), cells)
    slope_factor = np.clip((SLOPE_NONE - slope) / (SLOPE_NONE - SLOPE_FULL), 0.0, 1.0)
    land_cell = cell_m2 * open_frac * slope_factor
    d1 = disk(cells, RING_LAND)
    ring_open = np.sum([_lookup(_layer_src("land_cover", c.removeprefix("frac_")), d1.flat) for c in OPEN_LAND], axis=0) \
        if len(d1.flat) else np.zeros(0)
    ring_slope = _lookup(_layer_src("elevation", "slope"), d1.flat)
    ring_land = d1.sum(_cell_area_m2(d1.flat) * ring_open * np.clip((SLOPE_NONE - ring_slope) / (SLOPE_NONE - SLOPE_FULL), 0, 1))
    land_ring = np.where(np.isnan(land_cell), np.nan, np.maximum(ring_land, np.nan_to_num(land_cell)))

    # Water: rivers within ring 1, runoff over rings 0..2, basin stress at the centre
    dr = disk(cells, RING_RIVER)
    river_vals = _river_lookup(dr.flat)
    river = dr.max(river_vals) * 86_400.0 if river_vals is not None else np.full(n, np.nan)
    river = np.nan_to_num(river) if river_vals is not None else river  # no reach mapped = no river
    du = disk(cells, RING_RUNOFF)
    p = _lookup(_layer_src("era5_precip", "2024-ann"), du.flat)
    e = _lookup(_layer_src("era5_evap", "2024-ann"), du.flat)
    surplus = np.maximum(0.0, p - e) / 1000.0 * _cell_area_m2(du.flat)  # mm/day → m³/day per cell
    runoff = du.sum(surplus)
    has_climate = du.any(~np.isnan(p)) if len(du.flat) else np.zeros(n, dtype=bool)
    runoff = np.where(has_climate, runoff, np.nan)
    stress = _lookup(_layer_src("water_stress", "category"), cells)
    headroom = np.array([WATER_HEADROOM.get(float(v), np.nan) if not np.isnan(v) else np.nan for v in stress])
    renewable = np.fmax(river, runoff)  # river flow already includes upstream runoff: take the larger
    water = renewable * headroom
    # Coast: a nearby cell that is open water (or beyond WorldCover's land tiles) with no ERA5-Land value
    wc_water = _lookup(_layer_src("land_cover", "water"), dr.flat)
    era_flat = _lookup(_layer_src("era5_precip", "2024-ann"), dr.flat)
    flat_lat = np.array([h3.cell_to_latlng(h3store.cell_hex(c))[0] for c in dr.flat]) if len(dr.flat) else np.zeros(0)
    flat_lon = np.array([h3.cell_to_latlng(h3store.cell_hex(c))[1] for c in dr.flat]) if len(dr.flat) else np.zeros(0)
    sea_cell = (np.isnan(wc_water) | (wc_water >= 0.5)) & np.isnan(era_flat) & _in_regions(flat_lat, flat_lon)
    coastal = dr.any(sea_cell) & ~np.isnan(open_frac)

    # Grid: highest voltage within ring 1; settled areas get a distribution-network floor
    dg = disk(cells, RING_GRID)
    line_kv = _lookup(_file_src("power_grid_{region}_h3r6.parquet", "line_max_kv"), dg.flat)
    sub_kv = _lookup(_file_src("power_grid_{region}_h3r6.parquet", "substation_max_kv"), dg.flat)
    grid_line_kv, grid_sub_kv = dg.max(line_kv), dg.max(sub_kv)
    grid_kv = np.fmax(grid_line_kv, grid_sub_kv)
    grid_has_data = _in_regions_with(lats, lons, "power_grid_{region}_h3r6.parquet")
    pop_ring1 = dg.sum(_lookup(_layer_src("population_ghsl", "2025"), dg.flat))
    built = _lookup(_layer_src("land_cover", "built"), cells)
    settled = (pop_ring1 >= SETTLED_POP) | (np.nan_to_num(built) >= SETTLED_BUILT)
    grid_kw = np.fmax(np.nan_to_num(grid_capacity_kw(grid_line_kv)),
                      np.nan_to_num(grid_capacity_kw(grid_sub_kv, SUBSTATION_CLASSES)))
    grid_kw = np.where(settled, np.maximum(grid_kw, DISTRIBUTION_KW), grid_kw)
    grid_kw = np.where(grid_has_data, grid_kw, np.nan)

    # People within ~25 km
    dw = disk(cells, RING_WORK)
    pop_src = _layer_src("population_ghsl", "2025")
    population = dw.sum(_lookup(pop_src, dw.flat)) if pop_src is not None else np.full(n, np.nan)
    workforce = np.floor(population * LABOUR_SHARE * RECRUIT_SHARE)

    # Air quality: CAMS 2024 annual means at the cell
    air = {k: _lookup(_layer_src(layer, "2024-ann"), cells)
           for k, layer in (("pm25", "cams_pm25"), ("pm10", "cams_pm10"), ("no2col", "cams_no2"), ("so2col", "cams_so2"))}

    # Dark sky: population density over rings 0–1 and built-up share of the cell
    ring_area_km2 = dg.sum(_cell_area_m2(dg.flat)) / 1e6 if len(dg.flat) else np.zeros(0)
    has_pop = dg.any(~np.isnan(_lookup(_layer_src("population_ghsl", "2025"), dg.flat))) if len(dg.flat) \
        else np.zeros(0, dtype=bool)
    density = np.where(has_pop, pop_ring1 / np.where(ring_area_km2 > 0, ring_area_km2, np.nan), np.nan)
    built_share = _lookup(_layer_src("built_up", "2025"), cells) / cell_m2
    zone = light_zone(density, built_share)

    return SiteData(cells, lats, lons, cell_m2, open_frac, slope, slope_factor, land_cell, land_ring,
                    river, runoff, stress, headroom, water, coastal, grid_kv, grid_sub_kv, grid_has_data, settled, grid_kw,
                    population, workforce, air["pm25"], air["pm10"], air["no2col"], air["so2col"],
                    density, built_share, zone)


# --- building demand --------------------------------------------------------------------------


@dataclass
class Demand:
    footprint_m2: float | None
    water_m3_day: float | None
    power_kw: float | None  # electricity drawn from the grid (peak, else average while operating)
    export_kw: float | None  # electricity pushed into the grid (producers)
    water_out_m3_day: float | None  # net water a plant adds
    staff: float | None
    power_basis: str = ""
    staff_basis: str = ""
    materials: list[tuple[str, str, float | None]] = field(default_factory=list)  # (name, phase, kg)
    air_pollutants: list[tuple[str, float | None]] = field(default_factory=list)  # (pollutant, kg/h)
    upward_lumens: float | None = None
    water_source: str = "fresh"  # intake: fresh / seawater / wastewater

    @property
    def fresh_m3_day(self) -> float | None:
        """Intake drawn from rivers and runoff (the shared fresh-water pool)."""
        return self.water_m3_day if self.water_source == "fresh" else 0.0

    @property
    def effluent_m3_day(self) -> float | None:
        return self.water_m3_day if self.water_source == "wastewater" else 0.0


def demand_of(btype: str, stats: BuildingStats, result: BuildingResult) -> Demand:
    days = result.period_days
    water = None if result.water_demand.value is None else result.water_demand.value / days
    hours = result.operating_hours.value
    avg_in = None if result.electricity_demand.value is None or not hours else result.electricity_demand.value / hours
    if result.peak_demand.value is not None:
        power, basis = result.peak_demand.value, "peak demand"
    elif avg_in is not None:
        power, basis = avg_in, "average demand while operating (no peak declared)"
    elif result.electricity_demand.value == 0:
        power, basis = 0.0, "no electricity demand"
    else:
        power, basis = None, ""
    export = stats.power.rated_output_kw or stats.power.average_output_kw
    if export is None and result.electricity_output.value is not None and hours:
        export = result.electricity_output.value / hours
    net_kwh = result.electricity_net.value
    producer = bool(export) and (net_kwh is None or net_kwh > 0)
    if producer:
        power, basis = 0.0, "self-supplied (net producer)"
    source = stats.water.source
    if source == "fresh":  # treating fresh water: only the net gain adds to the supply
        water_out = None if result.water_net.value is None or result.water_net.value <= 0 else result.water_net.value / days
    else:  # seawater or effluent turned into usable water: all of its output is new supply
        water_out = None if not result.water_output.value else result.water_output.value / days
    staff = result.staffing_required.value
    staff_basis = "staffing required"
    if staff is None and result.worker_capacity.value is not None:
        staff, staff_basis = result.worker_capacity.value, "worker capacity (no staffing requirement declared)"
    materials = [(m.name, m.phase, m.quantity_kg) for m in stats.materials if m.name.strip()]
    air = [(e.pollutant, e.rate_kg_per_hour) for e in stats.emissions
           if is_air_pollutant(e.pollutant) and e.rate_kg_per_hour != 0]
    return Demand(result.footprint.value, water, power, export if producer else None, water_out, staff,
                  basis, staff_basis, materials, air, stats.light.upward_lumens, source)


# --- scenario sharing -------------------------------------------------------------------------


@dataclass
class Neighbour:
    id: UUID
    name: str
    h3_id: int
    demand: Demand


def _within(a: np.ndarray, b: int, k: int) -> np.ndarray:
    """Cells of `a` within grid distance k of cell `b`."""
    return np.isin(a, h3n.grid_disk(int(b), k).astype(np.uint64))


@dataclass
class Shared:
    """Effect of other scenario buildings on each centre cell's supply."""

    water_used: np.ndarray
    water_added: np.ndarray
    power_used: np.ndarray
    power_added: np.ndarray
    export_used: np.ndarray
    staff_used: np.ndarray
    land_used: np.ndarray
    notes: list[list[str]]
    unknown: list[list[str]]
    effluent_used: np.ndarray = None  # treated wastewater taken by other buildings within RING_EFFLUENT

    def __post_init__(self):
        if self.effluent_used is None:
            self.effluent_used = np.zeros(len(self.notes))


def shared(cells: np.ndarray, neighbours: list[Neighbour]) -> Shared:
    n = len(cells)
    z = lambda: np.zeros(n)  # noqa: E731
    s = Shared(z(), z(), z(), z(), z(), z(), z(), [[] for _ in range(n)], [[] for _ in range(n)])
    for nb in neighbours:
        d = nb.demand
        rings = {0, RING_RUNOFF, RING_GRID, RING_WORK} | ({RING_EFFLUENT} if d.water_source == "wastewater" else set())
        near = {k: _within(cells, nb.h3_id, k) for k in rings}
        terms = [
            (near[0], "land_used", d.footprint_m2, "footprint", "m²"),
            (near[RING_RUNOFF], "water_used", d.fresh_m3_day, "water", "m³/day"),
            (near[RING_RUNOFF], "water_added", d.water_out_m3_day, "water output", "m³/day"),
            (near[RING_GRID], "power_used", d.power_kw, "power", "kW"),
            (near[RING_GRID], "export_used", d.export_kw, "grid export", "kW"),
            (near[RING_WORK], "staff_used", d.staff, "staff", "people"),
        ]
        if d.water_source == "wastewater":
            terms.append((near[RING_EFFLUENT], "effluent_used", d.effluent_m3_day, "treated wastewater", "m³/day"))
        for mask, attr, value, what, unit in terms:
            if not mask.any():
                continue
            if value is None:
                if attr in ("water_added", "export_used"):
                    continue  # no declared output means it adds nothing, not an unknown
                for i in np.flatnonzero(mask):
                    s.unknown[i].append(f"{what} of {nb.name}")
                continue
            if value == 0:
                continue
            getattr(s, attr)[mask] += value
            for i in np.flatnonzero(mask):
                s.notes[i].append(f"{nb.name}: {what} {fmt_num(value)} {unit}")
    # A placed power station feeds the local grid with its export
    s.power_added = s.export_used.copy()
    return s


def effluent_m3_day(sd: SiteData) -> np.ndarray:
    """Treated wastewater from the population within RING_EFFLUENT (computed on first use, then cached)."""
    cached = getattr(sd, "_effluent", None)
    if cached is not None:
        return cached
    src = _layer_src("population_ghsl", "2025")
    if src is None or not len(sd.cells):
        out = np.full(len(sd.cells), np.nan)
    else:
        de = disk(sd.cells, RING_EFFLUENT)
        out = de.sum(_lookup(src, de.flat)) * EFFLUENT_M3_PER_PERSON
    sd._effluent = out
    return out


# --- checks -----------------------------------------------------------------------------------

PASS, FAIL, UNKNOWN = 0, 1, 2
_STATUS = ("pass", "fail", "unknown")


@dataclass
class SiteCheck:
    kind: str
    label: str
    status: np.ndarray
    build: object  # Callable[[int], CheckResult]
    required: bool = True  # False for advisory checks (raw materials, surplus output)


@dataclass
class Materials:
    """Advisory raw-material checks, kept for the site panel."""

    checks: list
    unmapped: list[str]


def pm25_standard(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, list[str]]:
    isos = regions.country_iso(lats, lons)
    vals = [PM25_STANDARDS.get(iso or "", PM25_DEFAULT) for iso in isos]
    return np.array([v for v, _ in vals], dtype=np.float64), [t for _, t in vals]


def _ck(kind: str, label: str, status: str, **kw) -> CheckResult:
    return CheckResult(criterion_id=f"auto-{kind}", kind=kind, label=label, required=True, status=status, **kw)


def _status(supply: np.ndarray, need: float) -> np.ndarray:
    return np.where(np.isnan(supply), UNKNOWN, np.where(supply >= need, PASS, FAIL)).astype(np.int8)


def _used_text(notes: list[str], unknown: list[str]) -> str:
    out = ""
    if notes:
        out += " Shared with nearby buildings in this scenario: " + "; ".join(notes) + "."
    if unknown:
        out += " Unknown use by: " + ", ".join(unknown) + "."
    return out


def site_checks(btype: str, demand: Demand, sd: SiteData, sh: Shared,
                stress: StressControls) -> tuple[list[SiteCheck], list[str], Materials]:
    """One SiteCheck per resource the building's specs need.

    Returns (checks, resources not checked, raw-material state). Raw-material checks are advisory."""
    n = len(sd.cells)
    checks: list[SiteCheck] = []
    skipped: list[str] = []
    w_mult, p_mult = stress.water_availability, stress.power_availability

    # ---- land ----
    fp = demand.footprint_m2
    if fp is None:
        checks.append(SiteCheck("site_land", "Open land for the footprint", np.full(n, UNKNOWN, dtype=np.int8),
                                lambda i: _ck("site_land", "Open land for the footprint", "unknown", unit="m²",
                                              source=MODELLED,
                                              explanation="The building's footprint is not declared, so whether it fits "
                                              "can't be judged. Enter the footprint in its specs.")))
    else:
        cell_free = sd.land_cell_m2 - sh.land_used
        ring_free = sd.land_ring_m2 - sh.land_used
        status = np.where(np.isnan(cell_free), UNKNOWN,
                          np.where((cell_free >= fp) | (ring_free >= fp), PASS, FAIL)).astype(np.int8)

        def build_land(i: int, fp=fp, cell_free=cell_free, ring_free=ring_free, status=status) -> CheckResult:
            st = _STATUS[status[i]]
            src = ("ESA WorldCover 2021 class shares [LAND-02] and Copernicus DEM mean slope [CTX-03] "
                   f"of cell {h3store.cell_hex(sd.cells[i])} and its {RING_LAND}-ring neighbours")
            if st == "unknown":
                return _ck("site_land", "Open land for the footprint", st, actual=fp, unit="m²", source=src,
                           explanation="No land-cover data for this location (outside the prepared regions).")
            cell_m2, free = sd.cell_m2[i], max(0.0, cell_free[i])
            slope_txt = ("slope unknown" if np.isnan(sd.slope[i])
                         else f"mean slope {sd.slope[i]:.1f}° → factor {sd.slope_factor[i]:.2f}")
            basis = (f"cell {fmt_num(cell_m2 / 1e6)} km² × open land {sd.open_frac[i] * 100:.0f}% "
                     f"(shrub, grass, crop, bare) × {slope_txt} = {fmt_num(sd.land_cell_m2[i])} m²")
            if fp <= free:
                expl = f"Footprint {fmt_num(fp)} m² fits the {fmt_num(free)} m² of open land in the cell ({basis})."
            elif fp <= ring_free[i]:
                expl = (f"Footprint {fmt_num(fp)} m² exceeds the cell's open land ({fmt_num(free)} m²) but fits "
                        f"with the neighbouring cells ({fmt_num(ring_free[i])} m² within ~{RING_KM:.0f} km).")
            else:
                expl = (f"Footprint {fmt_num(fp)} m² is more than the open land here: {fmt_num(free)} m² in the "
                        f"cell, {fmt_num(max(0.0, ring_free[i]))} m² including neighbours ({basis}).")
            return _ck("site_land", "Open land for the footprint", st, actual=fp,
                       required_value=float(max(free, ring_free[i])), unit="m²", source=src,
                       explanation=expl + _used_text([x for x in sh.notes[i] if "footprint" in x], []) +
                       " Open land is not proof of vacant or purchasable land.")

        checks.append(SiteCheck("site_land", "Open land for the footprint", status, build_land))

    # ---- water ----
    need = demand.water_m3_day
    if need is None or need == 0:
        skipped.append("water (no water use declared)" if need is None else "")
    elif demand.water_source == "seawater":
        known = ~np.isnan(sd.open_frac)
        status = np.where(~known, UNKNOWN, np.where(sd.coastal, PASS, FAIL)).astype(np.int8)

        def build_sea(i: int, need=need, status=status) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Seawater intake (coastal site)"
            src = "WorldCover water / ERA5-Land land mask within ~6 km"
            expl = {"pass": f"Coastal site: seawater can supply the {fmt_num(need)} m³/day intake.",
                    "fail": f"Its {fmt_num(need)} m³/day intake is seawater, but there is no coast within "
                            f"~{RING_KM:.0f} km. Choose a coastal hexagon or change the intake source.",
                    "unknown": "No land-cover data here to tell whether the site is coastal."}[st]
            return _ck("site_water", label, st, actual=need, unit="m³/day", source=src,
                       explanation=expl + " Assumes intake and discharge permits; not a licence.")

        checks.append(SiteCheck("site_water", "Seawater intake (coastal site)", status, build_sea))
    elif demand.water_source == "wastewater":
        supply = effluent_m3_day(sd)
        avail = np.where(np.isnan(supply), np.nan, np.maximum(0.0, supply - sh.effluent_used))
        status = _status(avail, need)

        def build_eff(i: int, need=need, avail=avail, supply=supply, status=status) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Treated wastewater available"
            km = RING_EFFLUENT * RING_KM
            src = f"GHSL population 2025 [CTX-05] within ~{km:.0f} km × {EFFLUENT_M3_PER_PERSON} m³ effluent per person per day"
            if st == "unknown":
                return _ck("site_water", label, st, actual=need, unit="m³/day", source=src,
                           explanation="No population data here to estimate treated wastewater.")
            a = float(avail[i])
            basis = (f"{fmt_num(supply[i] / EFFLUENT_M3_PER_PERSON)} people within ~{km:.0f} km × "
                     f"{EFFLUENT_M3_PER_PERSON} m³/person/day = {fmt_num(supply[i])} m³/day of effluent")
            if st == "pass":
                expl = f"Needs {fmt_num(need)} m³/day of treated wastewater; about {fmt_num(a)} m³/day is available ({basis})."
            else:
                expl = (f"Needs {fmt_num(need)} m³/day of treated wastewater but only about {fmt_num(a)} m³/day is "
                        f"available ({basis}); short by {fmt_num(need - a)} m³/day.")
            return _ck("site_water", label, st, actual=need, required_value=a, unit="m³/day", source=src,
                       explanation=expl + _used_text([x for x in sh.notes[i] if "wastewater" in x], [])
                       + " Assumes an effluent pipeline from the treatment works; a screening estimate, not a supply contract.")

        checks.append(SiteCheck("site_water", "Treated wastewater available", status, build_eff))
    else:
        sea_ok = sd.coastal & (btype in SEAWATER_TYPES)
        avail = sd.water_m3_day * w_mult + sh.water_added - sh.water_used
        avail = np.where(np.isnan(avail), np.nan, np.maximum(0.0, avail))
        status = np.where(sea_ok, PASS, _status(avail, need)).astype(np.int8)
        status = np.where((status == FAIL) & np.array([bool(u) for u in sh.unknown]), UNKNOWN, status).astype(np.int8)

        def build_water(i: int, need=need, avail=avail, status=status, sea_ok=sea_ok) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Fresh water available"
            src = ("HydroRIVERS mean discharge [NET-01], ERA5-Land 2024 precipitation − evaporation [CTX-01], "
                   "Aqueduct 4.0 baseline water stress [WATER-06]")
            if sea_ok[i]:
                return _ck("site_water", label, "pass", actual=need, unit="m³/day", source="WorldCover water / ERA5-Land land mask",
                           explanation=f"Coastal site: seawater can supply {fmt_num(need)} m³/day of cooling or "
                           "desalination intake (assumes the process is designed for seawater).")
            if np.isnan(sd.headroom[i]) or np.isnan(sd.water_m3_day[i]):
                why = ("no water-stress score for this basin" if np.isnan(sd.headroom[i])
                       else "no river or climate data here")
                return _ck("site_water", label, "unknown", actual=need, unit="m³/day", source=src,
                           explanation=f"Can't estimate water here: {why} (outside the prepared regions or data gap).")
            cat = WATER_STRESS_NAMES.get(float(sd.stress_cat[i]), "unknown")
            renewable = max(np.nan_to_num(sd.river_m3_day[i]), np.nan_to_num(sd.runoff_m3_day[i]))
            parts = (f"largest river within ~{RING_KM:.0f} km {fmt_num(sd.river_m3_day[i])} m³/day, local runoff "
                     f"(P − E over ~{RING_RUNOFF * RING_KM:.0f} km) {fmt_num(sd.runoff_m3_day[i])} m³/day → renewable "
                     f"{fmt_num(renewable)} m³/day × {sd.headroom[i] * 100:.0f}% unallocated (basin stress: {cat})")
            mult = "" if w_mult == 1 else f" × water availability {fmt_num(w_mult)}"
            a = float(avail[i])
            if st == "pass":
                expl = f"Needs {fmt_num(need)} m³/day; about {fmt_num(a)} m³/day is available ({parts}{mult})."
            elif st == "fail":
                expl = (f"Needs {fmt_num(need)} m³/day but only about {fmt_num(a)} m³/day is available ({parts}{mult}); "
                        f"short by {fmt_num(need - a)} m³/day.")
            else:
                expl = f"Needs {fmt_num(need)} m³/day; known availability {fmt_num(a)} m³/day ({parts}{mult})."
            return _ck("site_water", label, st, actual=need, required_value=a, unit="m³/day", source=src,
                       explanation=expl + _used_text([x for x in sh.notes[i] if "water" in x],
                                                     [x for x in sh.unknown[i] if "water" in x])
                       + " A screening estimate, not a water licence.")

        checks.append(SiteCheck("site_water", "Fresh water available", status, build_water))

    # ---- grid: supply for consumers ----
    need = demand.power_kw
    if need is None:
        skipped.append("grid power (no electricity demand declared)")
    elif need > 0:
        avail = np.maximum(0.0, sd.grid_kw * p_mult + sh.power_added - sh.power_used)
        status = _status(avail, need)
        checks.append(SiteCheck("site_power", "Grid power available", status,
                                _grid_builder("site_power", "Grid power available", need, demand.power_basis,
                                              avail, status, sd, sh, p_mult, "draw")))

    # ---- grid: export for producers ----
    out = demand.export_kw
    if out:
        # Nearby consumers in the scenario take part of the output locally (no export room needed).
        avail = np.maximum(0.0, sd.grid_kw * p_mult + sh.power_used - sh.export_used)
        # A plant can hold part of its output back as operating reserve instead of exporting it.
        status = np.where(np.isnan(avail), UNKNOWN, np.where(avail >= out * (1 - RESERVE_SHARE), PASS, FAIL)).astype(np.int8)
        # Output the grid can't take is surplus to use locally, not a reason the plant can't be built.
        checks.append(SiteCheck("site_grid_export", "Grid connection for output", status,
                                _grid_builder("site_grid_export", "Grid connection for output", out,
                                              "rated (else average) output", avail, status, sd, sh, p_mult, "export"),
                                required=False))

    # ---- workforce ----
    need = demand.staff
    if need is None or need == 0:
        skipped.append("workforce (no staffing declared)" if need is None else "")
    else:
        avail = np.maximum(0.0, sd.workforce - sh.staff_used)
        status = _status(avail, need)

        def build_work(i: int, need=need, avail=avail, status=status) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Local workforce"
            src = f"GHSL population 2025 [CTX-05] within ~{RING_WORK * RING_KM:.0f} km ({RING_WORK} rings)"
            if st == "unknown":
                return _ck("site_workforce", label, st, actual=need, unit="people", source=src,
                           explanation="No population data here.")
            a = float(avail[i])
            basis = (f"{fmt_num(sd.population[i])} people × {LABOUR_SHARE * 100:.0f}% in the labour force × "
                     f"{RECRUIT_SHARE * 100:.0f}% recruitable by one employer")
            expl = (f"Needs {fmt_num(need)} ({demand.staff_basis}); about {fmt_num(a)} could be recruited locally "
                    f"({basis}).")
            if st == "fail":
                expl += " Staff would have to relocate or commute further."
            return _ck("site_workforce", label, st, actual=need, required_value=a, unit="people", source=src,
                       explanation=expl + _used_text([x for x in sh.notes[i] if "staff" in x], []))

        checks.append(SiteCheck("site_workforce", "Local workforce", status, build_work))

    # ---- air quality ----
    if demand.air_pollutants:
        std, std_src = pm25_standard(sd.lats, sd.lons)
        status = np.where(np.isnan(sd.pm25), UNKNOWN, np.where(sd.pm25 <= std * AIR_MARGIN, PASS, FAIL)).astype(np.int8)
        emitted = "; ".join(f"{p} {'unknown rate' if r is None else fmt_num(r) + ' kg/h'}"
                            for p, r in demand.air_pollutants)

        def build_air(i: int, status=status, std=std, std_src=std_src, emitted=emitted) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Air-quality headroom for its emissions"
            src = f"CAMS EAC4 2024 annual mean PM2.5 at the cell [AIR-02] vs {std_src[i]}"
            if st == "unknown":
                return _ck("site_air", label, st, unit="µg/m³", source=src,
                           explanation=f"Emits {emitted}, but there is no air-quality data here (outside the "
                           "prepared regions).")
            pm, lim = float(sd.pm25[i]), float(std[i])
            ctx = (f" Context: NO₂ column {fmt_num(sd.no2col[i])} µmol/m², SO₂ column {fmt_num(sd.so2col[i])} µmol/m²"
                   if not np.isnan(sd.no2col[i]) else "")
            margin = f"{(AIR_MARGIN - 1) * 100:.0f}%"
            if st == "pass" and pm <= lim:
                expl = (f"Emits {emitted}. Background PM2.5 here is {fmt_num(pm)} µg/m³, within the annual "
                        f"standard of {fmt_num(lim)} µg/m³ (headroom {fmt_num(lim - pm)} µg/m³).")
            elif st == "pass":
                expl = (f"Emits {emitted}. Background PM2.5 here is {fmt_num(pm)} µg/m³, slightly above the annual "
                        f"standard of {fmt_num(lim)} µg/m³ but within the {margin} screening margin for this coarse "
                        "reanalysis. Borderline: local monitors decide, and emission offsets may be required.")
            else:
                expl = (f"Emits {emitted}, but background PM2.5 here is {fmt_num(pm)} µg/m³, clearly above the "
                        f"annual standard of {fmt_num(lim)} µg/m³ (more than the {margin} screening margin): a new "
                        "emitter would need emission offsets or tighter controls. Choose a cleaner-air hexagon or "
                        "remove the emissions from the specs.")
            return _ck("site_air", label, st, actual=pm, required_value=lim, unit="µg/m³", source=src,
                       explanation=expl + ctx + ". Emission rates are not converted into concentrations; "
                       "CAMS is a ~80 km reanalysis. Screening only, not an air permit.")

        checks.append(SiteCheck("site_air", "Air-quality headroom for its emissions", status, build_air))

    # ---- dark sky ----
    lum = demand.upward_lumens
    if lum is not None and lum > 0:
        status = np.where(np.isnan(sd.zone), UNKNOWN, np.where(sd.zone <= 1, FAIL, PASS)).astype(np.int8)

        def build_light(i: int, lum=lum, status=status) -> CheckResult:
            st = _STATUS[status[i]]
            label = "Dark-sky zone allows its upward light"
            src = ("ILP GN01:2021 lighting environmental zones, classified from GHSL 2025 population over "
                   f"~{RING_KM:.0f} km [CTX-05] and built-up share of the cell")
            if st == "unknown":
                return _ck("site_light", label, st, actual=lum, unit="lm", source=src,
                           explanation="No population or built-up data here to classify the lighting zone.")
            zname, ulr = ZONE_NAMES[int(sd.zone[i])]
            basis = (f"{fmt_num(sd.density[i])} people/km² nearby, built-up {fmt_num(sd.built_share[i] * 100)}% "
                     f"of the cell → {zname}")
            if st == "fail":
                expl = (f"Declares {fmt_num(lum)} lm of upward light, but this is a dark area ({basis}) where "
                        "the upward light ratio limit is 0%. Use fully shielded lighting (0 upward lumens) or "
                        "build in a lit settlement.")
            else:
                expl = (f"Declares {fmt_num(lum)} lm of upward light in zone {zname} ({basis}), which allows an "
                        f"upward light ratio up to {fmt_num(ulr)}% of the installation's flux.")
            return _ck("site_light", label, st, actual=lum, unit="lm", source=src,
                       explanation=expl + " Zones are a screening classification, not a sky-brightness measurement.")

        checks.append(SiteCheck("site_light", "Dark-sky zone allows its upward light", status, build_light))

    # ---- raw materials (advisory: they can be shipped) ----
    mchecks, unmapped, _ = site_materials.material_checks(demand.materials, sd.cells, sd.lats, sd.lons)
    for mc in mchecks:
        checks.append(SiteCheck(mc.kind, mc.label, mc.status, mc.build, required=False))
    if unmapped:
        skipped.append("raw-material sources for " + ", ".join(unmapped) + " (not a mapped raw material)")

    return checks, [s for s in skipped if s], Materials(mchecks, unmapped)


def _grid_builder(kind, label, need, basis, avail, status, sd: SiteData, sh: Shared, mult, mode):
    def build(i: int) -> CheckResult:
        st = _STATUS[status[i]]
        src = (f"OpenStreetMap power lines and substations within ~{RING_KM:.0f} km [GRID-OSM], "
               "GHSL population / WorldCover built-up for distribution networks")
        if st == "unknown":
            return _ck(kind, label, st, actual=need, unit="kW", source=src,
                       explanation="No power-grid data for this location (outside the prepared regions).")
        kv = sd.grid_kv[i]
        if np.isnan(kv):
            grid = ("no mapped transmission line or substation within ~6 km; a settled area's local distribution "
                    f"network ({fmt_kw(DISTRIBUTION_KW)})" if sd.settled[i]
                    else f"no mapped line, substation or settlement within ~{RING_KM:.0f} km")
        else:
            hub = "" if np.isnan(sd.grid_sub_kv[i]) else f", substation {fmt_num(sd.grid_sub_kv[i])} kV"
            grid = (f"highest mapped voltage {fmt_num(kv)} kV{hub} → indicative {fmt_kw(sd.grid_kw[i])} "
                    "for a new connection")
        m = "" if mult == 1 else f" × power availability {fmt_num(mult)}"
        a = float(avail[i])
        verb = "export" if mode == "export" else "draw"
        if st == "pass" and a < need:
            expl = (f"Needs to {verb} {fmt_kw(need)} ({basis}); about {fmt_kw(a)} can be used or exported "
                    f"({grid}{m}). The remaining {fmt_kw(need - a)} is within the {RESERVE_SHARE * 100:.0f}% of output a "
                    "plant can hold back as operating reserve.")
        elif st == "pass":
            expl = f"Needs to {verb} {fmt_kw(need)} ({basis}); about {fmt_kw(a)} is available ({grid}{m})."
        elif mode == "export":
            expl = (f"Produces {fmt_kw(need)} ({basis}); the grid here can take about {fmt_kw(a)} ({grid}{m}). "
                    f"The other {fmt_kw(need - a)} is surplus: a data centre or other large consumer in this or a "
                    "neighbouring hexagon can use it locally.")
        else:
            expl = (f"Needs to draw {fmt_kw(need)} ({basis}) but only about {fmt_kw(a)} is available "
                    f"({grid}{m}); short by {fmt_kw(need - a)}. Place a power station in this or a neighbouring "
                    "hexagon to add its output, or a new high-voltage line would be needed.")
        notes = [x for x in sh.notes[i] if ("grid export" in x) or ("power" in x)]
        local = "" if mode != "export" or not sh.power_used[i] else (
            f" Nearby buildings in this scenario use {fmt_kw(sh.power_used[i])} of it locally, which needs no export room.")
        boost = "" if mode == "export" or not sh.power_added[i] else (
            f" Includes {fmt_kw(sh.power_added[i])} from power stations placed nearby in this scenario.")
        return _ck(kind, label, st, actual=need, required_value=a, unit="kW", source=src,
                   explanation=expl + local + boost + _used_text(notes, []) + " Indicative only, not a connection offer.",
                   ).model_copy(update={"required": mode != "export"})
    return build


# --- location summary for the UI --------------------------------------------------------------


def capacity_at(sd: SiteData, sh: Shared, i: int, stress: StressControls, demand: Demand, btype: str,
                mats: Materials | None = None) -> SiteCapacity:
    """Everything the site offers (whether or not the building needs it), for the preview panel."""
    def v(x) -> float | None:
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)

    water_total = v(sd.water_m3_day[i])
    water_avail = None if water_total is None else max(0.0, water_total * stress.water_availability
                                                        + sh.water_added[i] - sh.water_used[i])
    water_label, water_reach, water_extra = "Fresh water", f"~{RING_RUNOFF * RING_KM:.0f} km catchment", []
    if demand.water_source == "wastewater":
        eff = v(effluent_m3_day(sd)[i])
        water_label, water_reach = "Treated wastewater", f"~{RING_EFFLUENT * RING_KM:.0f} km pipeline"
        water_avail = None if eff is None else max(0.0, eff - sh.effluent_used[i])
        water_extra = [SiteResourcePart(label=f"Population within ~{RING_EFFLUENT * RING_KM:.0f} km",
                                        value=None if eff is None else eff / EFFLUENT_M3_PER_PERSON, unit="people"),
                       SiteResourcePart(label="Effluent per person", value=EFFLUENT_M3_PER_PERSON, unit="m³/day")]
    elif demand.water_source == "seawater":
        water_label = "Seawater intake"
        water_avail = (float("inf") if sd.coastal[i] else 0.0) if not np.isnan(sd.open_frac[i]) else None
    if np.isnan(sd.grid_kw[i]):
        grid_avail = None
    elif demand.export_kw:  # a producer needs room to export, which other generators nearby take up
        grid_avail = max(0.0, sd.grid_kw[i] * stress.power_availability + sh.power_used[i] - sh.export_used[i])
    else:
        grid_avail = max(0.0, sd.grid_kw[i] * stress.power_availability + sh.power_added[i] - sh.power_used[i])
    land = v(sd.land_cell_m2[i])
    resources = [
        SiteResource(
            key="land", label="Open land", unit="m²",
            available=None if land is None else max(0.0, land - sh.land_used[i]),
            needed=demand.footprint_m2,
            reach=f"this cell ({fmt_num(sd.cell_m2[i] / 1e6)} km²)",
            parts=[
                SiteResourcePart(label="Open land share (shrub, grass, crop, bare)", value=v(sd.open_frac[i] * 100), unit="%"),
                SiteResourcePart(label="Mean slope", value=v(sd.slope[i]), unit="°"),
                SiteResourcePart(label="With neighbouring cells", value=v(sd.land_ring_m2[i]), unit="m²"),
            ],
        ),
        SiteResource(
            key="water", label=water_label, unit="m³/day",
            available=None if water_avail is None or math.isinf(water_avail) else water_avail,
            status=("pass" if water_avail and math.isinf(water_avail) else "fail" if water_avail == 0.0 and demand.water_m3_day
                    else None) if demand.water_source == "seawater" else None,
            needed=demand.water_m3_day, reach=water_reach,
            parts=water_extra + [
                SiteResourcePart(label=f"Largest river within ~{RING_KM:.0f} km", value=v(sd.river_m3_day[i]), unit="m³/day"),
                SiteResourcePart(label="Local runoff (rain − evaporation)", value=v(sd.runoff_m3_day[i]), unit="m³/day"),
                SiteResourcePart(label="Basin water stress", text=WATER_STRESS_NAMES.get(float(sd.stress_cat[i]))
                                 if not np.isnan(sd.stress_cat[i]) else None),
                SiteResourcePart(label="Unallocated share", value=v(sd.headroom[i] * 100), unit="%"),
            ] + ([SiteResourcePart(label="Seawater", text="coastal site" + (
                " (usable by this building type)" if btype in SEAWATER_TYPES else " (only cooling, desalination and marine intakes: thermal power, water plants, heavy industry, hydrogen and aquaculture)"))]
                 if sd.coastal[i] else []),
        ),
        SiteResource(
            key="power", label="Grid power", unit="kW", available=v(grid_avail),
            needed=demand.export_kw or demand.power_kw, reach=f"~{RING_KM:.0f} km",
            parts=[
                SiteResourcePart(label="Highest mapped voltage", value=v(sd.grid_kv[i]), unit="kV"),
                SiteResourcePart(label="Highest substation voltage", value=v(sd.grid_sub_kv[i]), unit="kV"),
                SiteResourcePart(label="Settled area (distribution network)", text="yes" if sd.settled[i] else "no"),
                SiteResourcePart(label="Added by power stations placed nearby", value=float(sh.power_added[i]), unit="kW"),
                SiteResourcePart(label="Used by buildings placed nearby", value=float(sh.power_used[i]), unit="kW"),
            ],
            note="Room to export this building's output" if demand.export_kw else None,
        ),
        SiteResource(
            key="workforce", label="Recruitable workers", unit="people",
            available=None if np.isnan(sd.workforce[i]) else max(0.0, sd.workforce[i] - sh.staff_used[i]),
            needed=demand.staff, reach=f"~{RING_WORK * RING_KM:.0f} km commute",
            parts=[SiteResourcePart(label="Population", value=v(sd.population[i]), unit="people")],
        ),
    ]
    resources += _extra_resources(sd, i, demand, mats)
    rings = {"land": RING_LAND, "water": RING_EFFLUENT if demand.water_source == "wastewater" else RING_RUNOFF,
             "power": RING_GRID, "workforce": RING_WORK, "air": 0, "light": 1}
    return SiteCapacity(h3_id=h3store.cell_hex(sd.cells[i]), resources=resources,
                        neighbour_cells=[h3store.cell_hex(c) for c in h3n.grid_disk(int(sd.cells[i]), RING_GRID)
                                         if int(c) != int(sd.cells[i])],
                        rings=rings, note=SITE_NOTE)


def _extra_resources(sd: SiteData, i: int, demand: Demand, mats: Materials | None) -> list[SiteResource]:
    def v(x) -> float | None:
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)

    out: list[SiteResource] = []
    std, std_src = pm25_standard(sd.lats[i:i + 1], sd.lons[i:i + 1])
    pm = v(sd.pm25[i])
    if not demand.air_pollutants:
        air_status = "none"
    else:
        air_status = "unknown" if pm is None else ("pass" if pm <= std[0] * AIR_MARGIN else "fail")
    out.append(SiteResource(
        key="air", label="Air-quality headroom", unit="µg/m³",
        available=None if pm is None else float(std[0] - pm), needed=None, status=air_status,
        reach="this cell (CAMS ~80 km grid)",
        parts=[SiteResourcePart(label="Background PM2.5 (2024 mean)", value=pm, unit="µg/m³"),
               SiteResourcePart(label="Annual standard", value=float(std[0]), unit="µg/m³"),
               SiteResourcePart(label="Standard", text=std_src[0]),
               SiteResourcePart(label="PM10 (2024 mean)", value=v(sd.pm10[i]), unit="µg/m³"),
               SiteResourcePart(label="Local air pollutants in its specs",
                                text=", ".join(p for p, _ in demand.air_pollutants) or "none")],
        note=None if demand.air_pollutants else "Its specs declare no local air pollutants (greenhouse gases do not count).",
    ))
    zone = v(sd.zone[i])
    lum = demand.upward_lumens
    if not lum:
        light_status = "none"
    else:
        light_status = "unknown" if zone is None else ("fail" if zone <= 1 else "pass")
    out.append(SiteResource(
        key="light", label="Dark-sky zone", unit="% upward light ratio",
        available=None if zone is None else ZONE_NAMES[int(zone)][1], needed=None, status=light_status,
        reach=f"~{RING_KM:.0f} km",
        parts=[SiteResourcePart(label="Lighting zone (ILP GN01)", text=None if zone is None else ZONE_NAMES[int(zone)][0]),
               SiteResourcePart(label="People per km² nearby", value=v(sd.density[i]), unit="people/km²"),
               SiteResourcePart(label="Built-up share of the cell",
                                value=None if v(sd.built_share[i]) is None else sd.built_share[i] * 100, unit="%"),
               SiteResourcePart(label="Upward light in its specs", value=lum, unit="lm")],
    ))
    if mats is not None:
        r = site_materials.material_resource(demand.materials, mats.checks, mats.unmapped, i)
        if r is not None:
            out.append(r)
    return out


SITE_NOTE = (
    "Estimated automatically from prepared data for this cell and its neighbours; nothing here is typed in. "
    "Buildings already in the scenario nearby use part of it, and placed power stations or water plants add to it. "
    "Raw materials can be shipped, so their local sources are shown for planning and never block a site. "
    "Screening estimates only: not a water licence, a grid connection offer, land ownership or planning permission."
)
