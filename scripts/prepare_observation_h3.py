"""Aggregate the satellite / reanalysis downloads to H3 resolution-6 cells, ready to colour the grid.

Run (one dataset, one region, or everything):
  uv run --no-project --with xarray --with netcdf4 --with h5netcdf --with rasterio --with pyproj \
    --with pyhdf --with duckdb --with pyarrow --with numpy --with h3 \
    python -I scripts/prepare_observation_h3.py [--dataset era5land|cams|...|all] [--region arizona|uk|all]

Inputs are data/raw/<ID>/<region>/ (provenance in each source.json). Outputs are
data/prepared/<dataset>_<region>_h3r6.parquet (or <dataset>_h3r6.parquet for global inputs), keyed by
`h3` (uint64, ascending, zstd), plus a JSON sidecar with provenance, method and per-column units.

Two ways a source becomes cell values, chosen by its pixel size against the ~36 km² res-6 cell:

- sample (grids coarser than a cell: ERA5-Land 0.1°, CAMS 0.75°, GRACE 0.25°/0.5°, SMAP 9 km, EMIT L3
  0.5°): every res-6 cell whose centre lies in the region box takes the value of the grid pixel that
  contains its centre, exactly like the NASA POWER climate layers. Neighbouring cells repeat values.
- mean (pixels finer than a cell: MODIS 1 km, GEDI 1 km, ECOSTRESS 70 m, SWOT 100 m, PACE 4 km, S5P
  ground pixels): mean of the valid pixels whose centres fall in the cell.

Fill, NaN and quality-flagged pixels are skipped, never counted as zero; cells with no valid pixel are
absent (shown grey). Monthly series also get an `ann` column: the mean of the months present in a cell.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr
from pyproj import Transformer

RES = 6
REGIONS = {
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
MONTHS = [f"m{i:02d}" for i in range(1, 13)]
DATA = Path("data")


# --------------------------------------------------------------------------- helpers
def h3_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    return con


_CELLS: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def cells_in(region: str):
    """(h3 uint64, lat, lng) of every res-6 cell whose centre lies in the region box (or the world)."""
    if region in _CELLS:
        return _CELLS[region]
    con = h3_con()
    if region == "global":
        base = [h3.str_to_int(c) for c in h3.get_res0_cells()]
        con.register("base", pa.table({"c": pa.array(base, pa.uint64())}))
        q = f"SELECT unnest(h3_cell_to_children(c, {RES})) AS h3 FROM base"
    else:
        w, s, e, n = REGIONS[region]
        wkt = f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"
        q = f"SELECT unnest(h3_polygon_wkt_to_cells('{wkt}', {RES})) AS h3"
    t = con.sql(f"SELECT h3, h3_cell_to_lat(h3) AS lat, h3_cell_to_lng(h3) AS lng FROM ({q}) ORDER BY h3").fetchnumpy()
    _CELLS[region] = (t["h3"].astype(np.uint64), t["lat"], t["lng"])
    return _CELLS[region]


def sample_regular(lat, lng, lat_c, lon_c, field):
    """Value of the regular-grid pixel (centres lat_c × lon_c) containing each point; NaN outside."""
    lat_c, lon_c = np.asarray(lat_c, float), np.asarray(lon_c, float)
    if lon_c.min() >= 0 and lon_c.max() > 180:
        lng = np.mod(lng, 360.0)
    dlat, dlon = lat_c[1] - lat_c[0], lon_c[1] - lon_c[0]
    i = np.floor((lat - (lat_c[0] - dlat / 2)) / dlat).astype(np.int64)
    j = np.floor((lng - (lon_c[0] - dlon / 2)) / dlon).astype(np.int64)
    ok = (i >= 0) & (i < lat_c.size) & (j >= 0) & (j < lon_c.size)
    out = np.full(lat.shape, np.nan)
    out[ok] = np.asarray(field, float)[i[ok], j[ok]]
    return out


def in_box(lat, lng, box):
    w, s, e, n = box
    return (lng >= w) & (lng < e) & (lat >= s) & (lat < n)


class Acc:
    """Long-format accumulator: (cell, column) → sum and count of valid values."""

    def __init__(self):
        self.con = h3_con()
        self.con.execute("CREATE TABLE acc (h3 UBIGINT, col VARCHAR, s DOUBLE, n BIGINT)")
        self.cols: list[str] = []

    def add(self, col: str, lat, lng, v, box=None) -> None:
        lat, lng, v = (np.asarray(x, dtype=np.float64).ravel() for x in (lat, lng, v))
        m = np.isfinite(v) & np.isfinite(lat) & np.isfinite(lng)
        if box is not None:
            m &= in_box(lat, lng, box)
        if col not in self.cols:
            self.cols.append(col)
        if not m.any():
            return
        self.con.register("batch", pa.table({"lat": lat[m], "lng": lng[m], "v": v[m]}))
        self.con.execute(f"""INSERT INTO acc SELECT h3_latlng_to_cell(lat, lng, {RES}), '{col}', sum(v), count(*)
                             FROM batch GROUP BY 1""")
        self.con.unregister("batch")

    def add_cells(self, col: str, cells, v) -> None:
        """Values already per res-6 cell (sampled grids)."""
        v = np.asarray(v, dtype=np.float64)
        m = np.isfinite(v)
        if col not in self.cols:
            self.cols.append(col)
        if not m.any():
            return
        self.con.register("batch", pa.table({"h3": pa.array(cells[m], pa.uint64()), "v": v[m]}))
        self.con.execute(f"INSERT INTO acc SELECT h3, '{col}', v, 1 FROM batch")
        self.con.unregister("batch")

    def table(self, counts: dict[str, str] | None = None, annual: list[str] | None = None) -> pa.Table:
        sel = [f"CAST(sum(s) FILTER (WHERE col = '{c}') / sum(n) FILTER (WHERE col = '{c}') AS FLOAT) AS \"{c}\""
               for c in self.cols]
        sel += [f"CAST(coalesce(sum(n) FILTER (WHERE col = '{c}'), 0) AS INTEGER) AS \"{name}\""
                for name, c in (counts or {}).items()]
        tbl = self.con.sql(f"SELECT h3, {', '.join(sel)} FROM acc GROUP BY h3 ORDER BY h3").to_arrow_table()
        for prefix in annual or []:
            cols = [f"{prefix}{m}" for m in MONTHS if f"{prefix}{m}" in tbl.column_names]
            stack = np.vstack([tbl[c].to_numpy(zero_copy_only=False).astype(np.float64) for c in cols])
            with np.errstate(all="ignore"):
                ann = np.nanmean(stack, axis=0)
            tbl = tbl.append_column(f"{prefix}ann", pa.array(ann.astype(np.float32), from_pandas=True))
        return tbl


def source_record(source_id: str, region: str) -> dict:
    return json.loads((DATA / "raw" / source_id / region / "source.json").read_text())


def write(name: str, tbl: pa.Table, source_id: str, region: str, *, method: str, units: dict, files: list[str],
          native_res: str, sampling: str, period: str) -> None:
    out = DATA / "prepared" / (f"{name}_h3r6.parquet" if region == "global" else f"{name}_{region}_h3r6.parquet")
    meta = {"native_res": native_res, "sampling": sampling, "period": period, "definition": method}
    tbl = tbl.replace_schema_metadata({**(tbl.schema.metadata or {}), **{k: v.encode() for k, v in meta.items()}})
    pq.write_table(tbl, out, compression="zstd")
    rec = source_record(source_id, region)
    lic = rec.get("licence") or {}
    if isinstance(lic, str):
        lic = {"name": lic}
    side = {
        "layer": out.stem.removesuffix("_h3r6"),
        "sourceId": rec.get("catalogueSourceId", source_id),
        "provider": rec.get("provider"),
        "product": rec.get("product"),
        "version": rec.get("version"),
        "licence": lic.get("name"),
        "licenceUrl": lic.get("url"),
        "attribution": lic.get("attribution"),
        "evidenceType": rec.get("evidenceType"),
        "retrievedAt": rec.get("retrievedAt"),
        "method": method,
        "nativeResolution": native_res,
        "sampling": sampling,
        "period": period,
        "h3Resolution": RES,
        "units": units,
        "region": region,
        "regionBbox": list(REGIONS[region]) if region in REGIONS else None,
        "inputFiles": files,
        "rowCount": tbl.num_rows,
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "script": "scripts/prepare_observation_h3.py",
    }
    out.with_suffix(".json").write_text(json.dumps(side, indent=2, ensure_ascii=False) + "\n")
    stats = []
    for c in tbl.column_names[1:4]:
        a = tbl[c].to_numpy(zero_copy_only=False).astype(float)
        a = a[np.isfinite(a)]
        if a.size:
            stats.append(f"{c}: {np.percentile(a, 2):.4g}..{np.median(a):.4g}..{np.percentile(a, 98):.4g}")
    print(f"  -> {out}  rows={tbl.num_rows:,}  {out.stat().st_size / 1e6:.2f} MB  [{'; '.join(stats)}]", flush=True)


def _rel(paths) -> list[str]:
    return [Path(p).name for p in paths]


SAMPLE = ("Each res-6 cell whose centre lies in the region box takes the value of the grid pixel containing "
          "its centre (nearest-pixel sampling, as for the NASA POWER layers); neighbouring cells repeat values.")
MEAN = "Mean of valid pixels whose centres fall in each res-6 cell inside the region box."


# --------------------------------------------------------------------------- CTX-01 ERA5-Land
ERA5 = {  # var: (column prefix, convert, units)
    "t2m": ("t2m_", lambda a: a - 273.15, "°C"),
    "tp": ("tp_", lambda a: a * 1000.0, "mm/day"),
    "e": ("evap_", lambda a: a * -1000.0, "mm/day"),
    "ssrd": ("ssrd_", lambda a: a / 3.6e6, "kWh/m²/day"),
    "swvl1": ("swvl1_", lambda a: a, "m³/m³"),
}


def run_era5land(region: str) -> None:
    f = DATA / "raw" / "CTX-01" / region / "era5land_monthly_2024.nc"
    ds = xr.open_dataset(f)
    cells, lat, lng = cells_in(region)
    acc = Acc()
    for var, (prefix, conv, _) in ERA5.items():
        for k in range(ds.sizes["valid_time"]):
            month = int(str(ds.valid_time.values[k])[5:7])
            vals = conv(ds[var].isel(valid_time=k).values.astype(np.float64))
            acc.add_cells(f"{prefix}m{month:02d}", cells, sample_regular(lat, lng, ds.latitude, ds.longitude, vals))
    tbl = acc.table(annual=[p for p, _, _ in ERA5.values()])
    write("era5land_2024", tbl, "CTX-01", region,
          method=SAMPLE + " Monthly means of 2024; accumulated fields (tp, e, ssrd) are ERA5-Land's mean daily "
                          "accumulation for the month. Evaporation sign flipped so evaporation is positive. "
                          "ERA5-Land is land-only, so sea cells are absent.",
          units={f"{p}*": u for p, _, u in ERA5.values()}, files=[f.name], native_res="0.1° (~9 km)",
          sampling="nearest grid pixel at each cell centre", period="2024, monthly")


# --------------------------------------------------------------------------- AIR-02 CAMS EAC4
CAMS = {
    "pm2p5": ("pm25_", lambda a: a * 1e9, "µg/m³"),
    "pm10": ("pm10_", lambda a: a * 1e9, "µg/m³"),
    "tcno2": ("no2col_", lambda a: a / 0.046006 * 1e6, "µmol/m²"),
    "tcso2": ("so2col_", lambda a: a / 0.064066 * 1e6, "µmol/m²"),
    "tcco": ("cocol_", lambda a: a / 0.028010 * 1e3, "mmol/m²"),
    "aod550": ("aod_", lambda a: a, "1"),
}


def run_cams(region: str) -> None:
    f = DATA / "raw" / "AIR-02" / region / "cams_eac4_monthly_2024.nc"
    ds = xr.open_dataset(f)
    cells, lat, lng = cells_in(region)
    acc = Acc()
    for var, (prefix, conv, _) in CAMS.items():
        for k in range(ds.sizes["valid_time"]):
            month = int(str(ds.valid_time.values[k])[5:7])
            vals = conv(ds[var].isel(valid_time=k).values.astype(np.float64))
            acc.add_cells(f"{prefix}m{month:02d}", cells, sample_regular(lat, lng, ds.latitude, ds.longitude, vals))
    tbl = acc.table(annual=[p for p, _, _ in CAMS.values()])
    write("cams_2024", tbl, "AIR-02", region,
          method=SAMPLE + " CAMS EAC4 monthly means of 2024. PM is the model's lowest-level (near-surface) mass "
                          "concentration; NO2/SO2/CO are total columns converted from kg/m² with molar masses.",
          units={f"{p}*": u for p, _, u in CAMS.values()}, files=[f.name], native_res="0.75° (~80 km)",
          sampling="nearest grid pixel at each cell centre", period="2024, monthly")


# --------------------------------------------------------------------------- WATER-02 GRACE DA (7-day) and mascons
GRACE_DA = {"gws_inst": "gws_", "rtzsm_inst": "rtzsm_", "sfsm_inst": "sfsm_"}


def run_grace_da(region: str) -> None:
    files = sorted(glob.glob(str(DATA / "raw" / "WATER-02" / region / "GRACEDADM_*.nc4")))
    cells, lat, lng = cells_in(region)
    by_month: dict[int, list[str]] = defaultdict(list)
    for f in files:
        by_month[int(re.search(r"\.A\d{4}(\d{2})\d{2}\.", f).group(1))].append(f)
    acc = Acc()
    for month, fs in sorted(by_month.items()):
        dss = [xr.open_dataset(f) for f in fs]
        for var, prefix in GRACE_DA.items():
            stack = np.stack([d[var].isel(time=0).values.astype(np.float64) for d in dss])
            with np.errstate(all="ignore"):
                mean = np.nanmean(stack, axis=0)
            acc.add_cells(f"{prefix}m{month:02d}", cells, sample_regular(lat, lng, dss[0].lat, dss[0].lon, mean))
    tbl = acc.table(annual=list(GRACE_DA.values()))
    write("grace_dadm_2024", tbl, "WATER-02", region,
          method=SAMPLE + " Monthly value = mean of the 7-day wetness percentiles whose start date falls in the "
                          "month (2024). Percentiles are relative to the 1948-2014 Catchment model climatology.",
          units={f"{p}*": "percentile (0-100)" for p in GRACE_DA.values()}, files=_rel(files),
          native_res="0.25° (~25 km)", sampling="nearest grid pixel at each cell centre",
          period="2024, 7-day fields averaged to months")


def run_grace_mascon(region: str) -> None:
    f = DATA / "raw" / "WATER-02" / "global" / "GRCTellus.JPL.200204_202608.GLO.RL06.3M.MSCNv04CRI.nc"
    ds = xr.open_dataset(f, decode_times=False)
    epoch = dt.date(2002, 1, 1)
    land = ds.land_mask.values == 1
    sf = ds.scale_factor.values.astype(np.float64)
    cells, lat, lng = cells_in("global")
    acc = Acc()
    used = []
    for k, t in enumerate(ds.time.values):
        d = epoch + dt.timedelta(days=float(t))
        if d.year != 2024:
            continue
        used.append(d.isoformat())
        vals = np.where(land, ds.lwe_thickness.isel(time=k).values.astype(np.float64) * sf, np.nan)
        acc.add_cells(f"tws_m{d.month:02d}", cells, sample_regular(lat, lng, ds.lat, ds.lon, vals))
    tbl = acc.table(annual=["tws_"])
    write("grace_tws_2024", tbl, "WATER-02", "global",
          method=SAMPLE + " JPL RL06.3 CRI mascon liquid-water-equivalent thickness × the CRI land scale factor, "
                          "land mask applied (ocean absent). Anomaly relative to the 2004.0-2009.999 mean. "
                          f"2024 months present: {', '.join(used)}.",
          units={"tws_*": "cm equivalent water height (anomaly)"}, files=[f.name],
          native_res="0.5° grid of ~3° mascons", sampling="nearest grid pixel at each cell centre",
          period="2024, monthly")


# --------------------------------------------------------------------------- GEO-01 EMIT L3 mineral abundance
EMIT_MINERALS = ["Calcite", "Chlorite", "Dolomite", "Goethite", "Gypsum", "Hematite", "Illite+Muscovite",
                 "Kaolinite", "Montmorillonite", "Vermiculite", "Quartz+Feldspar"]


def emit_col(m: str) -> str:
    return m.lower().replace("+", "_")


def run_emit_l3(region: str) -> None:
    f = DATA / "raw" / "GEO-01" / "global" / "EMIT_L3_ASA_002.nc"
    ds = xr.open_dataset(f)
    cells, lat, lng = cells_in("global")
    box = (float(ds.lon.min()) - 0.25, float(ds.lat.min()) - 0.25, float(ds.lon.max()) + 0.25, float(ds.lat.max()) + 0.25)
    m = in_box(lat, lng, box)
    cells, lat, lng = cells[m], lat[m], lng[m]
    acc = Acc()
    for mineral in EMIT_MINERALS:
        vals = ds[mineral].values.astype(np.float64)
        vals[vals < 0] = np.nan  # fill
        acc.add_cells(emit_col(mineral), cells, sample_regular(lat, lng, ds.lat, ds.lon, vals))
    tbl = acc.table()
    write("emit_minerals", tbl, "GEO-01", "global",
          method=SAMPLE + " EMIT L3 aggregated spectral abundance (baseline estimate) per mineral; only pixels "
                          "EMIT observed carry values.",
          units={emit_col(x): "spectral abundance (fraction)" for x in EMIT_MINERALS}, files=[f.name],
          native_res="0.5° (~55 km)", sampling="nearest grid pixel at each cell centre",
          period="EMIT mission to date (2022-)")


# --------------------------------------------------------------------------- WATER-01 SMAP
def run_smap(region: str) -> None:
    f = sorted(glob.glob(str(DATA / "raw" / "WATER-01" / region / "smap_spl3smpe_*.nc")))[0]
    ds = xr.open_dataset(f)
    retrievals = []
    for p in ("am", "pm"):
        sm = ds[f"soil_moisture_{p}"].values.astype(np.float64)
        q = ds[f"retrieval_qual_flag_{p}"].values
        ok = np.isfinite(q) & ((np.nan_to_num(q, nan=1).astype(np.int64) & 1) == 0) & (sm >= 0)
        retrievals.append(np.where(ok, sm, np.nan))
    stack = np.concatenate(retrievals)  # (2 × days, y, x)
    with np.errstate(all="ignore"):
        mean = np.nanmean(stack, axis=0)
    count = np.isfinite(stack).sum(axis=0).astype(np.float64)
    count[count == 0] = np.nan
    cells, lat, lng = cells_in(region)
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform(lng, lat)
    acc = Acc()
    acc.add_cells("sm_mean", cells, sample_regular(y, x, ds.y.values, ds.x.values, mean))
    acc.add_cells("n_retrievals", cells, sample_regular(y, x, ds.y.values, ds.x.values, count))
    tbl = acc.table()
    dates = [str(d) for d in ds.date.values]
    write("smap_sm", tbl, "WATER-01", region,
          method=SAMPLE + " SMAP SPL3SMP_E surface soil moisture: mean of the AM and PM DCA retrievals with "
                          f"recommended quality (retrieval_qual_flag bit 0 = 0), {dates[0]}-{dates[-1]}; the "
                          "9 km EASE-Grid 2.0 pixel is found by projecting the cell centre to EPSG:6933.",
          units={"sm_mean": "m³/m³", "n_retrievals": "count of AM/PM retrievals"}, files=[Path(f).name],
          native_res="9 km EASE-Grid 2.0", sampling="nearest grid pixel at each cell centre",
          period=f"{dates[0]}-{dates[-1]}")


# --------------------------------------------------------------------------- LAND-04 GEDI L4B
def run_gedi(region: str) -> None:
    import rasterio
    acc = Acc()
    files = []
    for kind, col in (("MU", "agbd"), ("SE", "agbd_se")):
        f = sorted(glob.glob(str(DATA / "raw" / "LAND-04" / region / f"GEDI04_B_*_{kind}_{region}.tif")))[0]
        files.append(Path(f).name)
        with rasterio.open(f) as src:
            a = src.read(1).astype(np.float64)
            T, nd, crs = src.transform, src.nodata, src.crs
        a[(a == nd) | (a < 0)] = np.nan
        rr, cc = np.nonzero(np.isfinite(a))
        x = T.c + (cc + 0.5) * T.a
        y = T.f + (rr + 0.5) * T.e
        lng, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
        acc.add(col, lat, lng, a[rr, cc], box=REGIONS[region])
    tbl = acc.table(counts={"n_pixels": "agbd"})
    write("gedi_agbd", tbl, "LAND-04", region,
          method=MEAN + " GEDI L4B v2.1 1 km gridded aboveground biomass density (MU) and its standard error (SE), "
                        "pixel centres projected from EPSG:6933. agbd_se is the mean of the pixel standard errors, "
                        "not the error of the cell mean. GEDI samples only up to ~51.6°N.",
          units={"agbd": "Mg/ha", "agbd_se": "Mg/ha", "n_pixels": "count of 1 km pixels"}, files=files,
          native_res="1 km EASE-Grid 2.0", sampling="mean of pixel centres in cell", period="Apr 2019 - Mar 2023")


# --------------------------------------------------------------------------- OBS-06 MODIS NDVI (MOD13A3)
MODIS_R = 6371007.181
MODIS_TILE = 1111950.5196666666
MODIS_PIX = MODIS_TILE / 1200


def run_modis_ndvi(region: str) -> None:
    from pyhdf.SD import SD, SDC
    files = sorted(glob.glob(str(DATA / "raw" / "OBS-06" / region / "MOD13A3.*.hdf")))
    box = REGIONS[region]
    acc = Acc()
    t0 = time.time()
    for f in files:
        name = Path(f).name
        doy = int(name.split(".")[1][5:])
        month = (dt.date(int(name.split(".")[1][1:5]), 1, 1) + dt.timedelta(days=doy - 1)).month
        h, v = map(int, re.match(r"h(\d+)v(\d+)", name.split(".")[2]).groups())
        sd = SD(f, SDC.READ)
        ndvi = sd.select("1 km monthly NDVI").get().astype(np.float64)
        qa = sd.select("1 km monthly VI Quality").get().astype(np.int64)
        sd.end()
        ok = (ndvi != -3000) & ((qa & 3) <= 1)
        rr, cc = np.nonzero(ok)
        x = -20015109.355798 + h * MODIS_TILE + (cc + 0.5) * MODIS_PIX
        y = 10007554.677899 - v * MODIS_TILE - (rr + 0.5) * MODIS_PIX
        lat = np.degrees(y / MODIS_R)
        lng = np.degrees(x / (MODIS_R * np.cos(np.radians(lat))))
        acc.add(f"ndvi_m{month:02d}", lat, lng, ndvi[rr, cc] * 1e-4, box=box)
        print(f"  modis {region}: {name}  {time.time() - t0:.0f}s", flush=True)
    acc.cols.sort()
    tbl = acc.table(annual=["ndvi_"])
    write("modis_ndvi_2024", tbl, "OBS-06", region,
          method=MEAN + " MOD13A3 v061 monthly 1 km NDVI (DN × 0.0001) on the MODIS sinusoidal grid; pixels kept "
                        "when MODLAND QA bits 0-1 are 00 (good) or 01 (check other QA); fill (-3000) skipped.",
          units={"ndvi_*": "NDVI (-0.2 to 1)"}, files=_rel(files), native_res="1 km (MODIS sinusoidal)",
          sampling="mean of pixel centres in cell", period="2024, monthly")


# --------------------------------------------------------------------------- OBS-05 ECOSTRESS LST
def run_ecostress(region: str) -> None:
    import rasterio
    files = sorted(glob.glob(str(DATA / "raw" / "OBS-05" / region / "*_LST.tif")))
    acc = Acc()
    for f in files:
        stamp = re.search(r"_(\d{8})T(\d{6})_", f).group(1)
        with rasterio.open(f) as src:
            lst = src.read(1).astype(np.float64)
            T, crs = src.transform, src.crs
        with rasterio.open(f.replace("_LST.tif", "_cloud.tif")) as src:
            cloud = src.read(1)
        ok = np.isfinite(lst) & (lst > 150) & (cloud == 0)
        rr, cc = np.nonzero(ok)
        x = T.c + (cc + 0.5) * T.a
        y = T.f + (rr + 0.5) * T.e
        lng, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
        acc.add(f"lst_{stamp}", lat, lng, lst[rr, cc] - 273.15, box=REGIONS[region])
    acc.cols.sort()
    tbl = acc.table()
    write("ecostress_lst", tbl, "OBS-05", region,
          method=MEAN + " ECOSTRESS L2T LSTE v002 70 m land surface (skin) temperature, cloud-masked with the "
                        "granule's cloud layer; one column per overpass date (tiles of the same pass combined). "
                        "Single instantaneous snapshots at differing times of day.",
          units={"lst_*": "°C (skin temperature)"}, files=_rel(files), native_res="70 m",
          sampling="mean of pixel centres in cell", period="single overpasses, 2025")


# --------------------------------------------------------------------------- OCEAN-01 PACE chlorophyll
def run_pace(region: str) -> None:
    files = sorted(glob.glob(str(DATA / "raw" / "OCEAN-01" / region / "PACE_OCI.*.nc")))
    acc = Acc()
    for f in files:
        ym = re.search(r"PACE_OCI\.(\d{6})", f).group(1)
        ds = xr.open_dataset(f)
        lat2, lng2 = np.meshgrid(ds.lat.values, ds.lon.values, indexing="ij")
        acc.add(f"chl_{ym[:4]}_{ym[4:]}", lat2, lng2, ds.chlor_a.values, box=REGIONS[region])
    acc.cols.sort()
    tbl = acc.table()
    write("pace_chlor_a", tbl, "OCEAN-01", region,
          method=MEAN + " PACE OCI L3 mapped monthly chlorophyll-a (OCI algorithm), 4 km; one column per month.",
          units={"chl_*": "mg/m³"}, files=_rel(files), native_res="4 km (1/24°)",
          sampling="mean of pixel centres in cell", period="Jun-Aug 2025, monthly")


# --------------------------------------------------------------------------- AIR-01 Sentinel-5P NO2
def run_s5p(region: str) -> None:
    f = sorted(glob.glob(str(DATA / "raw" / "AIR-01" / region / "s5p_no2_*.parquet")))[0]
    t = pq.read_table(f, columns=["latitude", "longitude", "no2_trop_column_mol_m2", "qa_value"])
    qa = t["qa_value"].to_numpy()
    v = np.where(qa >= 0.75, t["no2_trop_column_mol_m2"].to_numpy().astype(np.float64) * 1e6, np.nan)
    acc = Acc()
    acc.add("no2", t["latitude"].to_numpy(), t["longitude"].to_numpy(), v, box=REGIONS[region])
    tbl = acc.table(counts={"n_obs": "no2"})
    period = re.search(r"_(\d{8})_(\d{8})_", f).groups()
    write("s5p_no2", tbl, "AIR-01", region,
          method=MEAN + " Sentinel-5P TROPOMI L2 tropospheric NO2 vertical column, ground pixels with qa_value ≥ "
                        "0.75 averaged by pixel centre over the period; a column amount, not a ground-level "
                        "concentration.",
          units={"no2": "µmol/m²", "n_obs": "count of ground pixels"}, files=[Path(f).name],
          native_res="5.5 × 3.5 km", sampling="mean of pixel centres in cell", period=f"{period[0]}-{period[1]}")


# --------------------------------------------------------------------------- WATER-03 SWOT
def run_swot(region: str) -> None:
    files = sorted(glob.glob(str(DATA / "raw" / "WATER-03" / region / "SWOT_L2_HR_Raster_*.nc")))
    acc = Acc()
    for f in files:
        ds = xr.open_dataset(f, decode_times=False)
        lat, lng = ds.latitude.values, ds.longitude.values
        frac = ds.water_frac.values.astype(np.float64)
        aq = ds.water_area_qual.values
        frac = np.where(np.isfinite(frac) & (aq <= 1), np.clip(frac, 0, 1), np.nan)
        acc.add("water_frac", lat, lng, frac, box=REGIONS[region])
        wse = ds.wse.values.astype(np.float64)
        ok = np.isfinite(wse) & (ds.wse_qual.values <= 1) & (np.nan_to_num(frac) > 0.5)
        acc.add("wse", lat, lng, np.where(ok, wse, np.nan), box=REGIONS[region])
        ds.close()
        print(f"  swot {region}: {Path(f).name[:60]}…", flush=True)
    tbl = acc.table(counts={"n_pixels": "water_frac"})
    write("swot_water", tbl, "WATER-03", region,
          method=MEAN + " SWOT L2 HR Raster 100 m: water_frac is the mean water fraction of observed pixels with "
                        "water_area_qual ≤ 1 (suspect or better) over all passes; wse is the mean water-surface "
                        "elevation of pixels with wse_qual ≤ 1 and water_frac > 0.5. Single-pass snapshots.",
          units={"water_frac": "fraction of observed area", "wse": "m above EGM2008 geoid",
                 "n_pixels": "count of observed 100 m pixels"},
          files=_rel(files), native_res="100 m", sampling="mean of pixel centres in cell", period="Jul-Aug 2025 passes")


# --------------------------------------------------------------------------- driver
RUNNERS = {  # name: (runner, source dir, regions)
    "era5land": (run_era5land, "CTX-01", ("arizona", "uk")),
    "cams": (run_cams, "AIR-02", ("arizona", "uk")),
    "grace_da": (run_grace_da, "WATER-02", ("arizona", "uk")),
    "grace_mascon": (run_grace_mascon, "WATER-02", ("global",)),
    "emit_l3": (run_emit_l3, "GEO-01", ("global",)),
    "smap": (run_smap, "WATER-01", ("arizona", "uk")),
    "gedi": (run_gedi, "LAND-04", ("arizona", "uk")),
    "modis_ndvi": (run_modis_ndvi, "OBS-06", ("arizona", "uk")),
    "ecostress": (run_ecostress, "OBS-05", ("arizona", "uk")),
    "pace": (run_pace, "OCEAN-01", ("uk",)),
    "s5p": (run_s5p, "AIR-01", ("arizona", "uk")),
    "swot": (run_swot, "WATER-03", ("arizona", "uk")),
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", default="all", choices=[*RUNNERS, "all"])
    ap.add_argument("--region", default="all", choices=[*REGIONS, "global", "all"])
    ap.add_argument("--data", default="data", help="data directory (contains raw/ and prepared/)")
    a = ap.parse_args()
    DATA = Path(a.data)
    for name in RUNNERS if a.dataset == "all" else [a.dataset]:
        fn, src, regions = RUNNERS[name]
        for region in regions:
            if a.region != "all" and region != a.region:
                continue
            if not (DATA / "raw" / src / region).exists():
                print(f"{name} / {region}: no raw data, skipped")
                continue
            print(f"{name} / {region}", flush=True)
            t0 = time.time()
            fn(region)
            print(f"  {time.time() - t0:.0f}s", flush=True)
