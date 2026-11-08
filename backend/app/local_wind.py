"""Long-term local wind at a building, for the Timeline's illustrative air transport.

Reads ``power_wind10m_annual_grid.npz`` (NASA POWER MERRA-2 annual climatology, prepared by
``scripts/fetch_power_wind.py``) and returns the value of the native grid cell nearest the point.
``(u, v)`` is the vector-mean wind, i.e. the net long-term drift, so its speed is at most the mean
wind speed. This is reanalysis climatology at ~0.5 x 0.625 deg, not a forecast or terrain-resolved wind.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import settings

FILE = "power_wind10m_annual_grid.npz"


@lru_cache(maxsize=4)
def _grid(path: str, mtime: float) -> dict | None:
    with np.load(path) as data:
        meta = json.loads(str(data["meta"]))
        return {"meta": meta, "u": data["u10m"].copy(), "v": data["v10m"].copy(), "speed": data["ws10m"].copy()}


def _load() -> dict | None:
    path = Path(settings.prepared_data_dir) / FILE
    if not path.exists():
        return None
    return _grid(str(path), path.stat().st_mtime)


def direction_from(u: float, v: float) -> float:
    """Meteorological direction the wind blows FROM, degrees clockwise from north."""
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def local_wind(latitude: float, longitude: float) -> dict | None:
    grid = _load()
    if grid is None or not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    g = grid["meta"]["grid"]
    scale = 100.0
    iy = min(max(round((latitude - g["lat0"]) / g["dlat"]), 0), g["nlat"] - 1)
    ix = round((longitude - g["lon0"]) / g["dlon"]) % g["nlon"]
    u, v = float(grid["u"][iy, ix]) / scale, float(grid["v"][iy, ix]) / scale
    drift = math.hypot(u, v)
    return {
        "u": u, "v": v,
        "speed": round(drift, 2),
        "fromDegrees": round(direction_from(u, v), 1) if drift > 0 else None,
        "meanSpeed": float(grid["speed"][iy, ix]) / scale,
        "gridLatitude": g["lat0"] + iy * g["dlat"], "gridLongitude": g["lon0"] + ix * g["dlon"],
        "source": "NASA POWER MERRA-2 · 10 m · long-term annual mean",
    }
