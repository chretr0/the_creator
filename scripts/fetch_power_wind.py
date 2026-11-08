"""Fetch the long-term annual-mean 10 m wind vector (NASA POWER CTX-02, MERRA-2) for the Timeline.

The Timeline moves each building's air releases with the local climate wind. It only needs the wind
at building locations, so this keeps the native MERRA-2 grid (361 x 576, ~0.5 x 0.625 deg) in one small
committed file instead of a 14-million-cell H3 layer:

  data/prepared/power_wind10m_annual_grid.npz   (int16 centi-m/s; ~1 MB; read by backend/app/local_wind.py)

Variables, all from the POWER MERRA-2 climatology Zarr store (LST), annual slot (time index 13):
  U10M  eastward wind, V10M northward wind: averaged as components, so (U, V) is the vector-mean wind,
        i.e. the net long-term drift. Opposing winds cancel, so its speed is <= the mean speed.
  WS10M mean wind speed (scalar average of hourly speeds), kept for context.

Run from the repo root:
  uv run --no-project --with xarray --with zarr --with s3fs --with h5netcdf --with h5py --with numpy \
      python -I scripts/fetch_power_wind.py [fetch|prepare|all]
"""
import hashlib
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "CTX-02", "wind")
RAW_FILE = os.path.join(RAW, "power_merra2_wind10m_climatology_lst.nc")
OUT = os.path.join(ROOT, "data", "prepared", "power_wind10m_annual_grid.npz")
STORE = "nasa-power/merra2/spatial/power_merra2_climatology_spatial_lst.zarr"
VARS = ["U10M", "V10M", "WS10M"]
SCALE = 100  # stored as int16 centi-m/s: +-327 m/s range, 0.01 m/s resolution


def fetch():
    import s3fs
    import xarray as xr

    os.makedirs(RAW, exist_ok=True)
    fs = s3fs.S3FileSystem(anon=True)
    ds = xr.open_zarr(fs.get_mapper(STORE), consolidated=True)
    sub = ds[VARS]
    assert sub.sizes["time"] == 13, sub.time.values  # 1..12 months, 13 = annual
    sub = sub.load()
    sub.attrs["fetched_from"] = f"s3://{STORE}"
    sub.attrs["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for v in VARS:
        sub[v].encoding = {"zlib": True, "complevel": 4, "dtype": "float32", "_FillValue": np.float32(-999.0)}
    sub.to_netcdf(RAW_FILE, engine="h5netcdf")
    print(f"wrote {RAW_FILE} {os.path.getsize(RAW_FILE) / 1e6:.2f} MB")


def regular(coord):
    coord = np.asarray(coord, np.float64)
    step = np.diff(coord).mean()
    assert np.allclose(np.diff(coord), step, atol=1e-6), "grid is not regular"
    return float(coord[0]), float(step), len(coord)


def prepare():
    import xarray as xr

    ds = xr.open_dataset(RAW_FILE, engine="h5netcdf")
    lat0, dlat, nlat = regular(ds.lat.values)
    lon0, dlon, nlon = regular(ds.lon.values)
    arrays = {}
    for v in VARS:
        assert str(ds[v].attrs.get("units")) == "m/s", ds[v].attrs
        annual = ds[v].values[-1].astype(np.float64)  # (lat, lon); time index 13 = annual
        assert annual.shape == (nlat, nlon) and np.isfinite(annual).all(), v
        assert np.abs(annual).max() * SCALE < 32767
        arrays[v.lower()] = np.rint(annual * SCALE).astype(np.int16)
    meta = {
        "source_id": "CTX-02",
        "product": "NASA POWER MERRA-2 climatology (LST), annual mean",
        "variables": {"u10m": "U10M eastward wind at 10 m", "v10m": "V10M northward wind at 10 m",
                      "ws10m": "WS10M mean wind speed at 10 m"},
        "units": f"m/s; stored as int16 = value x {SCALE}",
        "grid": {"lat0": lat0, "dlat": dlat, "nlat": nlat, "lon0": lon0, "dlon": dlon, "nlon": nlon,
                 "lookup": "nearest native cell centre; longitude wraps, latitude clipped"},
        "period": "long-term climatology (store attrs 2001-2020; POWER API labels it 2001-2025, unresolved)",
        "upstream": f"s3://{STORE}",
        "power_version": str(ds.attrs.get("version", "")),
        "evidence_type": "modelled (reanalysis)",
        "interpretation": "(U10M, V10M) is the vector-mean wind: the net long-term drift. It is not a forecast, "
                          "not local terrain-resolved wind and not the prevailing (most frequent) direction.",
        "licence": "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project "
                   "funded through the NASA Earth Science/Applied Science Program.",
    }
    np.savez_compressed(OUT, meta=np.array(json.dumps(meta)), **arrays)
    print(f"wrote {OUT} {os.path.getsize(OUT) / 1e6:.2f} MB")
    speed = np.hypot(arrays["u10m"], arrays["v10m"]) / SCALE
    print(f"net drift speed m/s: min {speed.min():.2f} mean {speed.mean():.2f} max {speed.max():.2f}; "
          f"mean speed m/s: mean {arrays['ws10m'].mean() / SCALE:.2f}")
    write_source(meta)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_source(meta):
    record = {
        "id": "CTX-02-power-wind10m-annual",
        "catalogueSourceId": "CTX-02",
        "provider": "NASA Langley Research Center (LaRC) POWER Project",
        "product": meta["product"] + ": U10M, V10M, WS10M",
        "accessUrl": "https://nasa-power.s3.amazonaws.com/",
        "documentationUrl": "https://power.larc.nasa.gov/docs/services/aws/",
        "accessMethod": "download (anonymous S3 / Zarr subset by variable)",
        "evidenceType": "modelled",
        "retrievedAt": time.strftime("%Y-%m-%d"),
        "files": [[os.path.basename(RAW_FILE), sha256(RAW_FILE)]],
        "prepared": [[os.path.relpath(OUT, ROOT), sha256(OUT)]],
        "query": f"s3://{STORE} vars={','.join(VARS)} time=1..13, full global lat/lon",
        "processing": {"script": "scripts/fetch_power_wind.py", "kept": "annual slot only, native grid",
                       "use": "Timeline air transport: each building's air releases drift with the wind at its own grid cell."},
        "interpretation": meta["interpretation"],
        "licence": {"name": "NASA POWER open data (acknowledgement required)",
                    "url": "https://power.larc.nasa.gov/docs/referencing/",
                    "attribution": meta["licence"] + " Underlying meteorology: NASA GMAO MERRA-2."},
    }
    out = os.path.join(RAW, "source.json")
    with open(out, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("wrote", out)


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("fetch", "all"):
        fetch()
    if step in ("prepare", "all"):
        prepare()
