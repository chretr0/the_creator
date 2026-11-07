# Data you need to get by hand

Everything that works without an account or form has been downloaded, for both regions, by `scripts/fetch_open_data.sh` (which also calls `scripts/fetch_soilgrids.py`) and `scripts/fetch_imagery.py` (Arizona scene only) (see [STATUS.md](./STATUS.md)). The items below need a login, a form, a licence acceptance or an emailed key, so a person has to do them. Full routes are in [README.md](./README.md).

**Data scope:** big datasets are kept for the `arizona` and `uk` regions only (README §0.1). Save manual downloads to `data/raw/<ID>/<region>/`. Use the region boxes:
- arizona: `-113.5,31.3,-109.0,34.5`
- uk: `-8.7,49.8,1.9,60.9`

Order = demo value. Do 1–4 first.

| # | ID | What | Why it is manual | Exactly what to do | Save to |
| --- | --- | --- | --- | --- | --- |
| 1 | — | **NASA Earthdata Login** | Account | Register at https://urs.earthdata.nasa.gov/users/new, confirm the email. Then add it to `~/.netrc`: `printf 'machine urs.earthdata.nasa.gov login USER password PASS\n' >> ~/.netrc && chmod 600 ~/.netrc`. After this, tell Claude and it can script items 2, 6 and 7 itself. | — |
| 2 | GEO-01 | **EMIT minerals** (`EMITL2BMIN` v002) | Needs Earthdata | Once item 1 is done: in https://search.earthdata.nasa.gov search `EMITL2BMIN`, draw the Arizona box, pick 1–3 low-cloud scenes over Globe–Miami / Ray / Morenci, and download both the `_MIN_` and `_MINUNCERT_` `.nc` files. Or run the `earthaccess` snippet in README §3. **Arizona only:** EMIT mineral maps are not useful over the vegetated, cloudy UK. | `data/raw/GEO-01/arizona/` |
| 3 | IND-01 | **GEM Global Integrated Power Tracker** | Form (name and email) | https://globalenergymonitor.org/download-data → fill in the form → choose *Global Integrated Power Tracker* → save the `.xlsx` (keep the file name; it contains the release date). It is a single global workbook of about 30–60 MB (under the size rule), so keep it whole. | `data/raw/IND-01/<release>/` |
| 4 | LAND-05 | **FIRMS MAP_KEY** | Emailed key | Request it at https://firms.modaps.eosdis.nasa.gov/api/map_key/ and put it in `backend/.env` as `NEWWORLDS_FIRMS_MAP_KEY=...`. Claude can then run the fetch for both region boxes. (The 2024 archive is already clipped for both regions without a key.) | `backend/.env` |
| 5 | AIR-01 | Sentinel-5P NO₂ (`S5P_L2__NO2____HiR`) | Needs Earthdata | Same as item 2, for 3–7 days. Each orbit file is global (about 450 MB), so clip each one to the region boxes and delete the original. | `data/raw/AIR-01/<region>/` |
| 6 | WATER-01, OBS-05, OBS-06, WATER-02/03, OCEAN-01, LAND-04, GEO-04 | Other NASA collections | Needs Earthdata | Scriptable once item 1 is done. Short names are in README §4. Use the region boxes as `bounding_box`. | `data/raw/<ID>/<region>/` |
| 7 | CTX-01 | ERA5-Land monthly | ECMWF account and licence click | Register at https://cds.climate.copernicus.eu. Open *ERA5-Land monthly averaged data* → Download tab → tick the licence. Copy your token into `~/.cdsapirc` (`url: https://cds.climate.copernicus.eu/api` / `key: …`). Request `area` = each region box. | `data/raw/CTX-01/<region>/` |
| 8 | AIR-02 | CAMS EAC4 monthly | Same ECMWF account and licence click | Accept the licence on https://ads.atmosphere.copernicus.eu for `cams-global-reanalysis-eac4-monthly`. Request `area` = each region box. | `data/raw/AIR-02/<region>/` |
| 9 | OCEAN-02 | Copernicus Marine | Account | Register at https://data.marine.copernicus.eu/register, then run `copernicusmarine login`. UK seas only; not useful for inland Arizona. | `data/raw/OCEAN-02/uk/` |
| 10 | ACCESS-02 | Copernicus Data Space | Account | Only needed for Sentinel-1/3 or CDSE-only products. Sentinel-2, Landsat and the DEM were fetched without it. | — |
| 11 | MAP-02 | MapTiler satellite basemap (optional) | Account and API key | Create a key restricted to `localhost` / your domain at https://cloud.maptiler.com. | `frontend/.env.local` |
| 12 | GEO-08 | **BGS Geology 625k** (UK) | The download page is a web form | https://www.bgs.ac.uk/download/bgs-geology-625k-digmapgb/ → complete the form → download the shapefile/GeoPackage. OGL; credit BGS © UKRI. Small, so keep it whole. | `data/raw/GEO-08/uk/` |
| 12a | WATER-05 | **Environment Agency water quality** (England) | The 2025 API moved; its new address isn't documented and the old routes return 404 | https://environment.data.gov.uk/water-quality/view/landing → choose area, years and determinands → download CSV. Coordinates may be British National Grid (EPSG:27700). OGL. | `data/raw/WATER-05/uk/` |
| 12b | GEO-05 | USGS Spectral Library v7 (ASCII) | ScienceBase and usgs.gov block scripted downloads (Cloudflare/CloudFront 403) | Open https://www.sciencebase.gov/catalog/item/5807a2a2e4b0841e59e3a18d in a browser and download `ASCIIdata_splib07a.zip` (~21 MB). | `data/raw/GEO-05/` |
| 13 | GEO-02 | EnMAP | Registration, redistribution limits | Skip for the demo. | — |
| 14 | AIR-03 | IASI NH₃ | Data policy asks you to notify the investigators | Skip until that is resolved. | — |

## Gated: do not download for the demo

PRISMA (GEO-03), Carbon Mapper (AIR-04), EA Pollution Inventory (IND-03), UN Comtrade (IND-05), Global Fishing Watch (IND-06, non-commercial only), Planet (COM-01) and Pixxel (COM-02). Each needs a contract or explicit permission before public display. See [CLAUDE-Data-Sources.md](../CLAUDE-Data-Sources.md) §5–§13.

## After each manual download

Fill in `data/raw/<ID>/<region>/source.json` (template in README §0.3, plus `"region"`). Record the exact URL, file name, version, licence and attribution, and the retrieval date.
