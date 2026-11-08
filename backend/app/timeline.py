"""Read-only timeline inputs. Atmospheric baselines remain immutable and dated.

Daily resource/emission totals use the existing building calculator without stress multipliers.
The browser applies an explicitly illustrative transport model; this module does not turn
emission mass into observed concentrations or convert column measurements to surface values.
"""
from __future__ import annotations

import math

import h3
import numpy as np

from app import h3store, layers
from app.building_assess import ScenarioContext, location_context
from app.building_calc import calculate
from app import timeline_environment
from app.local_wind import local_wind


def baseline(cells: list[str], layer_id: str) -> list[float | None]:
    layer = layers.BY_ID[layer_id]
    source = layers.source_for(layer, layer.slice("2024-ann"))
    if source is None or not cells:
        return [None] * len(cells)
    values = h3store.lookup(source, 6, np.array([int(c, 16) for c in cells], dtype=np.uint64))
    return [float(v) if math.isfinite(v) else None for v in values]


def timeline_inputs(ctx: ScenarioContext) -> dict:
    # Bounded local display domains, roughly 50 km around each placed project. No global enumeration.
    cells: set[str] = set()
    for building in ctx.buildings:
        cells.update(h3.grid_disk(building.h3_id, 8))
        if len(cells) * 7 > 25_000:
            raise ValueError("Timeline covers too many separate locations (limit 25,000 cells). Use a smaller world.")
    ordered = sorted(cells)
    pm25, pm10 = baseline(ordered, "cams_pm25"), baseline(ordered, "cams_pm10")
    # Finer display cells show the illustrative plume, but never upsample the measured background:
    # each child repeats its parent's baseline (itself sampled from the much coarser CAMS grid).
    display_cells = []
    for i, parent in enumerate(ordered):
        for cell in sorted(h3.cell_to_children(parent, 7)):
            lat, lon = h3.cell_to_latlng(cell)
            display_cells.append({"h3Id": cell, "latitude": lat, "longitude": lon,
                                  "pm25": pm25[i], "pm10": pm10[i]})
    projects = []
    for b in ctx.buildings:
        result = calculate(b.type, b.snapshot.stats, b.parameters, 1, location=location_context(b.h3_id))
        projects.append({
            "id": str(b.id), "name": b.name, "type": b.type,
            "latitude": b.latitude, "longitude": b.longitude,
            "displayCell": h3.latlng_to_cell(b.latitude, b.longitude, 7),
            # Long-term climate wind at the building (None when the wind grid is not prepared).
            "wind": local_wind(b.latitude, b.longitude),
            "emissions": [{"pollutant": e.pollutant, "medium": e.medium, "kgPerDay": e.quantity.value,
                           "missing": e.quantity.missing} for e in result.emissions],
            "electricityKwhPerDay": result.electricity_demand.value,
            "waterM3PerDay": result.water_demand.value,
            "electricityOutputKwhPerDay": result.electricity_output.value,
            "waterOutputM3PerDay": result.water_output.value,
        })
    media = {e['medium'] for p in projects for e in p['emissions']}
    if media & {'soil', 'marine'}:
        timeline_environment.surfaces(display_cells)
    cells_by_id = {c['h3Id']: c for c in display_cells}
    for p in projects:
        own_media = {e['medium'] for e in p['emissions']}
        if 'freshwater' in own_media:
            p['river'] = timeline_environment.river_release(p['longitude'], p['latitude'])
            for river_cell in p['river']['cells']:
                cell = river_cell['h3Id']
                if cell not in cells_by_id:
                    lat, lon = h3.cell_to_latlng(cell)
                    cells_by_id[cell] = {'h3Id': cell, 'latitude': lat, 'longitude': lon,
                                         'pm25': None, 'pm10': None, 'surface': 'water'}
        if 'marine' in own_media:
            p['marineRelease'] = timeline_environment.marine_release(p['longitude'], p['latitude'], display_cells)
    if len(cells_by_id) > 25_000:
        raise ValueError('Timeline covers too many cells (limit 25,000). Use a smaller world.')
    return {
        "projects": projects,
        "cells": list(cells_by_id.values()),
        "baseline": {"label": "CAMS 2024 annual mean", "period": "2024", "resolution": "0.75° (~80 km)",
                     "sourceId": "AIR-02", "units": "µg/m³"},
    }
