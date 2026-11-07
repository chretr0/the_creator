"""Prepared vector layers: manifest, viewport queries and per-cell context."""

from __future__ import annotations

import json

import h3
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from shapely.geometry import Polygon

from app import features, geo
from app.features import PointLayer, ShapeLayer

router = APIRouter(prefix="/api", tags=["features"])

DEFAULT_LIMIT = 4000
MAX_LIMIT = 20000


def _meta(layer_id: str) -> dict:
    meta = features.layer_meta(layer_id)
    if meta is None:
        raise HTTPException(404, f"Unknown feature layer: {layer_id}")
    if not features.available(meta):
        raise HTTPException(503, f"{meta['name']} is not prepared yet.")
    return meta


@router.get("/features")
def feature_manifest():
    """Vector layers (points, lines, polygons, tables) with fields, styling hints and provenance."""
    m = features.manifest()
    return {**m, "layers": [{**layer, "available": features.available(layer)} for layer in m["layers"]]}


def _matches_text(props: dict, q: str) -> bool:
    return any(isinstance(v, str) and q in v.lower() for v in props.values())


@router.get("/features/{layer_id}")
def feature_layer(
    layer_id: str,
    west: float = Query(-180, ge=-540, le=540),
    south: float = Query(-90, ge=-90, le=90),
    east: float = Query(180, ge=-540, le=540),
    north: float = Query(90, ge=-90, le=90),
    category: list[str] | None = Query(None, description="Keep only these values of the layer's categoryField"),
    q: str | None = Query(None, description="Case-insensitive text match on any text property"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """GeoJSON of the features intersecting a bounding box. When more match than `limit`, an evenly
    spaced subset is returned with `truncated: true` and the full `matched` count (zoom in for all)."""
    meta = _meta(layer_id)
    data = features.load(meta)
    if meta["geometry"] == "table":
        return data
    cat_field = meta.get("categoryField")
    qn = q.strip().lower() if q else None
    cats = set(category) if category else None

    if isinstance(data, PointLayer):
        idx = np.flatnonzero(data.in_bbox(west, south, east, north))
        if cats and cat_field:
            col = data.data.get(cat_field, [])
            idx = np.array([i for i in idx if col[i] in cats], dtype=int)
        if qn:
            idx = np.array([i for i in idx if _matches_text(data.props(i), qn)], dtype=int)
        matched = len(idx)
        if matched > limit:
            idx = idx[np.linspace(0, matched - 1, limit).astype(int)]
        feats = [data.feature(int(i)) for i in idx]
    else:
        assert isinstance(data, ShapeLayer)
        hits = data.in_bbox(west, south, east, north)
        if cats and cat_field:
            hits = [i for i in hits if data.features[i]["properties"].get(cat_field) in cats]
        if qn:
            hits = [i for i in hits if _matches_text(data.features[i]["properties"], qn)]
        matched = len(hits)
        vf = meta.get("valueField")
        if matched > limit and vf:
            hits = sorted(hits, key=lambda i: -(data.features[i]["properties"].get(vf) or 0))[:limit]
        elif matched > limit:
            hits = hits[:limit]
        feats = [data.features[i] for i in hits]

    return {
        "type": "FeatureCollection",
        "layer": layer_id,
        "matched": matched,
        "truncated": matched > len(feats),
        "features": feats,
    }


@router.get("/cells/{h3_id}/features")
def cell_features(h3_id: str, radius_km: float = Query(25, gt=0, le=200), nearest: int = Query(5, ge=0, le=25)):
    """Vector context for one cell (resolution 0-6): polygons containing its centre, rivers crossing it,
    and for point layers the count inside the cell plus the nearest records within `radius_km` of its
    centre."""
    try:
        h3_id = geo.validate_cell(h3_id)
    except geo.InvalidCell as exc:
        raise HTTPException(404, str(exc)) from exc
    if h3.get_resolution(h3_id) > 6:
        raise HTTPException(422, "Use a cell of resolution 0 to 6.")
    lat, lon = h3.cell_to_latlng(h3_id)
    ring = [(p[1], p[0]) for p in h3.cell_to_boundary(h3_id)]
    lons = [p[0] for p in ring]
    if max(lons) - min(lons) > 180:  # crosses the antimeridian: unwrap so the polygon stays valid
        ring = [(x + 360 if x < 0 else x, y) for x, y in ring]
    cell_poly = Polygon(ring)

    out = []
    for meta in features.manifest()["layers"]:
        if not features.available(meta) or meta["geometry"] == "table":
            continue
        bbox = meta.get("bbox")
        pad = radius_km / 100  # ~degrees; generous
        if bbox and not (bbox[0] - pad <= lon <= bbox[2] + pad and bbox[1] - pad <= lat <= bbox[3] + pad):
            continue
        data = features.load(meta)
        entry = {"layer": meta["id"], "name": meta["name"], "geometry": meta["geometry"]}
        if isinstance(data, PointLayer):
            inside = data.in_cell(h3_id)
            near = data.nearest(lon, lat, radius_km, nearest) if nearest else []
            if len(inside) == 0 and not near:
                continue
            entry["inCell"] = int(len(inside))
            entry["nearest"] = [{**data.props(i), "lon": data.lon[i], "lat": data.lat[i], "distanceKm": round(d, 2)}
                                for i, d in near]
            entry["radiusKm"] = radius_km
        elif meta["geometry"] == "polygon":
            hits = data.containing(lon, lat)
            if not hits:
                continue
            entry["features"] = [data.features[i]["properties"] for i in hits]
        else:  # lines crossing the cell, biggest value first
            hits = data.intersecting(cell_poly)
            if not hits:
                continue
            vf = meta.get("valueField")
            if vf:
                hits.sort(key=lambda i: -(data.features[i]["properties"].get(vf) or 0))
            entry["count"] = len(hits)
            entry["features"] = [data.features[i]["properties"] for i in hits[:5]]
        out.append(entry)
    return {"h3Id": h3_id, "centre": {"latitude": lat, "longitude": lon}, "layers": out}


def _imagery_manifest() -> dict:
    p = features.features_dir().parent / "imagery" / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"scenes": []}


@router.get("/imagery")
def imagery_manifest():
    """Prepared true-colour scene clips (EPSG:4326 PNGs) with bounds, date and attribution."""
    scenes = _imagery_manifest()["scenes"]
    return {"scenes": [{**s, "url": f"/api/imagery/{s['id']}.png"} for s in scenes]}


@router.get("/imagery/{scene_id}.png")
def imagery_png(scene_id: str):
    scene = next((s for s in _imagery_manifest()["scenes"] if s["id"] == scene_id), None)
    if scene is None:
        raise HTTPException(404, f"Unknown scene: {scene_id}")
    return FileResponse(features.features_dir().parent / "imagery" / scene["file"], media_type="image/png")
