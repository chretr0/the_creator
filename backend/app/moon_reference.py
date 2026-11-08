"""Moon reference data prepared under data/prepared/moon/ (see scripts/moon/prepare_moon_reference.py).

Read lazily and cached per process. The cache is keyed by the prepared-data directory and the
size / mtime of source.json and of every layer file it lists, so re-preparing the data (or a test
pointing `settings.prepared_data_dir` somewhere else) is picked up on the next request without a
restart. `reset()` drops everything.

All geometry is on the Moon sphere (R = 1737.4 km, IAU_2015:30100, longitude positive east,
normalised to [-180, 180)). Missing values stay null; nothing here invents a 0.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import threading
from functools import cached_property
from pathlib import Path
from typing import Any

import h3
import numpy as np
import shapely
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from app import bodies, geo
from app.bodies import MOON
from app.config import settings

log = logging.getLogger(__name__)

PREPARE_SCRIPT = "scripts/moon/prepare_moon_reference.py"
NOT_PREPARED = (
    f"Moon reference data not prepared: run {PREPARE_SCRIPT} "
    "to write data/prepared/moon/source.json and its layers."
)

SITES_LAYER = "moon_sites"
PLACES_LAYER = "moon_places"
MARE_LAYER = "moon_mare"
MISSIONS_LAYER = "moon_missions"
KEEPOUT_LAYER = "moon_keepout"  # computed here, not a prepared file

# NASA 2011 "Recommendations to space-faring entities" (Rev A): no landing within 2.0 km of a
# heritage landing site or 0.5 km of a heritage impact site.
KEEPOUT_SOURCE_ID = "MOON-SITE-06"
HERITAGE_RADIUS_M = {"landing": 2000.0, "impact": 500.0}
HERITAGE_RULE = {"landing": "heritage_landing", "impact": "heritage_impact"}
KEEPOUT_VERTICES = 64

NEAREST_PLACES = 6
NEARBY_SITES = 6
NEARBY_SITES_RADIUS_KM = 150.0


class NotPrepared(RuntimeError):
    pass


class UnknownLayer(LookupError):
    pass


def moon_dir() -> Path:
    return Path(settings.prepared_data_dir) / "moon"


def h3_dir() -> Path:
    return moon_dir() / "h3"


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _finite(value: Any) -> float | None:
    """A JSON-safe number, or None for missing / NaN / infinite / non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # half-written by a concurrent prepare run, or corrupt
        log.warning("cannot read %s: %s", path, exc)
        return None


def _haversine_km(lat_rad: np.ndarray, lon_rad: np.ndarray, cos_lat: np.ndarray, lat: float, lon: float) -> np.ndarray:
    phi, lam = math.radians(lat), math.radians(lon)
    a = np.sin((lat_rad - phi) / 2) ** 2 + math.cos(phi) * cos_lat * np.sin((lon_rad - lam) / 2) ** 2
    return 2.0 * MOON.radius_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


class _Points:
    """Brute-force vectorised great-circle search; plenty for ~10k points per request."""

    def __init__(self, items: list[dict], lats: list[float], lons: list[float]):
        self.items = items
        self.lat_deg = np.asarray(lats, dtype=float)
        self.lon_deg = np.asarray(lons, dtype=float)
        self.lat = np.radians(self.lat_deg)
        self.lon = np.radians(self.lon_deg)
        self.cos_lat = np.cos(self.lat)
        self.has_quad = np.array([bool(p.get("quad")) for p in items], dtype=bool)

    def __len__(self) -> int:
        return len(self.items)

    def distances_km(self, lat: float, lon: float) -> np.ndarray:
        return _haversine_km(self.lat, self.lon, self.cos_lat, lat, lon)

    @staticmethod
    def nearest(d: np.ndarray, k: int, max_km: float | None = None) -> list[tuple[int, float]]:
        idx = np.arange(len(d)) if max_km is None else np.nonzero(d <= max_km)[0]
        if len(idx) > k:
            idx = idx[np.argpartition(d[idx], k - 1)[:k]]
        idx = idx[np.argsort(d[idx], kind="stable")]
        return [(int(i), float(d[i])) for i in idx]


def _point_features(fc: Any) -> tuple[list[dict], list[float], list[float]]:
    items, lats, lons = [], [], []
    for f in (fc or {}).get("features", []) if isinstance(fc, dict) else []:
        g = f.get("geometry") or {}
        coords = g.get("coordinates") if g.get("type") == "Point" else None
        if not coords or len(coords) < 2:
            continue
        lon, lat = _finite(coords[0]), _finite(coords[1])
        if lon is None or lat is None or not -90 <= lat <= 90:
            continue
        items.append(f.get("properties") or {})
        lats.append(lat)
        lons.append(geo.normalise_longitude(lon))
    return items, lats, lons


class _Polygons:
    def __init__(self, fc: Any):
        self.props: list[dict] = []
        geoms = []
        for f in (fc or {}).get("features", []) if isinstance(fc, dict) else []:
            if not f.get("geometry"):
                continue
            try:
                g = shape(f["geometry"])
            except Exception:  # malformed geometry: skip the feature, keep the rest
                continue
            geoms.append(g if g.is_valid else shapely.make_valid(g))
            self.props.append(f.get("properties") or {})
        self.tree = STRtree(geoms)

    def locate(self, lon: float, lat: float) -> dict | None:
        hits = self.tree.query(Point(lon, lat), predicate="intersects")
        return self.props[int(min(hits))] if len(hits) else None


class _Reference:
    def __init__(self, root: Path, signature: tuple, manifest: dict):
        self.root = root
        self.signature = signature
        self.manifest = manifest
        self.files = {
            layer["id"]: root / layer["file"]
            for layer in manifest.get("layers", [])
            if isinstance(layer, dict) and layer.get("id") and layer.get("file")
        }
        self.file_stats = {lid: _stat(p) for lid, p in self.files.items()}

    def current(self, root: Path, signature: tuple) -> bool:
        return (
            self.root == root
            and self.signature == signature
            and all(_stat(p) == self.file_stats[lid] for lid, p in self.files.items())
        )

    def layer_path(self, layer_id: str) -> Path | None:
        path = self.files.get(layer_id)
        if path is None:
            return None
        # Manifest paths are relative to data/prepared/moon; never serve anything outside it
        # (checked lexically, so symlinked data directories still work).
        if not Path(os.path.normpath(path)).is_relative_to(os.path.normpath(self.root)):
            return None
        return path

    def _load(self, layer_id: str) -> Any | None:
        path = self.layer_path(layer_id)
        return _read_json(path) if path is not None else None

    @cached_property
    def places(self) -> _Points | None:
        data = self._load(PLACES_LAYER)
        if not isinstance(data, list):
            return None
        items, lats, lons = [], [], []
        for p in data:
            if not isinstance(p, dict):
                continue
            lat, lon = _finite(p.get("lat")), _finite(p.get("lon"))
            if lat is None or lon is None or not -90 <= lat <= 90:
                continue
            items.append(p)
            lats.append(lat)
            lons.append(geo.normalise_longitude(lon))
        return _Points(items, lats, lons)

    @cached_property
    def sites(self) -> _Points | None:
        data = self._load(SITES_LAYER)
        if data is None:
            return None
        return _Points(*_point_features(data))

    @cached_property
    def heritage(self) -> list[dict]:
        """Sites with a NASA-2011 heritage keep-out: id, name, rule, radius and centre."""
        out = []
        sites = self.sites
        if sites is None:
            return out
        for props, lat, lon in zip(sites.items, sites.lat_deg, sites.lon_deg):
            kind = props.get("heritage")
            kind = kind.lower() if isinstance(kind, str) else None
            if kind not in HERITAGE_RADIUS_M:
                continue
            out.append({
                "siteId": props.get("id"),
                "siteName": props.get("name"),
                "rule": HERITAGE_RULE[kind],
                "radiusM": HERITAGE_RADIUS_M[kind],
                "latitude": float(lat),
                "longitude": float(lon),
            })
        return out

    @cached_property
    def heritage_points(self) -> _Points:
        h = self.heritage
        return _Points(h, [s["latitude"] for s in h], [s["longitude"] for s in h])

    @cached_property
    def mare(self) -> _Polygons | None:
        data = self._load(MARE_LAYER)
        return _Polygons(data) if data is not None else None

    @cached_property
    def keepout(self) -> dict:
        features = []
        for s in self.heritage:
            ring = bodies.geodesic_circle(s["latitude"], s["longitude"], s["radiusM"] / 1000.0, MOON, KEEPOUT_VERTICES)
            fid = f"keepout-{s['siteId'] or s['siteName']}"
            features.append({
                "type": "Feature",
                "id": fid,
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "id": fid,
                    "siteId": s["siteId"],
                    "siteName": s["siteName"],
                    "radiusM": s["radiusM"],
                    "rule": s["rule"],
                    "sourceId": KEEPOUT_SOURCE_ID,
                    "evidenceType": "rule",
                },
            })
        return {"type": "FeatureCollection", "features": features}


_lock = threading.Lock()
_current: _Reference | None = None


def reset() -> None:
    """Forget every cached manifest and index (tests; or after re-preparing the data)."""
    global _current
    with _lock:
        _current = None


def reference() -> _Reference:
    """The cached reference for the current prepared-data dir. Raises NotPrepared without source.json."""
    global _current
    root = moon_dir()
    src = root / "source.json"
    sig = _stat(src)
    if sig is None:
        raise NotPrepared(NOT_PREPARED)
    ref = _current
    if ref is not None and ref.current(root, sig):
        return ref
    with _lock:
        ref = _current
        if ref is not None and ref.current(root, sig):
            return ref
        manifest = _read_json(src)
        if not isinstance(manifest, dict):
            raise NotPrepared(f"{src} is unreadable (being re-written?). {NOT_PREPARED}")
        ref = _Reference(root, sig, manifest)
        _current = ref
        return ref


# ---------------------------------------------------------------------------------------------
# API helpers


def manifest() -> dict:
    """source.json plus `available` (file exists) per layer."""
    ref = reference()
    out = copy.deepcopy(ref.manifest)
    for layer in out.get("layers", []):
        if isinstance(layer, dict):
            path = ref.layer_path(layer.get("id", ""))
            layer["available"] = bool(path is not None and path.is_file())
    return out


def layer_file(layer_id: str) -> tuple[Path, str]:
    """(path, media type) of a prepared layer. UnknownLayer if not in the manifest; NotPrepared if missing."""
    ref = reference()
    if layer_id not in ref.files:
        known = ", ".join(sorted(ref.files)) or "none"
        raise UnknownLayer(f"unknown Moon layer {layer_id!r}; prepared layers: {known}")
    path = ref.layer_path(layer_id)
    if path is None or not path.is_file():
        raise NotPrepared(f"Moon layer {layer_id!r} is listed in source.json but its file is missing. {NOT_PREPARED}")
    media = "application/geo+json" if path.suffix == ".geojson" else "application/json"
    return path, media


def keepout() -> dict:
    return reference().keepout


def cell_context(h3_id: str) -> dict:
    """Named features, landed objects, keep-out rings, mare and LAC quadrangle around a cell centre.

    Raises geo.InvalidCell (bad id) or NotPrepared (no source.json). A layer whose file is missing
    contributes an empty list / null instead of failing the whole context.
    """
    h3_id = geo.validate_cell(h3_id)
    ref = reference()
    lat, lon = h3.cell_to_latlng(h3_id)
    lon = geo.normalise_longitude(lon)

    nearest_places: list[dict] = []
    quad = None
    places = ref.places
    if places is not None and len(places):
        d = places.distances_km(lat, lon)
        for i, dist in places.nearest(d, NEAREST_PLACES):
            p = places.items[i]
            diameter = _finite(p.get("diameterKm"))
            nearest_places.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "type": p.get("type"),
                "diameterKm": diameter,
                "quad": p.get("quad"),
                "latitude": float(places.lat_deg[i]),
                "longitude": float(places.lon_deg[i]),
                "distanceKm": round(dist, 3),
                "within": diameter is not None and dist <= diameter / 2,
            })
        # LAC quadrangle: that of the nearest named feature carrying one (approximate near chart edges).
        if places.has_quad.any():
            j = int(np.argmin(np.where(places.has_quad, d, np.inf)))
            quad = places.items[j].get("quad")

    nearby_sites: list[dict] = []
    sites = ref.sites
    if sites is not None and len(sites):
        d = sites.distances_km(lat, lon)
        for i, dist in sites.nearest(d, NEARBY_SITES, NEARBY_SITES_RADIUS_KM):
            s = sites.items[i]
            nearby_sites.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "mission": s.get("mission"),
                "kind": s.get("kind"),
                "date": s.get("date"),
                "heritage": s.get("heritage"),
                "latitude": float(sites.lat_deg[i]),
                "longitude": float(sites.lon_deg[i]),
                "distanceKm": round(dist, 3),
            })

    keepout_hits: list[dict] = []
    hp = ref.heritage_points
    if len(hp):
        d = hp.distances_km(lat, lon)
        for i in np.argsort(d, kind="stable"):
            s = hp.items[int(i)]
            if d[i] * 1000.0 > s["radiusM"]:
                continue
            keepout_hits.append({
                "siteId": s["siteId"],
                "siteName": s["siteName"],
                "rule": s["rule"],
                "radiusM": s["radiusM"],
                "distanceKm": round(float(d[i]), 3),
                "sourceId": KEEPOUT_SOURCE_ID,
            })

    mare = None
    if ref.mare is not None:
        hit = ref.mare.locate(lon, lat)
        if hit is not None:
            mare = {"id": hit.get("id"), "name": hit.get("name")}

    return {
        "h3Id": h3_id,
        "body": MOON.id,
        "centre": {"latitude": lat, "longitude": lon},
        "nearestPlaces": nearest_places,
        "nearbySites": nearby_sites,
        "keepout": keepout_hits,
        "mare": mare,
        "quad": quad,
    }


# ---------------------------------------------------------------------------------------------
# Credits

LROC_WMS_SOURCE = {
    "id": "MOON-MAP-01",
    "name": "LROC Lunaserv WMS (WAC global mosaic and overlays)",
    "provider": "LROC / IM-LDI (Arizona State University)",
    "licence": "U.S. public domain (NASA); credit requested",
    "attribution": "NASA/GSFC/Arizona State University",
    "evidenceType": "satellite_imagery",
    "retrievedAt": None,  # live tiles
    "url": "https://wms.im-ldi.com/",
    "layers": ["moon_basemap", "moon_overlays"],
    "limitations": [
        "Live third-party WMS: availability and rendering are not guaranteed.",
        "Web Mercator tiles stop at ±85° latitude; the poles are not shown.",
        "Visual context only: nothing in the imagery is classified or measured by this app.",
    ],
    "commercialUse": True,
    "notes": "Overlay labels (luna_nomenclature) use IAU-approved names.",
}

IAU_NOMENCLATURE_SOURCE = {
    "id": "MOON-PLACE-01",
    "name": "Gazetteer of Planetary Nomenclature (Moon)",
    "provider": "IAU Working Group for Planetary System Nomenclature / USGS Astrogeology Science Center",
    "licence": "IAU nomenclature; USGS data, U.S. public domain",
    "attribution": "Gazetteer of Planetary Nomenclature, IAU WGPSN / USGS Astrogeology Science Center",
    "evidenceType": "reference_gazetteer",
    "retrievedAt": None,
    "url": "https://planetarynames.wr.usgs.gov/",
    "layers": ["moon_overlays"],
    "limitations": ["Feature centres and diameters are nominal; names are labels, not surveyed boundaries."],
    "commercialUse": True,
}


def _source_items(sources: Any) -> list[tuple[str, dict]]:
    if isinstance(sources, dict):
        return [(str(k), v) for k, v in sources.items() if isinstance(v, dict)]
    if isinstance(sources, list):
        return [(str(s["id"]), s) for s in sources if isinstance(s, dict) and s.get("id")]
    return []


def _credit(sid: str, s: dict, layer_ids: list[str]) -> dict:
    out = {
        "id": s.get("id") or sid,
        "name": s.get("name") or s.get("product") or sid,
        "provider": s.get("provider"),
        "licence": s.get("licence") or "see source record",
        "attribution": s.get("attribution") or s.get("provider") or "",
        "evidenceType": s.get("evidenceType") or "reference",
        "retrievedAt": s.get("retrievedAt"),
        "url": s.get("url") or s.get("licenceUrl") or s.get("documentationUrl"),
        "layers": layer_ids,
        "limitations": list(s.get("limitations") or []),
        "commercialUse": s.get("commercialUse"),
    }
    if s.get("notes") or s.get("note"):
        out["notes"] = s.get("notes") or s.get("note")
    return out


def _add_layers(entry: dict, layer_ids: list[str]) -> None:
    entry["layers"] += [x for x in layer_ids if x not in entry["layers"]]


def sources() -> list[dict]:
    """Every Moon credit: prepared sources, H3 layer sources, the live LROC WMS and IAU names."""
    out: dict[str, dict] = {}

    try:
        m = reference().manifest
    except NotPrepared:
        m = None
    if m is not None:
        layers = [layer for layer in m.get("layers", []) if isinstance(layer, dict)]
        for sid, s in _source_items(m.get("sources")):
            ids = [layer["id"] for layer in layers if layer.get("source") == sid and layer.get("id")]
            if sid.endswith("-SUPPLEMENT"):  # hand-added rows inside a base source's layer
                base = sid.removesuffix("-SUPPLEMENT")
                ids += [layer["id"] for layer in layers if layer.get("source") == base and layer["id"] not in ids]
            if sid == KEEPOUT_SOURCE_ID:
                ids.append(KEEPOUT_LAYER)
            ids += [x for x in s.get("layers", []) if isinstance(x, str) and x not in ids]
            out[sid] = _credit(sid, s, ids)

    h3_manifest = _read_json(h3_dir() / "layers.json")
    if isinstance(h3_manifest, dict):
        h3_layers = [layer for layer in h3_manifest.get("layers", []) if isinstance(layer, dict)]
        for sid, s in _source_items(h3_manifest.get("sources")):
            ids = [f"h3:{layer['id']}" for layer in h3_layers if layer.get("sourceId") == sid and layer.get("id")]
            if sid in out:
                _add_layers(out[sid], ids)
            else:
                out[sid] = _credit(sid, s, ids)

    if LROC_WMS_SOURCE["id"] in out:
        _add_layers(out[LROC_WMS_SOURCE["id"]], LROC_WMS_SOURCE["layers"])
    else:
        out[LROC_WMS_SOURCE["id"]] = copy.deepcopy(LROC_WMS_SOURCE)
    if IAU_NOMENCLATURE_SOURCE["id"] in out:
        _add_layers(out[IAU_NOMENCLATURE_SOURCE["id"]], IAU_NOMENCLATURE_SOURCE["layers"])
    else:
        out[IAU_NOMENCLATURE_SOURCE["id"]] = copy.deepcopy(IAU_NOMENCLATURE_SOURCE)
    return list(out.values())
