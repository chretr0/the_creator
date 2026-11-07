"""Live hazard context: USGS earthquakes and NASA FIRMS active-fire detections.

Both are cached (memory + data/cache/) so a stale copy is served, and labelled stale, when the
upstream is unreachable. Records are region-tagged for search and aggregation.
"""

import csv
import io
import json
import urllib.error

from fastapi import APIRouter, HTTPException, Query

from app import fetchcache, regions
from app.config import settings

router = APIRouter(prefix="/api/hazards", tags=["hazards"])

USGS_FEEDS = {
    "week_m2.5": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
    "month_m4.5": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson",
    "month_significant": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson",
}
FIRMS_SOURCE = "VIIRS_NOAA20_NRT"


def _tags(lon: float, lat: float) -> dict:
    return regions.tag(lon, lat) if regions.available() else {}


@router.get("/earthquakes")
def earthquakes(feed: str = Query(default="week_m2.5", pattern="^(week_m2.5|month_m4.5|month_significant)$")):
    url = USGS_FEEDS[feed]
    try:
        got = fetchcache.fetch("usgs", url, ttl_s=300)
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(502, f"USGS feed unavailable and no cached copy: {exc}") from exc
    raw = json.loads(got.body)
    records = []
    for f in raw.get("features", []):
        lon, lat, depth = (f["geometry"]["coordinates"] + [None])[:3]
        p = f["properties"]
        records.append({
            "id": f["id"],
            "lon": lon,
            "lat": lat,
            "depthKm": depth,
            "magnitude": p.get("mag"),
            "magType": p.get("magType"),
            "place": p.get("place"),
            "time": p.get("time"),
            "status": p.get("status"),
            "tsunami": bool(p.get("tsunami")),
            "url": p.get("url"),
            **_tags(lon, lat),
        })
    return {
        "source": {
            "provider": "U.S. Geological Survey",
            "product": f"Earthquake Hazards Program summary feed ({feed})",
            "url": url,
            "licence": "U.S. public domain",
            "attribution": "Data courtesy of the U.S. Geological Survey",
            "evidenceType": "in_situ_observation",
            "retrievedAt": got.retrieved_at,
            "stale": got.stale,
            "notes": "Automatic solutions are revised; 'status' says whether an event was reviewed.",
        },
        "records": records,
    }


@router.get("/fires")
def fires(
    west: float = Query(ge=-180, le=180),
    south: float = Query(ge=-90, le=90),
    east: float = Query(ge=-180, le=180),
    north: float = Query(ge=-90, le=90),
    days: int = Query(default=1, ge=1, le=5),
):
    """FIRMS VIIRS (NOAA-20) detections inside a box for the last `days` days. Needs a MAP_KEY."""
    if not settings.firms_map_key:
        return {
            "source": {"provider": "NASA FIRMS", "available": False,
                       "reason": "Set NEWWORLDS_FIRMS_MAP_KEY (free key: https://firms.modaps.eosdis.nasa.gov/api/map_key/)."},
            "records": [],
        }
    if east <= west or north <= south:
        raise HTTPException(422, "Box must have west < east and south < north (split at the date line).")
    # Rounded so nearby views share a cache entry; the key itself is never cached or returned.
    box = f"{west:.1f},{south:.1f},{east:.1f},{north:.1f}"
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.firms_map_key}/{FIRMS_SOURCE}/{box}/{days}"
    try:
        got = fetchcache.fetch("firms", url, ttl_s=900, cache_key=f"firms:{FIRMS_SOURCE}:{box}:{days}")
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(502, "FIRMS unavailable and no cached copy for this view.") from exc
    if not got.body.startswith("latitude"):
        raise HTTPException(502, f"FIRMS returned an error: {got.body[:200]}")
    records = []
    for row in csv.DictReader(io.StringIO(got.body)):
        lat, lon = float(row["latitude"]), float(row["longitude"])
        frp = row.get("frp")
        records.append({
            "id": f"{row['acq_date']}T{row['acq_time']}:{lat:.4f},{lon:.4f}",
            "lon": lon,
            "lat": lat,
            "acqDate": row["acq_date"],
            "acqTime": row["acq_time"],
            "confidence": row.get("confidence"),
            "frpMw": float(frp) if frp not in (None, "") else None,
            "dayNight": row.get("daynight"),
            "satellite": row.get("satellite"),
            **_tags(lon, lat),
        })
    return {
        "source": {
            "provider": "NASA FIRMS",
            "product": f"{FIRMS_SOURCE} active-fire detections, last {days} day(s)",
            "licence": "NASA open data",
            "attribution": "We acknowledge the use of data and imagery from LANCE FIRMS operated by NASA's Earth Science Data and Information System (ESDIS).",
            "evidenceType": "satellite_retrieval",
            "nativeResolution": "375 m VIIRS pixel",
            "retrievedAt": got.retrieved_at,
            "stale": got.stale,
            "available": True,
            "notes": "A detection is a thermal anomaly in a pixel, not a mapped fire perimeter; industrial heat sources can appear.",
        },
        "records": records,
    }
