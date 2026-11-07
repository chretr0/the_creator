"""Data credits: every source the app can show, with licence, attribution and evidence type."""

import json
from pathlib import Path

from fastapi import APIRouter

from app import features, layers
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

PREPARED = [("boundaries", ["boundaries"]), ("cables", ["cables"])]


def _infrastructure_sources() -> list[dict]:
    """One credit per infrastructure source, listing the map layers it feeds."""
    path = Path(settings.prepared_data_dir) / "infrastructure" / "source.json"
    if not path.exists():
        return []
    m = json.loads(path.read_text())
    out = []
    for sid, s in m.get("sources", {}).items():
        ids = [layer["id"] for layer in m["layers"] if layer.get("source") == sid]
        if not ids:
            continue
        out.append({
            "id": sid, "name": s.get("product") or s.get("name"), "provider": s.get("provider"), "licence": s["licence"],
            "attribution": s["attribution"], "evidenceType": s["evidenceType"], "retrievedAt": s.get("retrievedAt"),
            "layers": ids, "limitations": s.get("limitations", []), "commercialUse": s.get("commercialUse", True),
            "url": s.get("url") or s.get("licenceUrl"),
        })
    return out


@router.get("/sources")
def sources():
    out = _infrastructure_sources()
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
    return out + LIVE_SOURCES + _data_layer_sources()


def _data_layer_sources() -> list[dict]:
    """One credit per acquired dataset: H3 layers grouped by source ID, then vector layers."""
    by_source: dict[str, dict] = {}
    for layer in layers.LAYERS:
        if not any(layers.slice_files(s) for s in layer.slices):
            continue
        p = layers.provenance(layer)
        entry = by_source.setdefault(layer.source_id, {
            "id": f"data-{layer.source_id}",
            "name": f"{p.get('product') or layer.name} ({layer.source_id})",
            "provider": p.get("provider"),
            "licence": p.get("licence") or "see source record",
            "attribution": p.get("attribution") or p.get("provider") or "",
            "evidenceType": p.get("evidenceType") or "model_output",
            "retrievedAt": p.get("retrievedAt"),
            "url": p.get("licenceUrl") or p.get("documentationUrl"),
            "layers": [],
            "limitations": [],
        })
        entry["layers"].append(f"h3:{layer.id}")
        entry["limitations"] += [x for x in layer.limitations if x not in entry["limitations"]]
    out = list(by_source.values())
    for m in features.manifest()["layers"]:
        if not features.available(m):
            continue
        out.append({
            "id": f"features-{m['id']}",
            "name": f"{m.get('product') or m['name']} ({m.get('sourceId')})",
            "provider": m.get("provider"),
            "licence": m.get("licence") or "see source record",
            "attribution": m.get("attribution") or "",
            "evidenceType": m.get("evidenceType") or "reported_record",
            "retrievedAt": m.get("retrievedAt"),
            "url": m.get("url"),
            "layers": [f"features:{m['id']}"],
            "limitations": m.get("limitations", []),
        })
    return out
