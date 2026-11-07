"""Region lookup over the prepared boundary packs (countries, admin-1, US counties).

Point-in-polygon with shapely STRtrees, built lazily once per process. Outlines are simplified, so
a point within a few hundred metres of a border can resolve to the neighbour; results carry that
caveat in the API.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import shapely
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from app.config import settings

LEVELS = ("countries", "admin1", "us_counties")


def boundaries_dir() -> Path:
    return Path(settings.prepared_data_dir) / "boundaries"


class _Index:
    def __init__(self, path: Path):
        fc = json.loads(path.read_text())
        self.props = [f["properties"] for f in fc["features"]]
        # Upstream simplification leaves some self-intersections; repair once so contains() is reliable.
        geoms = []
        for f in fc["features"]:
            g = shape(f["geometry"])
            geoms.append(g if g.is_valid else shapely.make_valid(g))
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def locate(self, lon: float, lat: float) -> dict | None:
        pt = Point(lon, lat)
        for i in self.tree.query(pt, predicate="intersects"):
            return self.props[int(i)]
        return None


@lru_cache(maxsize=None)
def _index(level: str) -> _Index | None:
    path = boundaries_dir() / f"{level}.geojson"
    return _Index(path) if path.exists() else None


def available() -> bool:
    return (boundaries_dir() / "source.json").exists()


def _brief(p: dict | None) -> dict | None:
    if p is None:
        return None
    return {k: p[k] for k in ("id", "name", "country", "iso", "iso2", "level") if k in p}


def locate(lon: float, lat: float) -> dict:
    out = {}
    for level, key in (("countries", "country"), ("admin1", "admin1"), ("us_counties", "county")):
        idx = _index(level)
        hit = idx.locate(lon, lat) if idx else None
        if key == "county" and hit is None:
            continue
        out[key] = _brief(hit)
    return out


def tag(lon: float, lat: float) -> dict:
    """Compact region tags for a record: country and admin-1 names and IDs (null when outside)."""
    c = _index("countries")
    a = _index("admin1")
    country = c.locate(lon, lat) if c else None
    admin1 = a.locate(lon, lat) if a else None
    return {
        "country": country["name"] if country else None,
        "countryId": country["id"] if country else None,
        "admin1": admin1["name"] if admin1 else None,
        "admin1Id": admin1["id"] if admin1 else None,
    }


@lru_cache(maxsize=1)
def search_index() -> list[dict]:
    """Names, bounding boxes and label points for local (keyless) place search."""
    items = []
    for level in ("countries", "admin1", "us_counties"):
        idx = _index(level)
        if not idx:
            continue
        for p, g in zip(idx.props, idx.geoms):
            label = p.get("label")
            if not label:
                c = g.representative_point()
                label = [round(c.x, 3), round(c.y, 3)]
            items.append({
                "id": p["id"],
                "name": p["name"],
                "level": p["level"],
                "country": p.get("country"),
                "state": p.get("state"),
                "bbox": p["bbox"],
                "label": label,
            })
    return items


def country_iso(lats, lons) -> list[str | None]:
    """ISO-3 country code at many points at once (None outside every country / no boundary pack)."""
    import numpy as np

    idx = _index("countries")
    n = len(lats)
    out: list[str | None] = [None] * n
    if idx is None or n == 0:
        return out
    pts = shapely.points(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
    pi, gi = idx.tree.query(pts, predicate="intersects")
    for p, g in zip(pi[::-1], gi[::-1]):  # reversed so the first match per point wins
        out[int(p)] = idx.props[int(g)].get("iso")
    return out
