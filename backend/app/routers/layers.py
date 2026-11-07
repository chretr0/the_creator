"""H3 cell layers: catalogue, viewport values at the display resolution, and per-cell profiles."""

from __future__ import annotations

import math
from functools import lru_cache

import h3
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import geo, h3store, layers
from app.layers import BY_ID, LAYERS, LayerDef, Slice

router = APIRouter(prefix="/api", tags=["layers"])

MAX_CELLS = 20_000
RES6_AVG_AREA_KM2 = h3.average_hexagon_area(6, unit="km^2")


class ValuesRequest(BaseModel):
    slice: str | None = None
    cells: list[str] = Field(max_length=MAX_CELLS)


def _layer(layer_id: str) -> LayerDef:
    layer = BY_ID.get(layer_id)
    if layer is None:
        raise HTTPException(404, f"Unknown layer: {layer_id}")
    return layer


def _slice(layer: LayerDef, slice_id: str | None) -> Slice:
    try:
        return layer.slice(slice_id)
    except KeyError:
        raise HTTPException(404, f"Layer {layer.id} has no slice {slice_id!r}") from None


def _source(layer: LayerDef, s: Slice) -> h3store.Source:
    src = layers.source_for(layer, s)
    if src is None:
        raise HTTPException(503, f"{layer.name} ({s.label}) is not prepared yet.")
    return src


def _transform(layer: LayerDef, s: Slice, vals: np.ndarray, areas_km2: np.ndarray | float) -> np.ndarray:
    display = layers.slice_display(layer, s)
    if display == "density":
        return vals / areas_km2 * layer.density_factor
    if display == "percent":
        return vals * 100.0
    return vals


def _sig(v: float) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return float(f"{v:.4g}")


@lru_cache(maxsize=512)
def _domain(layer_id: str, slice_id: str) -> list[float] | None:
    layer = BY_ID[layer_id]
    s = layer.slice(slice_id)
    if layers.is_categorical(layer, s):
        return None
    own_units = s.units is None and s.display is None
    if layer.domain and own_units:
        return list(layer.domain)
    src = layers.source_for(layer, s)
    if src is None:
        return None
    display = layers.slice_display(layer, s)
    qs = (0.05, 0.995) if layer.scale_type == "log" else (0.02, 0.98)
    q = h3store.quantiles(src, qs)
    if q is None:
        return None
    vals = _transform(layer, s, np.array(q), RES6_AVG_AREA_KM2)
    lo, hi = float(vals[0]), float(vals[1])
    if layer.scale_type == "log":
        lo = max(lo, hi / 1e4, 1e-6)
    if display == "percent":
        lo, hi = 0.0, min(100.0, max(hi, 1.0))
    if hi <= lo:
        hi = lo + 1.0
    return [_sig(lo), _sig(hi)]


@router.get("/layers")
def list_layers():
    """Every H3 layer the app knows about, with slices, units, colour hints and provenance.
    `available: false` means its prepared file is not on disk yet."""
    return [layers.describe(layer) for layer in LAYERS]


@router.get("/layers/{layer_id}")
def get_layer(layer_id: str):
    return layers.describe(_layer(layer_id))


@router.post("/layers/{layer_id}/values")
def layer_values(layer_id: str, body: ValuesRequest):
    """Values for the given cells (all at one display resolution ≤ 6), aligned with the request.

    Coarser cells aggregate their resolution-6 children (mean, sum or most-common class) using only
    children with data. `null` means no data, never zero. Sum layers are returned as densities so
    colours are comparable across zoom levels.
    """
    layer = _layer(layer_id)
    s = _slice(layer, body.slice)
    src = _source(layer, s)
    if not body.cells:
        return {"layer": layer.id, "slice": s.id, "resolution": None, "values": [], "domain": _domain(layer.id, s.id)}
    try:
        ids = [geo.validate_cell(c) for c in body.cells]
    except geo.InvalidCell as exc:
        raise HTTPException(422, str(exc)) from exc
    res = h3.get_resolution(ids[0])
    if res > h3store.SIM_RES or any(h3.get_resolution(c) != res for c in ids):
        raise HTTPException(422, "All cells must share one resolution between 0 and 6.")

    cells = np.array([int(c, 16) for c in ids], dtype=np.uint64)
    raw = h3store.lookup(src, res, cells).astype(np.float64)
    if layers.slice_display(layer, s) == "density":
        areas = np.array([h3.cell_area(c, unit="km^2") for c in ids])
    else:
        areas = 1.0
    vals = _transform(layer, s, raw, areas)
    return {
        "layer": layer.id,
        "slice": s.id,
        "resolution": res,
        "units": layers.slice_units(layer, s),
        "values": [_sig(v) for v in vals],
        "domain": _domain(layer.id, s.id),
        "withData": int(np.count_nonzero(~np.isnan(vals))),
    }


@router.get("/layers/{layer_id}/domain")
def layer_domain(layer_id: str, slice: str | None = None):
    layer = _layer(layer_id)
    s = _slice(layer, slice)
    _source(layer, s)
    return {"layer": layer.id, "slice": s.id, "domain": _domain(layer.id, s.id), "units": layers.slice_units(layer, s)}


def _slice_values(layer: LayerDef, files: tuple, slices: list[Slice], cell: int, res: int) -> dict[str, tuple]:
    """(value in stored units, children with data) per slice id, for a cell at any resolution ≤ 6."""
    cols = sorted({s.column for s in slices})
    if res == h3store.SIM_RES:
        got = h3store.point_values(files, layer.key_column, cols, cell)
        return {s.id: (got.get(s.column), None) for s in slices}
    lo, hi = h3store.descendant_range(cell)
    got = h3store.range_values(files, layer.key_column, cols, lo, hi)
    return {s.id: h3store.combine(got[s.column], s.agg or layer.agg) for s in slices}


def _attributes(layer: LayerDef, files: tuple, cell: int, res: int) -> list[dict]:
    """Descriptive columns of a single simulation cell (e.g. Aqueduct's category label)."""
    if not layer.attributes or res != h3store.SIM_RES:
        return []
    got = h3store.point_values(files, layer.key_column, [c for c, _ in layer.attributes], cell)
    return [{"key": c, "label": label, "value": got[c]} for c, label in layer.attributes if got.get(c) is not None]


@lru_cache(maxsize=256)
def _profile(h3_id: str) -> dict:
    cell = int(h3_id, 16)
    res = h3.get_resolution(h3_id)
    area = h3.cell_area(h3_id, unit="km^2")
    lat, lon = h3.cell_to_latlng(h3_id)
    region = layers.region_at(lat, lon)
    out = []
    for layer in LAYERS:
        by_files: dict[tuple, list[Slice]] = {}
        for s in layer.slices:
            files = tuple(layers.slice_files(s))
            if files:
                by_files.setdefault(files, []).append(s)
        if not by_files:
            continue
        values = []
        for files, slices in by_files.items():
            got = _slice_values(layer, files, slices, cell, res)
            for s in slices:
                v, n = got[s.id]
                if v is not None:
                    v = float(v) / (s.scale or layer.scale)
                shown = None if v is None else float(_transform(layer, s, np.array([v]), area)[0])
                values.append({
                    "slice": s.id,
                    "label": s.label,
                    "group": s.group,
                    "value": _sig(v) if v is not None else None,
                    "display": _sig(shown) if shown is not None else None,
                    "units": layers.slice_units(layer, s),
                    "rawUnits": s.units or layer.units or None,
                    "cellsWithData": n,
                    "categorical": layers.is_categorical(layer, s),
                })
        order = {s.id: i for i, s in enumerate(layer.slices)}
        values.sort(key=lambda x: order[x["slice"]])
        attributes = _attributes(layer, next(iter(by_files)), cell, res)
        if all(v["value"] is None for v in values) and not attributes and layer.coverage == "regions":
            continue  # outside the prepared regions: say nothing rather than "no data"
        out.append({
            "layer": layer.id,
            "name": layer.name,
            "category": layer.category,
            "coverage": layer.coverage,
            "categorical": bool(layer.categories),
            "categories": layer.categories,
            "values": values,
            "attributes": attributes,
            "source": layers.cell_source(layer, region),
        })
    return {
        "h3Id": h3_id,
        "resolution": res,
        "region": region,
        "areaKm2": area,
        "simulationCells": h3.cell_to_children_size(h3_id, h3store.SIM_RES),
        "layers": out,
    }


@router.get("/cells/{h3_id}/profile")
def cell_profile(h3_id: str):
    """Every prepared H3 layer's values for one cell (all slices, e.g. monthly series).

    A resolution-6 cell returns its own values. A coarser cell (a zoomed-out display hexagon) returns
    the same aggregate the map colours it by: the mean, sum or most common class of its resolution-6
    descendants that have data, with `cellsWithData` saying how many that was.
    """
    try:
        h3_id = geo.validate_cell(h3_id)
    except geo.InvalidCell as exc:
        raise HTTPException(404, str(exc)) from exc
    if h3.get_resolution(h3_id) > h3store.SIM_RES:
        raise HTTPException(422, "Profiles are defined for cells of resolution 0 to 6.")
    return _profile(h3_id)
