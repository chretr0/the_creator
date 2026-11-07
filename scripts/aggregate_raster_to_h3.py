"""Aggregate a WGS84 (EPSG:4326) raster to H3 cells by pixel centre, streaming in row blocks.

Run:
  uv run --no-project --with rasterio --with duckdb --with pyarrow --with numpy \
    python -I scripts/aggregate_raster_to_h3.py <raster> <out.parquet> --agg sum|mean [--res 6] [--scale 1]

Pixel-centre assignment is fine when pixels are much smaller than cells (res 6 ≈ 36 km²).
Output columns: h3 (uint64), value (float32), n_valid (pixels used).
Nodata pixels are skipped and never treated as zero; cells with no valid pixel are absent (unknown).
`sum` suits additive counts (population); `mean` suits intensive fields (pH, temperature).
Area weighting by latitude is NOT applied for `mean` (pixels inside one res-6 cell have ~equal area).
"""
import argparse
import time

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio

ap = argparse.ArgumentParser()
ap.add_argument("raster"); ap.add_argument("out")
ap.add_argument("--agg", choices=["sum", "mean"], required=True)
ap.add_argument("--res", type=int, default=6)
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--block-rows", type=int, default=512)
a = ap.parse_args()

con = duckdb.connect()
con.execute("INSTALL h3 FROM community; LOAD h3;")
con.execute("CREATE TABLE acc (h3 UBIGINT, s DOUBLE, n BIGINT)")
t0 = time.time()
with rasterio.open(a.raster) as src:
    assert src.crs and src.crs.to_epsg() == 4326, f"expected EPSG:4326, got {src.crs}"
    T, nd = src.transform, src.nodata
    cols = np.arange(src.width)
    lon_all = (T.c + (cols + 0.5) * T.a).astype(np.float64)
    for r0 in range(0, src.height, a.block_rows):
        h = min(a.block_rows, src.height - r0)
        blk = src.read(1, window=((r0, r0 + h), (0, src.width))).astype(np.float64)
        valid = np.isfinite(blk)
        if nd is not None:
            valid &= blk != nd
        rr, cc = np.nonzero(valid)
        if rr.size == 0:
            continue
        lat = T.f + (r0 + rr + 0.5) * T.e
        batch = pa.table({"lat": lat, "lng": lon_all[cc], "v": blk[rr, cc] * a.scale})
        con.register("batch", batch)
        con.execute(f"""INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {a.res}) AS h3, sum(v), count(*)
                        FROM batch GROUP BY 1""")
        con.unregister("batch")
        if (r0 // a.block_rows) % 10 == 0:
            print(f"rows {r0}/{src.height}  {time.time()-t0:.0f}s", flush=True)

agg = "sum(s)" if a.agg == "sum" else "sum(s)/sum(n)"
tbl = con.execute(f"""SELECT h3, CAST({agg} AS FLOAT) AS value, CAST(sum(n) AS INTEGER) AS n_valid
                      FROM acc GROUP BY h3 ORDER BY h3""").to_arrow_table()
pq.write_table(tbl, a.out, compression="zstd")
print(f"cells={tbl.num_rows:,}  written {a.out}  {time.time()-t0:.0f}s")
