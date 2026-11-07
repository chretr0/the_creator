"""Fetch ERA5-Land monthly means (CTX-01, Climate Data Store) and CAMS EAC4 monthly means
(AIR-02, Atmosphere Data Store) for each project region (data/README.md "Data scope").

Run from the repo root:
  uv run --no-project --with 'cdsapi>=0.7.4' python -I scripts/fetch_copernicus_cds.py [arizona uk] [--year 2024]

Credentials: one ECMWF personal access token in ~/.cdsapirc (`key: ...`). The same token works on
both stores, so the store URL is set per dataset here and the `url:` line in the file is ignored.
The token is read from the file and passed to the client only; it is never printed or written.
Each dataset's licence must have been accepted once on its web page (Download tab), or the
request fails with a "required licences not accepted" message.
"""
import argparse
import os
import sys

import cdsapi

REGIONS = {  # W, S, E, N — must match scripts/fetch_open_data.sh
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
CDS = "https://cds.climate.copernicus.eu/api"
ADS = "https://ads.atmosphere.copernicus.eu/api"


def token():
    with open(os.path.expanduser("~/.cdsapirc")) as f:
        for line in f:
            if line.strip().startswith("key:"):
                return line.split(":", 1)[1].strip()
    sys.exit("no `key:` line in ~/.cdsapirc")


def jobs(year):
    months = [f"{m:02d}" for m in range(1, 13)]
    yield ("CTX-01", CDS, "reanalysis-era5-land-monthly-means", f"era5land_monthly_{year}.nc", {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["2m_temperature", "2m_dewpoint_temperature", "total_precipitation", "total_evaporation",
                     "surface_solar_radiation_downwards", "10m_u_component_of_wind", "10m_v_component_of_wind",
                     "volumetric_soil_water_layer_1"],
        "year": [str(year)], "month": months, "time": ["00:00"],
        "data_format": "netcdf", "download_format": "unarchived",
    })
    yield ("AIR-02", ADS, "cams-global-reanalysis-eac4-monthly", f"cams_eac4_monthly_{year}.nc", {
        "product_type": ["monthly_mean"],
        "variable": ["particulate_matter_2.5um", "particulate_matter_10um", "total_column_nitrogen_dioxide",
                     "total_column_sulphur_dioxide", "total_column_carbon_monoxide", "total_aerosol_optical_depth_550nm"],
        "year": [str(year)], "month": months,
        "data_format": "netcdf", "download_format": "unarchived",
    })


ap = argparse.ArgumentParser()
ap.add_argument("regions", nargs="*", default=list(REGIONS))
ap.add_argument("--year", type=int, default=2024)
ap.add_argument("--root", default="data/raw")
a = ap.parse_args()

key = token()
clients = {}
failed = 0
for sid, url, dataset, fname, req in jobs(a.year):
    for region in a.regions:
        w, s, e, n = REGIONS[region]
        dest = os.path.join(a.root, sid, region, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print("skip", dest); continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        client = clients.setdefault(url, cdsapi.Client(url=url, key=key, quiet=True, progress=False))
        try:
            client.retrieve(dataset, req | {"area": [n, w, s, e]}, dest + ".part")
            os.replace(dest + ".part", dest)
            print(f"ok   {dest} ({os.path.getsize(dest)/1e6:.1f} MB)")
        except Exception as ex:  # report the API's message (licence not accepted, bad variable, ...)
            failed += 1
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            msg = str(ex).replace(key, "***")
            print(f"FAIL {sid} {region} {dataset}: {msg[:400]}")
sys.exit(1 if failed else 0)
