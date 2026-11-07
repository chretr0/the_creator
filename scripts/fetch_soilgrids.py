"""Clip SoilGrids 2.0 (250 m) layers to the demo bbox straight from the ISRIC cloud VRTs.

Run:  uv run --no-project --with rasterio python -I scripts/fetch_soilgrids.py <out_dir> [W,S,E,N]
      e.g. data/raw/SOIL-01/arizona/soilgrids_v2 -113.5,31.3,-109.0,34.5  (default bbox: Arizona)
Output stays in the native Interrupted Goode Homolosine CRS (ESRI:54052); values keep SoilGrids
integer scaling (e.g. phh2o = pH x 10, soc = dg/kg). See https://docs.isric.org/globaldata/soilgrids/
"""
import os
import sys

import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

BBOX = tuple(float(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else (-113.5, 31.3, -109.0, 34.5)  # W,S,E,N
BASE = "/vsicurl/https://files.isric.org/soilgrids/latest/data"
LAYERS = [
    (var, depth, stat)
    for var in ("phh2o", "soc", "clay", "sand", "nitrogen", "bdod")
    for depth in ("0-5cm", "15-30cm")
    for stat in ("mean", "uncertainty")
]

out = sys.argv[1] if len(sys.argv) > 1 else "data/raw/SOIL-01/arizona/soilgrids_v2"
os.makedirs(out, exist_ok=True)
with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
    for var, depth, stat in LAYERS:
        name = f"{var}_{depth}_{stat}"
        dest = os.path.join(out, name + ".tif")
        if os.path.exists(dest):
            print("skip", dest)
            continue
        try:
            with rasterio.open(f"{BASE}/{var}/{name}.vrt") as src:
                bounds = transform_bounds("EPSG:4326", src.crs, *BBOX, densify_pts=50)
                win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                data = src.read(1, window=win)
                prof = src.profile | {
                    "driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
                    "transform": src.window_transform(win), "compress": "deflate", "tiled": True,
                }
                prof.pop("blockxsize", None); prof.pop("blockysize", None)
                with rasterio.open(dest, "w", **prof) as dst:
                    dst.write(data, 1)
            print(f"ok   {dest} {data.shape} nodata={src.nodata}")
        except Exception as e:  # keep going; report at end
            print(f"FAIL {name}: {e}")
