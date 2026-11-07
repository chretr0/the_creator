"""Reproject a raster (e.g. SoilGrids 1 km in Interrupted Goode Homolosine) to an EPSG:4326 grid,
streaming row blocks through a GDAL WarpedVRT so the full global array is never held in memory.

Run:
  uv run --no-project --with rasterio --with numpy python -I scripts/reproject_to_4326.py <in.tif> <out.tif> \
      [--res 0.008333333333333333] [--resampling nearest|bilinear] [--south -90 --north 90]

Nodata is carried through as nodata (never 0). Nearest neighbour is the default so every output
pixel is an original SoilGrids prediction; bilinear is available but mixes neighbouring values.
"""
import argparse
import time

import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--res", type=float, default=1 / 120)
ap.add_argument("--resampling", choices=["nearest", "bilinear"], default="nearest")
ap.add_argument("--south", type=float, default=-90.0)
ap.add_argument("--north", type=float, default=90.0)
ap.add_argument("--block-rows", type=int, default=1024)
a = ap.parse_args()

t0 = time.time()
width = round(360 / a.res)
height = round((a.north - a.south) / a.res)
transform = from_origin(-180.0, a.north, a.res, a.res)

with rasterio.open(a.src) as src:
    nd = src.nodata
    assert nd is not None, "source has no nodata value; refusing to guess"
    dtype = src.dtypes[0]
    with WarpedVRT(src, crs="EPSG:4326", transform=transform, width=width, height=height,
                   resampling=Resampling[a.resampling], src_nodata=nd, nodata=nd,
                   warp_mem_limit=512, warp_extras={"NUM_THREADS": "ALL_CPUS"}) as vrt:
        profile = dict(driver="GTiff", dtype=dtype, count=1, crs="EPSG:4326", transform=transform,
                       width=width, height=height, nodata=nd, tiled=True, blockxsize=512,
                       blockysize=512, compress="deflate", predictor=2, BIGTIFF="IF_SAFER")
        with rasterio.open(a.dst, "w", **profile) as dst:
            for r0 in range(0, height, a.block_rows):
                h = min(a.block_rows, height - r0)
                w = Window(0, r0, width, h)
                blk = vrt.read(1, window=w)
                dst.write(blk, 1, window=w)
            dst.update_tags(SOURCE=a.src.rsplit("/", 1)[-1], RESAMPLING=a.resampling)
print(f"{a.dst}  {width}x{height}  nodata={nd}  {time.time()-t0:.0f}s")
