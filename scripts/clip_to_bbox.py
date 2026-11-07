"""Clip a raster, vector or point-CSV dataset to a lon/lat bounding box.

Used by fetch_open_data.sh to keep big datasets Arizona-only (see data/README.md "Data scope").

  uv run --no-project --with rasterio --with pyogrio --with duckdb python -I scripts/clip_to_bbox.py \
      raster <src> <dst.tif>          --bbox W,S,E,N
      vector <src> <dst.gpkg>         --bbox W,S,E,N [--layer NAME ...]   (all layers if omitted)
      points <src.csv> <dst.csv>      --bbox W,S,E,N [--lat latitude --lon longitude]

<src> may be a GDAL virtual path such as /vsizip/file.zip/inner.tif.
Rasters keep their native CRS, pixel grid and nodata; vectors keep every feature whose geometry
intersects the box (features are not cut at the edge). Points keep rows inside the box.
"""
import argparse
import os


def bbox_arg(s):
    w, s_, e, n = (float(x) for x in s.split(","))
    assert w < e and s_ < n, "bbox must be W,S,E,N with W<E and S<N (no date-line crossing)"
    return w, s_, e, n


def clip_raster(src, dst, bbox):
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open(src) as r:
        b = transform_bounds("EPSG:4326", r.crs, *bbox, densify_pts=50) if r.crs.to_epsg() != 4326 else bbox
        win = from_bounds(*b, transform=r.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, r.width, r.height))
        data = r.read(window=win)
        prof = r.profile | {"driver": "GTiff", "height": data.shape[1], "width": data.shape[2],
                            "transform": r.window_transform(win), "compress": "deflate", "tiled": True}
        for k in ("blockxsize", "blockysize", "photometric"):
            prof.pop(k, None)
        with rasterio.open(dst, "w", **prof) as out:
            out.write(data)
    print(f"raster {dst} {data.shape}")


def clip_vector(src, dst, bbox, layers):
    import pyogrio

    names = layers or [n for n, _ in pyogrio.list_layers(src)]
    if os.path.exists(dst):
        os.remove(dst)
    for name in names:
        info = pyogrio.read_info(src, layer=name)
        crs = info.get("crs") or "EPSG:4326"
        b = bbox
        if crs not in ("EPSG:4326", "OGC:CRS84"):
            from pyproj import Transformer
            b = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform_bounds(*bbox)
        try:
            df = pyogrio.read_dataframe(src, layer=name, bbox=b)
        except pyogrio.errors.FeatureError:
            # Some shapefiles ship a corrupt .sbn spatial index (seen in HydroBASINS na lev04-06):
            # read everything and filter in memory instead.
            df = pyogrio.read_dataframe(src, layer=name)
            df = df[df.intersects(__import__("shapely").geometry.box(*b))]
        pyogrio.write_dataframe(df, dst, layer=name, driver="GPKG", append=os.path.exists(dst))
        print(f"vector {dst}:{name} {len(df)} features")


def clip_points(src, dst, bbox, lat, lon):
    import duckdb

    w, s, e, n = bbox
    duckdb.sql(f"""COPY (SELECT * FROM read_csv_auto('{src}', all_varchar=true)
                        WHERE TRY_CAST("{lon}" AS DOUBLE) BETWEEN {w} AND {e}
                          AND TRY_CAST("{lat}" AS DOUBLE) BETWEEN {s} AND {n})
                   TO '{dst}' (HEADER, DELIMITER ',')""")
    rows = duckdb.sql(f"SELECT count(*) FROM read_csv_auto('{dst}')").fetchall()[0][0]
    print(f"points {dst} {rows} rows")


ap = argparse.ArgumentParser()
ap.add_argument("kind", choices=["raster", "vector", "points"])
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--bbox", type=bbox_arg, required=True)
ap.add_argument("--layer", action="append")
ap.add_argument("--lat", default="latitude"); ap.add_argument("--lon", default="longitude")
a = ap.parse_args()
os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
{"raster": lambda: clip_raster(a.src, a.dst, a.bbox),
 "vector": lambda: clip_vector(a.src, a.dst, a.bbox, a.layer),
 "points": lambda: clip_points(a.src, a.dst, a.bbox, a.lat, a.lon)}[a.kind]()
