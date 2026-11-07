"""Prepared vector layers (points, lines, polygons, tables) from data/prepared/features/.

The manifest (`manifest.json`) is written by the prepare scripts and describes each layer's file,
fields, category/value fields and provenance. Points live in Parquet (`id, lon, lat, ...`); lines and
polygons in GeoJSON. Everything is loaded lazily, once per file modification time.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

import h3
import numpy as np
import pyarrow.parquet as pq
import shapely
from shapely.geometry import Point, box, shape
from shapely.strtree import STRtree

from app.config import settings

EARTH_RADIUS_KM = 6371.0088
_guard = threading.Lock()


def features_dir() -> Path:
    return Path(settings.prepared_data_dir) / "features"


def _scrub(v):
    """JSON from prepare scripts may carry NaN; the API never emits it (NaN → null, dropped from lists)."""
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, list):
        return [_scrub(x) for x in v if not (isinstance(x, float) and x != x)]
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items()}
    return v


@lru_cache(maxsize=4)
def _manifest(_mtime: float) -> dict:
    return _scrub(json.loads((features_dir() / "manifest.json").read_text()))


def manifest() -> dict:
    p = features_dir() / "manifest.json"
    if not p.exists():
        return {"generatedAt": None, "layers": []}
    return _manifest(p.stat().st_mtime)


def layer_meta(layer_id: str) -> dict | None:
    return next((m for m in manifest()["layers"] if m["id"] == layer_id), None)


def file_path(meta: dict) -> Path:
    return features_dir() / meta["file"]


class PointLayer:
    def __init__(self, path: Path):
        t = pq.read_table(path)
        self.columns = [c for c in t.column_names]
        self.lon = t.column("lon").to_numpy(zero_copy_only=False).astype(np.float64)
        self.lat = t.column("lat").to_numpy(zero_copy_only=False).astype(np.float64)
        self.data = {c: t.column(c).to_pylist() for c in self.columns if c not in ("lon", "lat")}
        self.n = len(self.lon)

    def props(self, i: int) -> dict:
        return {c: _clean(self.data[c][i]) for c in self.data}

    def feature(self, i: int) -> dict:
        return {
            "type": "Feature",
            "id": self.data["id"][i] if "id" in self.data else str(i),
            "geometry": {"type": "Point", "coordinates": [round(self.lon[i], 5), round(self.lat[i], 5)]},
            "properties": self.props(i),
        }

    def in_bbox(self, west: float, south: float, east: float, north: float) -> np.ndarray:
        lat_ok = (self.lat >= south) & (self.lat <= north)
        if east - west >= 360:
            return lat_ok
        w, e = _norm_lon(west), _norm_lon(east)
        lon_ok = (self.lon >= w) & (self.lon <= e) if w <= e else (self.lon >= w) | (self.lon <= e)
        return lat_ok & lon_ok

    def nearest(self, lon: float, lat: float, radius_km: float, limit: int) -> list[tuple[int, float]]:
        d = _haversine(lon, lat, self.lon, self.lat)
        idx = np.flatnonzero(d <= radius_km)
        idx = idx[np.argsort(d[idx])][:limit]
        return [(int(i), float(d[i])) for i in idx]

    def in_cell(self, h3_id: str) -> np.ndarray:
        ring = h3.cell_to_boundary(h3_id)
        lats, lons = [p[0] for p in ring], [p[1] for p in ring]
        cand = np.flatnonzero(
            (self.lat >= min(lats) - 0.01) & (self.lat <= max(lats) + 0.01)
            & (self.lon >= min(lons) - 0.01) & (self.lon <= max(lons) + 0.01)
        )
        return np.array([i for i in cand if h3.latlng_to_cell(self.lat[i], self.lon[i], 6) == h3_id], dtype=int)


class ShapeLayer:
    def __init__(self, path: Path):
        fc = _scrub(json.loads(path.read_text()))
        self.features = fc["features"]
        geoms = []
        for f in self.features:
            g = shape(f["geometry"])
            geoms.append(g if g.is_valid else shapely.make_valid(g))
        self.geoms = geoms
        self.tree = STRtree(geoms)
        self.n = len(geoms)

    def in_bbox(self, west: float, south: float, east: float, north: float) -> list[int]:
        if east - west >= 360:
            return list(range(self.n))
        w, e = _norm_lon(west), _norm_lon(east)
        boxes = [box(w, south, e, north)] if w <= e else [box(w, south, 180, north), box(-180, south, e, north)]
        hits: set[int] = set()
        for b in boxes:
            hits.update(int(i) for i in self.tree.query(b, predicate="intersects"))
        return sorted(hits)

    def containing(self, lon: float, lat: float) -> list[int]:
        return [int(i) for i in self.tree.query(Point(lon, lat), predicate="intersects")]

    def intersecting(self, geom) -> list[int]:
        return [int(i) for i in self.tree.query(geom, predicate="intersects")]


@lru_cache(maxsize=16)
def _load(path: str, kind: str, _mtime: float):
    p = Path(path)
    if kind == "point":
        return PointLayer(p)
    if kind in ("line", "polygon"):
        return ShapeLayer(p)
    return _scrub(json.loads(p.read_text()))


def load(meta: dict):
    p = file_path(meta)
    with _guard:
        return _load(str(p), meta["geometry"], p.stat().st_mtime)


def available(meta: dict) -> bool:
    return file_path(meta).exists()


def _norm_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0 if not -180.0 <= lon <= 180.0 else lon


def _haversine(lon: float, lat: float, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(lat), np.radians(lats)
    dphi = p2 - p1
    dl = np.radians(lons - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _clean(v):
    if isinstance(v, float) and v != v:
        return None
    return v
