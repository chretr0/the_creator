"""Build the per-region H3 resolution-6 baseline layers the app shows (data/prepared/layers/).

By default only the layers the app reads are built (DEFAULT_LAYERS: water stress). The other
builders duplicate existing app layers and run only when named with --layer.

Run (default set, or named layers):
  uv run --no-project --with rasterio --with duckdb --with pyarrow --with numpy --with h3 \
    --with shapely --with pyogrio --with xarray --with netcdf4 --with pyhdf --with pandas \
    python -I scripts/build_layers.py [--layer ID ...] [--region arizona|uk ...]

Reads only the regional raw copies in data/raw/<ID>/<region>/ (never the global ones) and writes

  data/prepared/layers/<layer_id>/<region>.parquet   h3 (uint64, ascending), value (nullable float),
                                                     n_valid / coverage columns, per-layer extras
  data/prepared/layers/<layer_id>/layer.json         meaning, units, period, support, aggregation,
                                                     colour hints, caveats, licence + attribution
                                                     copied from the referenced source.json records

Shared rules (CLAUDE-Data-Sources.md §16, CLAUDE-World-Mapping.md §9):
- Cells are the resolution-6 cells whose centre lies inside the region box (README §0.1). Only
  source pixels/points inside the box are used, so cells along the box edge can be partly covered;
  `n_valid` says how many source pixels/points contributed.
- Missing is null/absent, never zero. A cell with no valid input has no row (or a null value with
  a status column, e.g. Aqueduct "No Data" basins).
- Fine rasters (pixels much smaller than a ~36 km² cell): each valid pixel goes to the cell that
  contains its centre; intensive fields are averaged, counts are summed.
- Coarse grids (POWER 1°, ERA5-Land 0.1°, CAMS 0.75°, GRACE 0.25°): each cell takes the native grid
  cell containing its centre (no interpolation), and keeps that grid cell's ID in `support_id`, so
  repeated values are visibly one observation rather than many.
- Basin indices (Aqueduct): each cell takes the basin polygon containing its centre; the index is
  never averaged or split.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import glob
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "prepared" / "layers"
RES = 6
REGIONS = {
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(msg, flush=True)


def h3_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    return con


class Cells:
    """Resolution-6 cells whose centre lies in a region box, sorted by uint64 index."""

    def __init__(self, region: str):
        w, s, e, n = REGIONS[region]
        poly = h3.LatLngPoly([(s, w), (s, e), (n, e), (n, w)])
        ids = h3.polygon_to_cells(poly, RES)
        keys = np.array(sorted(int(c, 16) for c in ids), dtype=np.uint64)
        self.keys = keys
        ll = np.array([h3.cell_to_latlng(format(int(k), "x")) for k in keys])
        self.lat, self.lon = ll[:, 0], ll[:, 1]

    def index_of(self, keys: np.ndarray) -> np.ndarray:
        """Row in self.keys for each key, or -1 when the key is not a region cell."""
        keys = np.asarray(keys, dtype=np.uint64)
        idx = np.searchsorted(self.keys, keys)
        idx_c = np.minimum(idx, len(self.keys) - 1)
        return np.where(self.keys[idx_c] == keys, idx_c, -1)


class PixelAcc:
    """Streaming per-cell sum / count / min / max of point samples via DuckDB's h3 extension."""

    def __init__(self, cols: list[str]):
        self.cols = cols
        self.con = h3_con()
        defs = ", ".join(f"{c}_s DOUBLE, {c}_n BIGINT, {c}_mn DOUBLE, {c}_mx DOUBLE" for c in cols)
        self.con.execute(f"CREATE TABLE acc (h3 UBIGINT, {defs})")

    def add(self, lat: np.ndarray, lon: np.ndarray, **vals: np.ndarray) -> None:
        if len(lat) == 0:
            return
        tbl = pa.table({"lat": lat.astype(np.float64), "lng": lon.astype(np.float64),
                        **{c: pa.array(np.asarray(vals[c], dtype=np.float64), from_pandas=True) for c in self.cols}})
        aggs = ", ".join(f"sum({c}), count({c}), min({c}), max({c})" for c in self.cols)
        self.con.register("batch", tbl)
        self.con.execute(f"INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {RES}), {aggs} FROM batch GROUP BY 1")
        self.con.unregister("batch")

    def result(self) -> dict[str, np.ndarray]:
        aggs = ", ".join(f"sum({c}_s) AS {c}_s, sum({c}_n) AS {c}_n, min({c}_mn) AS {c}_mn, max({c}_mx) AS {c}_mx"
                         for c in self.cols)
        t = self.con.sql(f"SELECT h3, {aggs} FROM acc GROUP BY h3 ORDER BY h3").to_arrow_table()
        return {name: t.column(name).to_numpy(zero_copy_only=False) for name in t.column_names}


def in_box(lat: np.ndarray, lon: np.ndarray, region: str) -> np.ndarray:
    w, s, e, n = REGIONS[region]
    return (lon >= w) & (lon < e) & (lat >= s) & (lat < n)


def grid_lookup(axis: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Index of the regular-grid cell (centred on `axis` points) containing each x, or -1 outside."""
    axis = np.asarray(axis, dtype=np.float64)
    step = float(np.median(np.diff(axis)))
    i = np.rint((x - axis[0]) / step).astype(np.int64)
    ok = (i >= 0) & (i < len(axis)) & (np.abs(x - axis[np.clip(i, 0, len(axis) - 1)]) <= abs(step) / 2 + 1e-9)
    return np.where(ok, i, -1)


def nullable(a: np.ndarray, dtype=pa.float32()) -> pa.Array:
    return pa.array(np.asarray(a, dtype=np.float64), type=pa.float64(), from_pandas=True).cast(dtype)


def source_record(source_id: str, region: str) -> tuple[str, dict]:
    rel = f"data/raw/{source_id}/{region}/source.json"
    return rel, json.loads((ROOT / rel).read_text())


def source_ref(source_id: str, region: str) -> dict:
    rel, rec = source_record(source_id, region)
    lic = rec.get("licence") or {}
    if isinstance(lic, str):
        lic = {"name": lic}
    return {
        "sourceId": source_id,
        "region": region,
        "record": rel,
        "recordId": rec.get("id"),
        "provider": rec.get("provider"),
        "product": rec.get("product"),
        "version": rec.get("version"),
        "doi": rec.get("doi"),
        "documentationUrl": rec.get("documentationUrl"),
        "evidenceType": rec.get("evidenceType"),
        "retrievedAt": rec.get("retrievedAt"),
        "licence": lic.get("name"),
        "licenceUrl": lic.get("url"),
        "attribution": lic.get("attribution") or rec.get("attribution"),
        "licenceNotes": lic.get("notes"),
    }


def write_region(layer_id: str, region: str, cells: Cells, rows: np.ndarray, columns: dict[str, pa.Array],
                 inputs: list[str]) -> dict:
    """Write one region file. `rows` are indexes into `cells`; `columns` are aligned with `rows`."""
    order = np.argsort(rows, kind="stable")
    tbl = pa.table({"h3": pa.array(cells.keys[rows[order]], type=pa.uint64()),
                    **{k: v.take(pa.array(order)) for k, v in columns.items()}})
    d = OUT / layer_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{region}.parquet"
    pq.write_table(tbl, path, compression="zstd")
    vals = tbl.column("value").to_numpy(zero_copy_only=False).astype(np.float64)
    ok = ~np.isnan(vals)
    stats = {
        "file": path.name,
        "regionCells": int(len(cells.keys)),
        "rows": tbl.num_rows,
        "cellsWithValue": int(ok.sum()),
        "valueRange": [round(float(vals[ok].min()), 6), round(float(vals[ok].max()), 6)] if ok.any() else None,
        "valueMedian": round(float(np.median(vals[ok])), 6) if ok.any() else None,
        "bbox": list(REGIONS[region]),
        "inputFiles": inputs,
    }
    log(f"  -> {path.relative_to(ROOT)}  rows={tbl.num_rows:,}  with value={stats['cellsWithValue']:,}  "
        f"range={stats['valueRange']}  ({path.stat().st_size / 1e3:.0f} kB)")
    return stats


def write_layer_json(layer_id: str, meta: dict, region_stats: dict[str, dict], source_ids: list[str]) -> None:
    d = OUT / layer_id
    path = d / "layer.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    regions = {**old.get("regions", {}), **region_stats}
    regions = {r: regions[r] for r in REGIONS if r in regions}
    refs = [source_ref(sid, r) for sid in source_ids for r in regions]
    first = refs[0] if refs else {}
    doc = {
        "id": layer_id,
        **meta,
        "h3Resolution": RES,
        "regions": regions,
        "sourceRefs": refs,
        "licence": {"name": first.get("licence"), "url": first.get("licenceUrl"), "attribution": first.get("attribution")},
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/build_layers.py",
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


# --------------------------------------------------------------------------- A: Aqueduct water stress
def build_water_stress(region: str, cells: Cells):
    import pyogrio
    import shapely

    f = RAW / "WATER-06" / region / f"aqueduct40_{region}.gpkg"
    meta, _, geoms, fields = pyogrio.raw.read(f, layer="baseline_annual",
                                              columns=["pfaf_id", "aq30_id", "string_id", "bws_score", "bws_cat", "bws_label"])
    by_name = dict(zip(meta["fields"], fields))
    pfaf, aq30, sid, score, cat, label = (by_name[k] for k in
                                          ("pfaf_id", "aq30_id", "string_id", "bws_score", "bws_cat", "bws_label"))
    polys = shapely.from_wkb(geoms)
    polys = np.array([g if g.is_valid else shapely.make_valid(g) for g in polys], dtype=object)
    tree = shapely.STRtree(polys)
    pts = shapely.points(cells.lon, cells.lat)
    pi, gi = tree.query(pts, predicate="within")
    # One polygon per centre (Aqueduct units do not overlap); keep the first hit.
    first = np.unique(pi, return_index=True)[1]
    pi, gi = pi[first], gi[first]
    sc = np.asarray(score, dtype=np.float64)[gi]
    ct = np.asarray(cat, dtype=np.float64)[gi]
    nodata = (sc <= -9999) | (ct <= -9999)
    cols = {
        "value": nullable(np.where(nodata, np.nan, sc)),
        "bws_cat": nullable(np.where(nodata, np.nan, ct), pa.int16()),
        "bws_label": pa.array([str(x) for x in np.asarray(label, dtype=object)[gi]]),
        "pfaf_id": pa.array(np.asarray(pfaf)[gi].astype(np.int64)),
        "aq30_id": pa.array(np.asarray(aq30)[gi].astype(np.int64)),
        "string_id": pa.array([str(x) for x in np.asarray(sid, dtype=object)[gi]]),
        "n_valid": pa.array(np.ones(len(pi), dtype=np.int32)),
    }
    return pi, cols, [f.name + ":baseline_annual"]


WATER_STRESS_META = {
    "title": "Baseline water stress (Aqueduct 4.0)",
    "group": "Water",
    "evidenceType": "modelled",
    "variable": {
        "name": "bws_score",
        "meaning": "Baseline water stress: ratio of total water withdrawals to available renewable surface and "
                   "groundwater supply, as a 0–5 score of the sub-basin it belongs to (higher = more competition "
                   "for water). Category labels give the withdrawal-to-supply ratio band.",
    },
    "units": "score 0–5",
    "period": {"label": "Aqueduct 4.0 baseline (hydrology 1979–2019)", "start": "1979-01-01", "end": "2019-12-31"},
    "nativeResolution": "HydroBASINS level-6 sub-basins split by admin-1 boundaries (Aqueduct 4.0 units)",
    "aggregation": {
        "toRes6": "Each cell takes the Aqueduct unit polygon containing its centre (no averaging or splitting of the index).",
        "coarser": "mode",
    },
    "colourScale": "sequential",
    "valueDomain": [0, 5],
    "missingData": "No row: the cell centre is outside every Aqueduct unit (sea). Null value with bws_label "
                   "'No Data': Aqueduct publishes no score for that basin.",
    "caveats": [
        "A basin-level risk index, not a measured water volume: it cannot be reduced by a project's water use or "
        "turned into available supply.",
        "Every cell in a basin repeats the same score; neighbouring cells are not independent observations.",
        "'Arid and Low Water Use' basins are scored 5 by Aqueduct; read the label as well as the score.",
    ],
    "attributes": [
        {"column": "bws_label", "label": "Category"},
        {"column": "pfaf_id", "label": "HydroBASINS Pfafstetter ID"},
        {"column": "string_id", "label": "Aqueduct unit"},
    ],
}


# --------------------------------------------------------------------------- A: NASA POWER solar
def build_solar(region: str, cells: Cells):
    d = RAW / "CTX-02" / region / "climatology"
    pts = {}
    for f in sorted(d.glob("*.json")):
        j = json.loads(f.read_text())
        lon, lat = j["geometry"]["coordinates"][:2]
        p = j["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        fill = j.get("header", {}).get("fill_value", -999.0)
        vals = [p[k] for k in ["ANN", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]]
        pts[(round(lat, 3), round(lon, 3))] = ([np.nan if v is None or v <= fill else float(v) for v in vals], f.name)
    # The API points sit at the centres of the 1° grid (x.5°); a cell takes the 1° box containing its centre.
    keys = [(round(float(np.floor(la)) + 0.5, 3), round(float(np.floor(lo)) + 0.5, 3)) for la, lo in zip(cells.lat, cells.lon)]
    rows = np.array([i for i, k in enumerate(keys) if k in pts], dtype=np.int64)
    arr = np.array([pts[keys[i]][0] for i in rows], dtype=np.float64)
    cols = {"value": nullable(arr[:, 0])}
    for m in range(12):
        cols[f"m{m + 1:02d}"] = nullable(arr[:, m + 1])
    cols["support_id"] = pa.array([f"POWER 1° box centred {keys[i][0]}, {keys[i][1]}" for i in rows])
    cols["n_valid"] = pa.array(np.ones(len(rows), dtype=np.int32))
    return rows, cols, sorted({pts[keys[i]][1] for i in rows})


SOLAR_META = {
    "title": "Solar irradiation, annual mean (NASA POWER)",
    "group": "Climate & solar",
    "evidenceType": "modelled",
    "variable": {
        "name": "ALLSKY_SFC_SW_DWN",
        "meaning": "All-sky global horizontal irradiation reaching the surface (clouds included), as a long-term "
                   "daily mean. It is a resource indicator, not a PV yield.",
    },
    "units": "kWh/m²/day",
    "period": {"label": "Climatology Jan 2001 – Dec 2025 (as labelled by the POWER API)", "start": "2001-01-01", "end": "2025-12-31"},
    "nativeResolution": "1° × 1° POWER solar grid (SYN1DEG); one API point per 1° box",
    "aggregation": {
        "toRes6": "Each cell takes the 1° POWER box containing its centre (value of the API point at the box centre). "
                  "Values repeat within each 1° box.",
        "coarser": "mean",
    },
    "colourScale": "sequential",
    "valueDomain": [2, 7],
    "missingData": "No row: the 1° box containing the cell centre was not requested from the API.",
    "caveats": [
        "Values repeat across every cell in the same 1° box (~100 km): neighbouring cells are one observation.",
        "Annual mean irradiation cannot show hourly or seasonal supply continuity.",
        "The climatology period label differs between POWER's store (2001–2020) and API (2001–2025); unresolved.",
    ],
    "slices": [{"id": "annual", "label": "Annual mean", "column": "value", "group": "Long-term climatology"}]
    + [{"id": f"clim-{m + 1:02d}", "label": MONTHS[m], "column": f"m{m + 1:02d}", "group": "Long-term climatology"}
       for m in range(12)],
    "attributes": [{"column": "support_id", "label": "Native grid cell"}],
}


# --------------------------------------------------------------------------- A/B: fine rasters (EPSG:4326 or projected)
def raster_mean(paths: list[Path], region: str, *, scale: float = 1.0, agg: str = "mean",
                valid_fn=None, band: int = 1) -> dict[str, np.ndarray]:
    """Per-cell sum/count/min/max of valid pixels (centres inside the box), any CRS."""
    import rasterio
    from rasterio.warp import transform as warp_transform
    from rasterio.windows import Window, from_bounds

    acc = PixelAcc(["v"])
    w, s, e, n = REGIONS[region]
    for p in paths:
        with rasterio.open(p) as src:
            geographic = src.crs.to_epsg() == 4326
            if geographic:
                win = from_bounds(w, s, e, n, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
                win = win.round_offsets().round_lengths()
            else:
                win = Window(0, 0, src.width, src.height)
            if win.width <= 0 or win.height <= 0:
                continue
            T = src.window_transform(win)
            nd = src.nodata
            block = max(1, 2_000_000 // int(win.width))
            for r0 in range(0, int(win.height), block):
                h = min(block, int(win.height) - r0)
                sub = Window(win.col_off, win.row_off + r0, win.width, h)
                a = src.read(band, window=sub).astype(np.float64)
                valid = np.isfinite(a)
                if nd is not None:
                    valid &= a != nd
                if valid_fn is not None:
                    valid &= valid_fn(a)
                rr, cc = np.nonzero(valid)
                if rr.size == 0:
                    continue
                xs = T.c + (cc + 0.5) * T.a
                ys = T.f + (r0 + rr + 0.5) * T.e
                if geographic:
                    lon, lat = xs, ys
                else:
                    lon, lat = (np.asarray(v) for v in warp_transform(src.crs, "EPSG:4326", xs, ys))
                keep = in_box(lat, lon, region)
                acc.add(lat[keep], lon[keep], v=a[rr[keep], cc[keep]] * scale)
        log(f"    {p.name}")
    return acc.result()


def finish_mean(cells: Cells, res: dict[str, np.ndarray], agg: str = "mean", extras: bool = False):
    idx = cells.index_of(res["h3"])
    ok = (idx >= 0) & (res["v_n"] > 0)
    rows = idx[ok]
    s, n = res["v_s"][ok].astype(np.float64), res["v_n"][ok].astype(np.int64)
    cols = {"value": nullable(s if agg == "sum" else s / n)}
    if extras:
        cols["min"] = nullable(res["v_mn"][ok])
        cols["max"] = nullable(res["v_mx"][ok])
    cols["n_valid"] = pa.array(n.astype(np.int32))
    return rows, cols


def build_population(region: str, cells: Cells):
    f = RAW / "CTX-04" / region / f"worldpop_2025_1km_{region}.tif"
    rows, cols = finish_mean(cells, raster_mean([f], region, valid_fn=lambda a: a >= 0), agg="sum")
    return rows, cols, [f.name]


POPULATION_META = {
    "title": "Population 2025 (WorldPop, 1 km)",
    "group": "People",
    "evidenceType": "modelled",
    "variable": {"name": "population", "meaning": "Modelled residential population count per cell (sum of 1 km pixels)."},
    "units": "people",
    "display": "density",
    "densityUnits": "people/km²",
    "scaleType": "log",
    "valueDomain": [1, 10000],
    "period": {"label": "2025 (projection)", "start": "2025-01-01", "end": "2025-12-31"},
    "nativeResolution": "30 arc-second (~1 km) grid, constrained to mapped settlements",
    "aggregation": {"toRes6": "Sum of the 1 km pixels whose centres fall in the cell (inside the region box).",
                    "coarser": "sum"},
    "colourScale": "sequential",
    "missingData": "No row: no settled pixel in the cell. WorldPop's constrained model leaves unsettled land as "
                   "no-data, so a blank cell means 'no mapped settlement', not a measured zero.",
    "caveats": [
        "Modelled from census and settlement maps, not counted.",
        "Alpha release (R2025A); figures may change.",
        "Shown as density so colours are comparable across zoom levels; the cell total is in the inspector.",
        "Do not add WorldPop and GHSL population together: they model the same people.",
    ],
}


def build_landcover(region: str, cells: Cells):
    """Exact class counts from every 10 m pixel, binned into ~100 m blocks assigned by block centre."""
    import rasterio
    from rasterio.windows import Window, from_bounds

    codes = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
    lut = np.full(256, 11, dtype=np.int64)
    for i, c in enumerate(codes):
        lut[c] = i
    B = 10  # pixels per block side (100 m)
    files = sorted((RAW / "LAND-02" / region / "v200_2021").glob("*_Map.tif"))
    con = h3_con()
    con.execute("CREATE TABLE acc (h3 UBIGINT, " + ", ".join(f"c{i} BIGINT" for i in range(11)) + ")")
    w, s, e, n = REGIONS[region]
    t0 = time.time()
    for fi, f in enumerate(files):
        with rasterio.open(f) as src:
            assert src.crs.to_epsg() == 4326
            win = from_bounds(w, s, e, n, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
            win = win.round_offsets().round_lengths()
            if win.width <= 0 or win.height <= 0:
                continue
            # Snap the window to whole blocks.
            c0 = int(win.col_off) // B * B
            r0 = int(win.row_off) // B * B
            c1 = min(src.width, -(-int(win.col_off + win.width) // B) * B)
            r1 = min(src.height, -(-int(win.row_off + win.height) // B) * B)
            W = (c1 - c0) // B * B
            T = src.transform
            step = 120 * B
            for rr0 in range(r0, r1, step):
                h = min(step, r1 - rr0) // B * B
                if h == 0:
                    break
                a = src.read(1, window=Window(c0, rr0, W, h))
                idx = lut[a]
                nb_r, nb_c = h // B, W // B
                blk = (np.arange(h)[:, None] // B) * nb_c + (np.arange(W)[None, :] // B)
                counts = np.bincount((blk * 12 + idx).ravel(), minlength=nb_r * nb_c * 12).reshape(nb_r * nb_c, 12)[:, :11]
                lon = T.c + (c0 + (np.arange(nb_c) + 0.5) * B) * T.a
                lat = T.f + (rr0 + (np.arange(nb_r) + 0.5) * B) * T.e
                LAT = np.repeat(lat, nb_c)
                LON = np.tile(lon, nb_r)
                keep = in_box(LAT, LON, region) & (counts.sum(axis=1) > 0)
                if not keep.any():
                    continue
                tbl = pa.table({"lat": LAT[keep], "lng": LON[keep], **{f"c{i}": counts[keep, i] for i in range(11)}})
                con.register("batch", tbl)
                con.execute(f"INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {RES}), "
                            + ", ".join(f"sum(c{i})" for i in range(11)) + " FROM batch GROUP BY 1")
                con.unregister("batch")
        log(f"    {f.name} ({fi + 1}/{len(files)})  {time.time() - t0:.0f}s")
    t = con.sql("SELECT h3, " + ", ".join(f"sum(c{i}) AS c{i}" for i in range(11)) + " FROM acc GROUP BY h3 ORDER BY h3").to_arrow_table()
    keys = t.column("h3").to_numpy()
    counts = np.stack([t.column(f"c{i}").to_numpy().astype(np.float64) for i in range(11)], axis=1)
    idx = cells.index_of(keys)
    tot = counts.sum(axis=1)
    ok = (idx >= 0) & (tot > 0)
    rows, counts, tot = idx[ok], counts[ok], tot[ok]
    frac = counts / tot[:, None]
    cols = {"value": nullable(np.array(codes, dtype=np.float64)[np.argmax(counts, axis=1)])}
    for i, (_, key, _, _) in enumerate(WORLDCOVER):
        cols[key] = nullable(frac[:, i])
    cols["n_valid"] = pa.array(tot.astype(np.int64))
    return rows, cols, [f.name for f in files]


WORLDCOVER = [  # (code, column, label, colour) — same colours as backend/app/layers.py
    (10, "frac_tree", "Tree cover", "#2d6a2d"),
    (20, "frac_shrub", "Shrubland", "#b8a03a"),
    (30, "frac_grass", "Grassland", "#e6d96a"),
    (40, "frac_crop", "Cropland", "#e58cd9"),
    (50, "frac_built", "Built-up", "#d7301f"),
    (60, "frac_bare", "Bare / sparse vegetation", "#bdb6a8"),
    (70, "frac_snow", "Snow and ice", "#f0f0f0"),
    (80, "frac_water", "Permanent water", "#2c6db5"),
    (90, "frac_wetland", "Herbaceous wetland", "#2aa198"),
    (95, "frac_mangrove", "Mangroves", "#1b9e5b"),
    (100, "frac_moss", "Moss and lichen", "#f3e3b0"),
]

LANDCOVER_META = {
    "title": "Land cover 2021 (ESA WorldCover)",
    "group": "Land cover",
    "evidenceType": "satellite_retrieval",
    "variable": {"name": "land cover class",
                 "meaning": "Share of each of the 11 WorldCover classes in the cell; `value` is the dominant class code."},
    "units": "class",
    "period": {"label": "2021", "start": "2021-01-01", "end": "2021-12-31"},
    "nativeResolution": "10 m classified Sentinel-1/Sentinel-2 pixels",
    "aggregation": {
        "toRes6": "Exact class counts of every valid 10 m pixel, binned into 100 m blocks; each block is assigned to the "
                  "cell containing its centre. Fractions = class pixels / valid pixels. Dominant = most frequent class.",
        "coarser": "mode (dominant class); class fractions average the child cells",
    },
    "colourScale": "categorical",
    "categories": [{"value": c, "label": label, "colour": colour} for c, _, label, colour in WORLDCOVER],
    "missingData": "No row: no valid WorldCover pixel (outside the tiles or the region box).",
    "caveats": [
        "A classification of 2021 imagery (satellite-derived), not a field survey; recent change is not reflected.",
        "WorldCover v200 overall accuracy is about 77% globally; mixed and edge pixels are least reliable.",
        "Pixels are assigned to cells in 100 m blocks, so cell edges are accurate to ~100 m.",
    ],
    "slices": [{"id": "dominant", "label": "Dominant class", "column": "value", "agg": "mode", "categorical": True}]
    + [{"id": key.removeprefix("frac_"), "label": label, "column": key, "agg": "mean", "display": "percent",
        "units": "fraction"} for _, key, label, _ in WORLDCOVER],
    "supersedes": ["land_cover"],
}


# --------------------------------------------------------------------------- A: ERA5-Land temperature
def build_era5_t2m(region: str, cells: Cells):
    import xarray as xr

    f = RAW / "CTX-01" / region / "era5land_monthly_2024.nc"
    with xr.open_dataset(f) as ds:
        t = ds["t2m"].values.astype(np.float64) - 273.15  # (12, lat, lon) K → °C
        lats, lons = ds["latitude"].values, ds["longitude"].values
        months = [str(v)[:7] for v in ds["valid_time"].values]
    assert months[6] == "2024-07", months
    iy, ix = grid_lookup(lats, cells.lat), grid_lookup(lons, cells.lon)
    ok = (iy >= 0) & (ix >= 0)
    vals = np.full((len(cells.keys), 12), np.nan)
    vals[ok] = t[:, iy[ok], ix[ok]].T
    rows = np.flatnonzero(ok & ~np.isnan(vals[:, 6]))
    cols = {"value": nullable(vals[rows, 6])}
    for m in range(12):
        if m != 6:
            cols[f"m{m + 1:02d}"] = nullable(vals[rows, m])
    cols["support_id"] = pa.array([f"ERA5-Land 0.1° point {lats[iy[i]]:.1f}, {lons[ix[i]]:.1f}" for i in rows])
    cols["n_valid"] = pa.array(np.ones(len(rows), dtype=np.int32))
    return rows, cols, [f.name + ":t2m"]


T2M_META = {
    "title": "Air temperature at 2 m, July 2024 (ERA5-Land)",
    "group": "Climate & solar",
    "evidenceType": "modelled",
    "variable": {"name": "t2m", "meaning": "Monthly mean air temperature 2 m above the land surface from the ERA5-Land "
                                          "reanalysis (a model constrained by observations), converted from kelvin."},
    "units": "°C",
    "period": {"label": "July 2024 (other 2024 months as variants)", "start": "2024-07-01", "end": "2024-07-31"},
    "nativeResolution": "0.1° × 0.1° ERA5-Land grid (~9 km), land points only",
    "aggregation": {"toRes6": "Each cell takes the 0.1° grid point nearest its centre (the grid box containing it); "
                              "no interpolation.", "coarser": "mean"},
    "colourScale": "diverging",
    "valueDomain": [-5, 40],
    "missingData": "No row: the nearest ERA5-Land point is sea (ERA5-Land has no values over the ocean).",
    "caveats": [
        "Reanalysis model output, not a station measurement.",
        "A single month of a single year; not a climatology.",
        "A 0.1° grid box spans one to three resolution-6 cells, so neighbouring values may repeat.",
    ],
    "slices": [{"id": f"2024-{m + 1:02d}", "label": f"{MONTHS[m]} 2024", "column": "value" if m == 6 else f"m{m + 1:02d}",
                "group": "2024 monthly means"} for m in range(12)],
    "defaultSlice": "2024-07",
    "attributes": [{"column": "support_id", "label": "Native grid point"}],
}


# --------------------------------------------------------------------------- A: CAMS PM2.5
def build_cams_pm25(region: str, cells: Cells):
    import xarray as xr

    f = RAW / "AIR-02" / region / "cams_eac4_monthly_2024.nc"
    with xr.open_dataset(f) as ds:
        pm = ds["pm2p5"].values.astype(np.float64) * 1e9  # kg/m³ → µg/m³
        lats, lons = ds["latitude"].values, ds["longitude"].values
        times = ds["valid_time"].values
    assert len(times) == 12
    days = np.array([calendar.monthrange(2024, m)[1] for m in range(1, 13)], dtype=np.float64)
    annual = np.tensordot(days, pm, axes=(0, 0)) / days.sum()  # day-weighted mean of monthly means
    annual[np.isnan(pm).any(axis=0)] = np.nan  # an incomplete year is not an annual mean
    iy, ix = grid_lookup(lats, cells.lat), grid_lookup(lons, cells.lon)
    ok = (iy >= 0) & (ix >= 0)
    v = np.full(len(cells.keys), np.nan)
    v[ok] = annual[iy[ok], ix[ok]]
    rows = np.flatnonzero(~np.isnan(v))
    cols = {"value": nullable(v[rows]),
            "support_id": pa.array([f"CAMS 0.75° point {lats[iy[i]]:.2f}, {lons[ix[i]]:.2f}" for i in rows]),
            "n_valid": pa.array(np.full(len(rows), 12, dtype=np.int32))}
    return rows, cols, [f.name + ":pm2p5"]


PM25_META = {
    "title": "PM2.5, 2024 mean (CAMS reanalysis)",
    "group": "Air quality",
    "evidenceType": "modelled",
    "variable": {"name": "pm2p5", "meaning": "Mass concentration of fine particulate matter (diameter ≤ 2.5 µm) near "
                                            "the surface from the CAMS EAC4 reanalysis, 2024 day-weighted mean of the "
                                            "monthly means."},
    "units": "µg/m³",
    "period": {"label": "2024 (annual mean of monthly means)", "start": "2024-01-01", "end": "2024-12-31"},
    "nativeResolution": "0.75° × 0.75° CAMS EAC4 grid (~80 km)",
    "aggregation": {"toRes6": "Each cell takes the 0.75° grid point whose box contains its centre; no interpolation.",
                    "coarser": "mean"},
    "colourScale": "sequential",
    "valueDomain": [0, 20],
    "missingData": "No row: the cell centre is outside the downloaded CAMS grid.",
    "caveats": [
        "Modelled (atmospheric model with assimilated satellite data), not a ground monitor measurement.",
        "Very coarse: one 0.75° box covers ~150 resolution-6 cells, so urban hot spots are smoothed out.",
    ],
    "attributes": [{"column": "support_id", "label": "Native grid point"}],
}


# --------------------------------------------------------------------------- B: SoilGrids pH
def build_soil_ph(region: str, cells: Cells):
    f = RAW / "SOIL-01" / region / "soilgrids_v2" / "phh2o_0-5cm_mean.tif"
    # Interrupted Goode Homolosine: pixel centres are transformed to lon/lat with PROJ (no resampling).
    rows, cols = finish_mean(cells, raster_mean([f], region, scale=0.1))
    return rows, cols, [f.name]


SOIL_PH_META = {
    "title": "Soil pH (water), 0–5 cm (SoilGrids)",
    "group": "Soil",
    "evidenceType": "modelled",
    "variable": {"name": "phh2o", "meaning": "Predicted soil pH measured in a water solution, topsoil 0–5 cm, mean "
                                            "of the 250 m predictions in the cell (stored ×10 upstream; divided by 10)."},
    "units": "pH",
    "period": {"label": "SoilGrids 2.0 (profiles collected over several decades)", "start": None, "end": None},
    "nativeResolution": "250 m (Interrupted Goode Homolosine)",
    "aggregation": {"toRes6": "Mean of valid 250 m pixels whose centres (transformed to lon/lat) fall in the cell.",
                    "coarser": "mean"},
    "colourScale": "diverging",
    "valueDomain": [4.5, 8.5],
    "missingData": "No row: SoilGrids has no prediction (water, urban, permanent ice, outside the clip).",
    "caveats": ["Machine-learning predictions from soil profiles and covariates, not samples at this location."],
}


# --------------------------------------------------------------------------- B: MODIS NDVI
def build_ndvi(region: str, cells: Cells):
    from pyhdf.SD import SD, SDC

    files = sorted((RAW / "OBS-06" / region).glob("MOD13A3.A2024183.*.hdf"))  # day 183 = 1 July 2024
    R = 6371007.181
    acc = PixelAcc(["v"])
    for f in files:
        sd = SD(str(f), SDC.READ)
        meta = sd.attributes()["StructMetadata.0"]
        ul = [float(x) for x in re.search(r"UpperLeftPointMtrs=\(([^)]+)\)", meta).group(1).split(",")]
        lr = [float(x) for x in re.search(r"LowerRightMtrs=\(([^)]+)\)", meta).group(1).split(",")]
        nd = sd.select("1 km monthly NDVI")
        ndvi = nd.get().astype(np.float64)
        rel = sd.select("1 km monthly pixel reliability").get()
        sd.end()
        ny, nx = ndvi.shape
        px, py = (lr[0] - ul[0]) / nx, (ul[1] - lr[1]) / ny
        # Pixel reliability 0 = good, 1 = marginal; 2 snow/ice, 3 cloudy, -1 fill are rejected.
        valid = ((rel == 0) | (rel == 1)) & (ndvi >= -2000) & (ndvi <= 10000)
        rr, cc = np.nonzero(valid)
        y = ul[1] - (rr + 0.5) * py
        x = ul[0] + (cc + 0.5) * px
        lat = np.degrees(y / R)
        lon = np.degrees(x / (R * np.cos(np.radians(lat))))
        keep = in_box(lat, lon, region)
        acc.add(lat[keep], lon[keep], v=ndvi[rr[keep], cc[keep]] / 10000.0)
        log(f"    {f.name}: {keep.sum():,} valid pixels in box")
    rows, cols = finish_mean(cells, acc.result())
    return rows, cols, [f.name for f in files]


NDVI_META = {
    "title": "Vegetation index (NDVI), July 2024 (MODIS)",
    "group": "Vegetation",
    "evidenceType": "satellite_retrieval",
    "variable": {"name": "NDVI", "meaning": "Normalised Difference Vegetation Index from the MODIS Terra monthly 1 km "
                                           "composite: higher = denser green vegetation; near 0 = bare ground, "
                                           "negative = water/snow."},
    "units": "NDVI (−1 to 1)",
    "period": {"label": "July 2024 monthly composite", "start": "2024-07-01", "end": "2024-07-31"},
    "nativeResolution": "1 km MODIS sinusoidal grid (MOD13A3 v061)",
    "aggregation": {"toRes6": "Mean of the 1 km pixels whose centres fall in the cell; pixel reliability 0 (good) or "
                              "1 (marginal) only; DN / 10000.", "coarser": "mean"},
    "colourScale": "sequential",
    "valueDomain": [0, 0.9],
    "missingData": "No row: no pixel passed the quality screen (cloud, snow, fill) or the cell is outside the tiles.",
    "caveats": ["A greenness index, not biomass or crop yield.", "One month only; seasonal change is not shown."],
}


# --------------------------------------------------------------------------- B: S5P NO2
def build_no2(region: str, cells: Cells):
    f = next((RAW / "AIR-01" / region).glob("s5p_no2_trop_*.parquet"))
    t = pq.read_table(f, columns=["latitude", "longitude", "no2_trop_column_mol_m2", "qa_value"])
    lat = t.column("latitude").to_numpy().astype(np.float64)
    lon = t.column("longitude").to_numpy().astype(np.float64)
    v = t.column("no2_trop_column_mol_m2").to_numpy(zero_copy_only=False).astype(np.float64) * 1e6  # µmol/m²
    qa = t.column("qa_value").to_numpy(zero_copy_only=False)
    keep = in_box(lat, lon, region) & (qa > 0.75) & np.isfinite(v)
    acc = PixelAcc(["v"])
    acc.add(lat[keep], lon[keep], v=v[keep])
    rows, cols = finish_mean(cells, acc.result())
    return rows, cols, [f.name]


NO2_META = {
    "title": "NO₂ tropospheric column, 1–7 Jul 2025 (Sentinel-5P)",
    "group": "Air quality",
    "evidenceType": "satellite_retrieval",
    "variable": {"name": "nitrogendioxide_tropospheric_column",
                 "meaning": "Amount of NO₂ in the column of air between the ground and the top of the troposphere, "
                            "mean of the quality-screened TROPOMI pixels whose centres fall in the cell."},
    "units": "µmol/m²",
    "period": {"label": "1–7 July 2025 (one week of overpasses)", "start": "2025-07-01", "end": "2025-07-07"},
    "nativeResolution": "TROPOMI pixels ~5.5 × 3.5 km",
    "aggregation": {"toRes6": "Mean of pixels with qa_value > 0.75 whose centres fall in the cell; n_valid = pixel count.",
                    "coarser": "mean"},
    "colourScale": "sequential",
    "scaleType": "linear",
    "missingData": "No row: no pixel passed the quality filter (mostly cloud) during the week.",
    "caveats": [
        "A column amount through the atmosphere, not a ground-level concentration.",
        "One week of overpasses: weather and cloud strongly affect the values; not an annual picture.",
        "In the UK, 14 of 32 orbits had no pixel passing the quality filter.",
    ],
}


# --------------------------------------------------------------------------- B: FIRMS
def build_fires(region: str, cells: Cells):
    import pandas as pd

    files = sorted((RAW / "LAND-05" / region).glob("viirs-snpp_2024_*.csv"))
    df = pd.concat([pd.read_csv(f, usecols=["latitude", "longitude", "type"]) for f in files], ignore_index=True)
    lat, lon = df.latitude.to_numpy(np.float64), df.longitude.to_numpy(np.float64)
    keep = in_box(lat, lon, region)
    typ = df.type.to_numpy()[keep]
    acc = PixelAcc(["all", "static", "veg"])
    acc.add(lat[keep], lon[keep], all=np.ones(keep.sum()), static=(typ == 2).astype(float),
            veg=(typ == 0).astype(float))
    r = acc.result()
    idx = cells.index_of(r["h3"])
    ok = idx >= 0
    rows = idx[ok]
    cols = {
        "value": nullable(r["all_s"][ok]),
        "static_count": pa.array(r["static_s"][ok].astype(np.int32)),
        "vegetation_count": pa.array(r["veg_s"][ok].astype(np.int32)),
        "n_valid": pa.array(r["all_n"][ok].astype(np.int32)),
    }
    return rows, cols, [f.name for f in files]


FIRES_META = {
    "title": "Fire detections 2024 (VIIRS S-NPP)",
    "group": "Hazards",
    "evidenceType": "satellite_retrieval",
    "variable": {"name": "detections", "meaning": "Number of VIIRS 375 m thermal-anomaly detections (hot pixels at "
                                                  "overpass time) in the cell during 2024, all types."},
    "units": "detections",
    "period": {"label": "2024", "start": "2024-01-01", "end": "2024-12-31"},
    "nativeResolution": "375 m VIIRS pixels (point detections)",
    "aggregation": {"toRes6": "Count of detections whose centres fall in the cell; static_count = type 2 (static land "
                              "source, e.g. industry/flares); vegetation_count = type 0 (presumed vegetation fire).",
                    "coarser": "sum"},
    "colourScale": "sequential",
    "scaleType": "log",
    "valueDomain": [1, 200],
    "missingData": "No row: no detection recorded in 2024. That is not proof there was no fire (cloud, overpass timing).",
    "caveats": [
        "A detection is a hot pixel at overpass time, not a fire perimeter or burned area.",
        "Includes static industrial heat sources (see the static-source variant).",
    ],
    "slices": [
        {"id": "all", "label": "All detections", "column": "value", "agg": "sum"},
        {"id": "static", "label": "Static land sources (type 2)", "column": "static_count", "agg": "sum"},
        {"id": "vegetation", "label": "Presumed vegetation fires (type 0)", "column": "vegetation_count", "agg": "sum"},
    ],
}


# --------------------------------------------------------------------------- B: GEDI biomass
def build_biomass(region: str, cells: Cells):
    mu = next((RAW / "LAND-04" / region).glob("*_MU_*.tif"))
    se = next((RAW / "LAND-04" / region).glob("*_SE_*.tif"))
    rows, cols = finish_mean(cells, raster_mean([mu], region, valid_fn=lambda a: a >= 0))
    r_se = raster_mean([se], region, valid_fn=lambda a: a >= 0)
    idx = cells.index_of(r_se["h3"])
    se_mean = np.full(len(cells.keys), np.nan)
    ok = (idx >= 0) & (r_se["v_n"] > 0)
    se_mean[idx[ok]] = r_se["v_s"][ok] / r_se["v_n"][ok]
    cols["se_mean"] = nullable(se_mean[rows])
    return rows, cols, [mu.name, se.name]


BIOMASS_META = {
    "title": "Aboveground biomass density (GEDI L4B)",
    "group": "Vegetation",
    "evidenceType": "modelled",
    "variable": {"name": "MU", "meaning": "Mean aboveground biomass density estimated from GEDI lidar footprints "
                                         "(2019–2023), averaged over the 1 km grid cells in the cell."},
    "units": "Mg/ha",
    "period": {"label": "April 2019 – March 2023 mission period", "start": "2019-04-18", "end": "2023-03-16"},
    "nativeResolution": "1 km EASE-Grid 2.0 (EPSG:6933)",
    "aggregation": {"toRes6": "Mean of valid 1 km pixels whose centres (transformed to lon/lat) fall in the cell; "
                              "se_mean = mean of the per-pixel standard errors.", "coarser": "mean"},
    "colourScale": "sequential",
    "valueDomain": [0, 150],
    "missingData": "No row: no GEDI estimate. GEDI only observes between 51.6°S and 51.6°N, so the UK north of "
                   "51.6°N has no coverage — not zero biomass.",
    "caveats": [
        "Gridded model estimates from sparse lidar footprints, not a wall-to-wall measurement.",
        "Standard errors are large where few footprints exist; see se_mean.",
    ],
    "slices": [
        {"id": "mean", "label": "Biomass density", "column": "value"},
        {"id": "se", "label": "Standard error", "column": "se_mean"},
    ],
}


# --------------------------------------------------------------------------- B: GRACE groundwater
def build_groundwater(region: str, cells: Cells):
    import xarray as xr

    files = sorted((RAW / "WATER-02" / region).glob("GRACEDADM_CLSM025GL_7D.A2024*.nc4"))
    f = files[-1]  # latest 2024 week
    with xr.open_dataset(f) as ds:
        vals = {k: ds[k].values[0].astype(np.float64) for k in ("gws_inst", "rtzsm_inst", "sfsm_inst")}
        lats, lons = ds["lat"].values, ds["lon"].values
        week = str(ds["time"].values[0])[:10]
    for k in vals:
        vals[k][vals[k] <= -999] = np.nan
    iy, ix = grid_lookup(lats, cells.lat), grid_lookup(lons, cells.lon)
    ok = (iy >= 0) & (ix >= 0)
    g = np.full(len(cells.keys), np.nan)
    g[ok] = vals["gws_inst"][iy[ok], ix[ok]]
    rows = np.flatnonzero(~np.isnan(g))
    cols = {"value": nullable(g[rows])}
    for k, col in (("rtzsm_inst", "rootzone_pct"), ("sfsm_inst", "surface_pct")):
        cols[col] = nullable(vals[k][iy[rows], ix[rows]])
    cols["support_id"] = pa.array([f"GRACE-DA 0.25° cell {lats[iy[i]]:.3f}, {lons[ix[i]]:.3f}" for i in rows])
    cols["n_valid"] = pa.array(np.ones(len(rows), dtype=np.int32))
    log(f"    week starting {week}")
    return rows, cols, [f.name]


GROUNDWATER_META = {
    "title": "Groundwater storage percentile, end of 2024 (GRACE-DA)",
    "group": "Water",
    "evidenceType": "modelled",
    "variable": {"name": "gws_inst", "meaning": "Groundwater storage for the week, as a percentile of the 1948–2012 "
                                               "record at that location (0 = driest, 100 = wettest), from a land "
                                               "model assimilating GRACE/GRACE-FO gravity data."},
    "units": "percentile",
    "period": {"label": "Week of 30 Dec 2024", "start": "2024-12-30", "end": "2025-01-05"},
    "nativeResolution": "0.25° × 0.25° (~25 km); GRACE itself resolves ~300 km",
    "aggregation": {"toRes6": "Each cell takes the 0.25° grid cell containing its centre; no interpolation.",
                    "coarser": "mean"},
    "colourScale": "diverging",
    "valueDomain": [0, 100],
    "missingData": "No row: the model has no value (sea, lakes, outside the grid).",
    "caveats": [
        "A drought indicator relative to local history, not a volume of extractable groundwater.",
        "The underlying satellite signal is ~300 km wide; local aquifers are not resolved.",
    ],
    "slices": [
        {"id": "groundwater", "label": "Groundwater", "column": "value"},
        {"id": "rootzone", "label": "Root-zone soil moisture", "column": "rootzone_pct"},
        {"id": "surface", "label": "Surface soil moisture", "column": "surface_pct"},
    ],
    "attributes": [{"column": "support_id", "label": "Native grid cell"}],
}


# --------------------------------------------------------------------------- B: DEM
def build_elevation(region: str, cells: Cells):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import prepare_regional_h3 as prh  # reuse the DEM aggregation (sea = 0 m skipped, slope per tile)

    with tempfile.TemporaryDirectory() as tmp:
        prh.run_dem(ROOT / "data", region, Path(tmp))
        t = pq.read_table(Path(tmp) / f"dem_{region}_h3r6.parquet")
    idx = cells.index_of(t.column("h3").to_numpy())
    ok = idx >= 0
    rows = idx[ok]
    take = pa.array(np.flatnonzero(ok))
    cols = {k: t.column(k).take(take) for k in ("value", "min", "max", "slope_mean", "n_valid")}
    files = sorted(p.name for p in (RAW / "CTX-03" / region / "glo90").glob("*.tif"))
    return rows, cols, files


ELEVATION_META = {
    "title": "Elevation (Copernicus DEM GLO-90)",
    "group": "Terrain",
    "evidenceType": "satellite_retrieval",
    "variable": {"name": "elevation", "meaning": "Mean surface height of the 90 m DEM pixels in the cell (EGM2008 "
                                                "heights; a surface model including buildings and canopy)."},
    "units": "m",
    "period": {"label": "TanDEM-X acquisitions 2011–2015", "start": "2011-01-01", "end": "2015-12-31"},
    "nativeResolution": "90 m (3 arc-second)",
    "aggregation": {"toRes6": "Mean, min and max of the 90 m pixels whose centres fall in the cell; pixels of exactly "
                              "0 m are treated as sea; slope = mean per-pixel slope.", "coarser": "mean"},
    "colourScale": "sequential",
    "missingData": "No row: no land pixel (sea) in the cell.",
    "caveats": ["Digital surface model: heights include buildings and trees."],
    "slices": [
        {"id": "mean", "label": "Mean", "column": "value"},
        {"id": "min", "label": "Minimum", "column": "min"},
        {"id": "max", "label": "Maximum", "column": "max"},
        {"id": "slope", "label": "Mean slope", "column": "slope_mean", "units": "°"},
    ],
    "supersedes": ["elevation"],
}


# --------------------------------------------------------------------------- registry
LAYERS = {
    # A (core demo)
    "water_stress_baseline": (build_water_stress, WATER_STRESS_META, ["WATER-06"]),
    "solar_irradiance_annual": (build_solar, SOLAR_META, ["CTX-02"]),
    "landcover_fractions": (build_landcover, LANDCOVER_META, ["LAND-02"]),
    "population_2025": (build_population, POPULATION_META, ["CTX-04"]),
    "air_temperature_july_2024": (build_era5_t2m, T2M_META, ["CTX-01"]),
    "pm25_2024": (build_cams_pm25, PM25_META, ["AIR-02"]),
    # B
    "soil_ph_0_5cm": (build_soil_ph, SOIL_PH_META, ["SOIL-01"]),
    "ndvi_july_2024": (build_ndvi, NDVI_META, ["OBS-06"]),
    "no2_tropospheric_column": (build_no2, NO2_META, ["AIR-01"]),
    "fire_detections_2024": (build_fires, FIRES_META, ["LAND-05"]),
    "biomass_agbd": (build_biomass, BIOMASS_META, ["LAND-04"]),
    "groundwater_percentile": (build_groundwater, GROUNDWATER_META, ["WATER-02"]),
    "elevation_mean": (build_elevation, ELEVATION_META, ["CTX-03"]),
}


# Layers the app reads from data/prepared/layers/ (backend/app/layers.py). The other builders
# above duplicate layers the app already gets from scripts/prepare_observation_h3.py and the
# PR #3 pipeline; they stay available via --layer for comparison but are not built by default.
DEFAULT_LAYERS = ["water_stress_baseline"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layer", nargs="*", choices=list(LAYERS),
                    help=f"layers to build (default: {', '.join(DEFAULT_LAYERS)})")
    ap.add_argument("--region", nargs="*", choices=list(REGIONS), help="regions to build (default: both)")
    a = ap.parse_args()
    regions = a.region or list(REGIONS)
    cells = {r: Cells(r) for r in regions}
    for layer_id in a.layer or DEFAULT_LAYERS:
        fn, meta, source_ids = LAYERS[layer_id]
        stats = {}
        for r in regions:
            log(f"{layer_id} / {r}")
            t0 = time.time()
            rows, cols, inputs = fn(r, cells[r])
            stats[r] = write_region(layer_id, r, cells[r], np.asarray(rows, dtype=np.int64), cols, inputs)
            log(f"  {time.time() - t0:.0f}s")
        write_layer_json(layer_id, meta, stats, source_ids)


if __name__ == "__main__":
    main()
