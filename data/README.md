# Data acquisition guide

How to obtain each source in [CLAUDE-Data-Sources.md](../CLAUDE-Data-Sources.md). Source IDs (e.g. `WATER-06`) match that catalogue.

Checked 2026-11-07. These routes responded on that date: WorldCover S3, Copernicus DEM S3, HydroSHEDS, SoilGrids VRT, NESO, NASA POWER, MRDS CSV, CMR, the Water Quality Portal WQX3 endpoint and the FIRMS key page. The NASA collection short names below were also confirmed in CMR. Anything marked *(check on page)* is from documentation and has not been tested. Logged-in downloads have not been tried.

---

## 0. Before downloading anything

### 0.1 Data scope: two regions, big data regional only

**Rule:** a dataset whose global file is bigger than about **100 MB** is kept **only for the project regions** below, never for the whole world. Smaller global files (for example MRDS, about 26 MB) are kept whole. This applies to raw downloads *and* to H3 outputs in `data/prepared/`.

| Region | Folder name | Bounding box (W, S, E, N; WGS84) | Hydro box (rivers and basins) | Why |
| --- | --- | --- | --- | --- |
| Central and southern Arizona, USA (demo) | `arizona` | -113.5, 31.3, -109.0, 34.5 | -119.0, 28.0, -105.0, 44.0 (Colorado + Gila + Sonora basins) | Data centres and water stress around Phoenix, strong solar, copper mines, good EMIT coverage, plus US sources (TRI, Water Quality Portal) |
| United Kingdom | `uk` | -8.7, 49.8, 1.9, 60.9 (England, Wales, Scotland incl. Shetland, Northern Ireland) | -10.7, 49.8, 1.9, 60.9 (whole island of Ireland) | UK sources: NESO carbon intensity, NSTA wells, BGS geology, Environment Agency water quality |

How the rule is applied:

- **Tiled sources** (WorldCover, Copernicus DEM): only the tiles covering the box are downloaded.
- **Windowed sources** (SoilGrids VRTs): only the box is read.
- **API sources** (POWER, Water Quality Portal, NESO): only the box is requested.
- **Global-only files** (Aqueduct, HydroSHEDS, GHSL, WorldPop, FIRMS country archive):
  1. The global file is downloaded to `data/raw/_global_tmp/`.
  2. It is clipped with `scripts/clip_to_bbox.py`.
  3. The global copy is deleted.
- **Hydrology** uses the wider *hydro box* so that rivers and basins upstream of the region stay connected. H3 adjacency is not a water model, and cutting the river network at the region edge would break upstream links.
- **Bounding boxes include some neighbouring land.** Clipped vectors keep every whole feature that touches the box. The UK box also covers the Isle of Man, the eastern Republic of Ireland (including Dublin) and a strip of northern France. It holds 74.5M people (WorldPop) against the UK's ~69M. Filter by country/admin-1 (`data/prepared/boundaries/`) when only UK territory is wanted.

**Global copies from the first run are still on disk.** Before this rule, the first run downloaded these globally: Aqueduct, HydroSHEDS, GHSL, WorldPop, SoilGrids 1 km, the FIRMS 2024 archive, NASA POWER grids, all-US TRI, and the global H3 Parquet files. They are kept on purpose. Their `source.json` says `"region": "global"` and they are listed in [STATUS.md](./STATUS.md). The scripts that made them are **global mode, opt-in only**. Do not run them for new data:

- `scripts/fetch_global_1km.py`
- `scripts/fetch_power_global.py`
- `scripts/aggregate_firms_h3.py` (when pointed at the whole archive)

**To add a region:** add a case to `region_vars` in `scripts/fetch_open_data.sh` and to `REGIONS` in `scripts/write_source_records.py`, then run both.

The single-region example commands in §2–§4 use the Arizona box. `scripts/fetch_open_data.sh` runs the equivalent for every region.

### 0.2 Folder layout

```
data/
  README.md, STATUS.md, MANUAL-DOWNLOADS.md
  raw/<SOURCE-ID>/<region>/...          ← regional downloads, region = arizona | uk (gitignored)
  raw/<SOURCE-ID>/<region>/source.json  ← provenance for that region (committed)
  raw/<SOURCE-ID>/...  + source.json    ← global copies kept from the first run (region "global")
  raw/_global_tmp/                      ← transient; global files waiting to be clipped
  prepared/                             ← H3 outputs and small layers the app reads
```

Run the scripts like this:

```bash
scripts/fetch_open_data.sh
```

```bash
scripts/fetch_open_data.sh uk
```

```bash
python3 -I scripts/write_source_records.py data/raw
```

`data/raw/` is gitignored because downloads can be gigabytes. The `source.json` files are not ignored, so commit them.

### 0.3 Record provenance at download time

Fill this in **while you download**. Reconstructing it later is painful. It mirrors `SourceRelease` in the catalogue (§17).

```json
{
  "id": "WATER-06-aq40",
  "catalogueSourceId": "WATER-06",
  "provider": "World Resources Institute",
  "product": "Aqueduct 4.0 Water Risk Atlas",
  "version": "4.0 (file name as downloaded)",
  "doi": "",
  "documentationUrl": "https://www.wri.org/data/aqueduct-global-maps-40-data",
  "accessUrl": "<exact URL you downloaded from>",
  "accessMethod": "download",
  "evidenceType": "modelled",
  "retrievedAt": "2026-11-07",
  "files": ["<file name>", "<sha256>"],
  "licence": {
    "name": "CC BY 4.0",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "<exact attribution text from the provider>",
    "notes": ""
  },
  "query": "<bbox / dates / parameters you used>"
}
```

Run `shasum -a 256 <file>` for the checksum.

### 0.4 Accounts to create now (some need email confirmation)

| Account | Unlocks | Where |
| --- | --- | --- |
| **NASA Earthdata Login** | EMIT, SMAP, ECOSTRESS, MODIS, GRACE, SWOT, PACE, GEDI, ASTER, S5P (GES DISC) | https://urs.earthdata.nasa.gov/users/new |
| **FIRMS MAP_KEY** (email only) | Active-fire data | https://firms.modaps.eosdis.nasa.gov/api/map_key/ |
| **GEM download form** (name and email) | Power/industrial trackers | https://globalenergymonitor.org/download-data |
| Copernicus Data Space (CDSE) | Sentinel-1/2/3/5P, Copernicus DEM, CLMS | https://dataspace.copernicus.eu → Register |
| ECMWF account (CDS + ADS) | ERA5-Land, CAMS | https://cds.climate.copernicus.eu → Login/Register |
| Copernicus Marine | Ocean products | https://data.marine.copernicus.eu/register |
| MapTiler (optional) | Satellite basemap | https://cloud.maptiler.com/auth/widget?mode=signup |

Only the first three matter for the P0/P1 demo.

**Earthdata credentials file.** Many command-line tools read `~/.netrc`. Create it once:

```bash
printf 'machine urs.earthdata.nasa.gov login YOUR_USER password YOUR_PASS\n' >> ~/.netrc && chmod 600 ~/.netrc
```

Put API keys in `backend/.env` (already gitignored), for example `NEWWORLDS_FIRMS_MAP_KEY=...`. Never put them in frontend code, scenario JSON or `source.json`.

### 0.5 Tools

```bash
brew install gdal awscli
```

```bash
cd backend && uv add --dev earthaccess pystac-client planetary-computer geopandas rasterio xarray netcdf4 cdsapi copernicusmarine openpyxl
```

Keep download scripts in `backend/scripts/` or `scripts/`, never inside `data/raw/`. Pass the raw paths in as arguments.

---

## 1. Priority checklist

Do these in order. Stop after P0 and the first P1 rows if time is short.

| # | ID | Source | Account | Effort | Size (Arizona box) |
| --- | --- | --- | --- | --- | --- |
| 1 | MAP-01 | OpenFreeMap basemap | none | already wired | — |
| 2 | WATER-06 | WRI Aqueduct 4.0 | none (form) | 10 min | ~0.5 GB global zip |
| 3 | CTX-02 | NASA POWER | none | 10 min | < 1 MB |
| 4 | LAND-02 | ESA WorldCover 2021 | none | 10 min | 4 tiles, ~0.3 GB |
| 5 | IND-01 | GEM Integrated Power Tracker | form | 10 min | ~30 MB xlsx |
| 6 | SOIL-01 | SoilGrids (one variable) | none | 10 min | < 50 MB |
| 7 | GEO-01 | NASA EMIT minerals | Earthdata | 30–60 min | 1–3 scenes, ~0.2–1 GB |
| 8 | GEO-06 | USGS MRDS | none | 5 min | ~100 MB zip |
| 9 | LAND-05 | NASA FIRMS | MAP_KEY | 5 min | < 1 MB |
| 10 | NET-01 | HydroRIVERS / HydroBASINS (North America) | none | 10 min | ~0.5 GB |
| 11 | CTX-03 | Copernicus DEM GLO-90 | none | 10 min | ~20 tiles, small |
| 12 | IND-07 | NESO carbon intensity (UK only) | none | 5 min | tiny |
| — | everything else | P2 or GATED: see §4–§5 | | | |

---

## 2. P0 sources: detailed steps

### MAP-01: OpenFreeMap / OpenStreetMap
Nothing to download. The app already uses `https://tiles.openfreemap.org/styles/liberty`. Keep the "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors" attribution visible.

### WATER-06: WRI Aqueduct 4.0 (baseline water stress)
1. Open https://www.wri.org/data/aqueduct-global-maps-40-data
2. Download the **Aqueduct 4.0 data** zip. The page may ask for name, use and email first. It is a single global file, so no bbox is needed. *(check on page: exact file name)*
3. It is a global-only file (over 100 MB), so under the data-scope rule (§0.1) it is clipped to each region (`data/raw/WATER-06/<region>/aqueduct40_<region>.gpkg`) and the global zip is deleted. `scripts/fetch_open_data.sh` does this for you.
4. Inside is a geodatabase/GeoPackage plus CSVs. Use the **baseline annual** layer. The key fields are:
   - `pfaf_id` (HydroBASINS level-6 basin ID)
   - `bws_raw` (ratio of withdrawals to available supply)
   - `bws_score` (0–5)
   - `bws_cat` / `bws_label`
5. Licence: CC BY 4.0. The citation is on the download page. Copy it into `source.json`.
6. Inspect it with `ogrinfo -so <file.gdb>` to list layers.

**Meaning:** this is a basin-level index, not litres. Join it to H3 by basin polygon. Never divide it among cells or subtract project water from it.

### CTX-02: NASA POWER (solar irradiation and temperature)
No key is needed.

**Point climatology** (long-term monthly means). This request was tested and works:

```bash
curl "https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=ALLSKY_SFC_SW_DWN,T2M&community=RE&longitude=-112.0&latitude=33.4&format=JSON"
```

**A specific year at monthly resolution** (use this for the period-based energy balance):

```bash
curl "https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=ALLSKY_SFC_SW_DWN,T2M&community=RE&longitude=-112.0&latitude=33.4&start=2024&end=2024&format=JSON"
```

How to cover the region:

- POWER solar data sit on a roughly 1° grid, and meteorology on about 0.5° × 0.625°.
- Loop over grid-cell centres inside the bbox. That is roughly 20 points for Arizona, so do not make one request per hexagon.
- Save each response as `data/raw/CTX-02/<region>/climatology/<lat>_<lon>.json`.

Units are in the response header. `ALLSKY_SFC_SW_DWN` is in **kWh/m²/day** (irradiation, not power) and `T2M` is in °C. Keep the `header` block for provenance.

### LAND-02: ESA WorldCover 2021 v200 (10 m land cover)
Public S3, with no account needed. Tiles are 3° × 3° and named by their lower-left corner. Arizona needs four tiles: N30W114, N30W111, N33W114 and N33W111.

```bash
mkdir -p data/raw/LAND-02/arizona/v200_2021 && for t in N30W114 N30W111 N33W114 N33W111; do curl -fL -o data/raw/LAND-02/arizona/v200_2021/ESA_WorldCover_10m_2021_v200_${t}_Map.tif "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_${t}_Map.tif"; done
```

- Class codes: 10 tree, 20 shrub, 30 grass, 40 crop, 50 built-up, 60 bare/sparse, 70 snow/ice, 80 water, 90 wetland, 95 mangrove, 100 moss/lichen. 0 means no data.
- Licence: CC BY 4.0. Required citation: "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium".
- Aggregate to H3 as **class fractions**, not as a mean class code.

### IND-01: Global Energy Monitor (power plants)
1. Go to https://globalenergymonitor.org/download-data and fill in the form. The link arrives immediately or by email.
2. Choose the **Global Integrated Power Tracker**. It covers coal, gas, solar, wind, hydro, nuclear and others in one workbook. If that is not offered, use the **Global Solar Power Tracker** plus the **Global Coal/Gas Plant Tracker**.
3. Save the `.xlsx` and the methodology/"About" sheet to `data/raw/IND-01/<release-month-year>/`.
4. Record the release date shown in the file name.
5. Useful fields: latitude, longitude, capacity (MW), status (operating/announced/retired…), type, owner.
6. Licence: CC BY 4.0 by default. Check the "About" sheet for rows from third-party sources, such as TransitionZero, which carry non-commercial terms.

**Meaning:** nameplate capacity is not generation or spare grid capacity. Filter on `status` before showing anything as operating.

---

## 3. P1 sources

### SOIL-01: ISRIC SoilGrids (one property, one depth)
The REST API is paused, so use the cloud VRT through GDAL. This command clips directly to the bbox without downloading the global file:

```bash
mkdir -p data/raw/SOIL-01/arizona/soilgrids_v2 && gdal_translate -projwin -113.5 34.5 -109.0 31.3 -projwin_srs EPSG:4326 /vsicurl/https://files.isric.org/soilgrids/latest/data/phh2o/phh2o_0-5cm_mean.vrt data/raw/SOIL-01/arizona/soilgrids_v2/phh2o_0-5cm_mean.tif
```

- The output keeps SoilGrids' Homolosine projection (ESRI:54052). Reproject it later in the pipeline.
- Useful variables: `phh2o` (pH), `soc` (organic carbon), `clay`, `sand`, `nitrogen`, `bdod`, `cec`.
- Depths: `0-5cm`, `5-15cm`, `15-30cm`, `30-60cm`, `60-100cm`, `100-200cm`.
- Also download the matching `_uncertainty` layer.
- **Scale factors:** pH is pH×10 and SOC is dg/kg. See the [SoilGrids FAQ](https://docs.isric.org/globaldata/soilgrids/) for the full conversion table.
- Licence: CC BY 4.0, ISRIC.

### GEO-01: NASA EMIT surface mineralogy
You need Earthdata Login (§0.4). The current version is **002**, confirmed in CMR.

```python
# scripts/fetch_emit.py   (run: uv run python -I scripts/fetch_emit.py)
import earthaccess
earthaccess.login(strategy="netrc")          # first time: strategy="interactive", persist=True
res = earthaccess.search_data(
    short_name="EMITL2BMIN", version="002",
    bounding_box=(-113.5, 31.3, -109.0, 34.5),
    temporal=("2023-01-01", "2025-12-31"),
)
print(len(res), "granules")
for g in res[:20]:
    print(g["umm"]["GranuleUR"])
earthaccess.download(res[:2], "data/raw/GEO-01/arizona")
```

How to pick scenes:

- Before downloading, preview scenes in [Earthdata Search](https://search.earthdata.nasa.gov/) (search "EMITL2BMIN") and pick 1–3 cloud-free ones over the copper-mining area (Globe–Miami, Ray, Morenci).
- Each granule comes as a mineral file plus an uncertainty file (`..._MIN_...nc` and `..._MINUNCERT_...nc`). Download both.
- Follow the [official L2B mineralogy tutorial](https://nasa.github.io/LPDAAC-Data-Resources/external/Working_with_EMIT_L2B_Mineralogy.html) for orthorectification with the GLT and for band-depth meaning.

Related collections:

| Short name | What it is |
| --- | --- |
| `EMITL3ASA` (v002) | Aggregated mineral spectral abundance; coarser, easier to start with |
| `EMITL2ARFL` (v002) | Reflectance; only needed for custom analysis |

Licence: NASA, effectively open. Cite the DOI shown on the collection page.

**Meaning:** surface spectral signature only. It is not ore grade or tonnage.

### GEO-06: USGS MRDS (mineral occurrences)
```bash
mkdir -p data/raw/GEO-06/mrds && curl -fL -o data/raw/GEO-06/mrds/mrds-csv.zip https://mrdata.usgs.gov/mrds/mrds-csv.zip
```

- Filter to the bbox or state `AZ`.
- Key fields: `dep_id`, `site_name`, `latitude`, `longitude`, `commod1`/`commod2`/`commod3`, `dev_stat`.
- MRDS is legacy data and is not current mine status. Label the record date.
- USMIN (newer US mine features) is linked from https://www.usgs.gov/programs/mineral-resources-program/mineral-resources-data
- Licence: USGS, public domain.

### LAND-05: NASA FIRMS (active fires)
1. Get a free MAP_KEY at https://firms.modaps.eosdis.nasa.gov/api/map_key/ (email only).
2. Run the request:

```bash
curl -o data/raw/LAND-05/arizona/viirs_noaa20_nrt_$(date +%F).csv "https://firms.modaps.eosdis.nasa.gov/api/area/csv/$NEWWORLDS_FIRMS_MAP_KEY/VIIRS_NOAA20_NRT/-113.5,31.3,-109.0,34.5/5"
```

- Source codes: `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `VIIRS_SNPP_NRT`, `MODIS_NRT`. For archived standard-quality data use `VIIRS_SNPP_SP` or `MODIS_SP` and add a date: `.../5/2025-07-01`.
- The day range per call is small (1–5 or 1–10). *(check on page; the limit has changed before)*
- Usage limit: about 5,000 transactions per 10 minutes.
- Keep the `confidence`, `frp` and `acq_date`/`acq_time` columns.

### NET-01: HydroRIVERS and HydroBASINS (river connectivity)
```bash
mkdir -p data/raw/NET-01 && curl -fL -o data/raw/NET-01/HydroRIVERS_v10_na_shp.zip https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_na_shp.zip && curl -fL -o data/raw/NET-01/hybas_na_lev01-12_v1c.zip https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_na_lev01-12_v1c.zip
```

- Region codes: `af ar as au eu na sa si`. The UK is in `eu`.
- Under the data-scope rule (§0.1), these continental zips are clipped to each region's **hydro box** (`data/raw/NET-01/<region>/*_hydrobox.gpkg`) and then deleted. `scripts/fetch_open_data.sh` does this for you.
- HydroRIVERS fields: `HYRIV_ID`, `NEXT_DOWN` (downstream link), `DIS_AV_CMS` (long-term mean discharge, m³/s).
- HydroBASINS fields: `HYBAS_ID`, `NEXT_DOWN`, `PFAF_ID`.
- Use **level 6** basins to join Aqueduct's `pfaf_id`.
- Licence: see https://www.hydrosheds.org/faq. Commercial use is allowed with attribution.

### CTX-03: Copernicus DEM GLO-90 (elevation)
Public AWS with no account. Tiles are 1°, named by their south-west corner. The `_30_` in the name means 3 arc-seconds (GLO-90). For GLO-30, use bucket `copernicus-dem-30m` and `_10_` instead.

```bash
mkdir -p data/raw/CTX-03/arizona/glo90 && for lat in 31 32 33 34; do for lon in 114 113 112 111 110; do n="Copernicus_DSM_COG_30_N${lat}_00_W${lon}_00_DEM"; curl -fsL -o data/raw/CTX-03/arizona/glo90/$n.tif "https://copernicus-dem-90m.s3.amazonaws.com/$n/$n.tif" || echo "missing $n"; done; done
```

Licence: Copernicus DEM GLO-90 is free with attribution. Credit text: "© DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA; all rights reserved". *(check on page: copy the exact text from the licence PDF linked in the catalogue)*

### IND-07: NESO Carbon Intensity API (Great Britain only)
No key is needed.

```bash
curl "https://api.carbonintensity.org.uk/regional" -o data/raw/IND-07/uk/regional_$(date +%FT%H%M).json
```

```bash
curl "https://api.carbonintensity.org.uk/intensity/2025-10-01T00:00Z/2025-10-14T23:30Z" -o data/raw/IND-07/uk/intensity_2025-10-01_14.json
```

- Query date ranges in windows of 14 days or less. *(check on page)*
- Licence: CC BY 4.0, NESO.
- Only relevant if you add a UK region.

### OBS-02: Sentinel-2 L2A (one prepared scene)
The easiest route needs no account: Planetary Computer STAC.

```python
import pystac_client, planetary_computer
cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                modifier=planetary_computer.sign_inplace)
items = cat.search(collections=["sentinel-2-l2a"], bbox=[-111.2, 33.2, -110.8, 33.5],
                   datetime="2025-04-01/2025-06-30", query={"eo:cloud_cover": {"lt": 5}}).item_collection()
# download only the bands you need (e.g. B04, B08, SCL) from items[0].assets[...].href
```

- The CDSE route is the alternative: https://browser.dataspace.copernicus.eu → log in → draw an area → filter Sentinel-2 L2A → download.
- Keep the box small. A full scene is about 1 GB.
- Licence: Sentinel. Credit "Contains modified Copernicus Sentinel data [year]".

### OBS-04: Landsat Collection 2 Level-2 (historical comparison)
- Use the same Planetary Computer code with `collections=["landsat-c2-l2"]`.
- Alternatively, use https://earthexplorer.usgs.gov/ (USGS account) → Landsat → Collection 2 Level-2.
- Apply the scale factors: SR × 0.0000275 − 0.2, and ST × 0.00341802 + 149.0 K.

### AIR-01: Sentinel-5P TROPOMI NO₂ (one gas layer)
- Easiest with Earthdata Login: GES DISC hosts it as `S5P_L2__NO2____HiR` (v2, confirmed in CMR). Use the same `earthaccess.search_data(short_name="S5P_L2__NO2____HiR", bounding_box=..., temporal=("2025-07-01","2025-07-07"))` pattern.
- Each orbit file is about 400–500 MB global, so take only a few days.
- Alternative: Copernicus Browser (CDSE) → Sentinel-5P → NO₂.
- Filter pixels to `qa_value > 0.75`.
- **Meaning:** tropospheric vertical column (mol/m²), not ground-level concentration.

### GEO-08: BGS geology (UK subset only)
1. Open https://www.bgs.ac.uk/geological-data/opengeoscience/map-data-downloads/
2. Download **BGS Geology 625k (DiGMapGB-625)** as a shapefile. It is OGL.
3. Only use products listed on that page. Other BGS products are paid licences.

### WATER-05: Environment Agency water quality (England only)
1. Open https://environment.data.gov.uk/water-quality/view/landing
2. Use the explorer's download for a chosen area, year and determinand set (CSV).
3. The API changed in 2025, so confirm the current API version on https://www.api.gov.uk/ea/water-quality/ before scripting. *(check on page)*
4. Coordinates may be British National Grid (EPSG:27700), in metres. Reproject them.
5. Licence: OGL.

---

## 4. P2 sources (later; quick routes)

These are mostly global or large rasters. Only fetch a bounded subset.

### NASA collections via `earthaccess`
These all use the same pattern as EMIT: Earthdata Login, then `search_data(short_name=..., bounding_box=BBOX, temporal=...)`.

| ID | Product | Short name (confirmed in CMR) | Notes |
| --- | --- | --- | --- |
| WATER-01 | SMAP enhanced soil moisture, 9 km daily | `SPL3SMP_E` v006 | NSIDC; HDF5; AM/PM retrievals |
| WATER-02 | GRACE-FO mascons | `TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4` | Monthly water-storage anomaly; very coarse |
| WATER-02 | GRACE data-assimilation groundwater/soil moisture | `GRACEDADM_CLSM025GL_7D` v3.0 | Weekly, 0.25°, GES DISC |
| WATER-03 | SWOT 100 m water raster | `SWOT_L2_HR_Raster_100m_D` (or `_2.0`) | Inland water elevation/extent |
| OBS-05 | ECOSTRESS land-surface temperature, tiled 70 m | `ECO_L2T_LSTE` v002 (v003 also listed) | Intermittent ISS passes |
| OBS-06 | MODIS NDVI, monthly 1 km | `MOD13A3` v061 | LP DAAC; HDF4 |
| GEO-04 | ASTER on-demand surface kinetic temperature | `AST_07XT` v004 | Geological indices need SWIR (pre-2008 only) |
| OCEAN-01 | PACE OCI Level-3 biogeochemistry (chlorophyll) | `PACE_OCI_L3M_BGC` v3.2 | Or use https://oceandata.sci.gsfc.nasa.gov/ |
| LAND-04 | GEDI gridded above-ground biomass | `GEDI_L4B_Gridded_Biomass_V2_1_2299` v2.1 | ORNL DAAC, 1 km |

### Copernicus Climate and Atmosphere Data Stores (ERA5-Land, CAMS)
1. Log in at https://cds.climate.copernicus.eu.
2. Open the dataset page, go to the **Download** tab, and **accept the licence** at the bottom (required once per dataset).
3. Copy your API token from your profile into `~/.cdsapirc`:

   ```
   url: https://cds.climate.copernicus.eu/api
   key: <your-token>
   ```

4. **CTX-01 ERA5-Land:** use dataset `reanalysis-era5-land-monthly-means` with:
   - `product_type: monthly_averaged_reanalysis`
   - variables `2m_temperature`, `total_precipitation`
   - `area: [34.5, -113.5, 31.3, -109.0]` (order is N, W, S, E)
   - `data_format: netcdf`

   Easiest: fill the web form and copy the "API request" code it generates.
5. **AIR-02 CAMS:** same process at https://ads.atmosphere.copernicus.eu (API URL `https://ads.atmosphere.copernicus.eu/api`). Dataset: `cams-global-reanalysis-eac4-monthly`.
6. Licence: CC BY 4.0 since July 2025.

### Other P2 sources

| ID | Source | Route |
| --- | --- | --- |
| OBS-01 | Sentinel-1 | Planetary Computer `sentinel-1-rtc` (analysis-ready backscatter) or CDSE Browser. Processing required; skip for the hackathon. |
| OBS-03 | Sentinel-3 | CDSE Browser → Sentinel-3 → choose instrument (OLCI/SLSTR) product. |
| OCEAN-02 | Copernicus Marine | `copernicusmarine login`, then `copernicusmarine subset --dataset-id <ID from catalogue "Data access" panel> --variable <var> --minimum-longitude … --maximum-longitude … --minimum-latitude … --maximum-latitude … --start-datetime … --end-datetime … --minimum-depth 0 --maximum-depth 10 -o data/raw/OCEAN-02/uk` using the uk box. Arizona is inland, so this is UK only. |
| OCEAN-03 | EMODnet | https://emodnet.ec.europa.eu/en/emodnet-themes → theme → download or WFS. European seas only. |
| LAND-01 | Copernicus Land (CLMS) | https://land.copernicus.eu/en/products → product → download (CLMS account) or via CDSE. |
| LAND-03 | ESA WorldCereal 2021 | https://zenodo.org/records/7875105: zips by product and agro-ecological zone. CC BY 4.0. |
| CTX-04 | WorldPop | https://hub.worldpop.org/ → Population Counts → choose the latest global release → country → year. Prefer the **1 km** version; the US 100 m file is several GB. |
| CTX-05 | GHSL | https://human-settlement.emergency.copernicus.eu/download.php → GHS-POP or GHS-BUILT-S, R2023A, WGS84 30″ tile. Pick GHSL **or** WorldPop for population, not both. |
| GEO-02 | EnMAP | https://www.enmap.org/data_access/ → EOWEB registration. Raw data cannot be redistributed publicly. |
| GEO-05 | USGS Spectral Library v7 | https://www.usgs.gov/data/usgs-spectral-library-version-7-data → zip. Reference spectra, not a map. |
| GEO-07 | USGS National Geochemical Database / CMiO | https://www.usgs.gov/centers/gggsc/science/national-geochemical-database → follow data-release links (CSV). Keep units and detection limits. |
| GEO-09 | Geoscience Australia / state surveys | https://www.australiaminerals.gov.au/portals. Only relevant for an Australian region. |
| WATER-04 | US Water Quality Portal | `curl "https://www.waterqualitydata.us/wqx3/Result/search?bBox=-113.5,31.3,-109.0,34.5&characteristicName=Nitrate&startDateLo=01-01-2023&mimeType=csv&dataProfile=basicPhysChem" -o data/raw/WATER-04/arizona/nitrate_2023plus.csv` (tested on a small box). Use the WQX3 endpoint; legacy WQX 2.2 misses USGS data after March 2024. Non-detects are not zero. |
| IND-02 | US EPA TRI | https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present → choose the latest year, then the state (AZ) → CSV. |
| IND-04 | UK NSTA wells | https://www.data.gov.uk/dataset/37538d3f-c320-4153-ad72-3768a2f6be12/oga-wells-wgs84 → GeoJSON/CSV. OGL. UK offshore only. |
| AIR-03 | IASI / AERIS | https://iasi.aeris-data.fr/ → product page → download. The data-use policy asks you to notify the investigators; resolve that before public display. |
| MAP-02 | MapTiler satellite | Create an account, make an API key restricted to your domain or localhost, and use the style URL from the MapTiler dashboard. Browser use only; no proxying. |
| ACCESS-04 | Google Earth Engine | Only if someone already has a working Cloud project. Not needed. |

---

## 5. GATED sources (do not fetch for the demo)

These need permission or a contract before public display. Note them in the source registry as `unresolved`. Do not download them into the demo.

| ID | Source | What is blocking |
| --- | --- | --- |
| GEO-03 | PRISMA (ASI) | Commercial use requires a qualifying access group; registration at https://prisma.asi.it/ |
| AIR-04 | Carbon Mapper | Non-commercial emissions-purpose terms; separate agreement for commercial use |
| IND-03 | EA Pollution Inventory | EA Conditional Licence, not OGL; onward-sharing terms need review |
| IND-05 | UN Comtrade | Redistribution restricted; needs an API subscription and permission |
| IND-06 | Global Fishing Watch | CC BY-NC 4.0: non-commercial only |
| COM-01 | Planet | Paid contract |
| COM-02 | Pixxel | Paid contract |

---

## 6. After downloading: quick sanity checks

Run these for every source before writing an adapter (catalogue §19):

- [ ] `gdalinfo <file>` / `ogrinfo -so <file>` / `ncdump -h <file>`: check the CRS, nodata value, scale/offset and units.
- [ ] Coordinates fall inside the bbox. Check that lon/lat are not swapped and that units are not metres.
- [ ] Missing values are recognised as nodata, not 0.
- [ ] `source.json` is filled in, including licence, attribution text, version and retrieval date.
- [ ] Note the date the data describes, which is not the date you downloaded it.

---

## 7. Moon data (`MOON-*` sources)

The Moon catalogue is [CLAUDE-Moon-Data-Sources.md](../CLAUDE-Moon-Data-Sources.md). The same rules apply: every layer has provenance, missing values are null (never 0), and approximate positions are flagged.

**Where it lives**

- `data/raw/MOON-<ID>/`: downloads (gitignored) plus a committed `source.json` with URL, redirect target, retrieval time, size, sha256, licence and credit.
- `data/prepared/moon/`: what the backend serves under `/api/moon`.
  - `source.json`: manifest of sources and layers.
  - `sites/anthropogenic_objects.geojson`: landers, rovers, impacts, retroreflectors, with heritage keep-out class.
  - `places/gazetteer.json`: IAU names.
  - `regions/mare.geojson`: mare outlines.
  - `missions/planned.geojson`: planned missions and Artemis candidate regions.
  - `h3/`: H3 layers. `layers.json` is committed; the Parquet files are gitignored.
- Frame: IAU_2015:30100 Moon Mean-Earth, R = 1737.4 km, planetocentric, longitudes normalised to [-180, 180).
- The Moon is prepared globally. The Earth `arizona` / `uk` region rule does not apply (catalogue §2.4).

**Regenerate**

```bash
(cd backend && uv run --with pyshp python ../scripts/moon/prepare_moon_reference.py)   # add --refresh to re-download
(cd backend && uv run python ../scripts/moon/prepare_moon_elevation.py)                # LOLA elevation H3 layer (MOON-TOPO-02)
```

Run the block from the repo root; each line runs in a subshell, so the shell stays where it was. `pyshp` is pulled in for that one run; it is not a backend dependency. Downloads are cached in `data/raw/`, so a re-run without `--refresh` works offline.

**Gotchas the reference script handles**

- **LROC `DATE`:** documented as the arrival date, but it holds the launch date for the Luna 16–24 landers and rovers and for Surveyor 1. Each of those rows gets a `dateNote` with the NASA NSSDCA landing date (Luna 23's comes from its NSSDCA Master Catalog entry, because the Soviet-missions page lists only its launch). The script prints a warning if a launch-dated row has no NSSDCA landing date.
- **LROC `RADIUS`:** distance from the Moon's centre in metres. `elevationM = RADIUS − 1 737 400`.
- **Gazetteer `center_lon`:** 0–360, converted to ±180. A diameter of 0 means "unknown" and becomes null.
- **Mare DBF:** lost its diacritics (`Chrtien`, `Von Krmn`); names are restored to IAU spelling. 7 self-intersecting polygons are repaired.
