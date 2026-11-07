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

BY_ID = {layer.id: layer for layer in LAYERS}


def is_categorical(layer: LayerDef, s: Slice) -> bool:
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


def provenance(layer: LayerDef) -> dict:
    """Licence, attribution and retrieval date from the first source.json found."""
    for rel in layer.provenance:
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
        meta = {k: m[k] for k in ("long_name", "definition", "native_res", "sampling", "period") if k in m}
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
        "nativeResolution": meta.get("native_res"),
        "sampling": meta.get("sampling"),
        "provenance": provenance(layer),
    }


def _region_of(path: Path) -> str:
    for r in REGIONS:
        if f"_{r}_" in path.name:
            return r
    return "global"
