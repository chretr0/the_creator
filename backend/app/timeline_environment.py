"""Local receiving environments for illustrative timelines, using prepared geography only.

River direction is NEXT_DOWN topology, never wind. Coastal cells use the simplified land boundary.
Unmapped receiving waters stay unknown; no river/sea connection is invented for inland sites.
"""
import json
import math
from functools import lru_cache

import h3
import shapely
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, substring
from shapely.strtree import STRtree

from app.config import settings
from pathlib import Path


def distance(a, b):
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(((b[0] - a[0] + 540) % 360) - 180)
    q = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(q)))


@lru_cache(maxsize=4)
def _index(path: str, mtime: float):
    rows = json.loads(Path(path).read_text())['features']
    geoms = [shapely.make_valid(shape(f['geometry'])) for f in rows]
    return rows, geoms, STRtree(geoms)


def surfaces(cells: list[dict]) -> None:
    path = Path(settings.prepared_data_dir) / 'boundaries/countries.geojson'
    if not path.exists():
        for c in cells:
            c['surface'] = 'unknown'
        return
    _, _, tree = _index(str(path), path.stat().st_mtime)
    points = shapely.points([c['longitude'] for c in cells], [c['latitude'] for c in cells])
    land = set(tree.query(points, predicate='intersects')[0].tolist())
    for i, cell in enumerate(cells):
        cell['surface'] = 'land' if i in land else 'marine'


def river_release(lon: float, lat: float) -> dict:
    path = Path(settings.prepared_data_dir) / 'features/hydrorivers.geojson'
    missing = {'cells': [], 'distanceKm': None, 'note': 'No mapped river within 10 km. Release total is known; river concentration is unknown.'}
    if not path.exists():
        return missing
    rows, geoms, tree = _index(str(path), path.stat().st_mtime)
    point = Point(lon, lat)
    # Degree-space nearest candidates, ranked by geodesic distance to the snapped point.
    nearby = tree.query(point.buffer(.3))
    if not len(nearby):
        return missing
    choices = [(distance((lon, lat), tuple(nearest_points(point, geoms[int(i)])[1].coords)[0]), int(i)) for i in nearby]
    nearest, idx = min(choices)
    if nearest > 10_000:
        return missing
    lookup = {str(r['properties']['hyrivId']): i for i, r in enumerate(rows)}
    upstream = {}
    for i, row in enumerate(rows):
        upstream.setdefault(str(row['properties'].get('nextDown')), []).append(i)
    visited, cell_rows = set(), {}
    travelled, entry = 0.0, nearest_points(point, geoms[idx])[1]
    while idx not in visited and travelled < 30_000:
        visited.add(idx)
        props, line = rows[idx]['properties'], geoms[idx]
        if line.geom_type != 'LineString':
            break
        next_idx = lookup.get(str(props.get('nextDown')))
        coords = list(line.coords)
        if next_idx is not None:
            # End nearest the next downstream reach is downstream, regardless of source vertex order.
            next_line = geoms[next_idx]
            if Point(coords[0]).distance(next_line) < Point(coords[-1]).distance(next_line):
                coords.reverse()
        elif len(visited) == 1:
            # Terminal/coastal reaches have no NEXT_DOWN. Connected upstream reaches still
            # establish their direction; never infer flow from wind or arbitrary vertex order.
            incoming = upstream.get(str(props['hyrivId']), [])
            if not incoming:
                return {'cells': [], 'distanceKm': round(nearest / 1000, 2),
                        'note': 'A nearby river is mapped, but its flow direction is unavailable. Release total is known; river concentration is unknown.'}
            start_distance = min(Point(coords[0]).distance(geoms[i]) for i in incoming)
            end_distance = min(Point(coords[-1]).distance(geoms[i]) for i in incoming)
            if end_distance < start_distance:
                coords.reverse()
        elif Point(coords[-1]).distance(entry) < Point(coords[0]).distance(entry):
            coords.reverse()
        line = LineString(coords)
        part = substring(line, line.project(entry), line.length)
        flow = props.get('disAvCms')
        flow = float(flow) if isinstance(flow, (int, float)) and math.isfinite(flow) and flow > 0 else None
        if part.geom_type == 'Point':
            cell = h3.latlng_to_cell(part.y, part.x, 7)
            cell_rows.setdefault(cell, {'h3Id': cell, 'distanceM': round(travelled, 2), 'flowM3PerSecond': flow})
            if next_idx is None:
                break
            entry, idx = part, next_idx
            continue
        if part.geom_type != 'LineString':
            break
        points = list(part.coords)
        for a, b in zip(points, points[1:]):
            length = distance(a, b)
            steps = max(1, math.ceil(length / 400))
            for step in range(steps + 1):
                fraction = step / steps
                d = travelled + fraction * length
                if d > 30_000:
                    break
                x, y = a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction
                cell = h3.latlng_to_cell(y, x, 7)
                if cell not in cell_rows:
                    cell_rows[cell] = {'h3Id': cell, 'distanceM': round(d, 2), 'flowM3PerSecond': flow}
            travelled += length
            if travelled >= 30_000:
                break
        if next_idx is None:
            break
        entry = Point(coords[-1])
        idx = next_idx
    if not cell_rows:
        return missing
    return {'cells': list(cell_rows.values()), 'distanceKm': round(nearest / 1000, 2),
            'note': f'Assumes discharge into the nearest mapped river ({nearest / 1000:.1f} km away). Follows HydroRIVERS NEXT_DOWN for up to 30 km; uses long-term average flow, not current flow. Actual discharge connection is unverified.'}


def marine_release(lon: float, lat: float, cells: list[dict]) -> dict:
    nearby = [(distance((lon, lat), (c['longitude'], c['latitude'])), c)
              for c in cells if c.get('surface') == 'marine']
    nearest, cell = min(nearby, key=lambda x: x[0]) if nearby else (math.inf, None)
    if nearest > 20_000 or cell is None:
        return {'latitude': None, 'longitude': None, 'note': 'No mapped sea within 20 km. Release total is known; marine concentration is unknown.'}
    return {'latitude': cell['latitude'], 'longitude': cell['longitude'],
            'note': f'Illustrative outfall at the nearest coastal-water cell ({nearest / 1000:.1f} km away). Simplified coastline; actual discharge connection is unverified.'}
