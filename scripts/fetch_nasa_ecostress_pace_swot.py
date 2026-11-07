"""Fetch regional NASA Earthdata subsets: ECOSTRESS LST (OBS-05), PACE OCI chlorophyll
(OCEAN-01) and SWOT 100 m water rasters (WATER-03).

Follows data/README.md section 0.1 (Data scope): only the `arizona` and `uk` regions are
kept. Global PACE files are downloaded to data/raw/_global_tmp/OCEAN-01/ one at a time,
clipped to the UK box and deleted. Every region folder gets a source.json.

Authentication: Earthdata Login via ~/.netrc (earthaccess strategy "netrc"). Credentials and
tokens are never printed or written. Stored URLs are plain archive paths (no signed queries).

Run (from the repo root):
    uv run --no-project --with earthaccess --with xarray --with netcdf4 --with h5netcdf \
        --with rasterio python -I scripts/fetch_nasa_ecostress_pace_swot.py [eco] [pace] [swot]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

import earthaccess
import numpy as np

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
TMP = RAW / "_global_tmp"
RETRIEVED = dt.date.today().isoformat()
TRANSFER_CAP = 4_000_000_000
DATA_SCOPE = "regional subset (data/README.md 'Data scope')"
NASA_LICENCE_URL = "https://earthdata.nasa.gov/earth-observation-data/data-use-policy"

REGIONS = {  # W, S, E, N (WGS84)
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}

transferred = 0


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(p: Path, base: Path, **extra) -> dict:
    return {"path": str(p.relative_to(base)), "bytes": p.stat().st_size, "sha256": sha256(p), **extra}


def strip_query(url: str) -> str:
    return url.split("?", 1)[0]


def download(urls: list[str], dest: Path) -> list[Path]:
    """Download with earthaccess, skipping files already present; enforce the transfer cap."""
    global transferred
    dest.mkdir(parents=True, exist_ok=True)
    todo = [u for u in urls if not (dest / strip_query(u).rsplit("/", 1)[1]).exists()]
    if todo:
        earthaccess.download(todo, local_path=str(dest), show_progress=False)
    paths = []
    for u in urls:
        p = dest / strip_query(u).rsplit("/", 1)[1]
        if not p.exists():
            raise RuntimeError(f"download failed: {p.name}")
        paths.append(p)
    transferred += sum((dest / strip_query(u).rsplit("/", 1)[1]).stat().st_size for u in todo)
    print(f"  transferred so far: {transferred / 1e6:.1f} MB", flush=True)
    if transferred > TRANSFER_CAP:
        raise RuntimeError("transfer cap exceeded")
    return paths


def write_json(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {p.relative_to(REPO)}")


def nasa_licence(citation: str) -> dict:
    return {
        "name": "NASA open data",
        "url": NASA_LICENCE_URL,
        "attribution": citation,
        "reviewedAt": RETRIEVED,
        "notes": "NASA Earth science data are openly shared without restriction on use; cite the "
        "collection DOI and acknowledge the DAAC.",
    }


# --------------------------------------------------------------------------------------------
# OBS-05 ECOSTRESS ECO_L2T_LSTE v002
# --------------------------------------------------------------------------------------------
ECO_LAYERS = ["LST", "LST_err", "QC", "cloud", "water"]
# Chosen 2026-11-07 from all ECO_L2T_LSTE v002 daytime granules (Jun-Aug 2025) intersecting the
# city point with local solar time 11:00-15:00 (solar = UTC + lon/15). Ranking used each
# candidate's own cloud mask and LST NaN (swath) coverage in a +/-15 km window around the city
# point, preferring near-complete clear coverage, one date per month where possible. Both MGRS
# tiles returned for the city point are kept (the point lies in the tile overlap strip).
ECO_SELECTION = {
    "arizona": {
        "point": (-112.07, 33.45),
        "cityBox": (-112.45, 33.25, -111.60, 33.75),  # Phoenix metro, for summary stats
        "granules": [
            "ECOv002_L2T_LSTE_39319_011_12SUC_20250612T214059_0713_01",
            "ECOv002_L2T_LSTE_39319_011_12SVC_20250612T214059_0713_01",
            "ECOv002_L2T_LSTE_40050_005_12SUC_20250729T193648_0713_01",
            "ECOv002_L2T_LSTE_40050_005_12SVC_20250729T193648_0713_01",
            "ECOv002_L2T_LSTE_40314_012_12SUC_20250815T202416_0713_01",
            "ECOv002_L2T_LSTE_40314_012_12SVC_20250815T202416_0713_01",
        ],
    },
    "uk": {
        "point": (-0.12, 51.5),
        "cityBox": (-0.51, 51.28, 0.34, 51.69),  # Greater London, for summary stats
        "granules": [
            "ECOv002_L2T_LSTE_39328_009_30UXC_20250613T112812_0713_01",
            "ECOv002_L2T_LSTE_39328_009_30UYC_20250613T112812_0713_01",
            "ECOv002_L2T_LSTE_40201_009_30UXC_20250808T132716_0713_01",
            "ECOv002_L2T_LSTE_40201_009_30UYC_20250808T132716_0713_01",
            "ECOv002_L2T_LSTE_40262_009_30UXC_20250812T114857_0713_01",
            "ECOv002_L2T_LSTE_40262_009_30UYC_20250812T114857_0713_01",
        ],
    },
}


def eco_stats(files: dict[str, Path], box) -> dict:
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(files["LST"]) as s:
        b = transform_bounds("EPSG:4326", s.crs, *box)
        win = from_bounds(*b, transform=s.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, s.width, s.height))
        lst = s.read(1, window=win).astype("float64")
    with rasterio.open(files["cloud"]) as s:
        cloud = s.read(1, window=win)
    with rasterio.open(files["water"]) as s:
        water = s.read(1, window=win)
    fin = np.isfinite(lst)
    clear_land = fin & (cloud == 0) & (water == 0)
    out = {
        "cityBoxWGS84": list(box),
        "windowPixels": int(lst.size),
        "fractionWithLST": round(float(fin.mean()), 3),
        "cloudFractionOfObserved": round(float((cloud[fin] == 1).mean()), 3) if fin.any() else None,
    }
    if clear_land.any():
        v = lst[clear_land] - 273.15
        out["clearLandLST_degC"] = {k: round(float(x), 1) for k, x in zip(
            ["min", "p1", "p50", "p99", "max"], [v.min(), *np.percentile(v, [1, 50, 99]), v.max()])}
    return out


def fetch_ecostress() -> None:
    print("OBS-05 ECOSTRESS ECO_L2T_LSTE v002")
    for region, sel in ECO_SELECTION.items():
        dest = RAW / "OBS-05" / region
        granules, files = [], []
        for gid in sel["granules"]:
            res = earthaccess.search_data(short_name="ECO_L2T_LSTE", version="002", granule_name=gid)
            if len(res) != 1:
                raise RuntimeError(f"granule lookup failed: {gid} ({len(res)} results)")
            g = res[0]
            urls = [u for u in g.data_links() for lay in ECO_LAYERS if u.endswith(f"_{lay}.tif")]
            assert len(urls) == len(ECO_LAYERS), gid
            paths = download(urls, dest)
            u = g["umm"]
            t0 = u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
            t = dt.datetime.fromisoformat(t0.replace("Z", "+00:00"))
            solar = (t.hour + t.minute / 60 + t.second / 3600 + sel["point"][0] / 15) % 24
            byl = {lay: p for lay, p in zip([next(l for l in ECO_LAYERS if x.endswith(f"_{l}.tif")) for x in urls], paths)}
            stats = eco_stats(byl, sel["cityBox"])
            parts = gid.split("_")
            granules.append({
                "granuleId": gid,
                "orbit": int(parts[3]),
                "scene": parts[4],
                "mgrsTile": parts[5],
                "overpassStartUTC": t0,
                "overpassEndUTC": u["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
                "approxLocalSolarTime": f"{int(solar):02d}:{int(round((solar % 1) * 60)) % 60:02d}",
                "dayNightFlag": u["DataGranule"]["DayNightFlag"],
                "pgeVersion": u.get("PGEVersionClass", {}).get("PGEVersion"),
                "bboxWGS84": u["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["BoundingRectangles"][0],
                "accessUrls": [strip_query(x) for x in urls],
                "cityBoxSummary": stats,
            })
            for lay, p in byl.items():
                files.append(file_record(p, dest, granuleId=gid, layer=lay))
            print(f"  {region} {gid} solar~{solar:.2f} {stats.get('clearLandLST_degC')}")
        record = {
            "id": f"OBS-05-{region}-{RETRIEVED.replace('-', '')}",
            "catalogueSourceId": "OBS-05",
            "provider": "NASA JPL / NASA Land Processes DAAC (LP DAAC)",
            "product": "ECOSTRESS Tiled Land Surface Temperature and Emissivity Instantaneous L2 Global 70 m",
            "collection": {"shortName": "ECO_L2T_LSTE", "version": "002", "conceptId": "C2076090826-LPCLOUD"},
            "version": "002 (collection 0713, PGE per granule)",
            "doi": "10.5067/ECOSTRESS/ECO_L2T_LSTE.002",
            "documentationUrl": "https://doi.org/10.5067/ECOSTRESS/ECO_L2T_LSTE.002",
            "accessUrl": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/",
            "accessMethod": "earthaccess (NASA Earthdata Cloud HTTPS, Earthdata Login)",
            "evidenceType": "satellite retrieval",
            "retrievedAt": RETRIEVED,
            "licence": nasa_licence(
                "Hook, S., Hulley, G. (2022). ECOSTRESS Tiled Land Surface Temperature and Emissivity "
                "Instantaneous L2 Global 70 m V002. NASA Land Processes Distributed Active Archive "
                "Center. https://doi.org/10.5067/ECOSTRESS/ECO_L2T_LSTE.002"),
            "region": region,
            "dataScope": DATA_SCOPE,
            "query": {
                "regionBboxWGS84": list(REGIONS[region]),
                "searchPoint_lonlat": list(sel["point"]),
                "temporal": "2025-06-01/2025-08-31",
                "criteria": "daytime granules intersecting the city point, local solar time 11:00-15:00, "
                "lowest cloud and most complete swath coverage in a +/-15 km window around the city "
                "(from the granule's own cloud mask and LST NaN pattern); 3 overpass dates; both MGRS "
                "tiles that contain the point kept for each date",
                "layers": ECO_LAYERS,
            },
            "processing": "None. Files are the provider's per-layer Cloud-Optimized GeoTIFFs as delivered "
            "(70 m MGRS/UTM tiles, 1568 x 1568 px). Other layers of the granule (EmisWB, height, "
            "view_zenith) were not downloaded.",
            "semantics": {
                "LST": "land surface (radiometric skin) temperature in kelvin; NOT near-surface air "
                "temperature. NaN = no retrieval (outside swath / failed).",
                "LST_err": "LST uncertainty, kelvin",
                "QC": "16-bit quality flags (bit definitions in the ECO_L2T_LSTE user guide)",
                "cloud": "cloud mask (1 = cloud, 0 = clear); applied separately, LST is not cloud-masked",
                "water": "water mask (1 = water)",
                "sampling": "ISS orbit is precessing and irregular: overpass time of day differs per date, "
                "revisits are intermittent, and these are single instantaneous snapshots, not daily "
                "maxima or means.",
            },
            "granules": granules,
            "files": files,
        }
        write_json(dest / "source.json", record)


# --------------------------------------------------------------------------------------------
# OCEAN-01 PACE OCI L3M BGC v3.2 (UK only)
# --------------------------------------------------------------------------------------------
def fetch_pace() -> None:
    import xarray as xr

    print("OCEAN-01 PACE_OCI_L3M_BGC v3.2 (uk)")
    region = "uk"
    w, s, e, n = REGIONS[region]
    dest = RAW / "OCEAN-01" / region
    dest.mkdir(parents=True, exist_ok=True)
    tmp = TMP / "OCEAN-01"
    res = earthaccess.search_data(short_name="PACE_OCI_L3M_BGC", version="3.2",
                                  temporal=("2025-06-01", "2025-08-31T23:59:59"))
    sel = sorted([g for g in res if ".L3m.MO." in g["umm"]["GranuleUR"] and ".4km." in g["umm"]["GranuleUR"]],
                 key=lambda g: g["umm"]["GranuleUR"])
    if len(sel) != 3:
        raise RuntimeError(f"expected 3 monthly 4km granules, got {[g['umm']['GranuleUR'] for g in sel]}")
    granules, files = [], []
    for g in sel:
        gid = g["umm"]["GranuleUR"]
        urls = [u for u in g.data_links() if u.endswith(".nc")]
        assert len(urls) == 1, urls
        (src,) = download(urls, tmp)
        src_bytes, src_sha = src.stat().st_size, sha256(src)
        out = dest / src.name.replace(".nc", "_uk.nc")
        with xr.open_dataset(src) as ds:
            lat_desc = bool(ds.lat[0] > ds.lat[-1])
            sub = ds[["chlor_a"]].sel(lat=slice(n, s) if lat_desc else slice(s, n), lon=slice(w, e)).load()
            gattrs = dict(ds.attrs)
        sub.attrs = gattrs
        sub.attrs["history"] = (gattrs.get("history", "") + f"\n{RETRIEVED}: subset to chlor_a and UK box "
                                f"W,S,E,N={w},{s},{e},{n} with xarray .sel (native 4 km grid, no resampling) by "
                                "scripts/fetch_nasa_ecostress_pace_swot.py").strip()
        sub.attrs["regional_subset_of"] = src.name
        for v in sub.variables:
            sub[v].encoding = {}
        enc = {"chlor_a": {"zlib": True, "complevel": 4, "dtype": "float32", "_FillValue": np.float32(-32767.0)}}
        sub.to_netcdf(out, engine="netcdf4", encoding=enc)
        a = sub["chlor_a"].values
        v = a[np.isfinite(a)]
        thames = sub["chlor_a"].sel(lat=slice(51.7, 51.3) if lat_desc else slice(51.3, 51.7), lon=slice(0.8, 1.9)).values
        tv = thames[np.isfinite(thames)]
        stats = {
            "grid": f"{sub.sizes['lat']} lat x {sub.sizes['lon']} lon",
            "validPixels": int(v.size),
            "nanFraction": round(float(1 - v.size / a.size), 3),
            "chlor_a_mg_m3": {k: round(float(x), 3) for k, x in zip(
                ["min", "p5", "p50", "p95", "max"], [v.min(), *np.percentile(v, [5, 50, 95]), v.max()])},
            "outerThamesEstuary_51.3-51.7N_0.8-1.9E_median_mg_m3": round(float(np.median(tv)), 3) if tv.size else None,
        }
        src.unlink()  # delete the global original
        u = g["umm"]["TemporalExtent"]["RangeDateTime"]
        granules.append({"granuleId": gid, "start": u["BeginningDateTime"], "end": u["EndingDateTime"],
                         "accessUrl": strip_query(urls[0]),
                         "globalFile": {"name": src.name, "bytes": src_bytes, "sha256": src_sha,
                                        "status": "deleted after clipping"},
                         "summary": stats})
        files.append(file_record(out, dest, granuleId=gid))
        print(f"  {out.name} {stats}")
    shutil.rmtree(tmp, ignore_errors=True)
    record = {
        "id": f"OCEAN-01-uk-{RETRIEVED.replace('-', '')}",
        "catalogueSourceId": "OCEAN-01",
        "provider": "NASA Ocean Biology Processing Group / Ocean Biology DAAC (OB.DAAC)",
        "product": "PACE OCI Level-3 Global Mapped Ocean Biogeochemical Properties (chlor_a), monthly, 4 km",
        "collection": {"shortName": "PACE_OCI_L3M_BGC", "version": "3.2", "conceptId": "C4184125847-OB_CLOUD"},
        "version": "3.2 (V3_2 in file names)",
        "doi": "10.5067/PACE/OCI/L3M/OC_BGC/3.2",
        "documentationUrl": "https://doi.org/10.5067/PACE/OCI/L3M/OC_BGC/3.2",
        "accessUrl": "https://obdaac-tea.earthdatacloud.nasa.gov/ob-cumulus-prod-public/",
        "accessMethod": "earthaccess (NASA Earthdata Cloud HTTPS, Earthdata Login)",
        "evidenceType": "satellite retrieval",
        "retrievedAt": RETRIEVED,
        "licence": nasa_licence(
            "NASA Ocean Biology Processing Group (2025). PACE OCI Level-3 Global Mapped Ocean "
            "Biogeochemical Properties Data, version 3.2. NASA Ocean Biology Distributed Active Archive "
            "Center. https://doi.org/10.5067/PACE/OCI/L3M/OC_BGC/3.2"),
        "region": region,
        "dataScope": DATA_SCOPE,
        "query": {"regionBboxWGS84": list(REGIONS[region]), "temporal": "2025-06/2025-08 monthly composites",
                  "fileFilter": "L3m.MO, 4km (0p1deg, 8-day and daily skipped)", "variable": "chlor_a"},
        "processing": "Each global ~130-145 MB file was downloaded to data/raw/_global_tmp/OCEAN-01/, subset "
        "to chlor_a and the UK box with xarray .sel on the native 4 km equirectangular grid (lat descending), "
        "written to NetCDF4 (zlib) with the original variable/global attributes, and the global file deleted. "
        "No resampling or gap filling. Land, cloud and no-retrieval pixels stay NaN (_FillValue -32767), never 0. "
        "Arizona is not processed (inland).",
        "semantics": {
            "chlor_a": "near-surface chlorophyll-a concentration, mg m^-3, OCI standard algorithm (OCx/CI "
            "blend); monthly composite of daily retrievals. Optically complex coastal/estuarine waters "
            "(e.g. Thames, Severn) can be biased high by sediment/CDOM. Not fish stock or harvestable biomass.",
        },
        "granules": granules,
        "files": files,
    }
    write_json(dest / "source.json", record)


# --------------------------------------------------------------------------------------------
# WATER-03 SWOT L2 HR Raster 100 m, version D
# --------------------------------------------------------------------------------------------
# targets: name -> (lon, lat) search point; boxes: W, S, E, N around the water body, used to
# drop granules whose swath only clips the footprint without observing the water body.
SWOT_SELECTION = {
    "arizona": {
        "zones": {"UTM12S"},
        "targets": {"Lake Pleasant": (-112.27, 33.85), "Theodore Roosevelt Lake": (-111.16, 33.67)},
        "boxes": {"Lake Pleasant": (-112.33, 33.80, -112.22, 33.92),
                  "Theodore Roosevelt Lake": (-111.30, 33.62, -110.95, 33.75)},
    },
    "uk": {
        "zones": {"UTM30U", "UTM30V", "UTM31U"},
        "targets": {"Thames estuary": (0.5, 51.5), "Loch Ness": (-4.45, 57.3)},
        "boxes": {"Thames estuary": (0.30, 51.40, 1.00, 51.60), "Loch Ness": (-4.72, 57.14, -4.25, 57.45)},
    },
}
SWOT_MIN_GOOD_PIXELS = 50
SWOT_CYCLE = "036"  # 2025-07-20 .. 2025-08-09 for these passes (one 21-day repeat cycle)
SWOT_MAX = 15


def swot_target_stats(path: Path, targets: dict, boxes: dict) -> dict:
    import xarray as xr

    out = {}
    with xr.open_dataset(path) as ds:
        lat, lon = ds["latitude"].values, ds["longitude"].values
        wse, q, wf = ds["wse"].values, ds["wse_qual"].values, ds["water_frac"].values
        okw = np.isfinite(wse) & (q <= 1) & (wf > 0.5)
        for name, (w, s, e, n) in boxes.items():
            inbox = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
            k = int((inbox & okw).sum())
            if k:
                out.setdefault(name, {})["goodWaterPixelsInBox"] = k
        for name, (tlon, tlat) in targets.items():
            d = np.hypot((lon - tlon) * np.cos(np.radians(tlat)), lat - tlat) * 111.2
            near = d < 2.0
            if not near.any():
                continue
            good = near & np.isfinite(wse) & (q <= 1) & (wf > 0.5)
            out.setdefault(name, {}).update({
                "pixelsWithin2km": int(near.sum()), "goodWaterPixelsWithin2km": int(good.sum()),
                "medianWseWithin2km_m": round(float(np.median(wse[good])), 2) if good.any() else None})
    return out


def fetch_swot() -> None:
    print(f"WATER-03 SWOT_L2_HR_Raster_100m_D cycle {SWOT_CYCLE}")
    for region, sel in SWOT_SELECTION.items():
        dest = RAW / "WATER-03" / region
        cand = {}
        for tname, pt in sel["targets"].items():
            for g in earthaccess.search_data(short_name="SWOT_L2_HR_Raster_100m_D", point=pt,
                                             temporal=("2025-07-10", "2025-08-20T23:59:59")):
                gid = g["umm"]["GranuleUR"]
                p = gid.split("_")
                # p[5]=UTM zone+band, p[10]=cycle, p[11]=pass, p[12]=scene, p[16]=product counter.
                # Zone filter drops date-line granules whose CMR footprints falsely match every point.
                if p[10] != SWOT_CYCLE or p[5] not in sel["zones"]:
                    continue
                key = (p[11], p[12], p[5])
                prev = cand.get(key)
                if prev is None or gid > prev[0]["umm"]["GranuleUR"]:
                    cand[key] = (g, set())
                cand[key][1].add(tname)
        chosen = sorted(cand.values(), key=lambda x: x[0]["umm"]["GranuleUR"])
        if len(chosen) > SWOT_MAX:
            raise RuntimeError(f"{region}: {len(chosen)} granules exceed cap {SWOT_MAX}")
        granules, files, excluded = [], [], []
        for g, hits in chosen:
            gid = g["umm"]["GranuleUR"]
            urls = [u for u in g.data_links() if u.endswith(".nc")]
            assert len(urls) == 1, urls
            (path,) = download(urls, dest)
            stats = swot_target_stats(path, sel["targets"], sel["boxes"])
            if not any(v.get("goodWaterPixelsInBox", 0) >= SWOT_MIN_GOOD_PIXELS for v in stats.values()):
                excluded.append({"granuleId": gid, "bytes": path.stat().st_size, "reason":
                                 f"fewer than {SWOT_MIN_GOOD_PIXELS} good water pixels (wse_qual<=1, "
                                 "water_frac>0.5) inside any target box; footprint only clips the target. "
                                 "Downloaded, checked, deleted.", "targetSummary": stats})
                path.unlink()
                print(f"  {region} excluded {path.name} {stats}")
                continue
            p = gid.split("_")
            te = g["umm"]["TemporalExtent"]["RangeDateTime"]
            granules.append({"granuleId": gid, "utmZone": p[5], "cycle": int(p[10]), "pass": int(p[11]),
                             "scene": p[12], "crid": p[15], "start": te["BeginningDateTime"],
                             "end": te["EndingDateTime"], "matchedTargets": sorted(hits),
                             "accessUrl": strip_query(urls[0]), "targetSummary": stats})
            files.append(file_record(path, dest, granuleId=gid))
            print(f"  {region} {path.name} {stats}")
        record = {
            "id": f"WATER-03-{region}-{RETRIEVED.replace('-', '')}",
            "catalogueSourceId": "WATER-03",
            "provider": "NASA JPL / CNES SWOT mission; distributed by NASA PO.DAAC",
            "product": "SWOT Level 2 Water Mask Raster Image 100m Data Product",
            "collection": {"shortName": "SWOT_L2_HR_Raster_100m_D", "version": "D", "conceptId": "C3233942298-POCLOUD"},
            "version": "D (CRID in each granule name, e.g. PID0)",
            "doi": "10.5067/SWOT-RASTER-D",
            "documentationUrl": "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-docs/web-misc/swot_mission_docs/D-109532_SWOT_UserHandbook_RevA_20250311_sig-final.pdf",
            "accessUrl": "https://archive.swot.podaac.earthdata.nasa.gov/podaac-swot-ops-cumulus-protected/SWOT_L2_HR_Raster_D/",
            "accessMethod": "earthaccess (NASA Earthdata Cloud HTTPS, Earthdata Login)",
            "evidenceType": "satellite retrieval",
            "retrievedAt": RETRIEVED,
            "licence": nasa_licence(
                "SWOT (2025). SWOT Level 2 Water Mask Raster Image 100m Data Product, Version D. "
                "Ver. D. PO.DAAC, CA, USA. https://doi.org/10.5067/SWOT-RASTER-D. SWOT is a joint "
                "NASA/CNES mission with contributions from CSA and UKSA."),
            "region": region,
            "dataScope": DATA_SCOPE,
            "query": {
                "regionBboxWGS84": list(REGIONS[region]),
                "targets_lonlat": {k: list(v) for k, v in sel["targets"].items()},
                "cycle": int(SWOT_CYCLE),
                "temporal": "granules of repeat cycle 036 (searched 2025-07-10/2025-08-20)",
                "criteria": "all cycle-036 granules whose CMR footprint contains a target point, restricted "
                "to the region's UTM zones, latest product counter per pass/scene, cap 15; then kept only if "
                f">= {SWOT_MIN_GOOD_PIXELS} good water pixels fall inside a target box",
                "targetBoxesWGS84": {k: list(v) for k, v in sel["boxes"].items()},
            },
            "processing": "None. Granule NetCDF files kept whole as delivered (UTM 100 m tiles; all "
            "variables including wse, wse_qual, wse_uncert, water_area, water_frac, geolocation "
            "latitude/longitude and quality flags).",
            "semantics": {
                "wse": "water-surface elevation, m, above the EGM2008 geoid (not ODN/NAVD88 directly)",
                "wse_qual": "0 good, 1 suspect, 2 degraded, 3 bad",
                "water_frac": "fraction of pixel area that is water",
                "note": "Single-pass snapshots; elevation/extent are not volumes, allocations or water "
                "quality. targetSummary = median wse within 2 km of the target with wse_qual<=1 and "
                "water_frac>0.5 (sanity check only).",
            },
            "granules": granules,
            "excludedGranules": excluded,
            "files": files,
        }
        write_json(dest / "source.json", record)


def main(argv: list[str]) -> None:
    which = argv or ["eco", "pace", "swot"]
    earthaccess.login(strategy="netrc")
    if "eco" in which:
        fetch_ecostress()
    if "pace" in which:
        fetch_pace()
    if "swot" in which:
        fetch_swot()
    print(f"total transferred this run: {transferred / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
