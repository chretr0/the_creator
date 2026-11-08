"""Graded site suitability: how ideal a resolution-6 cell is for a building type.

The hard screening state (``meets_criteria`` / ``insufficient_data`` / ``fails_criteria``) says whether
the site can provide what the specs need. This module grades *how ideal* the cell is, from every
relevant per-cell dataset we hold, and never changes that state.

Method (FAO land-suitability classes + a transparent weighted mean), in order:

- Each factor grades a cell ideal (S1, 3 points), good (S2, 2), marginal (S3, 1) or unsuitable (N, 0)
  with nested inclusive envelopes ``ideal ⊂ good ⊂ marginal`` (a ``None`` bound is open-ended);
  outside ``marginal`` is unsuitable. A cell without data for a factor leaves it out.
- Veto: a *constraint* factor graded unsuitable makes the whole cell unsuitable.
- Weighted mean: score = Σ(weight × points) / Σ(weight) over factors with data, rounded to 2 dp;
  ≥ 2.6 ideal, ≥ 2.0 good, ≥ 1.25 marginal, below that unsuitable.
- Coverage = Σ(weight with data) / Σ(all weights); below 0.5 the cell is not graded (tier None),
  unless vetoed.
- Then three bounds can only lower a graded grade: the one-class cap (at most one class better than
  the weakest factor with data: a marginal factor caps it at good, an unsuitable one at marginal);
  the constraint hold (no better than any constraint factor with data: marginal sunlight makes a
  solar site marginal); and the no-data cap (at most good while any constraint factor has no data,
  since the site can't be confirmed ideal without it).
- Limiting factors: those graded marginal or unsuitable, worst first, then by weight. The summary
  names whichever bound set the grade.

Data handling worth knowing: regional layers (UK, Arizona boxes) are no data elsewhere, never zero.
Open water outside those regions is inferred from missing land data (no SoilGrids soil, no GHSL or
WorldPop residents, no VIIRS detection of any type, no mapped power plant or airport → 100 %, called
ice where no month gets above 2 °C), otherwise unknown; ``offshore_water`` reads any of those land signs
as land and inferred ice as 0 % (not open sea).
Wildfire counts VIIRS vegetation fires only (industrial heat sources excluded), and a blank cell is 0
only on known land. Irrigated farms count rivers only as water access (they can't use seawater);
thermal plants, water plants and aquaculture without a system count the coast too. Wind farms split
on the ``siting`` parameter: onshore is a land building (open water vetoes), offshore drops the land
factors and needs a cell that is mostly open sea.

Values are compared at the precision they are displayed with, so a value shown on a band edge is
graded on the side its text says. Profiles are data tables (``_PROFILES`` and the builders below);
everything runs as numpy vectors over the cells of one ``site_capacity.SiteData``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import h3
import numpy as np

from app import features, layers, site_capacity
from app.building_models import (
    BuildingStats,
    FactorGrade,
    Suitability,
    SuitabilityFactor,
    SuitabilityProfile,
    SuitabilityTier,
)

Band = tuple[float | None, float | None]
ANY: Band = (None, None)


def ge(a: float) -> Band:
    return (a, None)


def le(b: float) -> Band:
    return (None, b)


def rng(a: float, b: float) -> Band:
    return (a, b)


TIERS: tuple[SuitabilityTier, ...] = ("ideal", "good", "marginal", "unsuitable")
NO_DATA, IDEAL, GOOD, MARGINAL, UNSUITABLE = 0, 1, 2, 3, 4  # per-factor codes ('0'..'4' in CellState.grades)
POINTS = np.array([0, 3, 2, 1, 0], dtype=np.float64)  # indexed by code
CUTS = ((2.6, 0), (2.0, 1), (1.25, 2))  # score ≥ cut → index into TIERS; below the last → unsuitable
MIN_COVERAGE = 0.5
NOT_GRADED = -1  # overall tier index when coverage is too low
UNGRADED_RANK = 4  # candidate ordering: ideal 0 … unsuitable 3, not graded 4
TIER_COUNT_KEYS = ("ideal", "good", "marginal", "unsuitable", "unknown")

METHOD = (
    "Each factor grades the cell ideal (3 points), good (2), marginal (1) or unsuitable (0) from nested "
    "bands: ideal lies inside good, good inside marginal, and anything outside marginal is unsuitable. "
    "Factors without data here are left out. "
    "1) A constraint factor graded unsuitable makes the whole cell unsuitable. "
    "2) Otherwise the score is the weighted mean of points over the factors with data (0–3). "
    f"3) If those factors carry less than {MIN_COVERAGE:.0%} of the total weight, the cell is not graded. "
    f"4) Score ≥ {CUTS[0][0]} is ideal, ≥ {CUTS[1][0]} good, ≥ {CUTS[2][0]} marginal, below that unsuitable; "
    "the grade is at most one class better than the weakest factor with data (a marginal factor caps it at "
    "good, an unsuitable one at marginal), and no better than any constraint factor (the building's main "
    "resource or a physical limit can't be outweighed: marginal sunlight makes a solar site marginal). "
    "While a constraint factor has no data here the grade is at most good: the site can't be confirmed "
    "ideal without it. "
    "5) Limiting factors are those graded marginal or unsuitable, worst first, then by weight. "
    "A screening grade from coarse public datasets, not a site survey."
)


# --- data access ------------------------------------------------------------------------------


class _Data:
    """Raw values for the cells of one SiteData (stored ÷ scale, no display transforms), looked up
    once per call and shared by every factor that needs them."""

    def __init__(self, sd: site_capacity.SiteData):
        self.sd = sd
        self.cells, self.lats, self.lons = sd.cells, sd.lats, sd.lons
        self.n = len(sd.cells)
        self._cache: dict = {}

    def memo(self, key, fn: Callable[[], np.ndarray]) -> np.ndarray:
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def layer(self, layer_id: str, slice_id: str) -> np.ndarray:
        return self.memo((layer_id, slice_id), lambda: site_capacity._lookup(
            site_capacity._layer_src(layer_id, slice_id), self.cells))

    def in_regions_with(self, pattern: str) -> np.ndarray:
        """Inside a prepared region whose file for `pattern` exists."""
        return self.memo(("regions", pattern), lambda: site_capacity._in_regions_with(self.lats, self.lons, pattern))

    def months(self) -> np.ndarray:
        """Monthly mean air temperature (NASA POWER climatology), shape (12, n)."""
        return self.memo("months", lambda: np.vstack(
            [self.layer("air_temperature", f"clim-{m:02d}") for m in range(1, 13)]) if self.n else np.zeros((12, 0)))


def _all_nan(a: np.ndarray) -> np.ndarray:
    return np.isnan(a).all(axis=0)


def _growing_season(d: _Data) -> np.ndarray:
    t = d.months()
    return np.where(_all_nan(t), np.nan, (np.nan_to_num(t, nan=-99.0) >= 5.0).sum(axis=0).astype(np.float64))


def _warmest(d: _Data) -> np.ndarray:
    t = d.months()
    return np.where(_all_nan(t), np.nan, np.nanmax(np.where(np.isnan(t), -np.inf, t), axis=0))


def _coldest(d: _Data) -> np.ndarray:
    t = d.months()
    return np.where(_all_nan(t), np.nan, np.nanmin(np.where(np.isnan(t), np.inf, t), axis=0))


def _river_m3s(d: _Data) -> np.ndarray:
    """Largest HydroRIVERS mean discharge within ring 1 (m³/s). SiteData stores 0 where no reach is
    mapped, everywhere; it is only evidence of "no river" where the prepared river network covers
    the cell (inside a prepared region and the network's bounding box), so elsewhere it is no data."""
    def compute() -> np.ndarray:
        meta = features.layer_meta("hydrorivers")
        if meta is None or not features.available(meta):
            return np.full(d.n, np.nan)
        w, s, e, n = meta.get("bbox") or (-180.0, -90.0, 180.0, 90.0)
        covered = (site_capacity._in_regions(d.lats, d.lons) & (d.lons >= w) & (d.lons <= e)
                   & (d.lats >= s) & (d.lats <= n))
        return np.where(covered, d.sd.river_m3_day / 86_400.0, np.nan)
    return d.memo("river", compute)


def _coastal(d: _Data) -> np.ndarray:
    """1 coastal, 0 inland, NaN unknown (SiteData.coastal is False where land cover is missing)."""
    def compute() -> np.ndarray:
        known = site_capacity._in_regions(d.lats, d.lons) & ~np.isnan(d.sd.open_frac)
        return np.where(known, d.sd.coastal.astype(np.float64), np.nan)
    return d.memo("coastal", compute)


def _share(*slices: str) -> Callable[[_Data], np.ndarray]:
    """WorldCover class shares (raw 0–1) as % of the cell."""
    return lambda d: np.sum([d.layer("land_cover", s) for s in slices], axis=0) * 100.0


# Power-plant kinds that can stand in the sea (GPPD has offshore wind farms and tidal barrages).
SEA_PLANT_KINDS = {"Wind", "Wave and Tidal"}


@lru_cache(maxsize=2)
def _infrastructure_index(key: tuple) -> np.ndarray:
    """Sorted res-6 cells holding a mapped power plant (except wind and wave/tidal) or an airport."""
    cells: set[int] = set()
    for path, _mtime in key:
        for f in json.loads(Path(path).read_text()).get("features", []):
            props = f.get("properties") or {}
            if props.get("kind") in SEA_PLANT_KINDS:
                continue
            h = props.get("h3Id")
            if not h:
                coords = (f.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 2:
                    continue
                h = h3.latlng_to_cell(coords[1], coords[0], 6)
            cells.add(int(h, 16))
    return np.array(sorted(cells), dtype=np.uint64)


def _infrastructure_cells() -> np.ndarray:
    root = Path(layers.settings.prepared_data_dir) / "infrastructure"
    files = [root / n for n in ("power_plants.geojson", "airports.geojson")]
    return _infrastructure_index(tuple((str(f), f.stat().st_mtime) for f in files if f.exists()))


def _land_evidence(d: _Data) -> np.ndarray:
    """Global signs that a cell is land: SoilGrids soil, GHSL or WorldPop residents, any VIIRS detection
    (industrial heat included: reclaimed land such as Caofeidian is typed "offshore"), or a mapped power
    plant or airport (Tuas, Singapore: an industrial island with no soil, residents or fires)."""
    def compute() -> np.ndarray:
        signs = [~np.isnan(d.layer("soil_nitrogen", "0-5cm")), d.layer("population_ghsl", "2025") > 0,
                 d.layer("population_worldpop", "2025") > 0, d.layer("fires_2024", "detections") > 0,
                 np.isin(d.cells, _infrastructure_cells())]
        return np.logical_or.reduce(signs)
    return d.memo("land_evidence", compute)


def _open_water(d: _Data) -> np.ndarray:
    """Open-water share of the cell (%).

    Inside a prepared region holding WorldCover and ERA5-Land: the WorldCover permanent-water share;
    open sea beyond WorldCover's land tiles has no WorldCover value, and a cell there with no ERA5-Land
    (land-only) value is sea (the coastline test of site_capacity) and counts as 100 %.

    Elsewhere there is no land-cover layer, so water is inferred from missing land data: a cell with
    none of the land signs of `_land_evidence` is sea, a lake or ice (100 %; flagged for the display,
    and called ice where no month gets above 2 °C). SoilGrids alone isn't enough: it also leaves city
    centres and industrial land blank. Every other cell outside the regions is no data."""
    def compute() -> np.ndarray:
        wc = d.layer("land_cover", "water")
        era = d.layer("era5_precip", "2024-ann")
        mapped = d.in_regions_with("worldcover_{region}_h3r6.parquet") & d.in_regions_with(layers.ERA5_FILE)
        sea = np.isnan(wc) & np.isnan(era) & mapped
        soil_known = site_capacity._layer_src("soil_nitrogen", "0-5cm") is not None
        inferred = ~mapped & soil_known & ~_land_evidence(d)
        d._cache["open_water_inferred"] = inferred
        d._cache["open_water_mapped"] = mapped
        # NASA POWER: no month above 2 °C. Catches ice sheets and ice caps (Vatnajökull, Svalbard ~1 °C) and
        # ice-covered polar seas; none of them is open water for a turbine or buildable land.
        d._cache["ice"] = inferred & (_warmest(d) < ICE_WARMEST_C)
        return np.where(sea | inferred, 100.0, np.where(mapped, wc * 100.0, np.nan))
    return d.memo("open_water", compute)


ICE_WARMEST_C = 2.0


def _offshore_water(d: _Data) -> np.ndarray:
    """Open water for an offshore site (%): the open-water share in the mapped regions. Outside them a
    cell is binary: inferred water (100 %) or, with any land sign, land (0 %). Inferred water where no
    month gets above 2 °C is ice (an ice sheet, an ice cap or ice-covered sea), not open sea: 0 %, so the
    constraint rules it out. Unlike `open_water` (where a cell with land signs may still be partly water,
    so its share is unknown), any land in the cell is enough to rule out an offshore site; mostly-sea
    cells right on the coast read as land, which only errs towards caution."""
    def compute() -> np.ndarray:
        ow = _open_water(d)
        mapped, inferred, ice = (d._cache[k] for k in ("open_water_mapped", "open_water_inferred", "ice"))
        soil_known = site_capacity._layer_src("soil_nitrogen", "0-5cm") is not None
        outside = ~mapped & soil_known
        d._cache["offshore_water_inferred"] = outside & inferred  # water or ice, both shown as inferred
        return np.where(mapped, ow, np.where(outside, np.where(inferred & ~ice, 100.0, 0.0), np.nan))
    return d.memo("offshore_water", compute)


def _land_known(d: _Data) -> np.ndarray:
    """Cells known to be land rather than mostly water: in the mapped regions, open water ≤ 90 % (the
    open-water veto line); elsewhere, any cell not inferred to be water (it has a land sign)."""
    ow = _open_water(d)
    mapped = d._cache["open_water_mapped"]
    return np.where(mapped, ow <= 90.0, ~(ow > 90.0))


def _fires(d: _Data) -> np.ndarray:
    """VIIRS vegetation-fire detections (type 0) in the cell; volcanoes, static land sources such as
    steelworks and flares, and offshore detections are excluded. The table is global and lists only
    cells with a detection, so a blank *land* cell means none were recorded (0); over water a blank
    is no data."""
    def compute() -> np.ndarray:
        src = site_capacity._layer_src("fires_2024", "vegetation")
        if src is None:
            return np.full(d.n, np.nan)
        v = site_capacity._lookup(src, d.cells)
        return np.where(np.isnan(v) & _land_known(d), 0.0, v)
    return d.memo("fires", compute)


def _water_price(d: _Data) -> np.ndarray:
    """Business water price, else the household price (the table has business water prices for few
    countries, none in the prepared regions)."""
    b = d.layer("water_price", "business")
    h = d.layer("water_price", "household")
    d._cache["water_price_household"] = np.isnan(b) & ~np.isnan(h)
    return np.where(np.isnan(b), h, b)


def _chlorophyll(d: _Data) -> np.ndarray:
    src = site_capacity._layer_src("pace_chlorophyll", "2025-07")
    if src is None or not d.n:
        return np.full(d.n, np.nan)
    ring = site_capacity.disk(d.cells, 1)
    return ring.max(site_capacity._lookup(src, ring.flat))


def _nan_if_none(a: np.ndarray | None, n: int) -> np.ndarray:
    return np.full(n, np.nan) if a is None else np.asarray(a, dtype=np.float64)


# --- factor catalogue -------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorDef:
    key: str
    label: str
    group: str
    unit: str  # display unit (API)
    decimals: int | None  # value precision; None = 3 significant figures
    layer_id: str | None
    slice_id: str | None
    source: str
    why: str
    value: Callable[[_Data], np.ndarray]
    prefix: bool = False  # unit written before the number: "pH 6.5", "NDVI 0.62"
    force_ideal: Callable[[_Data], np.ndarray] | None = None  # cells graded ideal whatever the value
    ideal_extra: str = ""  # appended to the ideal band text
    labels: dict[float, str] | None = None  # categorical values (coastal / inland)


def _soil(var: str, depth: str = "0-5cm") -> Callable[[_Data], np.ndarray]:
    return lambda d: d.layer(f"soil_{var}", depth)


_FACTORS: list[FactorDef] = [
    FactorDef("soil_nitrogen", "Soil nitrogen", "Soil", "g/kg", 2, "soil_nitrogen", "0-5cm",
              "SoilGrids 2.0 total nitrogen (0–5 cm)",
              "Total nitrogen is the pool that mineralises into plant-available nitrate (nitrate itself isn't "
              "mapped); low totals mean more fertiliser for the same yield.", _soil("nitrogen")),
    FactorDef("soil_ph", "Soil pH", "Soil", "pH", 1, "soil_phh2o", "0-5cm", "SoilGrids 2.0 pH in water (0–5 cm)",
              "pH controls which nutrients roots can take up; acid or alkaline soils need liming or limit "
              "crop choice.", _soil("phh2o"), prefix=True),
    FactorDef("soil_organic_carbon", "Soil organic carbon", "Soil", "g/kg", None, "soil_soc", "0-5cm",
              "SoilGrids 2.0 organic carbon (0–5 cm)",
              "Organic matter holds water and nutrients and keeps soil workable; very high values are peat, "
              "which drains poorly.", _soil("soc")),
    FactorDef("soil_clay", "Clay content", "Soil", "%", 1, "soil_clay", "0-5cm", "SoilGrids 2.0 clay (0–5 cm)",
              "Some clay holds water and nutrients; heavy clay drains and works poorly.", _soil("clay")),
    FactorDef("soil_sand", "Sand content", "Soil", "%", 1, "soil_sand", "0-5cm", "SoilGrids 2.0 sand (0–5 cm)",
              "Sandy soils drain freely but hold little water or nutrients.", _soil("sand")),
    FactorDef("soil_compaction", "Subsoil bulk density", "Soil", "kg/dm³", 2, "soil_bdod", "15-30cm",
              "SoilGrids 2.0 bulk density (15–30 cm)",
              "Dense (compacted) subsoil restricts roots and drainage.", _soil("bdod", "15-30cm")),
    FactorDef("rainfall", "Annual rainfall", "Climate", "mm/yr", 0, "precipitation", "clim-ann",
              "NASA POWER climatology (corrected precipitation, mean mm/day × 365.25)",
              "Rainfall supplies the site's water.", lambda d: d.layer("precipitation", "clim-ann") * 365.25),
    FactorDef("temperature", "Mean annual temperature", "Climate", "°C", 1, "air_temperature", "clim-ann",
              "NASA POWER climatology (2 m air temperature)", "Temperature sets what grows and what it costs to "
              "heat or cool.", lambda d: d.layer("air_temperature", "clim-ann")),
    FactorDef("growing_season", "Growing season", "Climate", "months", 0, "air_temperature", "clim-ann",
              "NASA POWER monthly climatology: months with a mean of 5 °C or more",
              "Months warm enough for crops to grow (monthly mean ≥ 5 °C).", _growing_season),
    FactorDef("warmest_month", "Warmest-month temperature", "Climate", "°C", 1, "air_temperature", "clim-07",
              "NASA POWER monthly climatology (warmest month's mean)",
              "Heat in the warmest month stresses plants and animals and drives cooling demand.", _warmest),
    FactorDef("coldest_month", "Coldest-month temperature", "Climate", "°C", 1, "air_temperature", "clim-01",
              "NASA POWER monthly climatology (coldest month's mean)", "Cold winters drive heating demand.",
              _coldest),
    FactorDef("sunshine", "Sunlight", "Climate", "kWh/m²/day", 1, "solar_ghi", "clim-ann",
              "NASA POWER all-sky global horizontal irradiation (annual mean)",
              "Sunlight drives plant growth and solar output.", lambda d: d.layer("solar_ghi", "clim-ann")),
    FactorDef("wind_resource", "Wind speed (10 m)", "Energy", "m/s", 1, "wind_10m", "clim-ann",
              "NASA POWER climatology at 10 m (≈ ×1.39 at a 100 m hub, 1/7 power law)",
              "Turbine output rises with the cube of wind speed.", lambda d: d.layer("wind_10m", "clim-ann")),
    FactorDef("soil_moisture", "Soil moisture", "Water", "m³/m³", 2, "era5_soil_water", "2024-ann",
              "ERA5-Land 2024 mean, top 7 cm (prepared regions)",
              "Soil water available to rain-fed crops; very wet soils are waterlogged.",
              lambda d: d.layer("era5_soil_water", "2024-ann")),
    FactorDef("water_stress", "Water stress", "Water", "score 0–5", 2, "water_stress", "category",
              "WRI Aqueduct 4.0 baseline water stress (prepared regions)",
              "Where withdrawals already approach renewable supply, new water use is hard to secure.",
              lambda d: d.layer("water_stress", "score"), prefix=True),
    FactorDef("groundwater", "Groundwater level (2024)", "Water", "percentile", 0, "grace_groundwater", "2024-ann",
              "GRACE-FO data assimilation, 2024 mean groundwater percentile (prepared regions)",
              "Groundwater storage against its 1948–2014 range: low percentiles mean depleted aquifers.",
              lambda d: d.layer("grace_groundwater", "2024-ann")),
    FactorDef("water_access", "Water access", "Water", "m³/s", None, None, None,
              "HydroRIVERS mean discharge within ~6 km, and the coastline (prepared regions)",
              "A river or the sea nearby can supply the water the building draws.", _river_m3s,
              force_ideal=lambda d: _coastal(d) == 1.0, ideal_extra=" or coastal"),
    FactorDef("river_flow", "River flow", "Water", "m³/s", None, None, None,
              "HydroRIVERS long-term mean discharge, largest reach within ~6 km (prepared regions)",
              "River flow is what a hydro plant turns into power.", _river_m3s),
    FactorDef("relief", "Height difference in cell", "Terrain", "m", 0, "elevation", "slope",
              "Copernicus DEM GLO-90, highest − lowest point in the cell (prepared regions)",
              "Height difference gives the head a hydro scheme can use.",
              lambda d: d.layer("elevation", "max") - d.layer("elevation", "min")),
    FactorDef("slope", "Slope", "Terrain", "°", 1, "elevation", "slope",
              "Copernicus DEM GLO-90 mean slope (prepared regions)", "Flat land is cheaper to build on and work.",
              lambda d: _nan_if_none(d.sd.slope, d.n)),
    FactorDef("farmland_share", "Existing farmland & grassland", "Land", "%", 0, "land_cover", "crop",
              "ESA WorldCover 2021 cropland + grassland share (prepared regions)",
              "Existing farmland and grassland is already cleared and proven.", _share("crop", "grass")),
    FactorDef("built_share", "Built-up land", "Land", "%", 1, "land_cover", "built",
              "ESA WorldCover 2021 built-up share (prepared regions)", "Built-up land isn't available for this use.",
              _share("built")),
    FactorDef("tree_cover", "Tree cover", "Land", "%", 0, "land_cover", "tree",
              "ESA WorldCover 2021 tree-cover share (prepared regions)", "Trees must be cleared and shade the site.",
              _share("tree")),
    FactorDef("vegetation", "Vegetation greenness", "Land", "NDVI", 2, "modis_ndvi", "2024-ann",
              "MODIS NDVI, 2024 annual mean (prepared regions)", "Greenness shows how well plants grow here now.",
              lambda d: d.layer("modis_ndvi", "2024-ann"), prefix=True),
    FactorDef("coastal", "Coastal site", "Water", "", 0, None, None,
              "Coastline from WorldCover water and the ERA5-Land land mask within ~6 km (prepared regions)",
              "The building needs the sea.", _coastal, labels={1.0: "coastal", 0.0: "inland"}),
    FactorDef("market_access", "People within ~50 km", "People", "people", None, "population_ghsl", "2025",
              "GHSL 2025 population within ~50 km (8 rings of cells)",
              "Customers, staff and suppliers within reach.", lambda d: _nan_if_none(d.sd.population, d.n)),
    FactorDef("neighbours", "Neighbours nearby", "People", "people/km²", None, "population_ghsl", "2025",
              "GHSL 2025 population density within ~6 km (the cell and its neighbours)",
              "Homes nearby limit noisy, smelly or hazardous uses.", lambda d: _nan_if_none(d.sd.density, d.n)),
    FactorDef("electricity_price", "Electricity price", "Energy", "USD/kWh", 3, "electricity_price", "business",
              "Average business electricity price for the country or state",
              "Electricity is a major operating cost.", lambda d: d.layer("electricity_price", "business")),
    FactorDef("water_price", "Water price", "Water", "USD/m³", 2, "water_price", "business",
              "Average water price for the country (business; household where no business price is published)",
              "Water is an operating cost.", _water_price),
    FactorDef("air_quality", "Air quality (PM2.5)", "Air", "µg/m³", 1, "cams_pm25", "2024-ann",
              "CAMS reanalysis, 2024 annual mean PM2.5 (prepared regions)",
              "Fine particles harm health (WHO 2021 annual guideline: 5 µg/m³).",
              lambda d: _nan_if_none(d.sd.pm25, d.n)),
    FactorDef("dust", "Dust & haze", "Air", "AOD", 3, "cams_aod", "2024-ann",
              "CAMS reanalysis, 2024 annual mean aerosol optical depth at 550 nm (prepared regions)",
              "Dust and haze cut sunlight and soil surfaces.", lambda d: d.layer("cams_aod", "2024-ann"), prefix=True),
    FactorDef("wildfire", "Wildfire activity", "Hazards", "detections", 0, "fires_2024", "vegetation",
              "VIIRS S-NPP 2024 vegetation-fire detections in the cell (type 0: industrial heat sources, "
              "volcanoes and offshore flares excluded; a land cell with none listed counts as 0)",
              "Fires nearby threaten the asset and raise insurance costs.", _fires),
    FactorDef("chlorophyll", "Sea productivity", "Water", "mg/m³", None, "pace_chlorophyll", "2025-07",
              "PACE chlorophyll-a, July 2025, highest within ~6 km (UK seas)",
              "Chlorophyll reflects plankton, the base of the food web; very high values signal blooms.",
              _chlorophyll),
    FactorDef("offshore_water", "Open sea", "Water", "%", 0, "land_cover", "water",
              "ESA WorldCover 2021 permanent-water share (prepared regions; sea beyond its land tiles is 100%). "
              "Elsewhere inferred: a cell with no SoilGrids soil, no GHSL or WorldPop residents, no VIIRS detection and no mapped power plant or airport is water (100%; ice, 0%, where no month gets above 2 °C, "
              "probably ice), any of those signs is land (0%)",
              "Offshore turbines stand in the sea: the cell must be mostly open water.", _offshore_water),
    FactorDef("open_water", "Open water", "Land", "%", 0, "land_cover", "water",
              "ESA WorldCover 2021 permanent-water share; open sea beyond WorldCover's land tiles counts as 100% "
              "(prepared regions). Elsewhere a cell with no SoilGrids soil, no GHSL or WorldPop residents, no VIIRS detection and no mapped power plant or airport is inferred to be water or ice "
              "(100%), anything else is no data",
              "Only a veto, with no weight in the score: a cell that is mostly sea, estuary or lake has little "
              "land to build on.", _open_water),
]
CATALOGUE: dict[str, FactorDef] = {f.key: f for f in _FACTORS}


# --- profiles ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorSpec:
    key: str
    weight: float
    ideal: Band
    good: Band
    marginal: Band
    constraint: bool = False
    why: str | None = None  # overrides the catalogue's generic reason

    def __post_init__(self):
        if self.key not in CATALOGUE:
            raise ValueError(f"unknown suitability factor {self.key!r}")


def F(key: str, weight: float, ideal: Band, good: Band, marginal: Band, constraint: bool = False,
      why: str | None = None) -> FactorSpec:
    return FactorSpec(key, weight, ideal, good, marginal, constraint, why)


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    noun: str  # "a crop farm (irrigated cotton)", for the summary
    factors: tuple[FactorSpec, ...]


# Cells that are mostly open water can't host a land building. Weight 0: a pure veto.
OPEN_WATER = F("open_water", 0.0, le(50), le(75), le(90), True)
BUILT_C = F("built_share", 1, le(5), le(15), le(40), True)
WILDFIRE = F("wildfire", 0.5, le(0), le(2), ANY)
PRICE = (le(0.08), le(0.13), ANY)
STRESS_LOW = (le(1), le(2), ANY)

# --- crop farm ---

IRRIGATED_METHODS = {"centre_pivot", "sprinkler", "drip", "furrow_flood"}


def _irrigated(stats: BuildingStats, params: dict) -> bool:
    """Irrigated when the irrigation method is one that irrigates, or (no method chosen) the specs
    declare a water input. An explicit "rainfed" always wins: water declared on a rain-fed farm is
    for other uses (washing, spraying, stock)."""
    method = str(params.get("irrigation") or "").strip().lower()
    if method == "rainfed":
        return False
    if method in IRRIGATED_METHODS:
        return True
    return (stats.water.input_m3_per_hour or 0) > 0


def _farm_base(irrigated: bool) -> list[FactorSpec]:
    out = [
        F("soil_nitrogen", 1.5, ge(1.5), ge(1.0), ge(0.5),
          why=CATALOGUE["soil_nitrogen"].why + " Ratings after Landon (1991)."),
        F("soil_ph", 1.5, rng(6.0, 7.5), rng(5.5, 8.0), rng(5.0, 8.5)),
        F("soil_organic_carbon", 1, rng(10, 120), rng(6, 200), ge(3)),
        F("soil_clay", 0.75, rng(15, 35), rng(8, 45), rng(3, 60)),
        # No lower sand limit: low-sand silt loams (Corn Belt, loess) are prime land, and heavy soils are
        # already graded by clay.
        F("soil_sand", 0.75, le(60), le(70), le(85)),
        F("soil_compaction", 0.5, le(1.40), le(1.55), le(1.70)),
        F("rainfall", 0.5, rng(200, 1600), le(2200), ANY,
          why="Irrigation supplies the crop's water, but very wet climates bring disease and waterlogging.")
        if irrigated else
        F("rainfall", 2, rng(600, 1500), rng(400, 2000), rng(250, 3000),
          why="A rain-fed crop has only the rain: too little caps yields, too much waterlogs the fields."),
        F("temperature", 1, rng(6, 26), rng(3, 29), rng(0, 32), why="Mean temperature sets which crops grow well."),
        F("growing_season", 1.5, ge(7), ge(5), ge(3)),
        F("warmest_month", 1, le(28), le(32), le(35), why="Heat in the warmest month cuts yields."),
        F("sunshine", 0.5, ge(3.0), ge(2.4), ge(1.8), why="Sunlight drives photosynthesis."),
        F("slope", 1.5, le(3), le(8), le(15), True, why="Steep fields erode and can't be worked by machinery."),
        F("farmland_share", 1, ge(50), ge(25), ANY),
        BUILT_C,
        # Global (GHSL), so it also catches city centres outside the regions with no built-up share. A pure
        # veto (one envelope): as a graded constraint it would hold dense farmland (Nile delta, Bangladesh,
        # Bihar: 500–4,000 people/km²) at good or marginal.
        F("neighbours", 0.0, le(4000), le(4000), le(4000), True, why="Dense settlement leaves no room for fields."),
        F("vegetation", 0.25, ge(0.45), ge(0.30), ANY) if irrigated else F("vegetation", 0.75, ge(0.45), ge(0.30), ge(0.15)),
    ]
    if irrigated:
        out += [
            F("water_stress", 1.5, le(1), le(2), le(4),
              why="Irrigation draws on the basin: where withdrawals already approach supply, new water rights "
                  "are hard to get."),
            F("groundwater", 0.5, ge(40), ge(20), ANY, why="Depleted aquifers make wells for irrigation less reliable."),
            # River only: a farm can't irrigate with seawater (farm is not a seawater type in site_capacity).
            F("river_flow", 1, ge(10), ge(1), ANY, why="A river within ~6 km can supply irrigation water; the sea can't."),
        ]
    else:
        out += [
            # ERA5-Land soil water above ~0.5 m³/m³ only occurs on its fine and organic soil classes
            # (porosity 0.52–0.77), so it marks soil type rather than waterlogging: wet is never unsuitable.
            F("soil_moisture", 1, rng(0.20, 0.40), rng(0.15, 0.50), ge(0.10)),
            F("water_stress", 0.5, le(2), le(3), ANY,
              why="Even rain-fed farms need some water (spraying, washing, stock), harder to get in stressed basins."),
        ]
    return out + [OPEN_WATER]


def _b(ideal: Band, good: Band, marginal: Band) -> dict:
    return {"ideal": ideal, "good": good, "marginal": marginal}


_TREE_CROPS = {"slope": _b(le(8), le(15), le(25)), "soil_nitrogen": {"weight": 0.5},
               "rainfall@rainfed": _b(rng(500, 1000), rng(350, 1400), rng(250, 2000))}
# Warm-season crops need a hot summer as well as tolerating one: the warmest month gets a floor and is
# a constraint (cotton's northern limit is a ~22–24 °C warmest month, grain maize and soybean ~18–20 °C).
_HEAT_NEED = "A warm-season crop needs a hot summer to mature, and suffers above the top of the band."
_WARM_CROPS = {"warmest_month": {**_b(rng(24, 32), rng(21, 35), rng(18, 38)), "constraint": True, "why": _HEAT_NEED},
               "temperature": _b(rng(15, 28), rng(12, 30), rng(8, 32)), "growing_season": _b(ge(8), ge(6), ge(5))}
# Maize and soybean grow in continental climates (Iowa: annual mean ~9–10 °C, July ~24 °C), so they get
# cooler annual and season bands than cotton and sugarcane. Maize ripens as UK silage with a ~17–18 °C
# warmest month and is grown irrigated in the hot Arizona valleys (~34 °C); soybean needs a warmer summer
# (UK soybean is trial-scale).
_CONTINENTAL = {"temperature": _b(rng(8, 24), rng(5, 27), rng(2, 30)), "growing_season": _b(ge(6), ge(5), ge(4))}
_MAIZE = {**_CONTINENTAL,
          "warmest_month": {**_b(rng(20, 32), rng(17, 35), rng(15, 38)), "constraint": True, "why": _HEAT_NEED}}
_SOYBEAN = {**_CONTINENTAL,
            "warmest_month": {**_b(rng(22, 30), rng(19, 33), rng(17, 36)), "constraint": True, "why": _HEAT_NEED}}
_COOL_CEREALS = {"temperature": _b(rng(6, 20), rng(3, 24), rng(0, 28)), "warmest_month": _b(le(26), le(30), le(34))}
# Replacements by parameters.cropType ("key@rainfed" applies only to rain-fed farms).
CROP_OVERRIDES: dict[str, dict[str, dict]] = {
    "rice": {"soil_clay": _b(rng(30, 60), rng(20, 70), rng(10, 80)), "soil_ph": _b(rng(5.5, 7.0), rng(5.0, 7.5), rng(4.5, 8.0)),
             "rainfall@rainfed": _b(rng(1200, 2500), rng(900, 3000), ge(600)),
             "temperature": _b(rng(20, 30), rng(16, 32), rng(12, 34)), "growing_season": _b(ge(9), ge(7), ge(5)),
             "warmest_month": {**_b(rng(24, 32), rng(22, 34), rng(20, 36)), "constraint": True, "why": _HEAT_NEED}},
    "potatoes": {"soil_ph": _b(rng(5.0, 6.5), rng(4.8, 7.0), rng(4.5, 7.8)), "temperature": _b(rng(6, 18), rng(4, 22), rng(0, 26)),
                 "soil_sand": _b(rng(30, 70), le(80), le(90)), "warmest_month": _b(le(22), le(26), le(30))},
    **{c: _TREE_CROPS for c in ("vineyard", "fruit_orchard", "nuts")},
    **{c: _WARM_CROPS for c in ("cotton", "sugarcane")},
    "maize": _MAIZE,
    "soybean": _SOYBEAN,
    **{c: _COOL_CEREALS for c in ("wheat", "barley")},
    "alfalfa_hay": {"soil_ph": _b(rng(6.5, 7.8), rng(6.0, 8.2), rng(5.5, 8.5)), "warmest_month": _b(le(32), le(35), le(38))},
}


def _farm(stats: BuildingStats, params: dict) -> Profile:
    irrigated = _irrigated(stats, params)
    mode = "irrigated" if irrigated else "rainfed"
    specs = _farm_base(irrigated)
    crop = str(params.get("cropType") or "").strip().lower()
    over = CROP_OVERRIDES.get(crop)
    if over:
        for k, upd in over.items():
            key, _, only = k.partition("@")
            if only and only != mode:
                continue
            specs = [replace(s, **upd) if s.key == key else s for s in specs]
    mode_label = "irrigated" if irrigated else "rain-fed"
    crop_label = crop.replace("_", " ")
    return Profile(
        id=f"farm:{mode}" + (f":{crop}" if over else ""),
        label=f"Crop farm · {mode_label}" + (f" {crop_label}" if over else ""),
        noun=_article(f"{mode_label} crop farm") + (f" ({crop_label})" if over else ""),
        factors=tuple(specs),
    )


# --- other building types ---


def _p(id_: str, label: str, noun: str, *specs: FactorSpec) -> Profile:
    return Profile(id_, label, noun, tuple(specs))


_PROFILES: dict[str, Profile] = {
    "livestock_farm": _p(
        "livestock_farm", "Livestock farm", "a livestock farm",
        F("soil_ph", 0.5, rng(5.5, 7.5), rng(5.0, 8.0), rng(4.5, 8.5), why="pH governs pasture and forage growth."),
        F("rainfall", 1, rng(500, 1800), rng(300, 2500), ge(150), why="Rainfall grows the pasture and forage."),
        F("temperature", 1, rng(5, 20), rng(0, 25), rng(-5, 30), why="Animals and pasture do best in a temperate climate."),
        F("warmest_month", 1.5, le(24), le(28), le(33), why="Heat stress lowers animal welfare, growth and milk yield."),
        F("slope", 1, le(8), le(15), le(25), True, why="Steep ground is hard to graze, fence and serve with vehicles."),
        F("farmland_share", 1.5, ge(50), ge(25), ANY),
        F("vegetation", 1.5, ge(0.5), ge(0.35), ge(0.15), why="Green pasture is the herd's feed."),
        F("neighbours", 1.5, le(50), le(150), le(500), why="Odour and nuisance rules keep livestock units away from homes."),
        F("water_stress", 0.75, le(2), le(3), ANY, why="Animals need a reliable water supply."),
        BUILT_C, OPEN_WATER),
    "greenhouse": _p(
        "greenhouse", "Greenhouse", "a greenhouse",
        F("sunshine", 2, ge(3.5), ge(2.5), ge(1.8), why="Sunlight is the greenhouse's main energy input."),
        F("coldest_month", 1.5, ge(8), ge(2), ge(-8), why="Cold winters need costly heating."),
        F("warmest_month", 1, le(24), le(28), le(36), why="Hot summers need cooling and shading."),
        F("slope", 1.5, le(2), le(5), le(10), True, why="Glasshouses need level ground."),
        F("electricity_price", 1, *PRICE, why="Lighting, heating and climate control run on electricity."),
        F("water_stress", 0.75, *STRESS_LOW, why="Irrigation water must be secured from the basin."),
        F("market_access", 0.5, ge(1_000_000), ge(250_000), ANY, why="Fresh produce sells best close to customers."),
        OPEN_WATER),
    "vertical_farm": _p(
        "vertical_farm", "Vertical farm", "a vertical farm",
        F("market_access", 2, ge(1_000_000), ge(250_000), ge(50_000), why="Vertical farms sell fresh produce into cities."),
        F("electricity_price", 2, *PRICE, why="LED lighting makes electricity the largest operating cost."),
        F("warmest_month", 0.5, le(22), le(27), ANY, why="Hot summers raise the cooling load."),
        F("water_price", 0.5, le(1), le(2.5), ANY),
        OPEN_WATER),
    "solar": _p(
        "solar", "Solar farm", "a solar farm",
        F("sunshine", 3, ge(5.0), ge(4.0), ge(2.0), True, why="Irradiation sets how much energy the panels generate."),
        F("slope", 1.5, le(5), le(10), le(20), True, why="Steep or north-facing ground shades rows and is costly to build on."),
        F("tree_cover", 1, le(10), le(30), le(60), why="Trees shade panels and must be cleared."),
        BUILT_C,
        F("temperature", 0.5, le(20), le(26), ANY, why="Hot panels lose output (about 0.4% per °C above 25 °C)."),
        F("dust", 0.5, le(0.15), le(0.30), ANY, why="Dust and haze cut irradiance and soil the panels."),
        WILDFIRE, OPEN_WATER),
    "hydro_plant": _p(
        "hydro_plant", "Hydroelectric plant", "a hydroelectric plant",
        F("river_flow", 3, ge(100), ge(20), ge(2), True),
        F("relief", 2, ge(300), ge(100), ge(30)),
        F("rainfall", 1, ge(1000), ge(600), ge(250), why="Rainfall feeds the catchment's runoff."),
        OPEN_WATER),
    "data_centre": _p(
        "data_centre", "Data centre", "a data centre",
        F("temperature", 1.5, le(12), le(18), ANY, why="A cool climate allows free cooling most of the year."),
        F("warmest_month", 1, le(22), le(27), ANY, why="Hot summers need mechanical cooling."),
        F("electricity_price", 2, *PRICE, why="Power is the largest operating cost of a data centre."),
        F("water_stress", 1, *STRESS_LOW, why="Evaporative cooling draws on the basin's water."),
        F("market_access", 0.5, ge(500_000), ge(100_000), ANY, why="Staff and users nearby."),
        F("air_quality", 0.5, le(10), le(20), ANY, why="Particulates foul air-side cooling filters."),
        WILDFIRE, OPEN_WATER),
    "airport": _p(
        "airport", "Airport", "an airport",
        F("slope", 1.5, le(2), le(4), le(8), why="Runways need long, level ground."),
        F("neighbours", 1.5, le(200), le(1000), ANY, why="Aircraft noise affects homes nearby."),
        F("market_access", 1.5, ge(1_000_000), ge(250_000), ANY, why="Passengers and cargo come from the region."),
        OPEN_WATER),
    "seaport": _p(
        "seaport", "Seaport", "a seaport",
        F("coastal", 3, ge(1), ge(1), ge(1), True, why="A seaport needs the coast."),
        F("market_access", 1, ge(1_000_000), ge(250_000), ANY, why="Cargo moves to and from the hinterland."),
        F("slope", 0.5, le(3), le(8), ANY, why="Container yards need flat land."),
        OPEN_WATER),
    "warehouse": _p(
        "warehouse", "Warehouse & logistics", "a warehouse",
        F("slope", 1, le(3), le(6), le(12), why="Large sheds and yards need flat land."),
        F("market_access", 2, ge(1_000_000), ge(250_000), ANY, why="Distribution serves the population nearby."),
        OPEN_WATER),
    "landfill": _p(
        "landfill", "Landfill", "a landfill",
        F("neighbours", 2, le(50), le(200), le(1000), why="Odour, litter and traffic need a buffer from homes."),
        F("soil_clay", 1.5, ge(30), ge(20), ANY, why="Clay-rich ground is a natural liner that slows leachate."),
        F("slope", 1, le(5), le(10), le(15), why="Steep sites make cells and liners unstable."),
        F("water_stress", 0.5, ge(2), ge(1), ANY,
          why="Drier basins (higher stress score) produce less leachate and recharge less groundwater."),
        F("market_access", 0.5, ge(250_000), ge(50_000), ANY, why="Waste comes from the population nearby."),
        OPEN_WATER),
    "recycling_facility": _p(
        "recycling_facility", "Recycling facility", "a recycling facility",
        F("market_access", 2, ge(500_000), ge(100_000), ANY, why="Material comes from the population nearby."),
        F("neighbours", 1, le(500), le(2000), ANY, why="Noise and traffic need some distance from homes."),
        F("slope", 0.5, le(3), le(8), ANY, why="Sorting halls and yards need flat land."),
        OPEN_WATER),
}

_THERMAL = {"power_station": "Power station", "waste_to_energy": "Waste-to-energy plant"}
_INDUSTRY = {"factory": "Factory", "steel_mill": "Steel mill", "aluminium_smelter": "Aluminium smelter",
             "cement_plant": "Cement plant", "chemical_plant": "Chemical plant", "oil_refinery": "Oil refinery",
             "semiconductor_fab": "Semiconductor fab", "food_processing": "Food processing plant",
             "hydrogen_plant": "Hydrogen plant"}
_POWER_HUNGRY = {"aluminium_smelter", "semiconductor_fab", "hydrogen_plant"}
_HEAVY = {"steel_mill", "cement_plant", "chemical_plant", "oil_refinery", "aluminium_smelter"}
_COMMUNITY = {"housing": "Housing", "hospital": "Hospital", "school": "School", "university": "University campus",
              "office": "Office building", "retail": "Retail centre", "hotel": "Hotel",
              "research_lab": "Research laboratory", "stadium": "Stadium & arena"}
_BIG_CATCHMENT = {"retail", "hospital", "stadium"}
_NOUNS = {"housing": "housing", "stadium": "a stadium", "university": "a university campus"}


def _article(label: str) -> str:
    low = label.lower()
    return ("an " if low[0] in "aeiou" else "a ") + low


def _thermal(btype: str) -> Profile:
    label = _THERMAL[btype]
    return _p(btype, label, _article(label),
              F("water_access", 2, ge(10), ge(1), ANY, why="Thermal plants need large volumes of cooling water."),
              F("neighbours", 1, le(200), le(1000), ANY, why="Noise, traffic and emissions need a buffer from homes."),
              F("slope", 0.5, le(3), le(8), le(15)),
              F("water_stress", 1, *STRESS_LOW, why="Cooling water must be secured from the basin."),
              OPEN_WATER)


def _water_plant(btype: str, stats: BuildingStats) -> Profile:
    label = "Water plant" if btype == "water_plant" else "Wastewater treatment"
    seawater = stats.water.source == "seawater"
    source = (F("coastal", 2, ge(1), ge(1), ge(1), True, why="Its intake is seawater, so it must be on the coast.")
              if seawater else
              F("water_access", 2, ge(10), ge(1), ANY, why="A river or the sea to draw from or discharge to."))
    return _p(btype + (":seawater" if seawater else ""), label + (" · seawater intake" if seawater else ""),
              ("a desalination plant" if seawater else "a water plant") if btype == "water_plant" else "wastewater treatment",
              source,
              F("market_access", 1, ge(1_000_000), ge(100_000), ANY, why="It serves the population nearby."),
              F("electricity_price", 0.5, *PRICE, why="Pumping and treatment run on electricity."),
              F("slope", 0.5, le(3), le(8), le(15)),
              OPEN_WATER)


def _wind(params: dict) -> Profile:
    """Siting parameter: onshore (or not given) is a land building, so open water is a veto; offshore
    drops the land factors and needs a cell that is mostly open water instead."""
    wind = F("wind_resource", 3, ge(5.0), ge(4.0), ge(3.0), True)
    homes = F("neighbours", 1.5, le(50), le(200), le(1000), why="Homes nearby limit turbines (noise, shadow flicker).")
    if str(params.get("siting") or "").strip().lower() == "offshore":
        return _p("wind_farm:offshore", "Wind farm · offshore", "an offshore wind farm", wind, homes,
                  F("offshore_water", 0.0, ge(90), ge(75), ge(50), True,
                    why="Offshore turbines stand in the sea: the cell must be mostly open water. Only a veto, with "
                        "no weight in the score."))
    return _p("wind_farm", "Wind farm · onshore", "an onshore wind farm", wind,
              F("slope", 1, le(10), le(20), le(30), why="Steep ground makes turbine access roads and foundations costly."),
              F("tree_cover", 0.75, le(20), le(50), ANY, why="Forest slows the wind near the ground and must be cleared."),
              homes, BUILT_C, OPEN_WATER)


_AQUA_SYSTEMS = {"marine_net_pen": "sea pens", "shellfish_longline": "shellfish longlines",
                 "freshwater_pond": "freshwater ponds", "flow_through": "flow-through raceways",
                 "recirculating_ras": "recirculating tanks (RAS)"}


def _aquaculture(stats: BuildingStats, params: dict) -> Profile:
    """By the `system` parameter: sea pens and longlines need the coast; ponds and raceways need a
    river and are on land; recirculating systems are indoor plants that mostly need cheap power.
    Without a system, any river or coast will do."""
    system = str(params.get("system") or "").strip().lower()
    homes = F("neighbours", 0.5, le(200), le(1000), ANY, why="Odour and discharges need room from homes.")
    climate = F("temperature", 1, rng(10, 28), rng(5, 31), rng(0, 34),
                why="Water temperature follows the climate and sets growth and survival.")
    stress = F("water_stress", 1, *STRESS_LOW, why="Freshwater farms draw on the basin's water.")
    if system in ("marine_net_pen", "shellfish_longline"):
        shellfish = system == "shellfish_longline"
        specs = [F("coastal", 2, ge(1), ge(1), ge(1), True, why="Pens and longlines are moored in the sea off the coast."),
                 climate,
                 F("chlorophyll", 1.5 if shellfish else 0.5, rng(1, 10), rng(0.5, 20), ANY,
                   why="Shellfish filter plankton from the water: chlorophyll is their food." if shellfish else None),
                 homes]
    elif system in ("freshwater_pond", "flow_through"):
        river = (F("river_flow", 2, ge(10), ge(1), ge(0.1), True, why="Raceways run a river's water through the tanks.")
                 if system == "flow_through" else
                 F("river_flow", 1.5, ge(1), ge(0.1), ANY, why="Ponds are filled and flushed from a river or stream nearby."))
        specs = [river, climate, stress, homes, OPEN_WATER]
    elif system == "recirculating_ras":
        specs = [F("electricity_price", 1.5, *PRICE, why="Pumps, filters, aeration and heating run around the clock."),
                 stress,
                 F("market_access", 0.5, ge(1_000_000), ge(250_000), ANY, why="Indoor farms sell fresh fish into cities."),
                 homes, OPEN_WATER]
    else:
        specs = [F("water_access", 2, ge(10), ge(1), ge(0.1), True, why="Fish farms need a river or the sea."),
                 climate, F("chlorophyll", 0.5, rng(1, 10), rng(0.5, 20), ANY)]
        if stats.water.source == "fresh":
            specs.append(stress)
        specs.append(homes)
    name = _AQUA_SYSTEMS.get(system)
    return Profile("aquaculture" + (f":{system}" if name else ""), "Aquaculture" + (f" · {name}" if name else ""),
                   f"aquaculture ({name})" if name else "aquaculture", tuple(specs))


def _industry(btype: str, stats: BuildingStats) -> Profile:
    label = _INDUSTRY[btype]
    water_input = (stats.water.input_m3_per_hour or 0) > 0
    specs = [
        F("slope", 1, le(2), le(5), le(10), why="Large plants need level ground."),
        F("electricity_price", 2 if btype in _POWER_HUNGRY else 1, *PRICE, why="Electricity is a major operating cost."),
        F("water_stress", 1 if water_input else 0.5, *STRESS_LOW, why="Process and cooling water must be secured."),
        F("market_access", 2, ge(2_000_000), ge(500_000), ge(100_000), why="A fab needs a deep pool of skilled staff.")
        if btype == "semiconductor_fab" else
        F("market_access", 1, ge(500_000), ge(100_000), ANY, why="Staff, suppliers and customers nearby."),
    ]
    if btype in _HEAVY:
        specs.append(F("neighbours", 1.5, le(100), le(500), le(2000), why="Heavy industry needs a buffer from homes."))
    specs += [WILDFIRE, OPEN_WATER]
    return Profile(btype, label, _article(label), tuple(specs))


def _community(btype: str) -> Profile:
    label = _COMMUNITY[btype]
    big = btype in _BIG_CATCHMENT
    return _p(btype, label, _NOUNS.get(btype, _article(label)),
              F("slope", 1, le(5), le(10), le(20), why="Flat land is cheaper to build on and easier to get around."),
              F("air_quality", 1.5, le(5), le(10), le(35), why="Clean air for the people using it (WHO 2021 guideline: 5 µg/m³)."),
              F("temperature", 0.5, rng(10, 22), rng(5, 26), rng(-5, 30), why="A mild climate keeps heating and cooling low."),
              F("market_access", 1.5, ge(1_000_000), ge(250_000), ge(20_000), why="It needs a large catchment of people.")
              if big else
              F("market_access", 1.5, ge(250_000), ge(50_000), ANY, why="People to use it, and staff, within reach."),
              F("wildfire", 0.75, le(0), le(2), ANY, why="Fires nearby threaten people and buildings."),
              OPEN_WATER)


def profile_for(btype: str, stats: BuildingStats, parameters: dict | None) -> Profile | None:
    """The suitability profile for a building, or None when the type has none (custom, extraction,
    battery storage, geothermal)."""
    params = parameters or {}
    if btype == "farm":
        return _farm(stats, params)
    if btype in _PROFILES:
        return _PROFILES[btype]
    if btype in _THERMAL:
        return _thermal(btype)
    if btype in ("water_plant", "wastewater_plant"):
        return _water_plant(btype, stats)
    if btype == "aquaculture":
        return _aquaculture(stats, params)
    if btype == "wind_farm":
        return _wind(params)
    if btype in _INDUSTRY:
        return _industry(btype, stats)
    if btype in _COMMUNITY:
        return _community(btype)
    return None


# --- grading (vectorised) ---------------------------------------------------------------------


def _round_values(v: np.ndarray, decimals: int | None) -> np.ndarray:
    """Round to the display precision (fixed decimals, or 3 significant figures)."""
    if decimals is not None:
        return np.round(v, decimals)
    out = v.copy()
    ok = np.isfinite(out) & (out != 0)
    mag = np.floor(np.log10(np.abs(out[ok])))
    scale = 10.0 ** (2 - mag)
    out[ok] = np.round(out[ok] * scale) / scale
    return out


def _inside(v: np.ndarray, band: Band) -> np.ndarray:
    lo, hi = band
    m = np.ones(v.shape, dtype=bool)
    if lo is not None:
        m &= v >= lo
    if hi is not None:
        m &= v <= hi
    return m


def classify(v: np.ndarray, spec: FactorSpec, force_ideal: np.ndarray | None = None) -> np.ndarray:
    """Per-cell code (IDEAL … UNSUITABLE, NO_DATA for NaN) of values already rounded for display."""
    v = np.asarray(v, dtype=np.float64)
    code = np.full(v.shape, UNSUITABLE, dtype=np.int8)
    code[_inside(v, spec.marginal)] = MARGINAL
    code[_inside(v, spec.good)] = GOOD
    code[_inside(v, spec.ideal)] = IDEAL
    code[np.isnan(v)] = NO_DATA
    if force_ideal is not None:
        code[force_ideal] = IDEAL
    return code


@dataclass
class Overall:
    score: np.ndarray  # (n,) 0–3 rounded to 2 dp, NaN when no factor has data
    coverage: np.ndarray  # (n,) 0–1
    tier: np.ndarray  # (n,) index into TIERS, NOT_GRADED when coverage is too low
    vetoed: np.ndarray  # (n,) a constraint factor is unsuitable
    capped: np.ndarray  # (n,) the one-class cap (weakest factor) set the grade
    held: np.ndarray  # (n,) a constraint factor held the grade at its own class
    unconfirmed: np.ndarray  # (n,) a constraint factor without data kept the grade from ideal


def overall(codes: np.ndarray, weights: np.ndarray, constraint: np.ndarray) -> Overall:
    """codes: (factors, cells). Section 1 of the method, as vectors.

    After the score cut-offs and the veto, three bounds can only lower a graded cell's grade (raise
    its tier index); each flag says that bound set the final grade:
    - cap: at most one class better than the weakest factor with data (worst code − 2);
    - hold: no better than any constraint factor with data (its code − 1);
    - unconfirmed: at most good while any constraint factor has no data (tier ≥ 1)."""
    weights = np.asarray(weights, dtype=np.float64)
    n = codes.shape[1]
    has = codes > NO_DATA
    wsum = weights @ has
    num = weights @ (POINTS[codes] * has)
    with np.errstate(invalid="ignore", divide="ignore"):
        score = np.where(wsum > 0, num / np.where(wsum > 0, wsum, 1.0), np.nan)
    score = np.round(score, 2)
    total = weights.sum()
    coverage = wsum / total if total > 0 else np.ones(n)
    tier = np.full(n, len(TIERS) - 1, dtype=np.int8)
    for cut, t in reversed(CUTS):
        tier[score >= cut] = t
    tier[(coverage < MIN_COVERAGE - 1e-9) | np.isnan(score)] = NOT_GRADED
    cons = np.asarray(constraint, dtype=bool)
    vetoed = (codes[cons] == UNSUITABLE).any(axis=0) if cons.any() else np.zeros(n, dtype=bool)
    tier[vetoed] = TIERS.index("unsuitable")
    none = np.full(n, -1, dtype=np.int8)
    cap = np.where(has, codes, NO_DATA).max(axis=0, initial=NO_DATA).astype(np.int8) - 2
    hold = codes[cons].max(axis=0).astype(np.int8) - 1 if cons.any() else none  # NO_DATA → −1: never holds
    unconf = np.where((codes[cons] == NO_DATA).any(axis=0), 1, -1).astype(np.int8) if cons.any() else none
    bound = np.maximum(np.maximum(cap, hold), unconf)
    raised = (tier != NOT_GRADED) & ~vetoed & (bound > tier)  # ungraded stays ungraded
    tier[raised] = bound[raised]
    return Overall(score, coverage, tier, vetoed, raised & (cap == tier), raised & (hold == tier),
                   raised & (unconf == tier))


@dataclass
class Graded:
    """Grades of every cell of one SiteData for one profile."""

    profile: Profile
    data: _Data
    values: np.ndarray  # (factors, cells) display-rounded values, NaN = no data
    codes: np.ndarray  # (factors, cells) int8
    result: Overall

    @property
    def rank(self) -> np.ndarray:
        """Candidate ordering: ideal 0 … unsuitable 3, not graded 4."""
        t = self.result.tier
        return np.where(t == NOT_GRADED, UNGRADED_RANK, t).astype(np.int8)

    def tier_names(self) -> list[SuitabilityTier | None]:
        names = np.array(list(TIERS) + [None], dtype=object)
        return names[self.result.tier].tolist()  # NOT_GRADED (-1) picks the trailing None

    def grade_strings(self) -> list[str]:
        f, n = self.codes.shape
        if n == 0:
            return []
        if f == 0:
            return [""] * n
        chars = np.ascontiguousarray((self.codes.T + ord("0")).astype(np.uint8))
        return chars.view(f"S{f}").ravel().astype(str).tolist()

    def tier_counts(self) -> dict[str, int]:
        t = self.result.tier
        out = {name: int(np.count_nonzero(t == k)) for k, name in enumerate(TIERS)}
        out["unknown"] = int(np.count_nonzero(t == NOT_GRADED))
        return out

    def profile_model(self) -> SuitabilityProfile:
        return profile_model(self.profile)

    def at(self, i: int, model: SuitabilityProfile | None = None) -> Suitability:
        return suitability_at(self, i, model)


def grade(profile: Profile, sd: site_capacity.SiteData) -> Graded:
    d = _Data(sd)
    specs = profile.factors
    values = np.full((len(specs), d.n), np.nan)
    codes = np.zeros((len(specs), d.n), dtype=np.int8)
    for k, spec in enumerate(specs):
        fd = CATALOGUE[spec.key]
        v = _round_values(np.asarray(fd.value(d), dtype=np.float64), fd.decimals)
        values[k] = v
        codes[k] = classify(v, spec, fd.force_ideal(d) if fd.force_ideal else None)
    weights = np.array([s.weight for s in specs], dtype=np.float64)
    constraint = np.array([s.constraint for s in specs], dtype=bool)
    return Graded(profile, d, values, codes, overall(codes, weights, constraint))


def grade_for(btype: str, stats: BuildingStats, parameters: dict | None,
              sd: site_capacity.SiteData) -> Graded | None:
    profile = profile_for(btype, stats, parameters)
    return None if profile is None else grade(profile, sd)


# --- text -------------------------------------------------------------------------------------


def _num(v: float, decimals: int | None) -> str:
    """Number for display: thousands separators, millions spelt out, Unicode minus."""
    if decimals is None:
        if v == 0 or not math.isfinite(v):
            decimals = 0
        else:
            decimals = max(0, 2 - math.floor(math.log10(abs(v))))
    if abs(v) >= 1e6:
        m = v / 1e6
        text = f"{m:,.2f}".rstrip("0").rstrip(".") + " million"
    else:
        text = f"{v:,.{decimals}f}"
    if text.startswith("-"):
        text = "−" + text[1:] if text.strip("-0.,") else text[1:]
    return text


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _with_unit(fd: FactorDef, text: str, value: float | None = None) -> str:
    unit = fd.unit
    if not unit:
        return text
    if fd.prefix:
        return f"{unit.split(' ')[0]} {text}"
    if unit in ("°", "%"):
        return text + unit
    if unit == "months" and value == 1:
        return f"{text} month"
    return f"{text} {unit}"


def display_value(fd: FactorDef, v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "no data"
    if fd.labels:
        return fd.labels.get(float(v), _num(v, fd.decimals))
    if fd.unit == "percentile":
        return f"{_ordinal(int(round(v)))} percentile"
    return _with_unit(fd, _num(float(v), fd.decimals), v)


def _min_decimals(x: float) -> int:
    return next((d for d in range(4) if abs(round(x, d) - x) < 1e-9), 3)


def _edge_decimals(fd: FactorDef, spec: FactorSpec, x: float) -> int:
    """Fixed-precision factors write every band edge with the same decimals (6.0–7.5, 1.40); factors
    shown to significant figures span magnitudes, so each edge is written as is (≥ 10, ≥ 0.1)."""
    if fd.decimals is None:
        return _min_decimals(x)
    return max(_min_decimals(e) for b in (spec.ideal, spec.good, spec.marginal) for e in b if e is not None)


def envelope_text(fd: FactorDef, spec: FactorSpec, band: Band) -> str:
    lo, hi = band
    if fd.labels:  # categorical: name the values inside the band
        inside = [name for val, name in fd.labels.items()
                  if (lo is None or val >= lo) and (hi is None or val <= hi)]
        return " or ".join(inside) if inside else "none"
    def n(x: float) -> str:
        if fd.unit == "percentile":
            return _ordinal(int(x))
        return _num(float(x), _edge_decimals(fd, spec, x))

    if lo is None and hi is None:
        return "any value"
    if lo is None:
        cmp = n(hi) if hi == 0 else f"≤ {n(hi)}"
    elif hi is None:
        cmp = f"≥ {n(lo)}"
    else:
        cmp = f"{n(lo)} to {n(hi)}" if lo < 0 or hi < 0 else f"{n(lo)}–{n(hi)}"
    if fd.unit == "percentile":
        return f"{cmp} percentile"
    return _with_unit(fd, cmp)


def bands_text(spec: FactorSpec) -> str:
    fd = CATALOGUE[spec.key]
    parts = [f"Ideal {envelope_text(fd, spec, spec.ideal)}{fd.ideal_extra}"]
    prev = spec.ideal
    for name, band in (("Good", spec.good), ("Marginal", spec.marginal)):
        if band == ANY:
            parts.append(f"otherwise {name.lower()}")
            break
        if band != prev:  # an envelope equal to the one before adds no class (coastal: ideal or nothing)
            parts.append(f"{name} {envelope_text(fd, spec, band)}")
        prev = band
    else:
        parts.append("otherwise unsuitable")
    return " · ".join(parts)


def factor_model(spec: FactorSpec) -> SuitabilityFactor:
    fd = CATALOGUE[spec.key]
    return SuitabilityFactor(
        key=fd.key, label=fd.label, group=fd.group, unit=fd.unit, weight=spec.weight, constraint=spec.constraint,
        bands=bands_text(spec), layer_id=fd.layer_id, slice_id=fd.slice_id, source=fd.source, why=spec.why or fd.why,
    )


def profile_model(profile: Profile) -> SuitabilityProfile:
    return SuitabilityProfile(id=profile.id, label=profile.label, method=METHOD,
                              factors=[factor_model(s) for s in profile.factors])


def _display_at(g: Graded, k: int, i: int) -> str:
    spec = g.profile.factors[k]
    fd = CATALOGUE[spec.key]
    v = float(g.values[k, i])
    if spec.key == "water_access" and g.codes[k, i] != NO_DATA and _coastal(g.data)[i] == 1.0:
        return "coastal" + (f"; river {display_value(fd, v)}" if not math.isnan(v) and v > 0 else "")
    text = display_value(fd, None if math.isnan(v) else v)
    if spec.key == "water_stress" and not math.isnan(v) and g.data.layer("water_stress", "category")[i] == -1:
        text += " (arid and low water use)"
    if spec.key == "water_price" and not math.isnan(v) and g.data._cache.get("water_price_household") is not None \
            and g.data._cache["water_price_household"][i]:
        text += " (household price)"
    if spec.key in ("open_water", "offshore_water") and not math.isnan(v) and _inferred_water(g, i, spec.key):
        text += ", inferred ice" if _is_ice(g, i) else ", inferred"
    return text


def _is_ice(g: Graded, i: int) -> bool:
    flags = g.data._cache.get("ice") if g.data is not None else None
    return flags is not None and bool(flags[i])


def _inferred_water(g: Graded, i: int, key: str = "open_water") -> bool:
    flags = g.data._cache.get(f"{key}_inferred") if g.data is not None else None
    return flags is not None and bool(flags[i])


def _explain(g: Graded, k: int, i: int, shown: str) -> str:
    spec = g.profile.factors[k]
    fd = CATALOGUE[spec.key]
    code = int(g.codes[k, i])
    env = lambda b: envelope_text(fd, spec, b)  # noqa: E731
    if code == NO_DATA:
        return ("No data for this cell (outside the dataset's coverage, or no value here such as over water or "
                "built-up land), so it is left out of the score."
                + (" As a constraint without data, it keeps the grade from ideal." if spec.constraint else ""))
    if spec.key == "water_access" and _coastal(g.data)[i] == 1.0:
        return f"Coastal site: the sea is within ~6 km, which counts as ideal ({env(spec.ideal)}{fd.ideal_extra})."
    if fd.labels:  # categorical (coastal / inland)
        if code == UNSUITABLE:
            return (f"{shown.capitalize()} site: it must be {env(spec.marginal)}, so unsuitable."
                    + (" This is a constraint, so it alone makes the cell unsuitable." if spec.constraint else ""))
        return f"{shown.capitalize()} site, which is {TIERS[code - 1]}."
    if code == IDEAL:
        text = f"{shown} is in the ideal band ({env(spec.ideal)}{fd.ideal_extra})."
    elif code == GOOD:
        text = f"{shown} is in the good band ({env(spec.good)}); ideal is {env(spec.ideal)}{fd.ideal_extra}."
    elif code == MARGINAL and spec.marginal == ANY:
        text = f"{shown} is outside the good band ({env(spec.good)}), so marginal; this factor is never unsuitable."
    elif code == MARGINAL:
        text = f"{shown} is in the marginal band ({env(spec.marginal)}); good is {env(spec.good)}."
    else:
        text = f"{shown} is outside the marginal band ({env(spec.marginal)}), so unsuitable."
        if spec.constraint:
            text += " This is a constraint, so it alone makes the cell unsuitable."
    if spec.key == "water_stress" and g.data.layer("water_stress", "category")[i] == -1:
        text += " Aqueduct scores arid, low-use basins 5: there is little renewable water to draw on."
    if spec.key == "open_water" and _inferred_water(g, i):
        text += (" Inferred from missing land data: no land-cover map covers this cell, and it has no SoilGrids soil, no GHSL or WorldPop residents, no VIIRS detection and no mapped power plant or airport, as "
                 + ("on ice (no month gets above 2 °C), which can't be built on either." if _is_ice(g, i)
                    else "over sea, lakes or ice."))
    if spec.key == "offshore_water" and _inferred_water(g, i, spec.key) and _is_ice(g, i):
        text += (" Inferred: no land sign here, but no month gets above 2 °C, so this is ice (an ice sheet, an ice "
                 "cap or ice-covered sea), not open sea (0%).")
    elif spec.key == "offshore_water" and _inferred_water(g, i, spec.key):
        text += (" Inferred: no land-cover map covers this cell; a cell with no SoilGrids soil, no GHSL or WorldPop residents, no VIIRS detection and no mapped power plant or airport reads as open water (100%), "
                 "any of those signs as land (0%).")
    return text


def _lower_first(s: str) -> str:
    return s if len(s) > 1 and s[1].isupper() else s[:1].lower() + s[1:]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def suitability_at(g: Graded, i: int, model: SuitabilityProfile | None = None) -> Suitability:
    p = g.profile
    model = model or profile_model(p)
    res = g.result
    weights = [s.weight for s in p.factors]
    factors: list[FactorGrade] = []
    for k, spec in enumerate(p.factors):
        code = int(g.codes[k, i])
        v = float(g.values[k, i])
        shown = _display_at(g, k, i)
        factors.append(FactorGrade(key=spec.key, tier=None if code == NO_DATA else TIERS[code - 1],
                                   value=None if math.isnan(v) else v, display=shown,
                                   explanation=_explain(g, k, i, shown)))
    weak = [k for k in range(len(p.factors)) if g.codes[k, i] in (MARGINAL, UNSUITABLE)]
    weak.sort(key=lambda k: (-int(g.codes[k, i]), -weights[k], k))
    limiting = [p.factors[k].key for k in weak]

    tier_idx = int(res.tier[i])
    tier = None if tier_idx == NOT_GRADED else TIERS[tier_idx]
    score = None if math.isnan(res.score[i]) else float(res.score[i])
    with_data = int(np.count_nonzero(g.codes[:, i] > NO_DATA))
    tail = f" Graded on {with_data} of {len(p.factors)} factors."
    label = lambda k: _lower_first(CATALOGUE[p.factors[k].key].label)  # noqa: E731
    if res.vetoed[i]:
        vetoes = [k for k in range(len(p.factors)) if p.factors[k].constraint and g.codes[k, i] == UNSUITABLE]
        summary = (f"Unsuitable for {p.noun}: " + _join([f"{label(k)} is unsuitable ({factors[k].display})" for k in vetoes])
                   + (", a constraint." if len(vetoes) == 1 else ", constraints.") + tail)
    elif tier is None:
        summary = (f"Not enough data to grade this site for {p.noun}: the factors with data here carry "
                   f"{res.coverage[i]:.0%} of the weight, and at least {MIN_COVERAGE:.0%} is needed." + tail)
    else:
        head = f"{tier.capitalize()} site for {p.noun}"
        if weak:
            shown = [f"{label(k)} ({TIERS[int(g.codes[k, i]) - 1]})" for k in weak[:3]]
            more = len(weak) - 3
            head += ": limited by " + _join(shown + ([f"{more} more"] if more > 0 else []))
        else:
            head += ": every factor with data is ideal or good"
        # Why the grade is below what the score gives (each bound that set it).
        reasons = []
        F_ = range(len(p.factors))
        if res.held[i]:
            hard = [k for k in F_ if p.factors[k].constraint and int(g.codes[k, i]) - 1 == tier_idx]
            reasons.append(_join([f"{label(k)} ({tier})" for k in hard])
                           + (" is a constraint" if len(hard) == 1 else " are constraints")
                           + f", so the site can't grade better than {tier}")
        if res.unconfirmed[i]:
            gone = [k for k in F_ if p.factors[k].constraint and g.codes[k, i] == NO_DATA]
            reasons.append(_join([label(k) for k in gone])
                           + (" has no data here and is a constraint" if len(gone) == 1
                              else " have no data here and are constraints")
                           + ", so the site can't be confirmed better than good")
        if res.capped[i]:
            reasons.append(f"its weakest factor caps the grade at {tier}, one class better than that factor")
        if reasons:
            head += "; " + "; ".join(reasons) + f" (score {score:.2f})"
        summary = head + "." + tail
    return Suitability(profile=model, tier=tier, score=score, coverage=round(float(res.coverage[i]), 3),
                       limiting=limiting, summary=summary, factors=factors)
