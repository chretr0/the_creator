#!/usr/bin/env bash
# Downloads every source that needs no account or form, for the project's data regions.
#
# Data scope (see data/README.md "Data scope"):
#   * Regions: arizona (demo) and uk (whole United Kingdom). Regional data lives in data/raw/<ID>/<region>/.
#   * BIG datasets (> ~100 MB as a global file) are kept for these regions only, never globally.
#     Global-only downloads are clipped and the global file is deleted (an existing global copy from an
#     earlier run is clipped in place and left as it is).
#   * Hydrology uses a wider "hydro box" per region so upstream rivers/basins stay connected.
#   * Small global files (< ~100 MB) are kept whole.
#
# Usage (from the repo root):  scripts/fetch_open_data.sh [region ...] [--root data/raw]
#   default regions: arizona uk.  Re-runnable: existing non-empty files are skipped.
set -uo pipefail

ROOT=data/raw
REGIONS=()
while [[ $# -gt 0 ]]; do
  case "$1" in --root) ROOT="$2"; shift 2;; *) REGIONS+=("$1"); shift;; esac
done
[[ ${#REGIONS[@]} -eq 0 ]] && REGIONS=(arizona uk)

UA="NewWorlds-hackathon-data-fetch/0.1"
TMP="$ROOT/_global_tmp"            # global files fetched only to be clipped; deleted after clipping
CLIP=(uv run --quiet --no-project --with rasterio --with pyogrio --with geopandas --with duckdb python -I scripts/clip_to_bbox.py)

# ---------------------------------------------------------------------------------------------
# Region definitions. BBOX/HYDRO are W,S,E,N in WGS84 degrees.
# ---------------------------------------------------------------------------------------------
region_vars() {
  case "$1" in
    arizona)
      BBOX="-113.5,31.3,-109.0,34.5"          # central/southern Arizona demo box (incl. a strip of Sonora)
      HYDRO="-119.0,28.0,-105.0,44.0"         # Colorado + Gila + Sonora basins upstream of the box
      HYDROSHEDS=na                            # HydroSHEDS continental file
      WC_TILES="N30W114 N30W111 N33W114 N33W111"
      DEM_LAT="31 32 33 34"; DEM_LON="-114 -113 -112 -111 -110"
      POWER_LAT="31.5 32.5 33.5 34.5"; POWER_LON="-113.5 -112.5 -111.5 -110.5 -109.5"
      FIRMS_COUNTRIES="United_States Mexico"
      ;;
    uk)
      BBOX="-8.7,49.8,1.9,60.9"               # England, Wales, Scotland (incl. Shetland), Northern Ireland
      HYDRO="-10.7,49.8,1.9,60.9"             # + rest of the island of Ireland (rivers crossing into NI)
      HYDROSHEDS=eu
      WC_TILES="N48W009 N48W006 N48W003 N48E000 N51W009 N51W006 N51W003 N51E000 N54W009 N54W006 N54W003 N54E000 N57W009 N57W006 N57W003 N57E000 N60W003 N60E000"
      DEM_LAT="49 50 51 52 53 54 55 56 57 58 59 60"; DEM_LON="-9 -8 -7 -6 -5 -4 -3 -2 -1 0 1"
      POWER_LAT="50.5 51.5 52.5 53.5 54.5 55.5 56.5 57.5 58.5 59.5 60.5"; POWER_LON="-8.5 -7.5 -6.5 -5.5 -4.5 -3.5 -2.5 -1.5 -0.5 0.5 1.5"
      FIRMS_COUNTRIES="United_Kingdom"
      ;;
    *) echo "unknown region $1" >&2; return 1;;
  esac
}

get() { # get <url> <dest> [optional]   ("optional": a 404 just means no tile there, e.g. open sea)
  local url="$1" dest="$2" opt="${3:-}"
  mkdir -p "$(dirname "$dest")"
  if [[ -s "$dest" ]]; then echo "skip  $dest"; return 0; fi
  local code
  code=$(curl -sSL -A "$UA" --retry 3 --retry-delay 5 --max-time 3600 -o "$dest.part" -w "%{http_code}" "$url")
  if [[ "$code" == 200 ]]; then
    mv "$dest.part" "$dest"; echo "ok    $dest ($(du -h "$dest" | cut -f1))"
  else
    rm -f "$dest.part"
    if [[ -n "$opt" && "$code" == 404 ]]; then echo "none  $dest (no tile)"; else echo "FAIL  $url (HTTP $code)" >&2; fi
  fi
}

# clipped <kind> <dst> <bbox> <url> <inner-in-download> <legacy-file> <inner-in-legacy> [clip args...]
# Writes a regional subset to <dst>. If a global copy from an earlier run exists at <legacy-file>, it is
# clipped in place and left untouched; otherwise <url> is downloaded to $TMP, clipped, and deleted.
# <inner-*> is a path inside a zip, or "".
clipped() {
  local kind="$1" dst="$2" bbox="$3" url="$4" inner_dl="$5" legacy="$6" inner_legacy="$7"; shift 7
  if [[ -s "$dst" ]]; then echo "skip  $dst"; return 0; fi
  local src inner tmp=""
  if [[ -n "$legacy" && -s "$legacy" ]]; then src="$legacy"; inner="$inner_legacy"
  else tmp="$TMP/$(basename "${url%%\?*}")"; get "$url" "$tmp"; src="$tmp"; inner="$inner_dl"; fi
  if [[ ! -s "$src" ]]; then echo "FAIL  no source for $dst" >&2; return 0; fi
  local path="$src"; [[ -n "$inner" ]] && path="/vsizip/$src/$inner"
  mkdir -p "$(dirname "$dst")"
  local err; if err=$("${CLIP[@]}" "$kind" "$path" "$dst" --bbox "$bbox" "$@" 2>&1 >/dev/null); then
    echo "ok    $dst ($(du -h "$dst" | cut -f1), clipped from ${legacy:+existing }$(basename "$src"))"
  else
    rm -f "$dst"; echo "FAIL  clip $dst: $(echo "$err" | tail -1)" >&2
  fi
  [[ -n "$tmp" ]] && rm -f "$tmp"
  return 0
}

# ---------------------------------------------------------------------------------------------
# Small global files (< ~100 MB): kept whole, fetched once
# ---------------------------------------------------------------------------------------------
get https://mrdata.usgs.gov/mrds/mrds-csv.zip "$ROOT/GEO-06/mrds/mrds-csv.zip"

# ---------------------------------------------------------------------------------------------
# Per-region data
# ---------------------------------------------------------------------------------------------
for R in "${REGIONS[@]}"; do
  region_vars "$R" || continue
  echo "===== region: $R  bbox $BBOX  hydro $HYDRO"
  IFS=, read -r W S E N <<<"$BBOX"

  # WATER-06 Aqueduct 4.0 (262 MB global-only zip) -> basins intersecting the region
  AQ_IN=Aqueduct40_waterrisk_download_Y2023M07D05/GDB/Aq40_Y2023D07M05.gdb
  clipped vector "$ROOT/WATER-06/$R/aqueduct40_$R.gpkg" "$BBOX" \
    https://files.wri.org/aqueduct/aqueduct-4-0-water-risk-data.zip "$AQ_IN" \
    "$ROOT/WATER-06/aqueduct40/aqueduct-4-0-water-risk-data.zip" "$AQ_IN"

  # NET-01 HydroRIVERS + HydroBASINS levels 1-12, clipped to the hydro box (keeps upstream links)
  clipped vector "$ROOT/NET-01/$R/HydroRIVERS_v10_${R}_hydrobox.gpkg" "$HYDRO" \
    "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_${HYDROSHEDS}_shp.zip" "HydroRIVERS_v10_${HYDROSHEDS}_shp/HydroRIVERS_v10_${HYDROSHEDS}.shp" \
    "$ROOT/NET-01/HydroRIVERS_v10_shp.zip" HydroRIVERS_v10_shp/HydroRIVERS_v10.shp
  for lev in 01 02 03 04 05 06 07 08 09 10 11 12; do
    z="hybas_${HYDROSHEDS}_lev01-12_v1c.zip"
    clipped vector "$ROOT/NET-01/$R/hybas_${HYDROSHEDS}_lev${lev}_v1c_${R}_hydrobox.gpkg" "$HYDRO" \
      "https://data.hydrosheds.org/file/HydroBASINS/standard/$z" "hybas_${HYDROSHEDS}_lev${lev}_v1c.shp" \
      "$ROOT/NET-01/$z" "hybas_${HYDROSHEDS}_lev${lev}_v1c.shp"
  done

  # CTX-05 GHSL population + built-up surface 2025, 30 arcsec (global-only zips, 484 + 188 MB)
  GHSL=https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL
  for p in POP BUILT_S; do
    f="GHS_${p}_E2025_GLOBE_R2023A_4326_30ss_V1_0"
    clipped raster "$ROOT/CTX-05/$R/${f}_$R.tif" "$BBOX" \
      "$GHSL/GHS_${p}_GLOBE_R2023A/GHS_${p}_E2025_GLOBE_R2023A_4326_30ss/V1-0/$f.zip" "$f.tif" \
      "$ROOT/CTX-05/$f.zip" "$f.tif"
  done

  # CTX-04 WorldPop R2025A 2025 1 km constrained (289 MB global mosaic)
  WP=global_pop_2025_CN_1km_R2025A_v1.tif
  clipped raster "$ROOT/CTX-04/$R/worldpop_2025_1km_$R.tif" "$BBOX" \
    "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/0_Mosaicked/v1/1km/constrained/$WP" "" \
    "$ROOT/CTX-04/worldpop_R2025A_1km/$WP" ""

  # LAND-05 FIRMS 2024 VIIRS S-NPP archive: per-country CSVs -> points in the region box
  for c in $FIRMS_COUNTRIES; do
    clipped points "$ROOT/LAND-05/$R/viirs-snpp_2024_${c}_$R.csv" "$BBOX" \
      "https://firms.modaps.eosdis.nasa.gov/data/country/viirs-snpp/2024/viirs-snpp_2024_${c}.csv" "" \
      "$ROOT/LAND-05/archive_2024/unzipped/viirs-snpp/2024/viirs-snpp_2024_${c}.csv" ""
  done

  # LAND-02 ESA WorldCover 2021 v200 (3° tiles named by SW corner; sea-only tiles do not exist)
  for t in $WC_TILES; do
    f="ESA_WorldCover_10m_2021_v200_${t}_Map.tif"
    get "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/$f" "$ROOT/LAND-02/$R/v200_2021/$f" optional
  done

  # CTX-03 Copernicus DEM GLO-90 (1° tiles named by SW corner; sea-only tiles do not exist)
  for lat in $DEM_LAT; do for lon in $DEM_LON; do
    if (( lon < 0 )); then ew=$(printf "W%03d" $(( -lon ))); else ew=$(printf "E%03d" "$lon"); fi
    n="Copernicus_DSM_COG_30_N${lat}_00_${ew}_00_DEM"
    get "https://copernicus-dem-90m.s3.amazonaws.com/$n/$n.tif" "$ROOT/CTX-03/$R/glo90/$n.tif" optional
  done; done

  # SOIL-01 SoilGrids 250 m (6 variables x 2 depths, mean + uncertainty), windowed reads from ISRIC VRTs
  uv run --quiet --no-project --with rasterio python -I scripts/fetch_soilgrids.py "$ROOT/SOIL-01/$R/soilgrids_v2" "$BBOX" | grep -v '^skip'

  # CTX-02 NASA POWER API points at 1° solar-grid centres
  for lat in $POWER_LAT; do for lon in $POWER_LON; do
    c="$ROOT/CTX-02/$R/climatology/${lat}_${lon}.json"; m="$ROOT/CTX-02/$R/monthly_2024/${lat}_${lon}.json"
    [[ -s "$c" && -s "$m" ]] && continue
    get "https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=ALLSKY_SFC_SW_DWN,CLRSKY_SFC_SW_DWN,T2M,T2M_MAX,WS10M,PRECTOTCORR&community=RE&longitude=$lon&latitude=$lat&format=JSON" "$c"
    get "https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=ALLSKY_SFC_SW_DWN,T2M,PRECTOTCORR&community=RE&longitude=$lon&latitude=$lat&start=2024&end=2024&format=JSON" "$m"
    sleep 1
  done; done

  # ---- Region-specific sources ----
  if [[ "$R" == arizona ]]; then
    # WATER-04 US Water Quality Portal (WQX3)
    for c in Nitrate Arsenic "Total dissolved solids"; do
      slug=$(echo "$c" | tr ' A-Z' '_a-z')
      get "https://www.waterqualitydata.us/wqx3/Result/search?bBox=$W,$S,$E,$N&characteristicName=$(echo "$c" | sed 's/ /%20/g')&startDateLo=01-01-2020&mimeType=csv&dataProfile=basicPhysChem" \
          "$ROOT/WATER-04/$R/wqx3_${slug}_2020plus.csv"
    done
    # IND-02 EPA Toxics Release Inventory (Arizona state files)
    for y in 2024 2023; do
      get "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/${y}_AZ/csv" "$ROOT/IND-02/$R/tri_basic_${y}_AZ.csv"
    done
  fi
  if [[ "$R" == uk ]]; then
    # IND-07 NESO carbon intensity (Great Britain; NI is not covered by NESO)
    get https://api.carbonintensity.org.uk/regional "$ROOT/IND-07/$R/regional_$(date -u +%Y%m%dT%H00).json"
    get "https://api.carbonintensity.org.uk/intensity/2025-10-01T00:00Z/2025-10-14T23:30Z" "$ROOT/IND-07/$R/intensity_2025-10-01_14.json"
    get "https://api.carbonintensity.org.uk/generation/2025-10-01T00:00Z/2025-10-14T23:30Z" "$ROOT/IND-07/$R/generation_2025-10-01_14.json"
    # IND-04 NSTA offshore wellbores: whole UKCS, small (scripts/fetch_nsta_wells.py) - fetched separately
  fi
done
rmdir "$TMP" 2>/dev/null || true
echo "done."
