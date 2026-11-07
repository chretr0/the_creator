"""Fast lookups over the prepared H3 resolution-6 Parquet layers.

Each (source files, column) pair is materialised once into the cache directory:

- ``keys_r6.npy``     sorted uint64 H3 indexes shared by every column of the same files
- ``<col>_r6.npy``    float32 values aligned with the keys (NaN = no data)
- ``<col>_r{0..5}_keys.npy`` / ``_vals.npy``  coarser levels aggregated from resolution 6

Arrays are memory-mapped, so a 14 M-cell global layer costs a few page reads per lookup instead of
hundreds of MB of RAM. Values are never invented: a parent cell's value only uses children that
have data, and ``n`` (children with data) is kept so sparse coverage stays visible.

Parquet stays the source of truth (data/STATUS.md): delete ``data/cache/h3`` to rebuild.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from app.config import settings

SIM_RES = 6
_RES_SHIFT = np.uint64(52)
_RES_MASK = np.uint64(0xF) << _RES_SHIFT

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def parent_index(cells: np.ndarray, res: int) -> np.ndarray:
    """Vectorised H3 cell_to_parent for uint64 arrays (every input at a finer resolution)."""
    low = (np.uint64(1) << np.uint64(3 * (15 - res))) - np.uint64(1)
    return (cells & ~_RES_MASK & ~low) | (np.uint64(res) << _RES_SHIFT) | low


def cell_int(h3_hex: str) -> int:
    return int(h3_hex, 16)


def cell_hex(value: int) -> str:
    return format(int(value), "x")


def cache_root() -> Path:
    return Path(settings.cache_dir) / "h3"


@dataclass(frozen=True)
class Source:
    """One logical layer column, possibly spread over several region files."""

    files: tuple[Path, ...]
    key_column: str
    column: str
    agg: str  # "mean" | "sum" | "mode"
    scale: float = 1.0  # divide stored values by this

    @property
    def files_id(self) -> str:
        h = hashlib.sha1()
        for f in self.files:
            st = f.stat()
            h.update(f"{f.name}:{st.st_size}:{int(st.st_mtime)}".encode())
        h.update(self.key_column.encode())
        return h.hexdigest()[:16]

    def available(self) -> bool:
        return bool(self.files) and all(f.exists() for f in self.files)


class _Level:
    __slots__ = ("keys", "vals", "counts")

    def __init__(self, keys: np.ndarray, vals: np.ndarray, counts: np.ndarray | None):
        self.keys, self.vals, self.counts = keys, vals, counts

    def lookup(self, cells: np.ndarray) -> np.ndarray:
        out = np.full(cells.shape, np.nan, dtype=np.float32)
        if len(self.keys) == 0 or len(cells) == 0:
            return out
        idx = np.searchsorted(self.keys, cells)
        idx_c = np.minimum(idx, len(self.keys) - 1)
        hit = self.keys[idx_c] == cells
        out[hit] = self.vals[idx_c[hit]]
        return out


_levels: dict[tuple[str, str, int], _Level] = {}


def _dir_for(src: Source) -> Path:
    d = cache_root() / src.files_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_keys_and_column(src: Source) -> tuple[np.ndarray, np.ndarray]:
    keys_parts, val_parts = [], []
    for f in src.files:
        t = pq.read_table(f, columns=[src.key_column, src.column])
        keys_parts.append(t.column(0).to_numpy(zero_copy_only=False).astype(np.int64).view(np.uint64))
        v = t.column(1).to_numpy(zero_copy_only=False)
        val_parts.append(np.asarray(v, dtype=np.float64))
    keys = np.concatenate(keys_parts)
    vals = np.concatenate(val_parts)
    order = np.argsort(keys, kind="stable") if not np.all(keys[:-1] <= keys[1:]) else None
    if order is not None:
        keys, vals = keys[order], vals[order]
    if src.scale != 1.0:
        vals = vals / src.scale
    return keys, vals.astype(np.float32)


def _aggregate(keys: np.ndarray, vals: np.ndarray, res: int, agg: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ok = ~np.isnan(vals)
    k, v = keys[ok], vals[ok].astype(np.float64)
    if len(k) == 0:
        return k, v.astype(np.float32), np.zeros(0, np.int32)
    parents = parent_index(k, res)  # monotone in k, so already sorted
    starts = np.flatnonzero(np.r_[True, parents[1:] != parents[:-1]])
    pk = parents[starts]
    counts = np.diff(np.r_[starts, len(parents)]).astype(np.int32)
    if agg == "sum":
        out = np.add.reduceat(v, starts)
    elif agg == "mean":
        out = np.add.reduceat(v, starts) / counts
    elif agg == "mode":
        # Most frequent child value per parent (ties → smallest code).
        group = np.repeat(np.arange(len(starts)), counts)
        order = np.lexsort((v, group))
        g, vv = group[order], v[order]
        run_start = np.flatnonzero(np.r_[True, (g[1:] != g[:-1]) | (vv[1:] != vv[:-1])])
        run_len = np.diff(np.r_[run_start, len(g)])
        run_g = g[run_start]
        best = np.full(len(starts), -1)
        best_len = np.zeros(len(starts), dtype=np.int64)
        for i in np.argsort(run_len, kind="stable"):  # increasing length: last write wins
            best[run_g[i]] = i
            best_len[run_g[i]] = run_len[i]
        out = vv[run_start[best]]
    else:
        raise ValueError(f"unknown aggregation {agg}")
    return pk, out.astype(np.float32), counts


def _materialise(src: Source, res: int) -> _Level:
    d = _dir_for(src)
    col = src.column.replace("/", "_")
    vals_path = d / f"{col}_r{res}_vals.npy" if res < SIM_RES else d / f"{col}_r6.npy"
    keys_path = d / f"{col}_r{res}_keys.npy" if res < SIM_RES else d / "keys_r6.npy"
    counts_path = d / f"{col}_r{res}_n.npy"
    if vals_path.exists() and keys_path.exists():
        counts = np.load(counts_path, mmap_mode="r") if counts_path.exists() else None
        return _Level(np.load(keys_path, mmap_mode="r"), np.load(vals_path, mmap_mode="r"), counts)

    r6_keys, r6_vals = d / "keys_r6.npy", d / f"{col}_r6.npy"
    if r6_keys.exists() and r6_vals.exists():
        keys, vals = np.load(r6_keys), np.load(r6_vals)
    else:
        keys, vals = _read_keys_and_column(src)
        if not r6_keys.exists():
            _atomic_save(r6_keys, keys)
        _atomic_save(r6_vals, vals)
    if res == SIM_RES:
        return _Level(np.load(r6_keys, mmap_mode="r"), np.load(r6_vals, mmap_mode="r"), None)

    pk, pv, pn = _aggregate(keys, vals, res, src.agg)
    _atomic_save(keys_path, pk)
    _atomic_save(vals_path, pv)
    _atomic_save(counts_path, pn)
    return _Level(pk, pv, pn)


def _atomic_save(path: Path, arr: np.ndarray) -> None:
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, arr)
    tmp.replace(path)


def level(src: Source, res: int) -> _Level:
    if not 0 <= res <= SIM_RES:
        raise ValueError("resolution must be 0..6")
    key = (src.files_id, src.column, res)
    hit = _levels.get(key)
    if hit is not None:
        return hit
    with _lock(f"{src.files_id}:{src.column}"):
        hit = _levels.get(key)
        if hit is None:
            hit = _materialise(src, res)
            _levels[key] = hit
    return hit


def lookup(src: Source, res: int, cells: np.ndarray) -> np.ndarray:
    return level(src, res).lookup(cells)


@lru_cache(maxsize=256)
def _row_group_ranges(path: str, key_column: str, _mtime: float) -> list[tuple[int, int]]:
    md = pq.ParquetFile(path).metadata
    idx = md.schema.to_arrow_schema().get_field_index(key_column)
    out = []
    for i in range(md.num_row_groups):
        st = md.row_group(i).column(idx).statistics
        out.append((int(st.min), int(st.max)) if st is not None and st.has_min_max else (0, 2**64 - 1))
    return out


def point_values(files: tuple[Path, ...], key_column: str, columns: list[str], cell: int) -> dict[str, float | None]:
    """Values of several columns for one resolution-6 cell, reading only the row group that holds it."""
    for f in files:
        ranges = _row_group_ranges(str(f), key_column, f.stat().st_mtime)
        for i, (lo, hi) in enumerate(ranges):
            if not lo <= cell <= hi:
                continue
            pf = pq.ParquetFile(f)
            t = pf.read_row_group(i, columns=[key_column, *columns])
            keys = t.column(0).to_numpy(zero_copy_only=False).astype(np.int64).view(np.uint64)
            j = int(np.searchsorted(keys, np.uint64(cell)))
            if j < len(keys) and keys[j] == cell:
                out = {}
                for c in columns:
                    v = t.column(c)[j].as_py()
                    out[c] = None if v is None or (isinstance(v, float) and v != v) else v
                return out
    return {c: None for c in columns}


def quantiles(src: Source, qs: tuple[float, ...], density_area_km2: float | None = None) -> list[float] | None:
    """Robust colour domain from resolution-6 values (optionally as density per km²)."""
    vals = np.asarray(level(src, SIM_RES).vals)
    if len(vals) > 2_000_000:
        vals = vals[:: len(vals) // 2_000_000]
    vals = vals[~np.isnan(vals)]
    if density_area_km2:
        vals = vals / density_area_km2
    if len(vals) == 0:
        return None
    return [float(x) for x in np.quantile(vals, qs)]
