"""Aggregate the regional DEM, WorldCover and GHSL built-up rasters to H3 resolution-6 cells.

Run (one layer, one region, or everything):
  uv run --no-project --with rasterio --with duckdb --with pyarrow --with numpy \
    python -I scripts/prepare_regional_h3.py [--layer dem|worldcover|ghsl_built|all] \
    [--region arizona|uk|all] [--data data]

Inputs (EPSG:4326 rasters, provenance in each folder's source.json):
  dem         data/raw/CTX-03/<region>/glo90/*.tif          Copernicus DEM GLO-90 (90 m, 1° tiles)
  worldcover  data/raw/LAND-02/<region>/v200_2021/*_Map.tif  ESA WorldCover 2021 v200 (10 m, 3° tiles)
  ghsl_built  data/raw/CTX-05/<region>/GHS_BUILT_S_*.tif     GHSL built-up surface 2025 (30 arcsec)

Outputs: data/prepared/<layer>_<region>_h3r6.parquet (h3 uint64 ascending, zstd) plus a JSON
sidecar with provenance, method and units. Same conventions as scripts/aggregate_raster_to_h3.py:
- each pixel goes to the res-6 cell containing its centre (pixels are far smaller than cells);
- only pixels whose centre lies inside the region box are used, so the tiles' overhang is dropped;
- nodata pixels are skipped and never counted as zero; cells with no valid pixel are absent.

Layer specifics:
- dem: pixels exactly 0.0 m are treated as sea and skipped (GLO-90 flattens the ocean to 0 m and
  has no nodata value; real land is almost never exactly 0.0). Slope is computed per tile at native
  resolution with central differences, using metres per degree at each pixel's latitude; pixels
  next to sea or a tile edge are skipped for slope.
- worldcover: the 10 m map is read decimated 10x (≈100 m, nearest-neighbour from the COG's internal
  overviews), i.e. a regular point sample of the classes; fractions are shares of valid samples.
- ghsl_built: built-up surface is summed (m²). Zero is a real value (no built-up surface).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds

RES = 6
REGIONS = {
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
WC_CLASSES = [  # (code, column suffix)
    (10, "tree"), (20, "shrub"), (30, "grass"), (40, "crop"), (50, "built"), (60, "bare"),
    (70, "snow"), (80, "water"), (90, "wetland"), (95, "mangrove"), (100, "moss"),
]
WC_DECIMATION = 10


def h3_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    return con


def pixel_centres(transform, r0: int, c0: int, h: int, w: int):
    """Lon (w,) and lat (h,) of pixel centres for a window starting at (r0, c0)."""
    lon = transform.c + (c0 + np.arange(w) + 0.5) * transform.a
    lat = transform.f + (r0 + np.arange(h) + 0.5) * transform.e
    return lon, lat


def in_box(lon, lat, box):
    w, s, e, n = box
    return ((lon >= w) & (lon < e))[None, :] & ((lat >= s) & (lat < n))[:, None]


def source_record(data: Path, source_id: str, region: str) -> dict:
    return json.loads((data / "raw" / source_id / region / "source.json").read_text())


def write_outputs(tbl: pa.Table, out: Path, rec: dict, layer: str, region: str, method: str,
                  units: dict, files: list[str]) -> None:
    pq.write_table(tbl, out, compression="zstd")
    lic = rec.get("licence", {})
    side = {
        "layer": f"{layer}_{region}",
        "sourceId": rec.get("catalogueSourceId"),
        "provider": rec.get("provider"),
        "product": rec.get("product"),
        "version": rec.get("version"),
        "licence": lic.get("name"),
        "licenceUrl": lic.get("url"),
        "attribution": lic.get("attribution"),
        "evidenceType": rec.get("evidenceType"),
        "retrievedAt": rec.get("retrievedAt"),
        "method": method,
        "h3Resolution": RES,
        "units": units,
        "region": region,
        "regionBbox": list(REGIONS[region]),
        "inputFiles": files,
        "rowCount": tbl.num_rows,
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/prepare_regional_h3.py",
    }
    out.with_suffix(".json").write_text(json.dumps(side, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"  -> {out}  rows={tbl.num_rows:,}  {out.stat().st_size/1e6:.1f} MB")


# --------------------------------------------------------------------------- DEM
def slope_deg(z: np.ndarray, lat: np.ndarray, res_x: float, res_y: float) -> np.ndarray:
    """Slope in degrees by central differences; NaN where a neighbour is sea/edge."""
    m_per_deg_lat = 111_132.954 - 559.822 * np.cos(2 * np.radians(lat)) + 1.175 * np.cos(4 * np.radians(lat))
    m_per_deg_lon = 111_412.84 * np.cos(np.radians(lat)) - 93.5 * np.cos(3 * np.radians(lat))
    dx = (m_per_deg_lon * abs(res_x))[:, None]
    dy = (m_per_deg_lat * abs(res_y))[:, None]
    out = np.full(z.shape, np.nan, dtype=np.float64)
    zx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx[1:-1])
    zy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * dy[1:-1])
    out[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(zx, zy)))
    return out  # NaN propagates from NaN (sea) neighbours


def run_dem(data: Path, region: str, out_dir: Path) -> None:
    box = REGIONS[region]
    files = sorted(glob.glob(str(data / "raw" / "CTX-03" / region / "glo90" / "*.tif")))
    con = h3_con()
    con.execute("CREATE TABLE acc (h3 UBIGINT, s DOUBLE, mn FLOAT, mx FLOAT, n BIGINT, ss DOUBLE, ns BIGINT)")
    t0 = time.time()
    for i, f in enumerate(files):
        with rasterio.open(f) as src:
            assert src.crs.to_epsg() == 4326, f"{f}: expected EPSG:4326, got {src.crs}"
            z = src.read(1).astype(np.float64)
            T, nd = src.transform, src.nodata
        lon, lat = pixel_centres(T, 0, 0, *z.shape)
        valid = np.isfinite(z) & (z != 0.0)
        if nd is not None:
            valid &= z != nd
        z = np.where(valid, z, np.nan)
        sl = slope_deg(z, lat, T.a, T.e)
        keep = valid & in_box(lon, lat, box)
        rr, cc = np.nonzero(keep)
        if rr.size == 0:
            continue
        v, s = z[rr, cc], sl[rr, cc]
        batch = pa.table({"lat": lat[rr], "lng": lon[cc], "v": v, "sl": np.nan_to_num(s, nan=0.0),
                          "hs": np.isfinite(s).astype(np.int8)})
        con.register("batch", batch)
        con.execute(f"""INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {RES}), sum(v), min(v), max(v),
                        count(*), sum(sl * hs), sum(hs) FROM batch GROUP BY 1""")
        con.unregister("batch")
        if i % 10 == 0:
            print(f"  dem {region}: tile {i+1}/{len(files)}  {time.time()-t0:.0f}s", flush=True)
    tbl = con.sql("""SELECT h3, CAST(sum(s)/sum(n) AS FLOAT) AS value, CAST(min(mn) AS FLOAT) AS min,
                                CAST(max(mx) AS FLOAT) AS max, CAST(sum(n) AS INTEGER) AS n_valid,
                                CAST(CASE WHEN sum(ns) > 0 THEN sum(ss)/sum(ns) END AS FLOAT) AS slope_mean
                         FROM acc GROUP BY h3 ORDER BY h3""").to_arrow_table()
    method = ("Mean, min and max of Copernicus DEM GLO-90 pixel heights whose centres fall in each H3 res-6 cell "
              "inside the region box; pixels of exactly 0.0 m (the DEM's flattened sea) are treated as sea and "
              "skipped; slope_mean is the mean per-pixel slope from central differences at native resolution "
              "(metres per degree at the pixel's latitude), excluding pixels next to sea or a tile edge.")
    write_outputs(tbl, out_dir / f"dem_{region}_h3r6.parquet", source_record(data, "CTX-03", region), "dem", region,
                  method, {"value": "m (mean elevation, EGM2008 heights)", "min": "m", "max": "m",
                           "n_valid": "count of 90 m pixels", "slope_mean": "degrees"},
                  [Path(f).name for f in files])


# --------------------------------------------------------------------------- WorldCover
def run_worldcover(data: Path, region: str, out_dir: Path) -> None:
    box = REGIONS[region]
    files = sorted(glob.glob(str(data / "raw" / "LAND-02" / region / "v200_2021" / "*_Map.tif")))
    con = h3_con()
    con.execute("CREATE TABLE acc (h3 UBIGINT, cls SMALLINT, n BIGINT)")
    t0 = time.time()
    for i, f in enumerate(files):
        with rasterio.open(f) as src:
            assert src.crs.to_epsg() == 4326
            win = from_bounds(*box, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
            win = win.round_offsets().round_lengths()
            if win.width <= 0 or win.height <= 0:
                continue
            oh, ow = max(1, win.height // WC_DECIMATION), max(1, win.width // WC_DECIMATION)
            a = src.read(1, window=win, out_shape=(oh, ow), resampling=Resampling.nearest)
            T = src.window_transform(win) * rasterio.Affine.scale(win.width / ow, win.height / oh)
            nd = src.nodata
        lon, lat = pixel_centres(T, 0, 0, oh, ow)
        valid = (a != 0) & in_box(lon, lat, box)
        if nd is not None:
            valid &= a != nd
        rr, cc = np.nonzero(valid)
        if rr.size == 0:
            continue
        batch = pa.table({"lat": lat[rr], "lng": lon[cc], "c": a[rr, cc].astype(np.int16)})
        con.register("batch", batch)
        con.execute(f"INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {RES}), c, count(*) FROM batch GROUP BY 1, 2")
        con.unregister("batch")
        print(f"  worldcover {region}: tile {i+1}/{len(files)} ({ow}x{oh} samples)  {time.time()-t0:.0f}s", flush=True)
    fr = ", ".join(f"CAST(coalesce(sum(n) FILTER (WHERE cls = {c}), 0) / sum(n) AS FLOAT) AS frac_{k}"
                   for c, k in WC_CLASSES)
    tbl = con.sql(f"""
        WITH t AS (SELECT h3, cls, sum(n) AS n FROM acc GROUP BY 1, 2)
        SELECT h3, {fr}, CAST(arg_max(cls, n) AS SMALLINT) AS dominant, CAST(sum(n) AS INTEGER) AS n_valid
        FROM t GROUP BY h3 ORDER BY h3""").to_arrow_table()
    method = (f"Share of valid ESA WorldCover 2021 v200 class samples per H3 res-6 cell inside the region box; the "
              f"10 m map was read decimated {WC_DECIMATION}x (~100 m grid, nearest-neighbour via the COG overviews), "
              "so fractions are a regular point sample, not exact 10 m areas; class 0 (nodata) is skipped.")
    units = {f"frac_{k}": f"fraction 0-1 of valid samples (class {c})" for c, k in WC_CLASSES}
    units |= {"dominant": "WorldCover class code (most frequent valid class)",
              "n_valid": f"count of ~100 m samples (10 m pixels decimated {WC_DECIMATION}x)"}
    write_outputs(tbl, out_dir / f"worldcover_{region}_h3r6.parquet", source_record(data, "LAND-02", region),
                  "worldcover", region, method, units, [Path(f).name for f in files])


# --------------------------------------------------------------------------- GHSL built-up
def run_ghsl_built(data: Path, region: str, out_dir: Path) -> None:
    box = REGIONS[region]
    f = sorted(glob.glob(str(data / "raw" / "CTX-05" / region / "GHS_BUILT_S_*.tif")))[0]
    with rasterio.open(f) as src:
        assert src.crs.to_epsg() == 4326
        a = src.read(1).astype(np.float64)
        T, nd = src.transform, src.nodata
    lon, lat = pixel_centres(T, 0, 0, *a.shape)
    valid = np.isfinite(a) & in_box(lon, lat, box)
    if nd is not None:
        valid &= a != nd
    rr, cc = np.nonzero(valid)
    con = h3_con()
    con.register("batch", pa.table({"lat": lat[rr], "lng": lon[cc], "v": a[rr, cc]}))
    tbl = con.sql(f"""SELECT h3_latlng_to_cell(lat, lng, {RES}) AS h3, CAST(sum(v) AS FLOAT) AS value,
                          CAST(count(*) AS INTEGER) AS n_valid FROM batch GROUP BY 1 ORDER BY 1""").to_arrow_table()
    method = ("Sum of GHSL GHS-BUILT-S 2025 built-up surface (30 arcsec, WGS84) over pixels whose centres fall in each "
              "H3 res-6 cell inside the region box; zero means no built-up surface, not missing data.")
    write_outputs(tbl, out_dir / f"ghsl_built_{region}_h3r6.parquet", source_record(data, "CTX-05", region),
                  "ghsl_built", region, method, {"value": "m² built-up surface (sum)", "n_valid": "count of 30″ pixels"},
                  [Path(f).name])


RUNNERS = {"dem": run_dem, "worldcover": run_worldcover, "ghsl_built": run_ghsl_built}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layer", default="all", choices=[*RUNNERS, "all"])
    ap.add_argument("--region", default="all", choices=[*REGIONS, "all"])
    ap.add_argument("--data", default="data", help="data directory (contains raw/ and prepared/)")
    a = ap.parse_args()
    data = Path(a.data)
    out_dir = data / "prepared"
    for layer in RUNNERS if a.layer == "all" else [a.layer]:
        for region in REGIONS if a.region == "all" else [a.region]:
            print(f"{layer} / {region}", flush=True)
            RUNNERS[layer](data, region, out_dir)
