"""Make true-colour PNG overlays (EPSG:4326, transparent nodata) from the demo satellite scene clips.

Run:
  uv run --no-project --with rasterio --with numpy --with pillow \
    python -I scripts/prepare_imagery.py [--data data] [--max-px 2400]

Inputs (one clipped scene each, Globe–Miami, Arizona; provenance in source.json, scene metadata in item.json):
  OBS-02  data/raw/OBS-02/arizona/<scene>/B04.tif, B03.tif, B02.tif   Sentinel-2 L2A, 10 m, UTM 12N
  OBS-04  data/raw/OBS-04/arizona/<scene>/red.tif, green.tif, blue.tif  Landsat 8 C2 L2, 30 m, UTM 12N

Outputs: data/prepared/imagery/<scene-id>.png and manifest.json
  {"scenes": [{"id", "name", "file", "bounds": [w,s,e,n] (WGS84), "acquired", "sourceId", "attribution",
               "licence", "crs", "stretch"}]}

Method: bands are warped to EPSG:4326 (bilinear; square ~native-resolution pixels, capped at --max-px on the
long side), then one linear 2–98 percentile stretch shared by the three bands (keeps the colour balance) and
a mild gamma. Pixels where any band is nodata (0) are fully transparent. The PNG is a display product
only: values are not reflectance and must not be used for analysis.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

SCENES = [  # (source id, band file names R,G,B, short name)
    ("OBS-02", ("B04.tif", "B03.tif", "B02.tif"), "Sentinel-2 L2A true colour"),
    ("OBS-04", ("red.tif", "green.tif", "blue.tif"), "Landsat 8 L2 true colour"),
]
DST_CRS = "EPSG:4326"
GAMMA = 1 / 1.3


def warp_bands(paths: list[str], max_px: int):
    with rasterio.open(paths[0]) as src:
        transform, w, h = calculate_default_transform(src.crs, DST_CRS, src.width, src.height, *src.bounds)
        scale = max(w, h) / max_px
        if scale > 1:
            transform = transform * rasterio.Affine.scale(scale)
            w, h = int(round(w / scale)), int(round(h / scale))
    out = np.zeros((3, h, w), dtype=np.float32)
    valid = np.ones((h, w), dtype=bool)
    for i, p in enumerate(paths):
        with rasterio.open(p) as src:
            a = src.read(1).astype(np.float32)
            nd = src.nodata if src.nodata is not None else 0
            a[a == nd] = np.nan
            dst = np.full((h, w), np.nan, dtype=np.float32)
            reproject(a, dst, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                      dst_transform=transform, dst_crs=DST_CRS, dst_nodata=np.nan, resampling=Resampling.bilinear)
        out[i] = dst
        valid &= np.isfinite(dst)
    w_, n_ = transform.c, transform.f
    bounds = [w_, n_ + h * transform.e, w_ + w * transform.a, n_]
    return out, valid, [round(float(b), 6) for b in bounds]


def to_rgba(bands: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, list[float]]:
    lo, hi = np.percentile(bands[:, valid], [2, 98])
    x = np.clip((bands - lo) / (hi - lo), 0, 1) ** GAMMA
    rgba = np.zeros((*valid.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.where(valid[..., None], np.moveaxis(x, 0, -1) * 255, 0).round().astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0)
    return rgba, [float(lo), float(hi)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="data")
    ap.add_argument("--max-px", type=int, default=2400, help="cap on the PNG's long side")
    a = ap.parse_args()
    data = Path(a.data)
    out_dir = data / "prepared" / "imagery"
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = []
    for sid, names, label in SCENES:
        for scene_dir in sorted(glob.glob(str(data / "raw" / sid / "arizona" / "*/"))):
            scene_dir = Path(scene_dir)
            paths = [str(scene_dir / n) for n in names]
            if not all(Path(p).exists() for p in paths):
                continue
            item = json.loads((scene_dir / "item.json").read_text())
            rec = json.loads((data / "raw" / sid / "arizona" / "source.json").read_text())
            bands, valid, bounds = warp_bands(paths, a.max_px)
            rgba, (lo, hi) = to_rgba(bands, valid)
            png = out_dir / f"{scene_dir.name}.png"
            Image.fromarray(rgba, "RGBA").save(png, optimize=True)
            acquired = item["properties"]["datetime"][:10]
            scenes.append({
                "id": scene_dir.name, "name": f"{label}, {acquired} (Globe–Miami)", "file": png.name,
                "bounds": bounds, "acquired": acquired, "sourceId": sid,
                "attribution": rec["licence"]["attribution"], "licence": rec["licence"]["name"],
                "crs": DST_CRS, "width": rgba.shape[1], "height": rgba.shape[0],
                "stretch": f"linear {lo:.0f}–{hi:.0f} DN (2–98th percentile, shared by R,G,B), gamma {GAMMA:.2f}; display only",
            })
            print(f"{png}  {rgba.shape[1]}x{rgba.shape[0]}  {png.stat().st_size/1e6:.1f} MB  bounds={bounds}")
    man = {"generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "scenes": scenes}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
