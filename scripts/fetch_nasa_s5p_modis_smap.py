"""Fetch regional subsets of three NASA Earthdata products (data/README.md 'Data scope').

  AIR-01  Sentinel-5P TROPOMI NO2 L2 (S5P_L2__NO2____HiR v2, GES DISC), 2025-07-01..07
          Orbits are streamed over HTTPS with byte-range reads (earthaccess.open + h5netcdf);
          only lat/lon and the scanline rows that fall in the box are read, so the ~590 MB
          global orbit file never lands on disk. Pixels inside the box with qa_value > 0.75
          are written to one Parquet file of points per region.
  OBS-06  MODIS Terra NDVI monthly 1 km (MOD13A3 v061, LP DAAC), calendar 2024.
          Only the sinusoidal tiles that intersect the box (computed exactly, not just CMR's
          footprint match) are downloaded as-is (HDF4, ~8-20 MB each).
  WATER-01 SMAP enhanced L3 soil moisture 9 km (SPL3SMP_E v006, NSIDC), 2025-07-01..07.
          Server-side bbox + variable subset with NASA Harmony (HOSS); per-day outputs are kept
          and stacked into one compact NetCDF per region.

Credentials come from ~/.netrc (earthaccess strategy="netrc"; harmony-py reads .netrc). Nothing
credential-like is printed or stored; stored URLs have query strings stripped.

Run (from the repo root):
  uv run --no-project --with earthaccess --with xarray --with netcdf4 --with h5netcdf --with h5py \
      --with rasterio --with pyarrow --with harmony-py python -I scripts/fetch_nasa_s5p_modis_smap.py \
      {s5p|modis|smap|all} [--region arizona|uk]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
TODAY = dt.date.today().isoformat()

REGIONS = {
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
DATA_SCOPE = "regional subset (data/README.md 'Data scope')"
NASA_LICENCE = {
    "name": "NASA open data",
    "url": "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
    "notes": "NASA Earth Science Data and Information Policy: no restrictions on reuse; cite the dataset DOI.",
    "reviewedAt": TODAY,
}


# ---------------------------------------------------------------- helpers
def strip_q(url):
    return url.split("?", 1)[0]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def file_list(d):
    out = []
    for p in sorted(Path(d).rglob("*")):
        if p.is_file() and p.name != "source.json":
            out.append({"path": str(p.relative_to(d)), "bytes": p.stat().st_size, "sha256": sha256(p)})
    return out


def collection_meta(short_name, version):
    import earthaccess

    c = earthaccess.search_datasets(short_name=short_name, version=version)[0]
    u = c["umm"]
    doi = (u.get("DOI") or {}).get("DOI", "")
    cit = ""
    cc = (u.get("CollectionCitations") or [{}])[0]
    if cc:
        parts = [cc.get("Creator"), f"({cc.get('ReleaseDate', '')[:4]})" if cc.get("ReleaseDate") else None,
                 cc.get("Title"), f"Version {cc.get('Version')}" if cc.get("Version") else None,
                 cc.get("Publisher"), f"https://doi.org/{doi}" if doi else None]
        cit = ". ".join(p.strip().rstrip(".") for p in parts if p) + "."
    return {"conceptId": c["meta"]["concept-id"], "doi": doi, "citation": cit, "title": u.get("EntryTitle", "")}


def write_source(d, rec):
    rec["files"] = file_list(d)
    with open(Path(d) / "source.json", "w") as fh:
        json.dump(rec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"  wrote {Path(d) / 'source.json'} ({len(rec['files'])} files)")


def bbox_str(b):
    return "W,S,E,N=" + ",".join(str(x) for x in b)


# ---------------------------------------------------------------- AIR-01 S5P NO2
S5P_SN, S5P_VER = "S5P_L2__NO2____HiR", "2"
S5P_TIME = ("2025-07-01T00:00:00", "2025-07-07T23:59:59")
S5P_VARS = ["nitrogendioxide_tropospheric_column", "nitrogendioxide_tropospheric_column_precision", "qa_value"]
QA_MIN = 0.75


def _s5p_one(g, box):
    import earthaccess
    import xarray as xr

    name = g["umm"]["GranuleUR"].split(":")[-1]
    orbit = int(name.split("_")[-4])
    W, S, E, N = box
    f = earthaccess.open([g], show_progress=False)[0]
    try:
        ds = xr.open_dataset(f, engine="h5netcdf", group="PRODUCT", decode_times=False, decode_timedelta=False)
        lat = ds["latitude"].isel(time=0).values
        lon = ds["longitude"].isel(time=0).values
        inbox = (lat >= S) & (lat <= N) & (lon >= W) & (lon <= E)
        n_box = int(inbox.sum())
        attrs = {v: {k: (str(a) if not isinstance(a, (int, float, str)) else a) for k, a in ds[v].attrs.items()}
                 for v in S5P_VARS + ["latitude", "longitude", "delta_time", "time"]}
        if n_box == 0:
            return name, orbit, None, n_box, attrs
        rows = np.where(inbox.any(axis=1))[0]
        r0, r1 = int(rows.min()), int(rows.max()) + 1
        sub = ds.isel(time=0, scanline=slice(r0, r1))
        m = inbox[r0:r1]
        qa = sub["qa_value"].values
        keep = m & (qa > QA_MIN)
        sl, gp = np.nonzero(keep)
        # delta_time: ms since the reference time (PRODUCT/time = seconds since 2010-01-01), per scanline
        du = str(ds["delta_time"].attrs.get("units", ""))
        tu = str(ds["time"].attrs.get("units", ""))
        assert du.startswith("milliseconds since") and tu.startswith("seconds since 2010-01-01"), (du, tu)
        ref = np.datetime64("2010-01-01T00:00:00", "ms") + np.timedelta64(int(ds["time"].values[0]), "s")
        dtm = np.asarray(sub["delta_time"].values).reshape(-1)  # (scanline,) ms
        t = ref + dtm[sl].astype("int64").astype("timedelta64[ms]")
        rec = {
            "orbit": np.full(sl.size, orbit, dtype="int32"),
            "granule": np.full(sl.size, name, dtype=object),
            "time_utc": t,
            "scanline": (sl + r0).astype("int32"),
            "ground_pixel": gp.astype("int16"),
            "latitude": lat[r0:r1][keep].astype("float32"),
            "longitude": lon[r0:r1][keep].astype("float32"),
            "no2_trop_column_mol_m2": sub["nitrogendioxide_tropospheric_column"].values[keep].astype("float32"),
            "no2_trop_column_precision_mol_m2": sub["nitrogendioxide_tropospheric_column_precision"].values[keep].astype("float32"),
            "qa_value": qa[keep].astype("float32"),
        }
        ds.close()
        return name, orbit, rec, n_box, attrs
    finally:
        f.close()


def run_s5p(region):
    import earthaccess
    import pyarrow as pa
    import pyarrow.parquet as pq

    box = REGIONS[region]
    out = RAW / "AIR-01" / region
    out.mkdir(parents=True, exist_ok=True)
    meta = collection_meta(S5P_SN, S5P_VER)
    grans = earthaccess.search_data(short_name=S5P_SN, version=S5P_VER, bounding_box=box, temporal=S5P_TIME)
    print(f"[AIR-01 {region}] {len(grans)} orbits intersect the box (CMR footprint)")
    results, attrs = [], None
    with cf.ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(_s5p_one, g, box): g for g in grans}
        for fu in cf.as_completed(futs):
            g = futs[fu]
            try:
                name, orbit, rec, n_box, a = fu.result()
            except Exception as e:  # keep going; record the failure
                name = g["umm"]["GranuleUR"].split(":")[-1]
                print(f"  FAIL {name}: {type(e).__name__}: {str(e)[:200]}")
                results.append({"granule": name, "error": f"{type(e).__name__}: {str(e)[:200]}",
                                "url": strip_q(g.data_links()[0]), "bytesUpstream": round(g.size * 1e6) if not callable(g.size) else None})
                continue
            attrs = attrs or a
            n_keep = 0 if rec is None else len(rec["orbit"])
            print(f"  {name}: {n_box} px in box, {n_keep} with qa>{QA_MIN}")
            results.append({"granule": name, "orbit": orbit, "pixelsInBox": n_box, "pixelsKept": n_keep,
                            "url": strip_q(g.data_links()[0]), "rec": rec})
    recs = [r.pop("rec") for r in results if r.get("rec") is not None]
    for r in results:
        r.pop("rec", None)
    results.sort(key=lambda r: r["granule"])
    cols = {k: np.concatenate([r[k] for r in recs]) for k in recs[0]} if recs else {}
    order = np.lexsort((cols["ground_pixel"], cols["scanline"], cols["orbit"])) if cols else []
    tbl = pa.table({k: (pa.array(v[order], type=pa.timestamp("ms", tz="UTC")) if k == "time_utc" else pa.array(v[order]))
                    for k, v in cols.items()})
    md = {
        "product": f"{S5P_SN} v{S5P_VER}",
        "quantity": "tropospheric vertical column of NO2 (mol/m2); NOT a ground-level concentration",
        "filter": f"pixel centre inside bbox {bbox_str(box)} and qa_value > {QA_MIN}",
        "variable_attributes": json.dumps(attrs, default=str),
    }
    tbl = tbl.replace_schema_metadata({**(tbl.schema.metadata or {}), **{k: v.encode() for k, v in md.items()}})
    fn = out / f"s5p_no2_trop_{region}_20250701_20250707_qa075.parquet"
    pq.write_table(tbl, fn, compression="zstd")
    print(f"  {fn.name}: {tbl.num_rows} rows, {fn.stat().st_size} bytes")
    unit_attrs = attrs.get("nitrogendioxide_tropospheric_column", {}) if attrs else {}
    rec = {
        "id": f"AIR-01-{region}-{TODAY.replace('-', '')}",
        "catalogueSourceId": "AIR-01",
        "provider": "ESA / Copernicus Sentinel-5P (KNMI processor), distributed by NASA GES DISC",
        "product": f"{meta['title']} ({S5P_SN})",
        "collectionShortName": S5P_SN,
        "version": S5P_VER + " (processor 02.08.00 per granule names: _020800_)",
        "collectionConceptId": meta["conceptId"],
        "doi": meta["doi"],
        "documentationUrl": "https://disc.gsfc.nasa.gov/datasets/S5P_L2__NO2____HiR_2/summary",
        "accessUrl": "https://data.gesdisc.earthdata.nasa.gov/data/S5P_TROPOMI_Level2/S5P_L2__NO2____HiR.2/",
        "accessMethod": "earthaccess CMR search + HTTPS byte-range streaming (earthaccess.open, h5netcdf); global orbit files never written to disk",
        "evidenceType": "satellite_retrieval",
        "semantics": ("nitrogendioxide_tropospheric_column is a tropospheric vertical column density in mol/m2 "
                      "(multiply by 6.02214e19 for molecules/cm2), NOT a ground-level / breathing-height concentration "
                      "and not a facility emission. Pixels ~5.5 x 3.5 km at nadir; overpass ~13:30 local solar time. "
                      "Each row = one L2 pixel (orbit, scanline, ground_pixel) with its scanline time."),
        "units": {"no2_trop_column_mol_m2": unit_attrs.get("units", "mol m-2"), "no2_trop_column_precision_mol_m2": "mol m-2",
                  "qa_value": "1 (0-1)", "latitude": "degrees_north (pixel centre)", "longitude": "degrees_east (pixel centre)",
                  "time_utc": "UTC scanline time (reference time + delta_time)"},
        "upstreamVariableAttributes": attrs,
        "licence": {
            "name": "Copernicus Sentinel data legal notice",
            "url": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
            "attribution": "Contains modified Copernicus Sentinel data 2025",
            "notes": "Free, full and open access; the credit line above is required on any display or redistribution. "
                     "GES DISC Harmony access asked for a separate EULA that was not accepted; direct HTTPS access was used.",
            "reviewedAt": TODAY,
        },
        "citation": meta["citation"] or "Copernicus Sentinel-5P (processed by ESA), 2021, TROPOMI Level 2 Nitrogen Dioxide total column products. Version 02. European Space Agency. https://doi.org/10.5270/S5P-9bnp8q8",
        "region": region,
        "dataScope": DATA_SCOPE,
        "query": f"short_name={S5P_SN} version={S5P_VER}; bbox {bbox_str(box)}; temporal {S5P_TIME[0]}..{S5P_TIME[1]} (UTC)",
        "processing": (f"For each orbit returned by CMR for the bbox/time: read PRODUCT/latitude+longitude, keep pixels whose centre "
                       f"lies inside the bbox, read only the scanline rows spanning them, keep pixels with qa_value > {QA_MIN} "
                       "(scale_factor applied by xarray), write one row per kept pixel to Parquet (zstd). "
                       "No regridding, averaging or unit conversion. Script: scripts/fetch_nasa_s5p_modis_smap.py s5p."),
        "granules": results,
        "rows": tbl.num_rows,
        "retrievedAt": TODAY,
    }
    write_source(out, rec)
    return tbl


# ---------------------------------------------------------------- OBS-06 MOD13A3
MOD_SN, MOD_VER = "MOD13A3", "061"
MOD_TIME = ("2024-01-01", "2024-12-31")
R_SIN = 6371007.181
T_SIN = 1111950.5197665


def modis_tiles(box, step=0.01):
    W, S, E, N = box
    lon, lat = np.meshgrid(np.arange(W, E + step / 2, step), np.arange(S, N + step / 2, step))
    x = R_SIN * np.radians(lon) * np.cos(np.radians(lat))
    y = R_SIN * np.radians(lat)
    h = np.floor((x + 18 * T_SIN) / T_SIN).astype(int)
    v = np.floor((9 * T_SIN - y) / T_SIN).astype(int)
    tiles = {}
    for hh, vv in zip(h.ravel(), v.ravel()):
        k = f"h{hh:02d}v{vv:02d}"
        tiles[k] = tiles.get(k, 0) + 1
    tot = h.size
    return {k: round(c / tot, 4) for k, c in sorted(tiles.items())}


def run_modis(region):
    import earthaccess

    box = REGIONS[region]
    out = RAW / "OBS-06" / region
    out.mkdir(parents=True, exist_ok=True)
    tiles = modis_tiles(box)
    print(f"[OBS-06 {region}] tiles intersecting box (fraction of box): {tiles}")
    meta = collection_meta(MOD_SN, MOD_VER)
    grans = earthaccess.search_data(short_name=MOD_SN, version=MOD_VER, bounding_box=box, temporal=MOD_TIME)
    keep = [g for g in grans if g["umm"]["GranuleUR"].split(".")[2] in tiles]
    print(f"  CMR returned {len(grans)}; keeping {len(keep)} on exact tile set")
    files = earthaccess.download(keep, local_path=str(out), threads=4, show_progress=False)
    got = sorted(Path(f).name for f in files)
    gl = []
    for g in sorted(keep, key=lambda g: g["umm"]["GranuleUR"]):
        links = [strip_q(l) for l in g.data_links() if l.endswith(".hdf")]
        gl.append({"granule": g["umm"]["GranuleUR"], "tile": g["umm"]["GranuleUR"].split(".")[2],
                   "date": g["umm"]["GranuleUR"].split(".")[1], "url": links[0] if links else ""})
    rec = {
        "id": f"OBS-06-mod13a3-{region}-{TODAY.replace('-', '')}",
        "catalogueSourceId": "OBS-06",
        "provider": "NASA LP DAAC (USGS EROS)",
        "product": f"{meta['title']} ({MOD_SN})",
        "collectionShortName": MOD_SN,
        "version": MOD_VER,
        "collectionConceptId": meta["conceptId"],
        "doi": meta["doi"],
        "documentationUrl": "https://lpdaac.usgs.gov/products/mod13a3v061/",
        "accessUrl": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MOD13A3.061/",
        "accessMethod": "earthaccess CMR search + whole-tile HTTPS download (tiles are already regional; no clip)",
        "evidenceType": "satellite_retrieval",
        "semantics": ("Monthly 1 km NDVI/EVI composites on the MODIS sinusoidal grid (HDF4-EOS). SDS '1 km monthly NDVI' is int16 "
                      "with scale factor 0.0001 (NDVI = DN * 0.0001; the in-file attribute scale_factor=10000 follows the MODIS convention physical = DN / scale_factor, so do not multiply by it), valid range -2000..10000, fill -3000. Use the "
                      "'1 km monthly VI Quality' bit field (bits 0-1 MODLAND QA: 00 good, 01 check other QA, 10/11 cloudy/not produced) "
                      "and 'pixel reliability' to screen pixels. Granule date AYYYYDDD is the first day of the month."),
        "tilesIntersectingBox": tiles,
        "tileNotes": "Fraction = share of a 0.01 deg lon/lat sample grid over the box falling in each tile; small fractions are edge slivers kept for completeness.",
        "licence": {**NASA_LICENCE, "attribution": meta["citation"]},
        "citation": meta["citation"],
        "region": region,
        "dataScope": DATA_SCOPE,
        "query": f"short_name={MOD_SN} version={MOD_VER}; bbox {bbox_str(box)}; temporal {MOD_TIME[0]}..{MOD_TIME[1]}",
        "processing": "None. Tiles kept exactly as downloaded (no clip/reprojection). Script: scripts/fetch_nasa_s5p_modis_smap.py modis.",
        "granules": gl,
        "retrievedAt": TODAY,
    }
    write_source(out, rec)
    return out, got


# ---------------------------------------------------------------- WATER-01 SPL3SMP_E
SM_SN, SM_VER = "SPL3SMP_E", "006"
SM_TIME = (dt.datetime(2025, 7, 1), dt.datetime(2025, 7, 7, 23, 59, 59))
SM_VARS = {
    "AM": ["soil_moisture", "retrieval_qual_flag", "latitude", "longitude"],
    "PM": ["soil_moisture_pm", "retrieval_qual_flag_pm", "latitude_pm", "longitude_pm"],
}


def run_smap(region):
    import earthaccess
    from harmony import BBox, Client, Collection, Request

    box = REGIONS[region]
    out = RAW / "WATER-01" / region
    sub = out / "harmony_subsets"
    if sub.exists():
        shutil.rmtree(sub)
    sub.mkdir(parents=True)
    meta = collection_meta(SM_SN, SM_VER)
    grans = earthaccess.search_data(short_name=SM_SN, version=SM_VER, bounding_box=box,
                                    temporal=(SM_TIME[0].isoformat(), SM_TIME[1].isoformat()))
    variables = [f"Soil_Moisture_Retrieval_Data_{p}/{v}" for p, vs in SM_VARS.items() for v in vs]
    h = Client()
    req = Request(collection=Collection(id=meta["conceptId"]), spatial=BBox(*box),
                  temporal={"start": SM_TIME[0], "stop": SM_TIME[1]}, variables=variables)
    assert req.is_valid()
    req_url = strip_q(h.request_as_url(req)) if hasattr(h, "request_as_url") else ""
    job = h.submit(req)
    print(f"[WATER-01 {region}] Harmony job {job}; {len(grans)} source granules")
    h.wait_for_processing(job, show_progress=False)
    res = h.result_json(job)
    print(f"  status={res['status']} msg={res.get('message')}")
    paths = [Path(f.result()) for f in h.download_all(job, directory=str(sub), overwrite=True)]
    # drop harmony's numeric download prefix for stable names
    clean = []
    for p in paths:
        nm = p.name.split("_", 1)[1] if p.name.split("_", 1)[0].isdigit() else p.name
        q = p.with_name(nm)
        p.rename(q)
        clean.append(q)
    clean.sort()
    combined = out / f"smap_spl3smpe_{region}_20250701_20250707.nc"
    stats = stack_smap(clean, combined, box)
    rec = {
        "id": f"WATER-01-spl3smpe-{region}-{TODAY.replace('-', '')}",
        "catalogueSourceId": "WATER-01",
        "provider": "NASA NSIDC DAAC (SMAP mission, JPL/GSFC)",
        "product": f"{meta['title']} ({SM_SN})",
        "collectionShortName": SM_SN,
        "version": SM_VER,
        "collectionConceptId": meta["conceptId"],
        "doi": meta["doi"],
        "documentationUrl": "https://nsidc.org/data/spl3smp_e/versions/6",
        "accessUrl": "https://harmony.earthdata.nasa.gov/ (service sds/HOSS-regridder-reformatter)",
        "harmonyJobId": str(job),
        "harmonyRequestUrl": req_url,
        "accessMethod": "NASA Harmony server-side bbox + variable subset (HOSS); global daily HDF5 (~650 MB) never downloaded",
        "evidenceType": "satellite_retrieval",
        "semantics": ("Surface (~0-5 cm) volumetric soil moisture (m3/m3; upstream unit string cm**3/cm**3) from the SMAP L-band radiometer, "
                      "DCA retrieval on the 9 km EASE-Grid 2.0 global grid (EPSG:6933). AM = 6:00 descending, PM = 18:00 ascending "
                      "local solar time passes; cells without a pass that day are NaN (missing, not zero). retrieval_qual_flag bit 0 = "
                      "recommended quality NOT met (0 = recommended). Soil moisture is not river discharge, groundwater or available water."),
        "licence": {**NASA_LICENCE, "attribution": meta["citation"]},
        "citation": meta["citation"],
        "region": region,
        "dataScope": DATA_SCOPE,
        "query": f"collection {meta['conceptId']}; bbox {bbox_str(box)}; temporal {SM_TIME[0].isoformat()}..{SM_TIME[1].isoformat()}; variables {variables}",
        "processing": ("Harmony HOSS returned the EASE-2 grid window covering the bbox (cells overlapping the edges are included) "
                       "with the listed variables; per-day outputs are kept in harmony_subsets/. The combined NetCDF stacks the 7 days "
                       "on a 'date' dimension, converts fills (-9999 / 65534) to NaN / kept fill, and adds lat/lon of every cell centre "
                       "computed from EASE-2 x/y (EPSG:6933 -> EPSG:4326). No resampling. Script: scripts/fetch_nasa_s5p_modis_smap.py smap."),
        "granules": [{"granule": g["umm"]["GranuleUR"], "url": strip_q([l for l in g.data_links() if l.endswith('.h5')][0])} for g in
                     sorted(grans, key=lambda g: g["umm"]["GranuleUR"])],
        "stats": stats,
        "retrievedAt": TODAY,
    }
    write_source(out, rec)


def stack_smap(paths, dst, box):
    import netCDF4
    from rasterio.warp import transform

    days, am, pm, qam, qpm = [], [], [], [], []
    x = y = None
    for p in paths:
        d = netCDF4.Dataset(p)
        d.set_auto_mask(False)
        x = d["x_global"][:]
        y = d["y_global"][:]
        ga, gp = d["Soil_Moisture_Retrieval_Data_AM"], d["Soil_Moisture_Retrieval_Data_PM"]
        a = ga["soil_moisture"][:].astype("float32"); a[a == -9999.0] = np.nan
        b = gp["soil_moisture_pm"][:].astype("float32"); b[b == -9999.0] = np.nan
        am.append(a); pm.append(b)
        qam.append(ga["retrieval_qual_flag"][:]); qpm.append(gp["retrieval_qual_flag_pm"][:])
        sm_attrs = {k: ga["soil_moisture"].getncattr(k) for k in ga["soil_moisture"].ncattrs() if k != "_FillValue"}
        q_attrs = {k: ga["retrieval_qual_flag"].getncattr(k) for k in ga["retrieval_qual_flag"].ncattrs() if k != "_FillValue"}
        days.append(p.name.split("_")[5])  # SMAP_L3_SM_P_E_YYYYMMDD_...
        d.close()
    xx, yy = np.meshgrid(x, y)
    lon, lat = transform("EPSG:6933", "EPSG:4326", xx.ravel().tolist(), yy.ravel().tolist())
    lon = np.array(lon, dtype="float32").reshape(xx.shape)
    lat = np.array(lat, dtype="float32").reshape(xx.shape)
    o = netCDF4.Dataset(dst, "w", format="NETCDF4")
    o.title = "SMAP SPL3SMP_E v006 soil moisture, regional subset"
    o.source = "NASA NSIDC DAAC via Harmony HOSS; see source.json"
    o.bbox_WSEN = ",".join(map(str, box))
    o.crs = "EASE-Grid 2.0 global 9 km (EPSG:6933)"
    o.createDimension("date", len(days)); o.createDimension("y", len(y)); o.createDimension("x", len(x))
    v = o.createVariable("date", str, ("date",)); v[:] = np.array(days, dtype=object); v.long_name = "UTC date of granule (YYYYMMDD)"
    v = o.createVariable("x", "f8", ("x",)); v[:] = x; v.units = "m"; v.standard_name = "projection_x_coordinate"
    v = o.createVariable("y", "f8", ("y",)); v[:] = y; v.units = "m"; v.standard_name = "projection_y_coordinate"
    v = o.createVariable("latitude", "f4", ("y", "x"), zlib=True); v[:] = lat; v.units = "degrees_north"
    v = o.createVariable("longitude", "f4", ("y", "x"), zlib=True); v[:] = lon; v.units = "degrees_east"
    for nm, arr, at in [("soil_moisture_am", am, sm_attrs), ("soil_moisture_pm", pm, sm_attrs)]:
        v = o.createVariable(nm, "f4", ("date", "y", "x"), zlib=True, fill_value=np.float32(np.nan))
        v[:] = np.stack(arr)
        for k, val in at.items():
            v.setncattr(k, val)
        v.units = "m3/m3"; v.upstream_units = at.get("units", "cm**3/cm**3"); v.coordinates = "latitude longitude"
    for nm, arr in [("retrieval_qual_flag_am", qam), ("retrieval_qual_flag_pm", qpm)]:
        v = o.createVariable(nm, "u2", ("date", "y", "x"), zlib=True, fill_value=np.uint16(65534))
        v[:] = np.stack(arr)
        for k, val in q_attrs.items():
            v.setncattr(k, val)
        v.flag_note = "bit 0 set = retrieval did not meet recommended quality; 65534 = fill"
        v.coordinates = "latitude longitude"
    o.close()
    A, P = np.stack(am), np.stack(pm)
    QA, QP = np.stack(qam), np.stack(qpm)
    good = np.concatenate([A[(QA & 1) == 0], P[(QP & 1) == 0]])
    good = good[np.isfinite(good)]
    allv = np.concatenate([A[np.isfinite(A)], P[np.isfinite(P)]])
    stats = {
        "dates": days, "grid": [len(y), len(x)],
        "validCellsAM": int(np.isfinite(A).sum()), "validCellsPM": int(np.isfinite(P).sum()),
        "rangeAll_m3m3": [float(allv.min()), float(allv.max())] if allv.size else None,
        "medianAll_m3m3": float(np.median(allv)) if allv.size else None,
        "rangeRecommendedQuality_m3m3": [float(good.min()), float(good.max())] if good.size else None,
    }
    print(f"  {dst.name}: {stats}")
    return stats


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["s5p", "modis", "smap", "all"])
    ap.add_argument("--region", choices=list(REGIONS), action="append")
    a = ap.parse_args()
    import earthaccess

    earthaccess.login(strategy="netrc")
    regions = a.region or list(REGIONS)
    for r in regions:
        if a.what in ("smap", "all"):
            run_smap(r)
        if a.what in ("modis", "all"):
            run_modis(r)
        if a.what in ("s5p", "all"):
            run_s5p(r)


if __name__ == "__main__":
    main()
