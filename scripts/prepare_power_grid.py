"""OSM electricity grid summarised per H3 resolution-6 cell, for the prepared regions.

Run from the repo root:

  uv run --no-project --with h3 --with pyarrow --with numpy python -I scripts/prepare_power_grid.py [--fetch]

`--fetch` (re)downloads the Overpass responses into data/raw/GRID-OSM/<region>/ (tiled, so no single
query times out). Without it the script reuses the copies already there.

Per cell it records what OSM maps there, nothing more:

- ``line_max_kv``        highest voltage of a power line/cable crossing the cell (lines are densified
                         to ~300 m steps, so every cell a line passes through is hit)
- ``substation_max_kv``  highest voltage of a substation whose centre is in the cell
- ``n_substations``      substations whose centre is in the cell
- ``plant_output_kw``    summed tagged nameplate output of plants whose centre is in the cell

Voltages and outputs are OSM tags (volunteer-mapped). They are not spare capacity or connection
headroom; the backend turns voltage into an indicative connectable capacity and says so.

Writes:
  data/prepared/power_grid_{region}_h3r6.parquet   h3 (uint64, sorted) + the columns above
  data/prepared/power_grid_{region}_h3r6.json      sidecar: provenance, method, caveats
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "GRID-OSM"
OUT = ROOT / "data" / "prepared"
OVERPASS = "https://overpass-api.de/api/interpreter"
REGIONS = {"arizona": (-113.5, 31.3, -109.0, 34.5), "uk": (-8.7, 49.8, 1.9, 60.9)}
TILE_DEG = 2.0
RES = 6
STEP_KM = 0.3

UNIT_TO_KW = {"w": 1e-3, "kw": 1.0, "mw": 1e3, "gw": 1e6}
POWER_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(w|kw|mw|gw)\s*$", re.IGNORECASE)


def parse_kw(raw):
    m = POWER_RE.match(str(raw)) if raw else None
    return float(m.group(1).replace(",", ".")) * UNIT_TO_KW[m.group(2).lower()] if m else None


def parse_kv(raw) -> float | None:
    vals = [int(p) / 1000 for p in str(raw or "").split(";") if p.strip().isdigit()]
    return max(vals) if vals else None


def tiles(box):
    w, s, e, n = box
    y = s
    while y < n:
        x = w
        while x < e:
            yield (round(y, 4), round(x, 4), round(min(y + TILE_DEG, n), 4), round(min(x + TILE_DEG, e), 4))
            x += TILE_DEG
        y += TILE_DEG


def query(bb: str) -> str:
    return (
        "[out:json][timeout:180];"
        f'way["power"~"^(line|minor_line|cable)$"]["voltage"]({bb});out tags geom;'
        f'nwr["power"="substation"]({bb});out tags center;'
        f'nwr["power"="plant"]({bb});out tags center;'
    )


def fetch(region: str) -> None:
    d = RAW / region
    d.mkdir(parents=True, exist_ok=True)
    for i, (s, w, n, e) in enumerate(tiles(REGIONS[region])):
        path = d / f"tile_{i:03d}.json"
        if path.exists():
            continue
        body = urllib.parse.urlencode({"data": query(f"{s},{w},{n},{e}")}).encode()
        for attempt in range(5):
            try:
                req = urllib.request.Request(OVERPASS, data=body, headers={"User-Agent": "the-creator-prepare-grid/0.1"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    raw = r.read()
                json.loads(raw)  # must be JSON (rate-limit pages are HTML)
                path.write_bytes(raw)
                print(f"{region} tile {i}: {len(raw) / 1e6:.1f} MB")
                break
            except Exception as exc:  # noqa: BLE001 - retry any transport/rate-limit failure
                wait = 20 * (attempt + 1)
                print(f"{region} tile {i}: {exc}; retrying in {wait}s")
                time.sleep(wait)
        else:
            raise SystemExit(f"{region} tile {i} failed")
        time.sleep(3)
    (d / "source.json").write_text(json.dumps({
        "id": f"GRID-OSM-{region}-{date.today():%Y%m%d}",
        "provider": "OpenStreetMap contributors via Overpass API",
        "licence": {"name": "ODbL-1.0", "attribution": "© OpenStreetMap contributors"},
        "accessUrl": OVERPASS,
        "region": region,
        "bbox": REGIONS[region],
        "tileDegrees": TILE_DEG,
        "query": query("{bbox}"),
        "retrievedAt": date.today().isoformat(),
        "evidenceType": "reported_record",
    }, indent=2) + "\n")


def _densify(coords):
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
        dy = (lat2 - lat1) * 110.57
        steps = max(1, int(math.hypot(dx, dy) / STEP_KM))
        for k in range(steps):
            t = k / steps
            yield lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t
    if coords:
        yield coords[-1][1], coords[-1][0]


def build(region: str) -> None:
    w, s, e, n = REGIONS[region]
    line_kv: dict[int, float] = {}
    sub_kv: dict[int, float] = {}
    n_sub: dict[int, int] = {}
    plant_kw: dict[int, float] = {}
    seen: set[tuple[str, int]] = set()  # tiles overlap at their edges
    counts = {"lines": 0, "substations": 0, "plants": 0}

    def inside(lat, lon):
        return s <= lat <= n and w <= lon <= e

    for path in sorted((RAW / region).glob("tile_*.json")):
        for el in json.loads(path.read_text()).get("elements", []):
            key = (el["type"], el["id"])
            if key in seen:
                continue
            seen.add(key)
            t = el.get("tags", {})
            kind = t.get("power")
            if kind in ("line", "minor_line", "cable"):
                kv = parse_kv(t.get("voltage"))
                geom = [(p["lon"], p["lat"]) for p in el.get("geometry") or [] if p]
                if kv is None or len(geom) < 2:
                    continue
                counts["lines"] += 1
                for lat, lon in _densify(geom):
                    if inside(lat, lon):
                        c = int(h3.latlng_to_cell(lat, lon, RES), 16)
                        line_kv[c] = max(line_kv.get(c, 0.0), kv)
                continue
            c0 = el.get("center") or el
            if "lat" not in c0 or not inside(c0["lat"], c0["lon"]):
                continue
            c = int(h3.latlng_to_cell(c0["lat"], c0["lon"], RES), 16)
            if kind == "substation":
                counts["substations"] += 1
                n_sub[c] = n_sub.get(c, 0) + 1
                kv = parse_kv(t.get("voltage"))
                if kv is not None:
                    sub_kv[c] = max(sub_kv.get(c, 0.0), kv)
            elif kind == "plant":
                counts["plants"] += 1
                kw = parse_kw(t.get("plant:output:electricity"))
                if kw is not None:
                    plant_kw[c] = plant_kw.get(c, 0.0) + kw

    cells = np.array(sorted(set(line_kv) | set(sub_kv) | set(n_sub) | set(plant_kw)), dtype=np.uint64)
    col = lambda d, default=np.nan: np.array([d.get(int(c), default) for c in cells], dtype=np.float64)  # noqa: E731
    table = pa.table({
        "h3": pa.array(cells, type=pa.uint64()),
        "line_max_kv": col(line_kv),
        "substation_max_kv": col(sub_kv),
        "n_substations": col(n_sub, 0.0),
        "plant_output_kw": col(plant_kw),
    })
    out = OUT / f"power_grid_{region}_h3r6.parquet"
    pq.write_table(table, out)
    src = json.loads((RAW / region / "source.json").read_text()) if (RAW / region / "source.json").exists() else {}
    (OUT / f"power_grid_{region}_h3r6.json").write_text(json.dumps({
        "layer": f"power_grid_{region}",
        "sourceId": "GRID-OSM",
        "provider": "OpenStreetMap contributors via Overpass API",
        "licence": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "evidenceType": "reported_record",
        "retrievedAt": src.get("retrievedAt"),
        "region": region,
        "regionBbox": REGIONS[region],
        "h3Resolution": RES,
        "counts": counts,
        "cells": int(len(cells)),
        "method": (f"Overpass power=line/minor_line/cable ways with a voltage tag, densified to {STEP_KM} km steps "
                   "and indexed to every res-6 cell they cross (max voltage kept); power=substation and power=plant "
                   "features indexed by their centre."),
        "units": {"line_max_kv": "kV", "substation_max_kv": "kV", "n_substations": "count",
                  "plant_output_kw": "kW (tagged nameplate, plant:output:electricity)"},
        "limitations": [
            "Volunteer-mapped; coverage and voltage tagging vary. A cell with no mapped line may still have one.",
            "Voltage is not spare capacity or a connection offer; capacity is inferred from voltage by the backend.",
            "Underground distribution cables are rarely mapped.",
        ],
    }, indent=2) + "\n")
    print(f"{region}: {len(cells)} cells, {counts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("regions", nargs="*", default=list(REGIONS))
    args = ap.parse_args()
    for r in args.regions:
        if args.fetch:
            fetch(r)
        build(r)


if __name__ == "__main__":
    main()
