"""Write provenance records for the automatically fetched sources:
  data/raw/<ID>/<region>/source.json  for regional subsets (arizona, uk)
  data/raw/<ID>/source.json           for global copies kept from the first run (GLOBAL_TOP)

Run: python3 -I scripts/write_source_records.py data/raw
Licence/attribution text comes from the catalogue (CLAUDE-Data-Sources.md) and provider pages;
verify against the actual release before publishing. Files are hashed (sha256) as found on disk.
"""
import hashlib
import json
import os
import sys
from datetime import date

ROOT = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
BBOX = "W -113.5, S 31.3, E -109.0, N 34.5 (WGS84)"
CC_BY = {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}

RECORDS = {
    "WATER-06": dict(provider="World Resources Institute", product="Aqueduct 4.0 water risk data", version="4.0",
        documentationUrl="https://www.wri.org/data/aqueduct-global-maps-40-data",
        accessUrl="https://files.wri.org/aqueduct/aqueduct-4-0-water-risk-data.zip", accessMethod="download",
        evidenceType="modelled", query="global",
        licence=CC_BY | {"attribution": "Kuzma, S. et al. 2023. Aqueduct 4.0: Updated decision-relevant global water risk indicators. WRI. (verify citation on download page)"}),
    "GEO-06": dict(provider="U.S. Geological Survey", product="Mineral Resources Data System (MRDS)", version="as downloaded (legacy, not maintained)",
        documentationUrl="https://mrdata.usgs.gov/mrds/", accessUrl="https://mrdata.usgs.gov/mrds/mrds-csv.zip",
        accessMethod="download", evidenceType="reported", query="global",
        licence={"name": "U.S. public domain (USGS)", "url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
                 "attribution": "U.S. Geological Survey, Mineral Resources Data System"}),
    "NET-01": dict(provider="WWF / HydroSHEDS", product="HydroRIVERS v1.0 (global) + HydroBASINS v1c (all 8 regions, levels 1-12)", version="HydroRIVERS 1.0; HydroBASINS 1c",
        documentationUrl="https://www.hydrosheds.org/products", accessUrl="https://data.hydrosheds.org/file/", accessMethod="download",
        evidenceType="modelled", query="global",
        licence={"name": "HydroSHEDS licence agreement", "url": "https://www.hydrosheds.org/faq",
                 "attribution": "Lehner, B., Grill G. (2013) Hydrol. Process. 27(15): 2171-2186. Data at www.hydrosheds.org"}),
    "CTX-05": dict(provider="European Commission JRC", product="GHSL GHS-POP and GHS-BUILT-S, epoch 2025, 30 arcsec, WGS84", version="R2023A V1-0",
        documentationUrl="https://human-settlement.emergency.copernicus.eu/download.php",
        accessUrl="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/", accessMethod="download", evidenceType="modelled", query="global",
        licence=CC_BY | {"attribution": "Schiavina M. et al. GHS-POP R2023A; Pesaresi M., Politis P. GHS-BUILT-S R2023A. European Commission, JRC (cite product DOIs)"}),
    "LAND-02": dict(provider="ESA", product="WorldCover 10 m 2021", version="v200",
        documentationUrl="https://esa-worldcover.org/en/data-access",
        accessUrl="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/", accessMethod="download",
        evidenceType="satellite_retrieval", query=BBOX + "; tiles N30W114 N30W111 N33W114 N33W111",
        licence=CC_BY | {"attribution": "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"}),
    "CTX-03": dict(provider="ESA / Airbus (Copernicus)", product="Copernicus DEM GLO-90 (COG, AWS open data)", version="as published on copernicus-dem-90m bucket",
        documentationUrl="https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
        accessUrl="https://copernicus-dem-90m.s3.amazonaws.com/", accessMethod="download", evidenceType="satellite_retrieval", query=BBOX,
        licence={"name": "Copernicus DEM GLO-90 licence", "url": "https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf",
                 "attribution": "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved (verify exact text)"}),
    "CTX-02": dict(provider="NASA Langley POWER", product="POWER API climatology + monthly 2024 point series (RE community)", version="API v2.x (see header in each JSON)",
        documentationUrl="https://power.larc.nasa.gov/docs/services/api/", accessUrl="https://power.larc.nasa.gov/api/temporal/",
        accessMethod="api", evidenceType="modelled", query=BBOX + "; 1° grid centres (lat 31.5..34.5, lon -113.5..-109.5)",
        licence={"name": "NASA open data (verify POWER acknowledgement)", "url": "https://power.larc.nasa.gov/",
                 "attribution": "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program."}),
    "SOIL-01": dict(provider="ISRIC", product="SoilGrids 2.0 (250 m), 6 variables x 2 depths, mean + uncertainty", version="latest (2.0)",
        documentationUrl="https://docs.isric.org/globaldata/soilgrids/", accessUrl="https://files.isric.org/soilgrids/latest/data/",
        accessMethod="download", evidenceType="modelled", query=BBOX + "; native Homolosine CRS, integer-scaled",
        licence=CC_BY | {"attribution": "Poggio, L. et al. (2021) SoilGrids 2.0. SOIL 7, 217-240. ISRIC - World Soil Information"}),
    "WATER-04": dict(provider="USGS / EPA / NWQMC", product="Water Quality Portal WQX3 results (Nitrate, Arsenic, TDS since 2020)", version="WQX 3.0 beta services",
        documentationUrl="https://www.waterqualitydata.us/webservices_documentation/", accessUrl="https://www.waterqualitydata.us/wqx3/Result/search",
        accessMethod="api", evidenceType="in_situ", query=BBOX,
        licence={"name": "U.S. public domain for USGS/EPA outputs; contributor terms apply", "url": "https://www.waterqualitydata.us/",
                 "attribution": "Water Quality Portal. National Water Quality Monitoring Council, USGS, EPA. https://doi.org/10.5066/P9QRKUVJ"}),
    "IND-02": dict(provider="U.S. EPA", product="TRI basic data files (regional folders: state files, e.g. AZ; top level: all-US files from the first run)", version="reporting years 2023, 2024 (as downloaded; revisions occur)",
        documentationUrl="https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present",
        accessUrl="https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/", accessMethod="download", evidenceType="reported", query="United States",
        licence={"name": "U.S. public domain (EPA)", "url": "https://pasteur.epa.gov/license/sciencehub-license.html", "attribution": "U.S. EPA Toxics Release Inventory"}),
    "IND-07": dict(  # Great Britain only (stored under region uk)
       provider="National Energy System Operator (NESO)", product="Carbon Intensity API (regional snapshot, national intensity + generation mix 1-14 Oct 2025)", version="API v2",
        documentationUrl="https://api.carbonintensity.org.uk/", accessUrl="https://api.carbonintensity.org.uk/", accessMethod="api",
        evidenceType="modelled", query="Great Britain",
        licence=CC_BY | {"attribution": "Carbon Intensity API, National Energy System Operator (NESO), CC BY 4.0"}),
    "OBS-02": dict(provider="ESA Copernicus (via Microsoft Planetary Computer)", product="Sentinel-2 L2A, one scene clip (bands B02-B12, SCL)", version="see item.json",
        documentationUrl="https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a", accessUrl="https://planetarycomputer.microsoft.com/api/stac/v1",
        accessMethod="stac", evidenceType="satellite_retrieval", query="W -111.05 S 33.30 E -110.70 N 33.50; Apr-Jun 2025; cloud < 5%",
        licence={"name": "Copernicus Sentinel data legal notice", "url": "https://cds.climate.copernicus.eu/licences/ec-sentinel",
                 "attribution": "Contains modified Copernicus Sentinel data 2025"}),
    "OBS-04": dict(provider="USGS / NASA (via Microsoft Planetary Computer)", product="Landsat Collection 2 Level-2, one scene clip", version="Collection 2 (see item.json)",
        documentationUrl="https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2", accessUrl="https://planetarycomputer.microsoft.com/api/stac/v1",
        accessMethod="stac", evidenceType="satellite_retrieval", query="W -111.05 S 33.30 E -110.70 N 33.50; Apr-Jun 2025; cloud < 5%",
        licence={"name": "U.S. public domain (USGS)", "url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
                 "attribution": "Landsat imagery courtesy of the U.S. Geological Survey"}),
    "CTX-01": dict(provider="Copernicus Climate Change Service (C3S) / ECMWF", product="ERA5-Land monthly averaged data from 1950 to present: monthly_averaged_reanalysis 2024 (t2m, d2m, tp, e, ssrd, u10, v10, swvl1)", version="as served by the CDS (see file history attribute)",
        documentationUrl="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means", accessUrl="https://cds.climate.copernicus.eu/api",
        accessMethod="api", evidenceType="modelled",
        licence=CC_BY | {"attribution": "Muñoz Sabater, J. (2019): ERA5-Land monthly averaged data from 1950 to present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS). DOI: 10.24381/cds.68d2bb30. Contains modified Copernicus Climate Change Service information 2024."}),
    "AIR-02": dict(provider="Copernicus Atmosphere Monitoring Service (CAMS) / ECMWF", product="CAMS global reanalysis (EAC4) monthly averaged fields: monthly_mean 2024 (pm2p5, pm10, tcno2, tcso2, tcco, aod550)", version="EAC4 as served by the ADS",
        documentationUrl="https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4-monthly", accessUrl="https://ads.atmosphere.copernicus.eu/api",
        accessMethod="api", evidenceType="modelled",
        licence=CC_BY | {"attribution": "Inness et al. (2019), CAMS global reanalysis (EAC4) monthly averaged fields. Copernicus Atmosphere Monitoring Service (CAMS) Atmosphere Data Store. DOI: 10.24381/d58bbf47. Contains modified Copernicus Atmosphere Monitoring Service information 2024."}),
    "CTX-04": dict(provider="WorldPop, University of Southampton", product="Global2 R2025A population counts 2025, 1 km constrained (regional clip)", version="R2025A v1",
        documentationUrl="https://hub.worldpop.org/", accessUrl="https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/0_Mosaicked/v1/1km/constrained/",
        accessMethod="download", evidenceType="modelled",
        licence=CC_BY | {"attribution": "WorldPop (www.worldpop.org), University of Southampton. Global2 R2025A. doi:10.5258/SOTON/WP00845"}),
    "LAND-05": dict(provider="NASA FIRMS", product="VIIRS S-NPP 375 m active fire detections, 2024 annual country archive (regional clip)", version="Collection 2 (version field 2)",
        documentationUrl="https://firms.modaps.eosdis.nasa.gov/country/", accessUrl="https://firms.modaps.eosdis.nasa.gov/data/country/viirs-snpp/2024/",
        accessMethod="download", evidenceType="satellite_retrieval",
        licence={"name": "NASA open data", "url": "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies",
                 "attribution": "We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Earth Science Data and Information System (ESDIS)."}),
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


REGIONS = {  # must match scripts/fetch_open_data.sh region_vars
    "arizona": {"bbox": "-113.5,31.3,-109.0,34.5", "hydro": "-119.0,28.0,-105.0,44.0"},
    "uk": {"bbox": "-8.7,49.8,1.9,60.9", "hydro": "-10.7,49.8,1.9,60.9"},
}
# Global copies kept from the first (pre-policy) run, recorded at data/raw/<ID>/source.json.
# Only these IDs get a top-level record here; other top-level records were written by the
# global/points scripts (fetch_global_1km.py, fetch_power_global.py, write_points_sources.py).
GLOBAL_TOP = {"WATER-06", "NET-01", "CTX-05", "GEO-06", "IND-02"}
CLIPPED_FROM_GLOBAL = {"WATER-06", "NET-01", "CTX-05", "CTX-04", "LAND-05"}


def file_list(d, skip_dirs=()):
    out = []
    for dp, dns, fns in os.walk(d):
        if dp == d:
            dns[:] = [x for x in dns if x not in skip_dirs]
        for fn in sorted(fns):
            if fn == "source.json" or fn.endswith(".part"):
                continue
            p = os.path.join(dp, fn)
            out.append({"path": os.path.relpath(p, d), "bytes": os.path.getsize(p), "sha256": sha256(p)})
    return out


def write(d, rec_id, sid, meta, files, extra):
    rec = {"id": rec_id, "catalogueSourceId": sid, **meta, **extra, "retrievedAt": str(date.today()), "files": files}
    rec["licence"] = rec["licence"] | {"reviewedAt": str(date.today()),
                                       "notes": "Auto-generated from catalogue; confirm against the release's own licence before publishing."}
    with open(os.path.join(d, "source.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(f"wrote {os.path.relpath(d, ROOT)}/source.json ({len(files)} files, {sum(x['bytes'] for x in files)/1e6:.1f} MB)")


for sid, meta in RECORDS.items():
    base = os.path.join(ROOT, sid)
    if not os.path.isdir(base):
        print("missing", sid); continue
    for region, r in REGIONS.items():
        d = os.path.join(base, region)
        if not os.path.isdir(d):
            continue
        box = r["hydro"] if sid == "NET-01" else r["bbox"]
        q = f"region={region}; bbox W,S,E,N={box}" + (" (hydro box: wider than the region so upstream links stay intact)" if sid == "NET-01" else "")
        if sid in ("OBS-02", "OBS-04"):
            q = meta.get("query", q)
        extra = {"region": region, "query": q, "dataScope": "regional subset (data/README.md 'Data scope')"}
        if sid in CLIPPED_FROM_GLOBAL:
            extra["processing"] = "Clipped from the provider's global file by scripts/clip_to_bbox.py (vectors: whole features intersecting the box; rasters: native grid window; points: inside the box)."
        write(d, f"{sid}-{region}-{date.today():%Y%m%d}", sid, {k: v for k, v in meta.items() if k != "query"}, file_list(d), extra)
    if sid in GLOBAL_TOP:
        files = file_list(base, skip_dirs=set(REGIONS))
        if files:
            write(base, f"{sid}-global-{date.today():%Y%m%d}", sid, {k: v for k, v in meta.items() if k != "query"}, files,
                  {"region": "global", "query": "global",
                   "dataScope": "global copy kept from the first download run; new runs fetch regional subsets only"
                   if sid != "GEO-06" else "small global file (< ~100 MB), kept whole"})
