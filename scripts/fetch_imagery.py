"""Clip one low-cloud Sentinel-2 L2A and one Landsat C2 L2 scene over a small demo window.

Uses Microsoft Planetary Computer STAC (no account; URLs are signed on the fly).
Run:  uv run --no-project --with rasterio --with pystac-client --with planetary-computer \
        python -I scripts/fetch_imagery.py data/raw
Writes data/raw/OBS-02/... and data/raw/OBS-04/... plus an item.json with the full STAC metadata.
"""
import json
import os
import sys

import planetary_computer
import pystac_client
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

ROOT = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
WINDOW = (-111.05, 33.30, -110.70, 33.50)  # Globe–Miami copper district, Arizona
JOBS = [
    ("OBS-02", "sentinel-2-l2a", "2025-04-01/2025-06-30", ["B02", "B03", "B04", "B08", "B11", "B12", "SCL"]),
    ("OBS-04", "landsat-c2-l2", "2025-04-01/2025-06-30", ["blue", "green", "red", "nir08", "swir16", "swir22", "lwir11", "qa_pixel"]),
]

cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                modifier=planetary_computer.sign_inplace)
for sid, coll, dates, bands in JOBS:
    items = list(cat.search(collections=[coll], bbox=WINDOW, datetime=dates,
                            query={"eo:cloud_cover": {"lt": 5}}).items())
    items = [i for i in items if all(b in i.assets for b in bands)]
    if not items:
        print(f"FAIL {sid}: no items"); continue
    item = sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100))[0]
    out = os.path.join(ROOT, sid, item.id)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "item.json"), "w") as f:
        d = item.to_dict()
        for a in d.get("assets", {}).values():  # drop expiring SAS tokens from stored metadata
            a["href"] = a["href"].split("?")[0]
        json.dump(d, f, indent=1)
    for b in bands:
        dest = os.path.join(out, f"{b}.tif")
        if os.path.exists(dest):
            continue
        with rasterio.open(item.assets[b].href) as src:
            win = from_bounds(*transform_bounds("EPSG:4326", src.crs, *WINDOW), transform=src.transform)
            win = win.round_offsets().round_lengths()
            data = src.read(1, window=win)
            prof = src.profile | {"driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
                                  "transform": src.window_transform(win), "compress": "deflate", "tiled": True}
            prof.pop("blockxsize", None); prof.pop("blockysize", None)
            with rasterio.open(dest, "w", **prof) as dst:
                dst.write(data, 1)
    print(f"ok   {sid} {item.id} cloud={item.properties.get('eo:cloud_cover')} -> {out}")
