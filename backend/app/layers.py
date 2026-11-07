"""Registry of H3 cell layers (choropleths) built from data/prepared/*_h3r6.parquet.

A layer is a measured/modelled quantity with one or more *slices* (a month, a depth, a statistic).
Each slice is one Parquet column in one or more files: global files, or one file per project region
(`<layer>_<region>_h3r6.parquet`). Missing files make a layer (or slice) unavailable rather than
breaking the API, so new data shows up as soon as its prepare script has run.

Provenance (licence, attribution, retrieval date) is read from the committed
data/raw/<ID>/[region/]source.json records, never restated by hand here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq

from app.config import REPO_ROOT, settings
from app.h3store import Source

REGIONS = ("arizona", "uk")
# Boxes the regional (big) datasets are clipped to: data/README.md §0.1. W, S, E, N.
REGION_BOXES = {"arizona": (-113.5, 31.3, -109.0, 34.5), "uk": (-8.7, 49.8, 1.9, 60.9)}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

RAW_DIR = REPO_ROOT / "data" / "raw"


@dataclass
class Slice:
    id: str
    label: str
    files: tuple[str, ...]  # file names in the prepared dir; "{region}" expands to each region
    column: str
    group: str | None = None  # e.g. "Long-term climatology", "2024"
    agg: str | None = None  # overrides the layer aggregation
    scale: float | None = None
    units: str | None = None
    display: str | None = None  # overrides the layer display ("value" | "density" | "percent")
    categorical: bool | None = None  # overrides "categories + mode aggregation means categorical"


@dataclass
class LayerDef:
    id: str
    name: str
    category: str
    source_id: str
    provenance: tuple[str, ...]  # data/raw-relative dirs holding source.json
    slices: list[Slice]
    units: str
    agg: str = "mean"  # how resolution-6 cells combine into coarser display cells
    scale: float = 1.0
    display: str = "value"  # "value" | "density" (sum / km² × density_factor) | "percent" (×100)
    density_factor: float = 1.0
    density_units: str | None = None
    key_column: str = "h3"
    palette: str = "sequential"  # "sequential" | "diverging" | "categorical"
    scale_type: str = "linear"  # "linear" | "log"
    domain: tuple[float, float] | None = None  # fixed colour domain; computed from data otherwise
    categories: list[dict] | None = None  # for categorical layers: [{value, label, colour}]
    coverage: str = "global"  # "global" | "regions"
    description: str = ""
    limitations: list[str] = field(default_factory=list)
    default_slice: str | None = None
    # Extra per-cell columns shown in the cell profile (resolution 6 only), as (column, label).
    attributes: list[tuple[str, str]] = field(default_factory=list)

    def slice(self, slice_id: str | None) -> Slice:
        if slice_id is None:
            slice_id = self.default_slice or self.slices[0].id
        for s in self.slices:
            if s.id == slice_id:
                return s
        raise KeyError(slice_id)


def _prepared(name: str) -> Path:
    return Path(settings.prepared_data_dir) / name


def slice_files(s: Slice) -> list[Path]:
    out = []
    for f in s.files:
        names = [f.format(region=r) for r in REGIONS] if "{region}" in f else [f]
        out += [p for p in (_prepared(n) for n in names) if p.exists()]
    return out


def source_for(layer: LayerDef, s: Slice) -> Source | None:
    files = slice_files(s)
    if not files:
        return None
    agg = s.agg or layer.agg
    return Source(tuple(files), layer.key_column, s.column, agg, s.scale or layer.scale)


def slice_display(layer: LayerDef, s: Slice) -> str:
    return s.display or layer.display


# ---------------------------------------------------------------------------------------------
# Definitions


def _power(var: str, layer_id: str, name: str, *, palette="sequential", domain=None, description="") -> LayerDef:
    slices = [Slice("clim-ann", "Annual mean", (f"power_{var}_climatology_h3r6.parquet",), "ann", "Long-term climatology")]
    slices += [
        Slice(f"clim-{i + 1:02d}", m, (f"power_{var}_climatology_h3r6.parquet",), f"m{i + 1:02d}", "Long-term climatology")
        for i, m in enumerate(MONTHS)
    ]
    slices += [
        Slice(f"2024-{i + 1:02d}", f"{m} 2024", (f"power_{var}_monthly2024_h3r6.parquet",), f"m{i + 1:02d}", "2024")
        for i, m in enumerate(MONTHS)
    ]
    return LayerDef(
        id=layer_id,
        name=name,
        category="Solar & climate",
        source_id="CTX-02",
        provenance=("CTX-02/global",),
        slices=slices,
        units="",  # filled from Parquet metadata
        palette=palette,
        domain=domain,
        description=description,
        limitations=[
            "Coarse model grid (about 0.5–1°) sampled to every H3 cell: neighbouring cells repeat the same value.",
            "Climatology period is unresolved (store says 2001–2020, the API labels it 2001–2025).",
        ],
    )


def _soil(var: str, name: str, scale: float, units: str, domain=None) -> LayerDef:
    return LayerDef(
        id=f"soil_{var}",
        name=name,
        category="Soil",
        source_id="SOIL-01",
        provenance=("SOIL-01",),
        slices=[
            Slice("0-5cm", "0–5 cm", (f"soilgrids_{var}_0-5cm_mean_h3r6.parquet",), "value"),
            Slice("15-30cm", "15–30 cm", (f"soilgrids_{var}_15-30cm_mean_h3r6.parquet",), "value"),
        ],
        units=units,
        scale=scale,
        domain=domain,
        description="SoilGrids 2.0 1 km mean prediction, averaged to H3 resolution 6.",
        limitations=[
            "Modelled predictions, not soil samples.",
            "Urban areas, water and permanent ice are no-data (blank), not zero.",
        ],
    )


WORLDCOVER = [
    (10, "frac_tree", "Tree cover", "#2d6a2d"),
    (20, "frac_shrub", "Shrubland", "#b8a03a"),
    (30, "frac_grass", "Grassland", "#e6d96a"),
    (40, "frac_crop", "Cropland", "#e58cd9"),
    (50, "frac_built", "Built-up", "#d7301f"),
    (60, "frac_bare", "Bare / sparse vegetation", "#bdb6a8"),
    (70, "frac_snow", "Snow and ice", "#f0f0f0"),
    (80, "frac_water", "Permanent water", "#2c6db5"),
    (90, "frac_wetland", "Herbaceous wetland", "#2aa198"),
    (95, "frac_mangrove", "Mangroves", "#1b9e5b"),
    (100, "frac_moss", "Moss and lichen", "#f3e3b0"),
]

LAYERS: list[LayerDef] = [
    _power(
        "ALLSKY_SFC_SW_DWN",
        "solar_ghi",
        "Solar irradiation (all sky, GHI)",
        domain=(0.0, 8.0),
        description="Daily global horizontal irradiation reaching the surface, including clouds.",
    ),
    _power(
        "CLRSKY_SFC_SW_DWN",
        "solar_clearsky",
        "Solar irradiation (clear sky)",
        domain=(0.0, 9.0),
        description="Irradiation the surface would get without clouds; compare with all-sky to see cloud loss.",
    ),
    _power("T2M", "air_temperature", "Air temperature (2 m)", palette="diverging", domain=(-30.0, 30.0)),
    _power("PRECTOTCORR", "precipitation", "Precipitation", domain=(0.0, 10.0)),
    _power("WS10M", "wind_10m", "Wind speed (10 m)", domain=(0.0, 10.0)),
    LayerDef(
        id="population_ghsl",
        name="Population (GHSL 2025)",
        category="People & settlement",
        source_id="CTX-05",
        provenance=("CTX-05",),
        slices=[Slice("2025", "2025", ("ghsl_pop_2025_h3r6.parquet",), "value")],
        units="people",
        agg="sum",
        display="density",
        density_units="people/km²",
        scale_type="log",
        domain=(1.0, 10000.0),
        description="Modelled residential population (GHS-POP R2023A, epoch 2025), summed per cell.",
        limitations=["Do not add GHSL and WorldPop together; they model the same people."],
    ),
    LayerDef(
        id="population_worldpop",
        name="Population (WorldPop 2025)",
        category="People & settlement",
        source_id="CTX-04",
        provenance=("CTX-04",),
        slices=[Slice("2025", "2025", ("worldpop_2025_1km_h3r6.parquet",), "value")],
        units="people",
        agg="sum",
        display="density",
        density_units="people/km²",
        scale_type="log",
        domain=(1.0, 10000.0),
        description="Constrained 1 km model: only mapped settlement pixels carry people, so unsettled land is blank.",
        limitations=["Alpha release (R2025A); may change.", "Do not add GHSL and WorldPop together."],
    ),
    LayerDef(
        id="built_up",
        name="Built-up surface (GHSL 2025)",
        category="People & settlement",
        source_id="CTX-05",
        provenance=tuple(f"CTX-05/{r}" for r in REGIONS),
        slices=[Slice("2025", "2025", ("ghsl_built_{region}_h3r6.parquet",), "value")],
        units="m²",
        agg="sum",
        display="density",
        density_factor=1e-4,  # m² per km² → percent of cell area
        density_units="% of area",
        domain=(0.0, 30.0),
        coverage="regions",
        description="Built-up surface (GHS-BUILT-S), shown as share of cell area.",
    ),
    LayerDef(
        id="fires_2024",
        name="Fire detections 2024 (VIIRS)",
        category="Hazards",
        source_id="LAND-05",
        provenance=("LAND-05",),
        key_column="h3_r6",
        slices=[
            Slice("detections", "Detections", ("firms_viirs_snpp_2024_h3r6.parquet",), "detections"),
            Slice("days", "Days with a detection", ("firms_viirs_snpp_2024_h3r6.parquet",), "days_with_detection",
                  agg="mean", units="days", display="value"),
            Slice("frp", "Fire radiative power (sum)", ("firms_viirs_snpp_2024_h3r6.parquet",), "frp_sum_mw",
                  units="MW", display="density"),
        ],
        units="detections",
        agg="sum",
        display="density",
        density_factor=100.0,
        density_units="per 100 km²",
        scale_type="log",
        domain=(0.1, 500.0),
        description="VIIRS S-NPP 375 m thermal anomalies in 2024, including industrial heat sources.",
        limitations=[
            "A detection is a hot pixel at overpass time, not a fire perimeter or burned area.",
            "Cells with no detection are blank, which is not proof there was no fire.",
        ],
    ),
    LayerDef(
        id="elevation",
        name="Elevation (Copernicus DEM)",
        category="Terrain & land cover",
        source_id="CTX-03",
        provenance=tuple(f"CTX-03/{r}" for r in REGIONS),
        slices=[
            Slice("mean", "Mean", ("dem_{region}_h3r6.parquet",), "value"),
            Slice("min", "Minimum", ("dem_{region}_h3r6.parquet",), "min", agg="mean"),
            Slice("max", "Maximum", ("dem_{region}_h3r6.parquet",), "max", agg="mean"),
            Slice("slope", "Mean slope", ("dem_{region}_h3r6.parquet",), "slope_mean", units="°"),
        ],
        units="m",
        coverage="regions",
        description="Copernicus DEM GLO-90 surface heights (includes buildings and trees), averaged per cell.",
        limitations=["Digital surface model: heights include buildings and canopy."],
    ),
    LayerDef(
        id="land_cover",
        name="Land cover (ESA WorldCover 2021)",
        category="Terrain & land cover",
        source_id="LAND-02",
        provenance=tuple(f"LAND-02/{r}" for r in REGIONS),
        slices=[Slice("dominant", "Dominant class", ("worldcover_{region}_h3r6.parquet",), "dominant", agg="mode",
                      display="value")]
        + [
            Slice(col.removeprefix("frac_"), label, ("worldcover_{region}_h3r6.parquet",), col, display="percent")
            for _, col, label, _ in WORLDCOVER
        ],
        units="% of cell",
        palette="sequential",
        domain=(0.0, 100.0),
        coverage="regions",
        categories=[{"value": code, "label": label, "colour": colour} for code, _, label, colour in WORLDCOVER],
        description="10 m land-cover classes summarised per cell (dominant class, or the share of one class).",
        limitations=["Classified from 2021 imagery; mixed pixels and recent change are not reflected."],
    ),
]

_SOIL = [
    _soil("phh2o", "Soil pH (water)", 10, "pH", (4.5, 8.5)),
    _soil("soc", "Soil organic carbon", 10, "g/kg", (0.0, 100.0)),
    _soil("clay", "Clay content", 10, "%", (0.0, 60.0)),
    _soil("sand", "Sand content", 10, "%", (0.0, 90.0)),
    _soil("nitrogen", "Soil nitrogen", 100, "g/kg", (0.0, 5.0)),
    _soil("bdod", "Bulk density", 100, "kg/dm³", (0.8, 1.7)),
]
LAYERS += _SOIL


# ---------------------------------------------------------------------------------------------
# Satellite and reanalysis layers built by scripts/prepare_observation_h3.py. Grids coarser than a
# res-6 cell are sampled at each cell centre (like POWER); finer pixels are averaged per cell.


def _monthly(file: str, prefix: str, year: str = "2024") -> list[Slice]:
    """Annual mean plus one slice per month, so the month stepper works as for the POWER layers."""
    slices = [Slice(f"{year}-ann", f"{year} mean", (file,), f"{prefix}ann", year)]
    slices += [
        Slice(f"{year}-{i + 1:02d}", f"{m} {year}", (file,), f"{prefix}m{i + 1:02d}", year)
        for i, m in enumerate(MONTHS)
    ]
    return slices


def _regional(r: str) -> tuple[str, ...]:
    return tuple(f"{r}/{reg}" for reg in REGIONS)


SAMPLED = "Coarse grid sampled to every H3 cell: neighbouring cells repeat the same value."
ERA5_FILE = "era5land_2024_{region}_h3r6.parquet"
CAMS_FILE = "cams_2024_{region}_h3r6.parquet"
GRACE_DA_FILE = "grace_dadm_2024_{region}_h3r6.parquet"


def _era5(layer_id: str, name: str, prefix: str, units: str, category="Solar & climate", **kw) -> LayerDef:
    return LayerDef(
        id=layer_id,
        name=name,
        category=category,
        source_id="CTX-01",
        provenance=_regional("CTX-01"),
        slices=_monthly(ERA5_FILE, prefix),
        units=units,
        coverage="regions",
        limitations=[SAMPLED + " (0.1° grid, ~9 km)", "Reanalysis model output, land only: sea cells are blank."],
        **kw,
    )


def _cams(layer_id: str, name: str, prefix: str, units: str, description: str, **kw) -> LayerDef:
    return LayerDef(
        id=layer_id,
        name=name,
        category="Air quality",
        source_id="AIR-02",
        provenance=_regional("AIR-02"),
        slices=_monthly(CAMS_FILE, prefix),
        units=units,
        coverage="regions",
        description=description,
        limitations=[SAMPLED + " (0.75° grid, ~80 km)", "Global reanalysis: smooths out local sources such as roads."],
        **kw,
    )


def _grace_da(layer_id: str, name: str, prefix: str, description: str) -> LayerDef:
    return LayerDef(
        id=layer_id,
        name=name,
        category="Water",
        source_id="WATER-02",
        provenance=_regional("WATER-02"),
        slices=_monthly(GRACE_DA_FILE, prefix),
        units="percentile",
        palette="diverging",
        domain=(0.0, 100.0),
        coverage="regions",
        description=description,
        limitations=[
            SAMPLED + " (0.25° grid)",
            "Drought indicator relative to 1948–2014, not a volume or an allocatable supply.",
            "Monthly value is the mean of the 7-day percentiles starting in that month.",
        ],
    )


ECOSTRESS_PASSES = {
    "arizona": [("20250612", "12 Jun 2025"), ("20250729", "29 Jul 2025"), ("20250815", "15 Aug 2025")],
    "uk": [("20250613", "13 Jun 2025"), ("20250808", "8 Aug 2025"), ("20250812", "12 Aug 2025")],
}
EMIT_MINERALS = ["Calcite", "Chlorite", "Dolomite", "Goethite", "Gypsum", "Hematite", "Illite+Muscovite",
                 "Kaolinite", "Montmorillonite", "Vermiculite", "Quartz+Feldspar"]

LAYERS += [
    _era5("era5_t2m", "Air temperature (ERA5-Land 2024)", "t2m_", "°C", palette="diverging", domain=(-30.0, 30.0),
          description="Monthly mean 2 m air temperature from the ERA5-Land reanalysis."),
    _era5("era5_precip", "Precipitation (ERA5-Land 2024)", "tp_", "mm/day", domain=(0.0, 10.0),
          description="Mean daily precipitation for each month of 2024."),
    _era5("era5_evap", "Evaporation (ERA5-Land 2024)", "evap_", "mm/day",
          description="Mean daily total evaporation (positive = water leaving the surface)."),
    _era5("era5_solar", "Solar irradiation (ERA5-Land 2024)", "ssrd_", "kWh/m²/day", domain=(0.0, 8.0),
          description="Mean daily surface downward short-wave radiation (GHI) per month."),
    _era5("era5_soil_water", "Soil water 0–7 cm (ERA5-Land 2024)", "swvl1_", "m³/m³", category="Water",
          domain=(0.0, 0.5), description="Volumetric soil water in the top layer (0–7 cm), modelled."),
    _cams("cams_pm25", "PM2.5 (CAMS 2024)", "pm25_", "µg/m³", "Near-surface fine particulate matter, monthly mean."),
    _cams("cams_pm10", "PM10 (CAMS 2024)", "pm10_", "µg/m³", "Near-surface coarse particulate matter, monthly mean."),
    _cams("cams_no2", "NO₂ total column (CAMS 2024)", "no2col_", "µmol/m²",
          "Total-column nitrogen dioxide; a column amount, not a ground-level concentration."),
    _cams("cams_so2", "SO₂ total column (CAMS 2024)", "so2col_", "µmol/m²", "Total-column sulphur dioxide."),
    _cams("cams_co", "CO total column (CAMS 2024)", "cocol_", "mmol/m²", "Total-column carbon monoxide."),
    _cams("cams_aod", "Aerosol optical depth 550 nm (CAMS 2024)", "aod_", "", "Total aerosol optical depth."),
    LayerDef(
        id="s5p_no2",
        name="NO₂ tropospheric column (Sentinel-5P)",
        category="Air quality",
        source_id="AIR-01",
        provenance=_regional("AIR-01"),
        slices=[
            Slice("mean", "Mean, 1–7 Jul 2025", ("s5p_no2_{region}_h3r6.parquet",), "no2"),
            Slice("n", "Ground pixels used", ("s5p_no2_{region}_h3r6.parquet",), "n_obs", agg="sum", units="pixels"),
        ],
        units="µmol/m²",
        coverage="regions",
        description="TROPOMI tropospheric NO₂ (qa ≥ 0.75) averaged over one week of overpasses.",
        limitations=["Column amount, not a breathing-height concentration.", "One week only: weather-dependent."],
    ),
    _grace_da("grace_groundwater", "Groundwater percentile (GRACE DA 2024)", "gws_",
              "Groundwater storage wetness percentile from GRACE/GRACE-FO data assimilation."),
    _grace_da("grace_rootzone", "Root-zone soil moisture percentile (GRACE DA 2024)", "rtzsm_",
              "Root-zone soil moisture wetness percentile from GRACE/GRACE-FO data assimilation."),
    _grace_da("grace_surface_sm", "Surface soil moisture percentile (GRACE DA 2024)", "sfsm_",
              "Surface soil moisture wetness percentile from GRACE/GRACE-FO data assimilation."),
    LayerDef(
        id="grace_tws",
        name="Water storage anomaly (GRACE mascons 2024)",
        category="Water",
        source_id="WATER-02",
        provenance=("WATER-02/global",),
        slices=_monthly("grace_tws_2024_h3r6.parquet", "tws_"),
        units="cm",
        palette="diverging",
        domain=(-30.0, 30.0),
        description="Terrestrial water storage anomaly (equivalent water height) against the 2004–2009 mean.",
        limitations=[SAMPLED + " (~3° mascons on a 0.5° grid)", "Not a kilometre-scale aquifer measure."],
    ),
    LayerDef(
        id="smap_soil_moisture",
        name="Soil moisture (SMAP, Jul 2025)",
        category="Water",
        source_id="WATER-01",
        provenance=_regional("WATER-01"),
        slices=[
            Slice("mean", "Mean, 1–7 Jul 2025", ("smap_sm_{region}_h3r6.parquet",), "sm_mean"),
            Slice("n", "Retrievals used", ("smap_sm_{region}_h3r6.parquet",), "n_retrievals", units="retrievals"),
        ],
        units="m³/m³",
        domain=(0.0, 0.5),
        coverage="regions",
        description="Surface (~0–5 cm) soil moisture from the SMAP radiometer, recommended-quality retrievals only.",
        limitations=[SAMPLED + " (9 km EASE grid)", "One week of retrievals; not groundwater or river flow."],
    ),
    LayerDef(
        id="swot_water",
        name="Surface water (SWOT, summer 2025)",
        category="Water",
        source_id="WATER-03",
        provenance=_regional("WATER-03"),
        slices=[
            Slice("frac", "Water share of observed area", ("swot_water_{region}_h3r6.parquet",), "water_frac",
                  display="percent"),
            Slice("wse", "Water-surface elevation", ("swot_water_{region}_h3r6.parquet",), "wse", units="m"),
        ],
        units="fraction",
        coverage="regions",
        description="SWOT 100 m raster passes: share of observed area that is water, and water-surface height.",
        limitations=[
            "Only cells under the few passes downloaded have values.",
            "Elevation is above the EGM2008 geoid; single-pass snapshots, not volumes.",
        ],
    ),
    LayerDef(
        id="gedi_biomass",
        name="Aboveground biomass (GEDI L4B)",
        category="Vegetation",
        source_id="LAND-04",
        provenance=_regional("LAND-04"),
        slices=[
            Slice("mean", "Biomass density", ("gedi_agbd_{region}_h3r6.parquet",), "agbd"),
            Slice("se", "Standard error", ("gedi_agbd_{region}_h3r6.parquet",), "agbd_se"),
        ],
        units="Mg/ha",
        domain=(0.0, 150.0),
        coverage="regions",
        description="Gridded 1 km aboveground biomass density from GEDI lidar footprints (2019–2023).",
        limitations=["No coverage north of ~51.6°N (most of the UK box).", "Model-based gridded mean, not wall-to-wall."],
    ),
    LayerDef(
        id="modis_ndvi",
        name="Vegetation greenness NDVI (MODIS 2024)",
        category="Vegetation",
        source_id="OBS-06",
        provenance=_regional("OBS-06"),
        slices=_monthly("modis_ndvi_2024_{region}_h3r6.parquet", "ndvi_"),
        units="NDVI",
        domain=(0.0, 0.9),
        coverage="regions",
        description="Monthly 1 km NDVI composites (MOD13A3), good-quality pixels averaged per cell.",
        limitations=["Cloudy months leave cells blank.", "Greenness index, not biomass or crop yield."],
    ),
    LayerDef(
        id="ecostress_lst",
        name="Land surface temperature (ECOSTRESS)",
        category="Solar & climate",
        source_id="OBS-05",
        provenance=_regional("OBS-05"),
        slices=[
            Slice(f"{region}-{day}", label, (f"ecostress_lst_{region}_h3r6.parquet",), f"lst_{day}",
                  group="Arizona" if region == "arizona" else "UK")
            for region, passes in ECOSTRESS_PASSES.items()
            for day, label in passes
        ],
        units="°C",
        coverage="regions",
        description="70 m skin temperature from single ISS overpasses, cloud-masked, averaged per cell.",
        limitations=[
            "Skin (surface) temperature, not air temperature.",
            "Each slice is one instantaneous overpass at a different time of day.",
        ],
    ),
    LayerDef(
        id="pace_chlorophyll",
        name="Ocean chlorophyll-a (PACE 2025)",
        category="Ocean",
        source_id="OCEAN-01",
        provenance=("OCEAN-01/uk",),
        slices=[
            Slice(f"2025-{m:02d}", f"{MONTHS[m - 1]} 2025", ("pace_chlor_a_uk_h3r6.parquet",), f"chl_2025_{m:02d}",
                  "2025")
            for m in (6, 7, 8)
        ],
        units="mg/m³",
        scale_type="log",
        domain=(0.1, 20.0),
        coverage="regions",
        description="Near-surface chlorophyll-a concentration, monthly 4 km composites (UK waters).",
        limitations=["Sediment-rich coastal waters (Thames, Severn) can read high.", "Not fish stock or biomass."],
    ),
    LayerDef(
        id="emit_minerals",
        name="Surface mineral abundance (EMIT L3)",
        category="Geology",
        source_id="GEO-01",
        provenance=("GEO-01/global",),
        slices=[
            Slice(m.lower().replace("+", "_"), m.replace("+", " + "), ("emit_minerals_h3r6.parquet",),
                  m.lower().replace("+", "_"))
            for m in EMIT_MINERALS
        ],
        units="abundance",
        description="Spectral abundance of exposed surface minerals from the EMIT imaging spectrometer.",
        limitations=[SAMPLED + " (0.5° grid)", "Only arid areas EMIT has imaged carry values.",
                     "Exposed surface only; says nothing about ore at depth.",
                     "Built from the gridded L3 product only. The L2B scenes in data/raw/GEO-01/arizona are unused: "
                     "they need the GLT to be georeferenced, and their portlandite hits look like misidentification."],
    ),
]

# ---------------------------------------------------------------------------------------------
# Aqueduct 4.0 baseline water stress, built by scripts/build_layers.py. Each cell takes the basin
# containing its centre; the index is never averaged or split, so coarser hexagons show the most
# common class (mode) rather than a mean. "No Data" basins keep a null value.

AQUEDUCT_BWS = [
    (0, "Low (<10%)", "#fde3d6"),
    (1, "Low – medium (10–20%)", "#f8bc9f"),
    (2, "Medium – high (20–40%)", "#f29169"),
    (3, "High (40–80%)", "#c4501f"),
    (4, "Extremely high (>80%)", "#62270d"),
    (-1, "Arid and low water use", "#9b8fd0"),
]
WATER_STRESS_FILE = "layers/water_stress_baseline/{region}.parquet"

LAYERS.append(
    LayerDef(
        id="water_stress",
        name="Baseline water stress (Aqueduct 4.0)",
        category="Water",
        source_id="WATER-06",
        provenance=_regional("WATER-06"),
        slices=[
            Slice("category", "Category", (WATER_STRESS_FILE,), "bws_cat", agg="mode", categorical=True),
            Slice("score", "Score (0–5)", (WATER_STRESS_FILE,), "value", agg="mode", categorical=False,
                  units="score 0–5"),
        ],
        units="score 0–5",
        agg="mode",
        domain=(0.0, 5.0),
        coverage="regions",
        categories=[{"value": v, "label": label, "colour": c} for v, label, c in AQUEDUCT_BWS],
        attributes=[("bws_label", "Aqueduct category"), ("string_id", "Aqueduct unit")],
        description=(
            "Ratio of water withdrawals to renewable supply in the sub-basin containing the cell centre, "
            "as Aqueduct's 0–5 score and category."
        ),
        limitations=[
            "Basin-level risk index, not a measured volume or an allocatable supply.",
            "Every cell in a basin repeats the same score; zoomed out, hexagons show the most common class.",
            "'Arid and low water use' basins score 5: read the category as well as the score.",
            "Basins Aqueduct publishes no score for ('No Data') are blank.",
        ],
    )
)

# ---------------------------------------------------------------------------------------------
# Average utility prices, built by scripts/prepare_utility_prices.py. One price per country (or US/Canadian/
# Australian state for electricity) repeated in each of its cells; zoomed-out hexagons show the mean.
# Day/night and seasonal tariffs are averaged into one rate (see data/reference/utility_prices/README.md).

PRICES_FILE = "utility_prices_h3r6.parquet"
PRICE_LIMITS = [
    "One average per country (or state/province): real tariffs vary by utility, city, customer size and contract.",
    "Day/night and seasonal rates are averaged into one figure; time-of-use savings are not modelled.",
    "Converted to USD at the World Bank annual average exchange rate for the price year.",
    "Sources differ in year and tax treatment: read the basis line for the cell before comparing two places.",
]

LAYERS += [
    LayerDef(
        id="electricity_price",
        name="Electricity price (average)",
        category="Prices",
        source_id="PRICE-01",
        provenance=("PRICE-01/global",),
        slices=[
            Slice("household", "Household", (PRICES_FILE,), "elec_household"),
            Slice("business", "Business", (PRICES_FILE,), "elec_business"),
        ],
        units="USD/kWh",
        domain=(0.0, 0.4),
        attributes=[("price_area_name", "Price area"), ("elec_household_basis", "Household basis"),
                    ("elec_business_basis", "Business basis")],
        description="Average end-user electricity price per kWh in the country, or the state/province in the US, "
                    "Canada and Australia.",
        limitations=PRICE_LIMITS + [
            "Business is the commercial / non-household average where reported; a few countries only have an "
            "industrial or 2019 World Bank survey figure (see basis).",
        ],
    ),
    LayerDef(
        id="water_price",
        name="Water price (average)",
        category="Prices",
        source_id="PRICE-01",
        provenance=("PRICE-01/global",),
        slices=[
            Slice("household", "Household", (PRICES_FILE,), "water_household"),
            Slice("business", "Business", (PRICES_FILE,), "water_business"),
        ],
        units="USD/m³",
        domain=(0.0, 6.0),
        attributes=[("price_area_name", "Price area"), ("water_household_basis", "Household basis"),
                    ("water_business_basis", "Business basis")],
        description="Average household price per m³ of drinking water plus wastewater, at about 15 m³ a month "
                    "with fixed charges spread in.",
        limitations=PRICE_LIMITS + [
            "Outside Europe and Latin America this is usually the capital or largest city's utility tariff.",
            "Some areas price water only, without wastewater (stated in the basis line).",
            "Business water prices exist for few countries.",
        ],
    ),
]

BY_ID = {layer.id: layer for layer in LAYERS}


def is_categorical(layer: LayerDef, s: Slice) -> bool:
    if s.categorical is not None:
        return s.categorical
    return layer.categories is not None and (s.agg or layer.agg) == "mode"


# ---------------------------------------------------------------------------------------------
# Metadata


@lru_cache(maxsize=None)
def _parquet_meta(path: str, _mtime: float) -> dict[str, str]:
    md = pq.read_schema(path).metadata or {}
    return {k.decode(): v.decode(errors="replace") for k, v in md.items() if k != b"ARROW:schema"}


def parquet_meta(path: Path) -> dict[str, str]:
    return _parquet_meta(str(path), path.stat().st_mtime)


@lru_cache(maxsize=None)
def _source_record(rel: str) -> dict | None:
    p = RAW_DIR / rel / "source.json"
    return json.loads(p.read_text()) if p.exists() else None


def provenance(layer: LayerDef, region: str | None = None) -> dict:
    """Licence, attribution and retrieval date from the layer's source.json (the cell's region first)."""
    rels = sorted(layer.provenance, key=lambda rel: not (region and rel.endswith(f"/{region}")))
    for rel in rels:
        rec = _source_record(rel)
        if not rec:
            continue
        lic = rec.get("licence") or {}
        if isinstance(lic, str):
            lic = {"name": lic}
        return {
            "provider": rec.get("provider"),
            "product": rec.get("product"),
            "version": rec.get("version"),
            "licence": lic.get("name"),
            "licenceUrl": lic.get("url"),
            "attribution": lic.get("attribution") or rec.get("attribution"),
            "retrievedAt": rec.get("retrievedAt"),
            "evidenceType": rec.get("evidenceType"),
            "documentationUrl": rec.get("documentationUrl"),
        }
    return {}


@lru_cache(maxsize=None)
def _sidecar(path: str, _mtime: float) -> dict:
    return json.loads(Path(path).read_text())


def sidecar(data_file: Path) -> dict:
    """The prepare script's JSON record next to a prepared file (<stem>.json, or layer.json in a layer dir)."""
    for p in (data_file.with_suffix(".json"), data_file.parent / "layer.json"):
        if p.exists():
            return _sidecar(str(p), p.stat().st_mtime)
    return {}


def _text(v) -> str | None:
    if isinstance(v, dict):
        return v.get("label") or v.get("name")
    return v if isinstance(v, str) and v else None


def layer_meta(layer: LayerDef, region: str | None = None) -> dict:
    """Period, native resolution, sampling and evidence type from Parquet metadata or the sidecar JSON."""
    files = next((slice_files(s) for s in layer.slices if slice_files(s)), [])
    if region:
        files = sorted(files, key=lambda f: _region_of(f) != region)
    if not files:
        return {}
    pm = parquet_meta(files[0])
    sc = sidecar(files[0])
    return {
        "period": _text(sc.get("period")) or pm.get("period"),
        "nativeResolution": _text(sc.get("nativeResolution")) or pm.get("native_res"),
        "sampling": _text(sc.get("sampling")) or pm.get("sampling"),
        "evidenceType": sc.get("evidenceType"),
    }


def region_at(lat: float, lon: float) -> str | None:
    for r, (w, s_, e, n) in REGION_BOXES.items():
        if w <= lon <= e and s_ <= lat <= n:
            return r
    return None


def cell_source(layer: LayerDef, region: str | None) -> dict:
    """Everything the inspector shows next to a value: what it is, where it came from and its licence."""
    prov = provenance(layer, region)
    meta = layer_meta(layer, region)
    return {
        "sourceId": layer.source_id,
        "provider": prov.get("provider"),
        "product": prov.get("product"),
        "period": meta.get("period"),
        "nativeResolution": meta.get("nativeResolution"),
        "sampling": meta.get("sampling"),
        "evidenceType": prov.get("evidenceType") or meta.get("evidenceType"),
        "licence": prov.get("licence"),
        "licenceUrl": prov.get("licenceUrl"),
        "attribution": prov.get("attribution"),
        "retrievedAt": prov.get("retrievedAt"),
        "documentationUrl": prov.get("documentationUrl"),
        "limitations": layer.limitations,
    }


def slice_units(layer: LayerDef, s: Slice) -> str:
    """Units of the value the API returns for this slice (after density/percent conversion)."""
    display = slice_display(layer, s)
    if is_categorical(layer, s):
        return "class"
    if display == "percent":
        return "% of cell"
    base = s.units or layer.units
    if not base:
        files = slice_files(s)
        base = parquet_meta(files[0]).get("units", "") if files else ""
        base = {"C": "°C", "kWh/m^2/day": "kWh/m²/day"}.get(base, base)
    if display == "density":
        if layer.density_units and (s.units is None or s.units == layer.units):
            return layer.density_units
        return f"{base} per {'100 km²' if layer.density_factor == 100 else 'km²'}"
    return base


def describe(layer: LayerDef) -> dict:
    slices = []
    for s in layer.slices:
        files = slice_files(s)
        slices.append({
            "id": s.id,
            "label": s.label,
            "group": s.group,
            "units": slice_units(layer, s),
            "rawUnits": s.units or layer.units or (parquet_meta(files[0]).get("units") if files else None),
            "aggregation": s.agg or layer.agg,
            "display": slice_display(layer, s),
            "categorical": is_categorical(layer, s),
            "available": bool(files),
            "regions": sorted({_region_of(f) for f in files}),
        })
    available = [s for s in slices if s["available"]]
    meta = {}
    first = next((slice_files(s) for s in layer.slices if slice_files(s)), [])
    if first:
        m = parquet_meta(first[0])
        meta = {k: m[k] for k in ("long_name", "definition") if k in m}
    lm = layer_meta(layer)
    return {
        "id": layer.id,
        "name": layer.name,
        "category": layer.category,
        "sourceId": layer.source_id,
        "description": layer.description or meta.get("definition", ""),
        "available": bool(available),
        "coverage": layer.coverage,
        "regions": sorted({r for s in available for r in s["regions"]}),
        "palette": layer.palette,
        "scaleType": layer.scale_type,
        "domain": list(layer.domain) if layer.domain else None,
        "categories": layer.categories,
        "defaultSlice": layer.default_slice or (available[0]["id"] if available else layer.slices[0].id),
        "slices": slices,
        "limitations": layer.limitations,
        "nativeResolution": lm.get("nativeResolution"),
        "sampling": lm.get("sampling"),
        "period": lm.get("period"),
        "provenance": provenance(layer),
    }


def _region_of(path: Path) -> str:
    for r in REGIONS:
        if f"_{r}_" in path.name or path.stem == r:
            return r
    return "global"
