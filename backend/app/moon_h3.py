"""Moon H3 layers: the catalogue in data/prepared/moon/h3/layers.json and per-cell value lookups.

Each layer is one Parquet file (``h3`` uint64, ``res`` uint8, ``value`` float32 with NaN = no data,
``count`` uint32) holding every cell from resolution 0 to the layer's ``maxResolution``. It is read
lazily on first use into two arrays, sorted uint64 keys and float32 values (~12 bytes per row, so the
2.35 M-row LOLA elevation layer costs ~28 MB), and looked up with ``np.searchsorted``.

Cells finer than ``maxResolution`` resolve to their ancestor at ``maxResolution`` (a res-6 cell on a
res-5 layer gets its parent's value). Missing cells and NaN values come back as ``None``, never 0.

Paths come from ``settings.prepared_data_dir`` at call time; files are reloaded when their mtime or
size changes, and ``reset()`` drops every cache (tests).
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import h3
import numpy as np
import pyarrow.parquet as pq

from app import geo
from app.config import settings

MAX_CELLS = 20_000


class UnknownLayer(KeyError):
    pass


class LayerUnavailable(RuntimeError):
    """Listed in layers.json but its Parquet file is missing or unreadable."""


class InvalidCell(ValueError):
    pass


@dataclass(frozen=True)
class _Table:
    stamp: tuple[float, int]
    keys: np.ndarray  # sorted uint64
    vals: np.ndarray  # float32, NaN = no data


_lock = threading.Lock()
_catalogue: tuple[tuple[str, float, int], dict] | None = None
_tables: dict[str, _Table] = {}


def reset() -> None:
    global _catalogue
    with _lock:
        _catalogue = None
        _tables.clear()


def h3_dir() -> Path:
    return Path(settings.prepared_data_dir) / "moon" / "h3"


def _stamp(path: Path) -> tuple[float, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime, st.st_size


def catalogue() -> dict:
    """layers.json as {"layers": [...], "sources": {...}}; empty when not prepared."""
    global _catalogue
    path = h3_dir() / "layers.json"
    st = _stamp(path)
    if st is None:
        return {"layers": [], "sources": {}}
    key = (str(path), *st)
    cached = _catalogue
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"layers": [], "sources": {}}
    data = {"layers": list(data.get("layers") or []), "sources": dict(data.get("sources") or {})}
    with _lock:
        _catalogue = (key, data)
    return data


def _file(meta: dict) -> Path:
    return h3_dir() / (meta.get("file") or f"{meta['id']}.parquet")


def list_layers() -> list[dict]:
    """Catalogue entries plus ``available`` (the layer's Parquet file exists)."""
    return [{**m, "available": _file(m).exists()} for m in catalogue()["layers"] if m.get("id")]


def layer(layer_id: str) -> dict | None:
    return next((m for m in catalogue()["layers"] if m.get("id") == layer_id), None)


def _table(meta: dict) -> _Table:
    path = _file(meta)
    st = _stamp(path)
    if st is None:
        raise LayerUnavailable(f"Moon layer {meta['id']} is not prepared ({path.name} missing).")
    hit = _tables.get(meta["id"])
    if hit is not None and hit.stamp == st:
        return hit
    with _lock:
        hit = _tables.get(meta["id"])
        if hit is not None and hit.stamp == st:
            return hit
        try:
            t = pq.read_table(path, columns=["h3", "value"])
        except (OSError, ValueError, KeyError) as exc:
            raise LayerUnavailable(f"Moon layer {meta['id']} could not be read: {exc}") from exc
        keys = t.column("h3").to_numpy(zero_copy_only=False).astype(np.uint64, copy=False)
        vals = t.column("value").to_numpy(zero_copy_only=False).astype(np.float32, copy=False)
        if len(keys) > 1 and not np.all(keys[:-1] <= keys[1:]):
            order = np.argsort(keys, kind="stable")
            keys, vals = keys[order], vals[order]
        hit = _Table(st, np.ascontiguousarray(keys), np.ascontiguousarray(vals))
        _tables[meta["id"]] = hit
    return hit


def _clean(v: float) -> float | None:
    if not math.isfinite(v):
        return None
    return float(f"{v:.6g}")  # float32 carries ~7 significant digits


def validate_cells(cells: list[str]) -> list[str]:
    """Lower-cased H3 cell ids (geo.validate_cell's strict check); raises InvalidCell on the first bad one."""
    out = []
    for c in cells:
        try:
            out.append(geo.validate_cell(c))
        except geo.InvalidCell:
            raise InvalidCell(f"Not a valid H3 cell id: {c!r}") from None
    return out


def values(layer_id: str, cells: list[str]) -> dict:
    """{"values": {cell: number|None}, "servedResolution": {cell: res}} keyed by the ids as requested.

    Raises UnknownLayer, InvalidCell (bad id or too many cells) or LayerUnavailable.
    """
    meta = layer(layer_id)
    if meta is None:
        raise UnknownLayer(layer_id)
    if len(cells) > MAX_CELLS:
        raise InvalidCell(f"At most {MAX_CELLS} cells per request.")
    ids = validate_cells(cells)
    if not ids:
        return {"values": {}, "servedResolution": {}}
    max_res = int(meta.get("maxResolution", 15))
    table = _table(meta)

    served_ids = []
    served_res = []
    for c in ids:
        r = h3.get_resolution(c)
        if r > max_res:
            served_ids.append(h3.cell_to_parent(c, max_res))
            served_res.append(max_res)
        else:
            served_ids.append(c)
            served_res.append(r)
    query = np.fromiter((int(c, 16) for c in served_ids), dtype=np.uint64, count=len(served_ids))
    out = np.full(len(query), np.nan, dtype=np.float32)
    if len(table.keys):
        idx = np.minimum(np.searchsorted(table.keys, query), len(table.keys) - 1)
        hit = table.keys[idx] == query
        out[hit] = table.vals[idx[hit]]
    return {
        "values": {orig: _clean(float(v)) for orig, v in zip(cells, out)},
        "servedResolution": dict(zip(cells, served_res)),
    }
