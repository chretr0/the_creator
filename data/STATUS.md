# Data status and global storage estimate

Snapshot 2026-11-07. Covers what has been downloaded, what has been parsed to H3, and how big a whole-world version would be. Manual steps are in [MANUAL-DOWNLOADS.md](./MANUAL-DOWNLOADS.md), and the access routes in [README.md](./README.md).

## 1. Downloaded so far (no account needed)

**Data scope:** big datasets (> ~100 MB as a global file) are kept for two regions only:

- `arizona`: W -113.5, S 31.3, E -109.0, N 34.5
- `uk`: W -8.7, S 49.8, E 1.9, N 60.9

Hydrology uses a wider upstream "hydro box". Small global files stay global. The full rule is in [README.md §0.1](./README.md). Everything in this section was produced by `scripts/fetch_open_data.sh` (all regions), except where another script is named. Each folder has a `source.json` with URLs, sha256 checksums, licence, attribution and region.

### Regional data: `data/raw/<ID>/<region>/`

| ID | What | arizona | uk |
| --- | --- | --- | --- |
| LAND-02 | ESA WorldCover 2021 v200, 10 m | 4 tiles, 432 MB | 15 tiles, 526 MB |
| CTX-03 | Copernicus DEM GLO-90 | 20 tiles, 95 MB | 93 tiles, 179 MB |
| SOIL-01 | SoilGrids 250 m: 6 variables × 2 depths, mean + uncertainty | 37 MB | 115 MB |
| NET-01 | HydroRIVERS + HydroBASINS levels 1–12, clipped to the hydro box | 161 MB (Colorado/Gila/Sonora) | 40 MB (GB + island of Ireland) |
| WATER-06 | Aqueduct 4.0 basins (baseline/monthly/future layers) | 86 baseline basins, 1.5 MB | 433 baseline basins, 5 MB |
| CTX-05 | GHSL population + built-up 2025, 30″ | 0.4 MB (7.2 M people) | 4.4 MB (73.2 M people) |
| CTX-04 | WorldPop R2025A 2025, 1 km | 0.2 MB (8.5 M people) | 1.9 MB (74.5 M people) |
| LAND-05 | FIRMS VIIRS S-NPP 2024 detections | US + Mexico CSVs, 0.5 MB | UK CSV, 0.3 MB |
| CTX-02 | NASA POWER API points (climatology + monthly 2024), 1° grid | 20 points | 121 points |
| WATER-04 | US Water Quality Portal: nitrate, arsenic, TDS since 2020 | 6.5 MB | — (US only; the UK equivalent is manual, WATER-05) |
| IND-02 | EPA TRI 2023 + 2024, Arizona state files | 1.5 MB | — (US only) |
| OBS-02 / OBS-04 | Sentinel-2 L2A and Landsat 8 clips, Globe–Miami (`scripts/fetch_imagery.py`) | 11 + 10 MB | — (demo scene only) |
| IND-07 | NESO carbon intensity: regional snapshots + 1–14 Oct 2025 | — | 0.3 MB (Great Britain only, not NI) |
| IND-04 | NSTA offshore wellbores, whole UK continental shelf (`scripts/fetch_nsta_wells.py`) | — | 38 MB in `IND-04/2026-11-07/` |

The region boxes include neighbouring land:

- The UK box covers the eastern Republic of Ireland (including Dublin), the Isle of Man and a strip of northern France. That is why its population is 74.5 M rather than the UK's ~69 M.
- The Arizona box includes a strip of Sonora.

Filter with `data/prepared/boundaries/` when only one country is wanted.

### Small global files (kept whole by the rule)

| ID | What | Size |
| --- | --- | --- |
| GEO-06 | USGS MRDS CSV | 26 MB |
| CTX-02 | NASA POWER global NetCDF subsets (`CTX-02/global/`, `fetch_power_global.py`) | 31 MB |
| IND-04 | NSTA wells (see above) | 38 MB |

### Global copies kept from the first run (before the rule; `"region": "global"`)

These stay on disk on purpose. New runs do not create global copies. Their scripts are marked **GLOBAL MODE (opt-in)**.

| ID | What | Size |
| --- | --- | --- |
| WATER-06 | Aqueduct 4.0 global zip | 262 MB |
| NET-01 | HydroRIVERS global + HydroBASINS all 8 regions | 3.1 GB |
| CTX-05 | GHSL POP + BUILT_S global zips | 672 MB |
| CTX-04 | WorldPop global 1 km mosaic (`fetch_global_1km.py`) | 289 MB |
| SOIL-01 | SoilGrids 1 km global means, 12 layers, plus EPSG:4326 copies (`fetch_global_1km.py`) | 3.8 GB |
| LAND-05 | FIRMS 2024 all-countries archive, zipped + unzipped (`aggregate_firms_h3.py`) | 2.4 GB |
| IND-02 | EPA TRI 2023 + 2024, all US | 117 MB |

`data/raw` is **12 GB** in total. About 1.9 GB of the regional data is described in this section; the rest is the global copies from the first run.

Things to know about these downloads:

- **IND-04 licence:** the old data.gov.uk OGL links now return 403. The replacement NSTA service says "NSTA Open User Licence", so confirm the licence before any public export.
- **GEO-05 (USGS Spectral Library) failed:** the site blocks scripted downloads. It is on the manual list.
- **BGS geology (GEO-08):** the download is a web form, so it is on the manual list.
- **EA water quality (WATER-05):** the API moved and the new address isn't documented, so it is on the manual list.
- **SoilGrids:** values are integer-scaled. The divisors are in `SOIL-01/source.json`. There is no 1 km uncertainty layer.
- **POWER climatology period:** the store's metadata says 2001–2020, but the API labels the identical values 2001–2025. This is unresolved.

## 2. Parsed to H3 resolution 6 (whole world: kept from the first run)

These global Parquet files were built before the data-scope rule and are kept as they are. New H3 outputs should be made **per region**, with `scripts/aggregate_raster_to_h3.py` on the regional rasters (name them `<layer>_<region>_h3r6.parquet`). The measurements below are still the basis for the storage estimates.

All files are in `data/prepared/*_h3r6.parquet`, zstd-compressed, keyed by `h3` as uint64. Total **1.23 GB for 140 global layer-slices**. They are gitignored and can be rebuilt from the scripts.

| Output | Rows (cells) | Size | Check |
| --- | --- | --- | --- |
| GHSL population 2025 | 14,116,387 | 35 MB | Global sum 8.19 billion |
| WorldPop 2025 (1 km) | 2,290,000 (settled land only) | 14 MB | Global sum 8.195 billion; Arizona box 8.64 M |
| SoilGrids, 12 layers | 3.66 M each (land only) | 15–21 MB each, 223 MB total | pH (÷10) ranges 3.6–9.5 |
| POWER, 5 variables × (13 climatology + 12 monthly 2024 columns) | 14,117,882 each | 65–122 MB each, 974 MB total | Phoenix annual irradiation 5.848 kWh/m²/day, equal to the API |
| FIRMS VIIRS 2024 | 933,751 | 16 MB | 20.98 M detections; 5,875 in the Arizona box |

Rules of thumb from these measurements:

| Kind of layer | Parquet size per global slice (one variable, one time step) |
| --- | --- |
| Fine source, all cells (e.g. GHSL) | ~35 MB |
| Fine source, land only (e.g. SoilGrids) | ~15–20 MB |
| Coarse 0.5°–1° source sampled to every cell (POWER) | ~5–9 MB, because values repeat |
| Sparse points aggregated (FIRMS) | ~16 MB per year |

The resolution-6 grid has 14,117,882 cells, of which about 3.7–4.1 M are land. Aggregating a global 1 km raster takes about 30 s, plus about 3 min to reproject if the source is not in lon/lat.

**Postgres comparison (measured in the project database):** one row per layer, time and cell, with a primary key, takes **84 bytes per row**. That is 1.2 GB per all-cell slice, or 0.3 GB per land-only slice. A long-format Postgres store would therefore be about 25× larger than Parquet. Keep global layers in Parquet and query them with DuckDB, which can filter by bbox on the sorted `h3` column. Keep Postgres for scenarios and projects.

**Size tip for coarse grids:** storing a cell-to-native-grid-index lookup once, plus small per-variable grid tables, would shrink POWER from 974 MB to well under 100 MB.

## 3. Whole-world raw download sizes

GB means 10⁹ bytes. **M** = measured by listing or summing actual file sizes. **E** = estimated (sample × count, or grid × data type). **C** = cited from the provider. All rows were checked 2026-11-07.

### Tier A: already downloaded globally, or small (< 5 GB each)
Aqueduct 0.26 · HydroSHEDS 3.1 · MRDS 0.03 · GHSL 0.67 · WorldPop 1 km 0.28 · SoilGrids 1 km (12 layers) 2.0 · POWER subset 0.03 · FIRMS 2024 0.46 · TRI 0.12 · GRACE mascons 0.04 (M) · GRACE data assimilation 2024 0.11 (M) · EMIT L3 aggregate 0.02 (M) · GEDI biomass 2.5 (M) · PACE chlorophyll 2025 1.7 (M) · ERA5-Land monthly t2m+tp 0.1–0.6 (E) · CAMS monthly 0.01 (E) · GEM tracker ~0.05 (E) · USGS spectral library ASCII 0.02 (C)

**About 12 GB in total.** About 8 GB of that is already on disk.

### Tier B: global fine-resolution rasters
Do not keep these. Stream each tile, aggregate it to H3, then delete it.

| ID | Product | Global raw | |
| --- | --- | --- | --- |
| LAND-02 | WorldCover 2021, 10 m, 2,651 tiles | **124 GB** | M |
| CTX-03 | Copernicus DEM GLO-90, 26,475 tiles (DEM only) | **71 GB** | M |
| CTX-03 | Copernicus DEM GLO-30 | 589 GB | M |
| SOIL-01 | SoilGrids 250 m, one variable/depth | 4.6 GB | M |
| SOIL-01 | SoilGrids 250 m, all variables, depths and quantiles | ~1.25 TB | E |
| LAND-03 | WorldCereal 2021 (all 21 products) | 237 GB | M |
| OBS-06 | MODIS NDVI monthly 1 km (MOD13A3), 2024 | 30 GB | M |
| WATER-01 | SMAP 9 km daily, 2024 | 234 GB | M |
| OCEAN-02 | Copernicus Marine BGC monthly, 2024, full depth | 12.6 GB | M |
| WATER-04 | Water Quality Portal, all US results (454 M rows) | 260–420 GB CSV | E |
| CTX-01 | ERA5-Land hourly t2m+tp, one year | 70–170 GB | E |

**About 0.9 TB without the full SoilGrids 250 m set, and about 2.2 TB with it.** This disk has about 335 GB free.

### Tier C: swath and scene archives (terabytes per year)
Process these in the cloud or as regional subsets only.

| ID | Product | Size | |
| --- | --- | --- | --- |
| AIR-01 | Sentinel-5P NO₂ L2, 2024 | 3.0 TB | M |
| GEO-01 | EMIT L2B minerals, whole archive | 11.9 TB (5.1 TB mineral files only) | M |
| OBS-05 | ECOSTRESS LST, 2024 | ~9.5 TB | E |
| WATER-03 | SWOT 100 m raster, 2024 | ~15.2 TB | E |
| GEO-04 | ASTER AST_07XT, 2024 | ~5 TB | E |
| OBS-02 | Sentinel-2 10 m global composite (WorldCover S2 RGBNIR) | 9.2 TB | M |
| OBS-02 | Sentinel-2 L2A, 2024 | ~3.3 PB | E |
| OBS-04 | Landsat C2 L2, 2024 | ~0.37 PB | E |

**About 45 TB per year before the imagery archives.**

Gated sources (Planet, Pixxel, PRISMA, Carbon Mapper, Comtrade, Global Fishing Watch) are not sized.

## 4. Whole-world size once parsed to H3 resolution 6

These projections are built from the per-slice measurements in §2, for a one-year global snapshot of every non-gated catalogue source.

| Group | Slices | Parquet |
| --- | --- | --- |
| **Already built** (POWER, soil 12, population 2, FIRMS) | 140 | **1.23 GB** (measured) |
| WorldCover class fractions (11 columns) | 1 table | ~0.05 GB |
| DEM elevation mean/min/max + slope | 4 | ~0.1 GB |
| SoilGrids remaining 1 km variables and depths (66 total) | 54 | ~1.0 GB |
| Aqueduct (cell→basin map + indicator table), HydroBASINS/HydroRIVERS cell links | — | ~0.15 GB |
| MODIS NDVI, SMAP, ERA5-Land, S5P NO₂ monthly | ~60 | ~0.9 GB |
| CAMS monthly (5 variables) | 60 | ~0.4 GB |
| GRACE monthly record (~250 months) | 250 | ~1.3 GB (≈0.01 GB if trend only) |
| PACE + Copernicus Marine surface monthly (ocean cells) | ~70 | ~1.5 GB |
| EMIT mineral groups, ECOSTRESS/SWOT/GEDI/WorldCereal annual summaries | ~20 | ~0.3 GB |
| Point layers (MRDS ~300k, GEM 143k, TRI, WQP per-cell summaries, FIRMS more years) | — | ~0.6 GB |
| **Total, one-year global snapshot** | **~650** | **≈ 8 GB** |
| Add the 250 m SoilGrids quantiles and uncertainty | +270 | +~5 GB → ≈ 13 GB |
| Each further year of monthly series | | +~2–3 GB/yr |

**Bottom line:**

- **Parsed size is small.** All sources, globally at resolution 6, come to about **8–13 GB of Parquet**.
- **Postgres in long format would be huge:** about 650 slices × 0.3–1.2 GB ≈ **0.2–0.8 TB**. It belongs in Parquet with DuckDB.
- **The bottleneck is the raw download and the compute, not storage.** Tier B is about 1–2 TB of transfer, which fits if streamed tile by tile with a peak of a few GB on disk. Tier C is about 45 TB/year and cannot be done on a laptop. Use cloud processing (Earthdata cloud, Planetary Computer, Earth Engine) or keep it to regional subsets.

## 5. Suggested next steps

1. **Build per-region H3 layers** for both regions from the regional rasters (WorldCover fractions, DEM, SoilGrids 250 m, GHSL/WorldPop) with `scripts/aggregate_raster_to_h3.py`. That is minutes of compute and a few MB each.
2. **After you create an Earthdata login** (manual list item 1): EMIT minerals (Arizona only), GEDI biomass, MODIS NDVI and S5P, fetched for both region boxes.
3. **After you complete the GEM download form:** the power-plant tracker. The global workbook is under 100 MB, so it is kept whole.
4. **UK manual items:** BGS Geology 625k and Environment Agency water quality.

The whole-world figures in §3–§4 are a sizing reference only. The data-scope rule means global fine-resolution datasets are not downloaded.
