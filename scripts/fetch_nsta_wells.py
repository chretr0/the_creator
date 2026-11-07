"""Fetch NSTA (UK) offshore wellbore top holes (WGS84) as one GeoJSON FeatureCollection.

Run: uv run --no-project --with certifi python -I scripts/fetch_nsta_wells.py data/raw/IND-04/<release>/nsta_offshore_wellbore_top_holes_wgs84.geojson

The data.gov.uk "OGA Wells WGS84" CSV/GeoJSON links (ArcGIS item 40b80e75...) now return 403;
this pulls the current NSTA_GIS successor layer from its public FeatureServer, paging by
OBJECTID order (maxRecordCount 2000). Response bodies are parsed as JSON only.
"""
import json
import ssl
import sys
import urllib.parse
import urllib.request

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # system trust store
    CTX = ssl.create_default_context()

SERVICE = ("https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/"
           "UKCS_offshore_wellbore_top_holes_(WGS84)/FeatureServer/0")
PAGE = 2000
out_path = sys.argv[1]


def get(params):
    url = f"{SERVICE}/query?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120, context=CTX) as r:
        return json.load(r)


expected = get({"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
features, offset = [], 0
while True:
    page = get({"where": "1=1", "outFields": "*", "outSR": "4326", "orderByFields": "OBJECTID",
                "resultOffset": offset, "resultRecordCount": PAGE, "f": "geojson"})
    batch = page.get("features", [])
    features.extend(batch)
    offset += len(batch)
    if not batch or (not page.get("exceededTransferLimit") and not page.get("properties", {}).get("exceededTransferLimit") and len(batch) < PAGE):
        break
ids = {f["properties"]["OBJECTID"] for f in features}
assert len(ids) == len(features) == expected, (len(ids), len(features), expected)
with open(out_path, "w") as fh:
    json.dump({"type": "FeatureCollection", "features": features}, fh)
print(f"{len(features)} features (service count {expected}) -> {out_path}")
