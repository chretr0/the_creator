"""GLOBAL MODE (opt-in). Not part of the default data scope: big datasets are kept for the arizona/uk
regions only (data/README.md §0.1). Kept for reference and for deliberate global runs.

Fetch global NASA POWER grids (CTX-02) from the public `nasa-power` S3 Zarr stores and
sample them at every H3 resolution-6 cell centre.

Run from the repo root:
  uv run --no-project --with xarray --with zarr --with s3fs --with h5netcdf --with h5py --with h3 \
      --with pyarrow --with numpy python -I scripts/fetch_power_global.py [fetch|aggregate|all]

fetch:     subsets (variable x time) of four Zarr stores -> data/raw/CTX-02/global/*.nc
           MERRA-2 (0.5 deg x 0.625 deg): T2M, PRECTOTCORR, WS10M
           CERES SYN1deg (1 deg x 1 deg):  ALLSKY_SFC_SW_DWN, CLRSKY_SFC_SW_DWN
           slices: long-term climatology (12 months + annual) and calendar-year 2024 monthly means.
aggregate: nearest-native-grid-cell value at each of the 14,117,882 H3 res-6 cell centres
           -> data/prepared/power_<var>_<slice>_h3r6.parquet (h3 uint64 + one float32 column per period).

Values are copied unchanged except SYN1deg irradiance, converted W m-2 -> kWh/m^2/day (x0.024) to
match the POWER API unit. NaN/fill -> Parquet null.
Values repeat across all H3 cells that fall inside the same native grid cell; they are NOT
finer-resolution measurements.
"""
import hashlib
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "CTX-02", "global")
PREP = os.path.join(ROOT, "data", "prepared")
BUCKET = "nasa-power"

# Time standard: the POWER API climatology/monthly endpoints report LST; use the *_lst stores to match.
TS = "lst"
STORES = {
    ("merra2", "climatology"): ["T2M", "PRECTOTCORR", "WS10M"],
    ("merra2", "monthly"): ["T2M", "PRECTOTCORR", "WS10M"],
    ("syn1deg", "climatology"): ["ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN"],
    ("syn1deg", "monthly"): ["ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN"],
}
NATIVE = {"merra2": "MERRA-2, 0.5 deg lat x 0.625 deg lon", "syn1deg": "CERES SYN1deg Ed4.x, 1 deg x 1 deg"}
MONTHS = [f"m{m:02d}" for m in range(1, 13)]
# SYN1deg Zarr stores irradiance as mean W m-2; the POWER API publishes the same field as kW-hr/m^2/day.
# Verified: Zarr 243.65 W m-2 * 0.024 = 5.8476 == API ANN value at (33.5, -112.5). Convert to the API unit
# so prepared layers match the POWER API and data/README.md; raw NetCDF stays in native W m-2.
TO_API_UNITS = {"W m-2": (0.024, "kWh/m^2/day")}


def store_path(prod, temporal):
    return f"{BUCKET}/{prod}/spatial/power_{prod}_{temporal}_spatial_{TS}.zarr"


def raw_name(prod, temporal):
    sl = "climatology" if temporal == "climatology" else "monthly2024"
    return f"power_{prod}_{sl}_{TS}.nc"


def fetch():
    import s3fs
    import xarray as xr

    os.makedirs(RAW, exist_ok=True)
    fs = s3fs.S3FileSystem(anon=True)
    for (prod, temporal), vars_ in STORES.items():
        path = store_path(prod, temporal)
        ds = xr.open_zarr(fs.get_mapper(path), consolidated=True)
        sub = ds[vars_]
        if temporal == "monthly":
            sub = sub.sel(time=slice("2024-01-01", "2024-12-31"))
            assert sub.sizes["time"] == 12, sub.time.values
        else:
            assert sub.sizes["time"] == 13, sub.time.values  # 1..12 months, 13 = annual
        sub = sub.load()
        sub.attrs["fetched_from"] = f"s3://{path}"
        sub.attrs["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = os.path.join(RAW, raw_name(prod, temporal))
        for v in vars_:
            sub[v].encoding = {"zlib": True, "complevel": 4, "dtype": "float32", "_FillValue": np.float32(-999.0)}
        sub.to_netcdf(out, engine="h5netcdf")
        print(f"wrote {out} {os.path.getsize(out)/1e6:.2f} MB  time={sub.time.values.tolist()}")


def h3_res6_centres():
    import h3
    import h3.api.numpy_int as h3n

    t = time.time()
    cells = np.concatenate([h3n.cell_to_children(h3.str_to_int(c), 6) for c in h3.get_res0_cells()])
    cells.sort()
    assert len(cells) == h3.get_num_cells(6) == 14_117_882
    ll = np.fromiter((x for c in cells.tolist() for x in h3n.cell_to_latlng(c)), np.float64, count=2 * len(cells))
    lat, lng = ll[0::2].copy(), ll[1::2].copy()
    print(f"enumerated {len(cells):,} res-6 cells + centres in {time.time()-t:.1f}s")
    return cells, lat, lng


def nearest_index(coord, query, periodic):
    coord = np.asarray(coord, np.float64)
    d = np.diff(coord)
    step = d.mean()
    assert np.allclose(d, step, atol=1e-6), "grid is not regular"
    idx = np.rint((query - coord[0]) / step).astype(np.int64)
    if periodic:
        idx %= len(coord)
    else:
        idx = np.clip(idx, 0, len(coord) - 1)
    return idx


def aggregate():
    import pyarrow as pa
    import pyarrow.parquet as pq
    import xarray as xr

    cells, lat, lng = h3_res6_centres()
    h3col = pa.array(cells, pa.uint64())
    results = {}
    for (prod, temporal), vars_ in STORES.items():
        src = os.path.join(RAW, raw_name(prod, temporal))
        ds = xr.open_dataset(src, engine="h5netcdf")
        iy = nearest_index(ds.lat.values, lat, periodic=False)
        ix = nearest_index(ds.lon.values, lng, periodic=True)
        slice_ = "climatology" if temporal == "climatology" else "monthly2024"
        cols = MONTHS + (["ann"] if temporal == "climatology" else [])
        for v in vars_:
            arr = ds[v].values.astype(np.float64)  # (time, lat, lon), NaN where fill
            attrs = ds[v].attrs
            native_units = str(attrs.get("units", ""))
            factor, units = TO_API_UNITS.get(native_units, (1.0, native_units))
            arr = (arr * factor).astype(np.float32)
            data = {"h3": h3col}
            for t, name in enumerate(cols):
                vals = arr[t][iy, ix]
                data[name] = pa.array(vals, pa.float32(), mask=np.isnan(vals))
            meta = {
                "source_id": "CTX-02",
                "variable": v,
                "long_name": str(attrs.get("long_name", "")),
                "units": units,
                "native_units_in_zarr": native_units,
                "unit_conversion": f"value = zarr_value * {factor} (W m-2 daily mean x 24 h / 1000)" if factor != 1.0 else "none",
                "definition": str(attrs.get("definition", "")),
                "slice": slice_,
                "period": ("long-term climatology; Zarr attrs say time_coverage "
                           f"{ds.attrs.get('time_coverage_start','?')}..{ds.attrs.get('time_coverage_end','?')} but the "
                           "POWER climatology API returns identical values labelled January 2001 - December 2025 "
                           "(unresolved); m01..m12 monthly means, ann = annual mean")
                if temporal == "climatology" else "calendar year 2024, monthly means m01..m12",
                "time_standard": ds.attrs.get("time_standard", TS.upper()),
                "native_res": NATIVE[prod],
                "sampling": "nearest native grid cell to each H3 res-6 cell centre; values repeat across all H3 "
                            "cells inside one native cell and are not finer-resolution measurements",
                "nodata": "null (never 0)",
                "upstream": f"s3://{store_path(prod, temporal)}",
                "power_version": str(ds.attrs.get("version", "")),
                "evidence_type": "modelled (reanalysis / satellite-derived)",
                "licence": "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project "
                           "funded through the NASA Earth Science/Applied Science Program.",
            }
            table = pa.table(data).replace_schema_metadata({"power": json.dumps(meta)} | {k: str(x) for k, x in meta.items()})
            out = os.path.join(PREP, f"power_{v}_{slice_}_h3r6.parquet")
            pq.write_table(table, out, compression="zstd", compression_level=9, row_group_size=1 << 20)
            # sanity stats over all H3 cells (area-weighted by construction): climatology 'ann' column,
            # 2024 = unweighted mean of the 12 monthly columns
            col = arr[-1] if temporal == "climatology" else np.nanmean(arr, axis=0)
            sampled = col[iy, ix]
            results[os.path.relpath(out, ROOT)] = dict(
                rows=table.num_rows, bytes=os.path.getsize(out), sha256=sha256(out), columns=table.column_names[1:],
                units=units, native_res=NATIVE[prod], nulls_in_stat=int(np.isnan(sampled).sum()),
                stat=("ann" if temporal == "climatology" else "mean(m01..m12)"),
                min=round(float(np.nanmin(sampled)), 3), mean=round(float(np.nanmean(sampled)), 3),
                max=round(float(np.nanmax(sampled)), 3))
            print(os.path.basename(out), results[os.path.relpath(out, ROOT)])
    return results


def write_source(prepared):
    raw_files = sorted(f for f in os.listdir(RAW) if f.endswith(".nc"))
    q = []
    for (prod, temporal), vars_ in STORES.items():
        when = "time=1..13 (12 months + annual)" if temporal == "climatology" else "time in 2024-01..2024-12 (12 monthly steps)"
        q.append(f"s3://{store_path(prod, temporal)} vars={','.join(vars_)} {when}, full global lat/lon")
    rec = {
        "id": "CTX-02-power-global-v10",
        "catalogueSourceId": "CTX-02",
        "provider": "NASA Langley Research Center (LaRC) POWER Project",
        "product": "POWER spatial Zarr stores (AWS Open Data): MERRA-2 (T2M, PRECTOTCORR, WS10M) and CERES SYN1deg "
                   "(ALLSKY_SFC_SW_DWN, CLRSKY_SFC_SW_DWN); climatology + monthly, LST",
        "version": "POWER Version 10.0.0 (Zarr global attrs)",
        "doi": "",
        "documentationUrl": "https://power.larc.nasa.gov/docs/services/aws/",
        "accessUrl": "https://nasa-power.s3.amazonaws.com/",
        "accessMethod": "download (anonymous S3 / Zarr subset by variable and time)",
        "evidenceType": "modelled",
        "retrievedAt": time.strftime("%Y-%m-%d"),
        "files": [[f, sha256(os.path.join(RAW, f))] for f in raw_files],
        "licence": {
            "name": "NASA POWER open data (acknowledgement required)",
            "url": "https://power.larc.nasa.gov/docs/referencing/",
            "attribution": "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project "
                           "funded through the NASA Earth Science/Applied Science Program.",
            "notes": "Also acknowledge underlying products: NASA GMAO MERRA-2 (meteorology) and NASA CERES SYN1deg "
                     "(solar). Verify against the POWER referencing page before publishing.",
        },
        "query": "; ".join(q),
        "nativeResolution": {"merra2": NATIVE["merra2"] + " (361 x 576 grid, centres lat -90..90, lon -180..179.375)",
                             "syn1deg": NATIVE["syn1deg"] + " (180 x 360 grid, centres lat -89.5..89.5, lon -179.5..179.5)"},
        "timeStandard": "LST (matches the POWER climatology/monthly API; verified at 33.5,-112.5)",
        "climatologyPeriodNote": "Zarr attrs state time_coverage 2001-01-01..2020-12-31; the POWER climatology API "
                                 "returns identical values at the checked point labelled 'January 2001 - December 2025'. Unresolved.",
        "units": {"T2M": "C", "PRECTOTCORR": "mm/day", "WS10M": "m/s",
                  "ALLSKY_SFC_SW_DWN": "raw .nc: W m-2 (daily-mean irradiance); prepared: kWh/m^2/day = W m-2 x 0.024, "
                                       "the unit the POWER API publishes (verified: 243.65 W m-2 -> 5.8476, API ANN 5.8476)",
                  "CLRSKY_SFC_SW_DWN": "as ALLSKY_SFC_SW_DWN"},
        "processing": {
            "script": "scripts/fetch_power_global.py",
            "method": "Every H3 res-6 cell (14,117,882; enumerated via cell_to_children of the 122 res-0 cells) takes the "
                      "value of the native grid cell nearest its centre (longitude wraps; latitude clipped).",
            "warning": "Values repeat across all H3 cells within one native grid cell (~0.5 x 0.625 deg or 1 x 1 deg, i.e. "
                       "~2,000-12,000 km2 at the equator vs ~36 km2 per res-6 cell). They are NOT finer-resolution "
                       "measurements; adjacent cells straddling a native boundary may step abruptly.",
            "nodata": "NaN/_FillValue -> Parquet null, never 0 (no nulls occur in these global model fields).",
            "evidence": "MERRA-2 is a reanalysis (model + assimilated observations); SYN1deg is satellite-derived (CERES) "
                        "with modelled radiative transfer. Neither is an in-situ measurement.",
            "parquetSchema": "h3 uint64 (sorted) + float32 columns m01..m12 (+ ann for climatology); per-file schema "
                             "metadata key 'power' holds JSON provenance incl. native_res and units.",
        },
        "prepared": prepared,
    }
    out = os.path.join(RAW, "source.json")
    with open(out, "w") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("wrote", out)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("fetch", "all"):
        fetch()
    if step in ("aggregate", "all"):
        write_source(aggregate())
