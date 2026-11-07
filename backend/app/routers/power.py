"""OSM electricity infrastructure near a point, via Overpass (cached to disk).

Context only: mapped plants, substations and transmission lines. It does not establish grid
capacity, connection headroom or which plant supplies which load.
"""

import json
import math
import re
import urllib.error
import urllib.parse

from fastapi import APIRouter, HTTPException, Query

from app import fetchcache
from app.config import settings

router = APIRouter(prefix="/api/osm", tags=["osm"])

UNIT_TO_KW = {"w": 1e-3, "kw": 1.0, "mw": 1e3, "gw": 1e6}
POWER_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(w|kw|mw|gw)\s*$", re.IGNORECASE)


def parse_kw(raw):
    m = POWER_RE.match(str(raw)) if raw else None
    return round(float(m.group(1).replace(",", ".")) * UNIT_TO_KW[m.group(2).lower()], 3) if m else None


def parse_kv(raw):
    """'400000;132000' -> [400.0, 132.0]. Non-numeric parts are dropped."""
    out = []
    for part in str(raw or "").split(";"):
        part = part.strip()
        if part.isdigit():
            out.append(int(part) / 1000)
    return out


def box(lat: float, lon: float, half_km: float):
    dlat = half_km / 111.32
    dlon = half_km / (111.32 * max(math.cos(math.radians(lat)), 0.05))
    return round(lat - dlat, 4), round(lon - dlon, 4), round(lat + dlat, 4), round(lon + dlon, 4)


@router.get("/power")
def power(
    latitude: float = Query(ge=-85, le=85),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=10, ge=1, le=25, alias="radiusKm"),
):
    s, w, n, e = box(latitude, longitude, radius_km)
    bb = f"({s},{w},{n},{e})"
    query = (
        "[out:json][timeout:25];"
        f'nwr["power"~"^(plant|substation)$"]{bb};out tags center;'
        f'way["power"~"^(line|cable)$"]{bb};out tags geom;'
    )
    try:
        got = fetchcache.fetch(
            "overpass", settings.overpass_url, ttl_s=24 * 3600, timeout_s=35,
            data=urllib.parse.urlencode({"data": query}).encode(),
            cache_key=f"power:{s},{w},{n},{e}",
        )
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(502, f"Overpass unavailable and no cached copy for this area: {exc}") from exc
    try:
        raw = json.loads(got.body)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "Overpass returned a non-JSON response (likely rate-limited); try again shortly.") from exc

    features = []
    for el in raw.get("elements", []):
        t = el.get("tags", {})
        kind = t.get("power")
        props = {
            "kind": kind,
            "name": t.get("name:en") or t.get("name"),
            "operator": t.get("operator"),
            "owner": t.get("owner"),
            "voltageKv": parse_kv(t.get("voltage")),
            "voltageRaw": t.get("voltage"),
            "plantSource": t.get("plant:source"),
            "outputRaw": t.get("plant:output:electricity"),
            "outputKw": parse_kw(t.get("plant:output:electricity")),
            "osmUrl": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        }
        if "geometry" in el:
            coords = [[p["lon"], p["lat"]] for p in el["geometry"] if p]
            if len(coords) < 2:
                continue
            geom = {"type": "LineString", "coordinates": coords}
        else:
            c = el.get("center") or el
            if "lat" not in c:
                continue
            geom = {"type": "Point", "coordinates": [c["lon"], c["lat"]]}
        features.append({"type": "Feature", "id": f"osm:{el['type']}/{el['id']}", "geometry": geom, "properties": props})

    return {
        "type": "FeatureCollection",
        "features": features,
        "bbox": [w, s, e, n],
        "source": {
            "provider": "OpenStreetMap contributors via Overpass API",
            "licence": "ODbL-1.0",
            "attribution": "© OpenStreetMap contributors",
            "evidenceType": "reported_record",
            "retrievedAt": got.retrieved_at,
            "stale": got.stale,
            "notes": "Volunteer-mapped; coverage varies. Output tags are nameplate capacity, not generation. "
                     "Lines show mapped routes, not available capacity or connection headroom.",
        },
    }
