"""Data credits: every source the app can show, with licence, attribution and evidence type."""

import json
from pathlib import Path

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api", tags=["sources"])

LIVE_SOURCES = [
    {"id": "basemap", "name": "OpenFreeMap basemap (OpenMapTiles schema)", "licence": "ODbL-1.0 data; OpenFreeMap terms",
     "attribution": "OpenFreeMap © OpenMapTiles · Data from OpenStreetMap", "evidenceType": "reference_map",
     "url": "https://openfreemap.org/", "layers": ["basemap", "buildings3d"],
     "notes": "Building heights come from OSM height/levels or a default value; display only."},
    {"id": "usgs-earthquakes", "name": "USGS earthquake summary feeds", "licence": "U.S. public domain",
     "attribution": "Data courtesy of the U.S. Geological Survey", "evidenceType": "in_situ_observation",
     "url": "https://earthquake.usgs.gov/earthquakes/feed/", "layers": ["earthquakes"]},
    {"id": "nasa-firms", "name": "NASA FIRMS VIIRS active fires", "licence": "NASA open data (MAP_KEY required)",
     "attribution": "LANCE FIRMS, NASA ESDIS", "evidenceType": "satellite_retrieval",
     "url": "https://firms.modaps.eosdis.nasa.gov/", "layers": ["fires"]},
    {"id": "nasa-gibs", "name": "NASA GIBS imagery tiles (HLS Sentinel-2 / Landsat, VIIRS) and CMR catalogue",
     "licence": "U.S. public domain (NASA)",
     "attribution": "Imagery: NASA Global Imagery Browse Services (GIBS), part of NASA ESDIS", "evidenceType": "satellite_imagery",
     "url": "https://gibs.earthdata.nasa.gov", "layers": ["imagery"],
     "notes": "True-colour imagery for visual context; nothing on it is classified or detected by this app."},
    {"id": "open-meteo", "name": "Open-Meteo forecast API (GFS and ECMWF IFS models)", "licence": "CC BY 4.0",
     "attribution": "Weather data by Open-Meteo.com", "evidenceType": "model_output",
     "url": "https://open-meteo.com/", "layers": ["weather"],
     "notes": "Short-range forecast for one point; not a climatology or wind/solar resource assessment."},
    {"id": "photon", "name": "Photon place search (komoot)", "licence": "ODbL-1.0 data; fair-use public service",
     "attribution": "Search by Photon (komoot) · © OpenStreetMap contributors", "evidenceType": "reference",
     "url": "https://photon.komoot.io", "layers": ["search"]},
    {"id": "overpass-power", "name": "OSM power infrastructure via Overpass API", "licence": "ODbL-1.0",
     "attribution": "© OpenStreetMap contributors", "evidenceType": "reported_record",
     "url": "https://overpass-api.de/", "layers": ["power"]},
]

PREPARED = [("infrastructure", ["datacenters", "dams"]), ("boundaries", ["boundaries"]), ("cables", ["cables"])]


@router.get("/sources")
def sources():
    out = []
    for group, layers in PREPARED:
        path = Path(settings.prepared_data_dir) / group / "source.json"
        if not path.exists():
            continue
        m = json.loads(path.read_text())
        out.append({
            "id": m["id"], "name": m["product"], "provider": m["provider"], "licence": m["licence"],
            "attribution": m["attribution"], "evidenceType": m["evidenceType"], "retrievedAt": m.get("retrievedAt"),
            "layers": layers, "limitations": m.get("limitations", []), "commercialUse": m.get("commercialUse", True),
            "url": m.get("licenceUrl"),
        })
    return out + LIVE_SOURCES
