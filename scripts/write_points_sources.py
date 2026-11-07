"""Write source.json for LAND-05 (FIRMS 2024 archive) and IND-04 (NSTA wells). Run: python3 -I scripts/write_points_sources.py data/raw"""
import hashlib, json, os, sys

ROOT = sys.argv[1]


def files(d, names):
    out = []
    for n in names:
        p = os.path.join(d, n)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        out.append({"name": n, "bytes": os.path.getsize(p), "sha256": h.hexdigest()})
    return out


firms_dir = os.path.join(ROOT, "LAND-05", "archive_2024")
firms = {
    "id": "LAND-05-archive-2024",
    "catalogueSourceId": "LAND-05",
    "provider": "NASA LANCE / FIRMS (ESDIS)",
    "product": "FIRMS annual country archive 2024, all countries: VIIRS S-NPP 375 m (VNP14IMG) and MODIS (MCD14ML) active fire / thermal anomalies",
    "version": "collection version field = 2 (VIIRS, standard/archive quality); files dated 2025-06-19..23 inside zips",
    "doi": "",
    "documentationUrl": "https://firms.modaps.eosdis.nasa.gov/country/",
    "accessUrl": [
        "https://firms.modaps.eosdis.nasa.gov/data/country/zips/viirs-snpp_2024_all_countries.zip",
        "https://firms.modaps.eosdis.nasa.gov/data/country/zips/modis_2024_all_countries.zip",
    ],
    "accessMethod": "download (no MAP_KEY required)",
    "evidenceType": "satellite_retrieval",
    "retrievedAt": "2026-11-07",
    "files": files(firms_dir, ["viirs-snpp_2024_all_countries.zip", "modis_2024_all_countries.zip"]),
    "derived": {
        "unzipped/": "per-country CSVs extracted from the zips (218 VIIRS, 206 MODIS) + AttributesReadme.txt",
        "../../../prepared/firms_viirs_snpp_2024_h3r6.parquet": "scripts/aggregate_firms_h3.py (VIIRS only; H3 r6; exact-duplicate rows removed)",
    },
    "licence": {
        "name": "NASA open data (Earth Science Data and Information Policy); no restrictions on reuse",
        "url": "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
        "attribution": "We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Earth Science Data and Information System (ESDIS).",
        "notes": "AttributesReadme.txt asks redistributors to replicate or link the LANCE/FIRMS disclaimer: https://www.earthdata.nasa.gov/data/tools/firms",
    },
    "query": "calendar year 2024, all countries (detections assigned to country files by location)",
    "semantics": "Each row is a thermal anomaly detection in a 375 m (VIIRS) / 1 km (MODIS) pixel, not a fire perimeter or burned area. type: 0 presumed vegetation fire, 1 active volcano, 2 other static land source (industrial, gas flares, smelters), 3 offshore. frp in MW. confidence VIIRS h/n/l; MODIS 0-100.",
}

wells_dir = os.path.join(ROOT, "IND-04", "2026-11-07")
svc = "https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/UKCS_offshore_wellbore_top_holes_(WGS84)/FeatureServer/0"
wells = {
    "id": "IND-04-wells-tophole-wgs84-2026-11-07",
    "catalogueSourceId": "IND-04",
    "provider": "North Sea Transition Authority (NSTA, formerly Oil and Gas Authority)",
    "product": "UKCS offshore wellbores top holes (WGS84) (ArcGIS item b5752e9f56a949e3ad44a08144e621a8)",
    "version": "live service snapshot 2026-11-07 (item modified 2026-11-07); 13,389 wellbores",
    "doi": "",
    "documentationUrl": "https://www.data.gov.uk/dataset/37538d3f-c320-4153-ad72-3768a2f6be12/oga-wells-wgs84",
    "accessUrl": svc + "/query?where=1=1&outFields=*&outSR=4326&orderByFields=OBJECTID&resultOffset=<n>&resultRecordCount=2000&f=geojson",
    "accessMethod": "api (ArcGIS FeatureServer, paged; scripts/fetch_nsta_wells.py)",
    "evidenceType": "reported_record",
    "retrievedAt": "2026-11-07",
    "files": files(wells_dir, ["nsta_offshore_wellbore_top_holes_wgs84.geojson"]),
    "licence": {
        "name": "Open Government Licence v3.0 (as listed on data.gov.uk for 'OGA Wells WGS84'); current ArcGIS item states no licence, sibling NSTA_GIS well layers state 'NSTA Open User Licence'",
        "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "attribution": "Contains information provided by the North Sea Transition Authority and/or other third parties, licensed under the Open Government Licence v3.0.",
        "notes": "The data.gov.uk CSV/GeoJSON links (hub item 40b80e75b8004fab8c87218ae1664d91) returned 403 on 2026-11-07; this is the current NSTA_GIS successor layer, not byte-identical to that release. Confirm OGL vs NSTA Open User Licence (https://www.nstauthority.co.uk/footer/access-to-information/) before public export. All records have OPEN_DATA=Y.",
    },
    "query": "where=1=1 (all offshore UKCS wellbores), outSR=4326",
    "semantics": "Point = well origin (top hole) where the bit penetrated the seabed. Includes Present/Decommissioned/Derogated wellbores. Not evidence of recoverable reserves.",
}

for d, rec in ((firms_dir, firms), (wells_dir, wells)):
    p = os.path.join(os.path.dirname(d), "source.json")
    with open(p, "w") as fh:
        json.dump(rec, fh, indent=2)
    print("wrote", p)
