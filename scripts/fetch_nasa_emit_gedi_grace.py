"""Fetch NASA Earthdata products GEO-01 (EMIT), LAND-04 (GEDI L4B) and WATER-02 (GRACE) as regional subsets.

Follows data/README.md "Data scope": big data are kept for the two project regions only.

  uv run --no-project --with earthaccess --with xarray --with netcdf4 --with h5netcdf --with rasterio \
      python -I scripts/fetch_nasa_emit_gedi_grace.py [emit|emit-l3|gedi|grace-mascon|grace-da|all]
  (emit-search, which lists candidate EMIT scenes, also needs --with shapely)

Credentials come from ~/.netrc (earthaccess strategy "netrc"); nothing here prints or stores them.
Downloads go to data/raw/_global_tmp/<ID>/ and that directory is deleted at the end of each step.

What each step writes:
  emit          data/raw/GEO-01/arizona/   EMITL2BMIN v002 MIN + MINUNCERT swaths (kept whole, unorthorectified)
  emit-l3       data/raw/GEO-01/global/    EMITL3ASA v002 global 0.5 deg aggregate (~22 MB, kept whole)
  gedi          data/raw/LAND-04/<region>/ GEDI L4B v2.1 MU and SE GeoTIFFs clipped with scripts/clip_to_bbox.py
  grace-mascon  data/raw/WATER-02/global/  JPL RL06.3Mv04 CRI mascon whole record (~44 MB, kept whole)
  grace-da      data/raw/WATER-02/<region>/ GRACE-DA CLSM 7-day 0.25 deg, calendar 2024, clipped per week
"""
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import earthaccess

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TMP = RAW / "_global_tmp"
SCRIPTS = ROOT / "scripts"
TODAY = date.today().isoformat()

REGIONS = {
    "arizona": (-113.5, 31.3, -109.0, 34.5),
    "uk": (-8.7, 49.8, 1.9, 60.9),
}
SCOPE_REGIONAL = "regional subset (data/README.md 'Data scope')"
SCOPE_GLOBAL = "global file < ~100 MB kept whole (data/README.md 'Data scope')"
NASA_LICENCE_URL = "https://science.data.nasa.gov/about/license"

# EMIT scenes chosen with the `emit-search` step: CMR CloudCover 0 % and footprint containing a copper district.
EMIT_GRANULES = {
    "EMIT_L2B_MIN_002_20231027T170527": ["Globe-Miami", "Ray"],
    "EMIT_L2B_MIN_002_20240404T174632": ["Morenci"],
    "EMIT_L2B_MIN_002_20230526T220606": ["Globe-Miami"],
}
COPPER_DISTRICTS = {"Globe-Miami": (-110.85, 33.4), "Ray": (-110.98, 33.16), "Morenci": (-109.36, 33.08)}

GEDI_SHORT = "GEDI_L4B_Gridded_Biomass_V2_1_2299"
GEDI_LAYERS = {"MU": "mean aboveground biomass density (AGBD), Mg/ha",
               "SE": "standard error of mean AGBD, Mg/ha"}
GRACE_DA_VARS = ["gws_inst", "rtzsm_inst", "sfsm_inst"]


# ---------------------------------------------------------------- helpers
def sha256(p, algo="sha256"):
    h = hashlib.new(algo)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(p, base):
    p = Path(p)
    return {"path": str(p.relative_to(base)), "bytes": p.stat().st_size, "sha256": sha256(p)}


def clean_url(u):
    """Strip any query string (signed URLs must never be stored)."""
    return u.split("?", 1)[0]


def data_urls(g):
    return [clean_url(l["URL"]) for l in g["umm"].get("RelatedUrls", []) if l.get("Type") == "GET DATA"]


def collection_meta(short_name, version=None):
    kw = {"short_name": short_name}
    if version:
        kw["version"] = version
    cs = earthaccess.search_datasets(**kw)
    assert cs, f"collection {short_name} {version} not found in CMR"
    u, m = cs[0]["umm"], cs[0]["meta"]
    cit = (u.get("CollectionCitations") or [{}])[0]
    if cit.get("Title"):
        citation = (f"{cit.get('Creator', '')}. {cit.get('ReleaseDate', '')[:4]}. {cit['Title']}. "
                    f"{cit.get('Publisher', '')}. https://doi.org/{u['DOI']['DOI']}").strip()
    else:
        citation = cit.get("OtherCitationDetails", "")
    return {"shortName": short_name, "version": u.get("Version"), "doi": u.get("DOI", {}).get("DOI"),
            "conceptId": m.get("concept-id"), "provider": m.get("provider-id"),
            "title": u.get("EntryTitle"), "citation": citation}


def licence(coll, notes=""):
    return {"name": "NASA open data", "url": NASA_LICENCE_URL, "attribution": coll["citation"],
            "reviewedAt": TODAY,
            "notes": ("NASA Earth science data are open with no restriction on reuse; cite the product DOI. "
                      + notes).strip()}


def base_record(rid, cat_id, coll, region, evidence, doc_url, product):
    return {
        "id": f"{rid}-{region}-{TODAY.replace('-', '')}",
        "catalogueSourceId": cat_id,
        "provider": f"NASA Earthdata ({coll['provider']})",
        "product": product,
        "collectionShortName": coll["shortName"],
        "collectionConceptId": coll["conceptId"],
        "version": coll["version"],
        "doi": coll["doi"],
        "documentationUrl": doc_url,
        "accessMethod": "earthaccess (CMR search + HTTPS download, Earthdata Login)",
        "evidenceType": evidence,
        "region": region,
        "dataScope": SCOPE_GLOBAL if region == "global" else SCOPE_REGIONAL,
        "retrievedAt": TODAY,
    }


def write_source(folder, rec):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "source.json", "w") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")
    print(f"wrote {folder / 'source.json'}")


def download(granules, dest):
    dest.mkdir(parents=True, exist_ok=True)
    paths = earthaccess.download(granules, str(dest), show_progress=False)
    return [Path(p) for p in paths]


def cmr_checksums(g):
    out = {}
    for a in g["umm"].get("DataGranule", {}).get("ArchiveAndDistributionInformation", []):
        if a.get("Checksum"):
            out[a["Name"]] = (a["Checksum"]["Algorithm"], a["Checksum"]["Value"], a.get("SizeInBytes"))
    return out


def verify(p, sums):
    if p.name not in sums:
        return "no upstream checksum"
    algo, val, _ = sums[p.name]
    got = sha256(p, algo.replace("-", "").lower())
    assert got.lower() == val.lower(), f"checksum mismatch for {p.name}"
    return f"{algo} verified against CMR"


# ---------------------------------------------------------------- EMIT
def emit_search():
    from shapely.geometry import Point, Polygon
    res = earthaccess.search_data(short_name="EMITL2BMIN", version="002", bounding_box=REGIONS["arizona"],
                                  temporal=("2023-01-01", "2025-12-31"))
    rows = []
    for g in res:
        u = g["umm"]
        polys = [Polygon([(p["Longitude"], p["Latitude"]) for p in gp["Boundary"]["Points"]])
                 for gp in u["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"].get("GPolygons", [])]
        hits = [k for k, xy in COPPER_DISTRICTS.items() if any(P.contains(Point(*xy)) for P in polys)]
        if hits:
            rows.append((u.get("CloudCover", 999), u["GranuleUR"], hits))
    print(len(res), "granules in box;", len(rows), "over copper districts")
    for r in sorted(rows)[:20]:
        print(r)


def emit_minerals(nc_path):
    """Count pixels by identified mineral (group 1 and 2) to sanity-check a scene."""
    import netCDF4
    import numpy as np
    with netCDF4.Dataset(nc_path) as ds:
        names = [str(n) for n in ds["mineral_metadata"]["name"][:]]
        assert "glt_x" in ds["location"].variables, "GLT missing from location group"
        counts = {}
        for grp in ("group_1_mineral_id", "group_2_mineral_id"):
            ids = np.ma.filled(ds[grp][:], 0).ravel()
            u, c = np.unique(ids[ids > 0], return_counts=True)
            for i, n in zip(u, c):
                nm = names[int(i)] if int(i) < len(names) else f"id{int(i)}"
                counts[nm] = counts.get(nm, 0) + int(n)
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def fetch_emit():
    coll = collection_meta("EMITL2BMIN", "002")
    tmp = TMP / "GEO-01"
    out = RAW / "GEO-01" / "arizona"
    out.mkdir(parents=True, exist_ok=True)
    granules_meta, scenes = [], {}
    for gid, districts in EMIT_GRANULES.items():
        res = earthaccess.search_data(short_name="EMITL2BMIN", version="002", granule_name=gid)
        assert len(res) == 1, f"{gid}: {len(res)} results"
        g = res[0]
        sums = cmr_checksums(g)
        paths = [p for p in download([g], tmp / gid) if p.suffix == ".nc"]
        assert len(paths) == 2, paths
        checks = {}
        for p in paths:
            checks[p.name] = verify(p, sums)
            shutil.move(str(p), out / p.name)
        u = g["umm"]
        min_nc = out / f"{gid}.nc"
        minerals = emit_minerals(min_nc)
        scenes[gid] = minerals
        granules_meta.append({
            "granuleId": gid,
            "beginDateTime": u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
            "cloudCoverPercent": u.get("CloudCover"),
            "copperDistrictsInFootprint": districts,
            "orbit": next((a["Values"][0] for a in u.get("AdditionalAttributes", []) if a["Name"] == "ORBIT"), None),
            "dataUrls": [x for x in data_urls(g) if x.endswith(".nc")],
            "upstreamChecksum": checks,
            "topMineralsByPixelCount": dict(list(minerals.items())[:8]),
        })
        print(gid, "->", list(minerals.items())[:6])
    shutil.rmtree(tmp, ignore_errors=True)

    rec = base_record("GEO-01-emitl2bmin", "GEO-01", coll, "arizona", "satellite_retrieval",
                      "https://nasa.github.io/LPDAAC-Data-Resources/external/Working_with_EMIT_L2B_Mineralogy.html",
                      coll["title"])
    rec |= {
        "accessUrl": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/EMITL2BMIN.002/",
        "licence": licence(coll),
        "query": ("short_name=EMITL2BMIN version=002; bbox W,S,E,N=-113.5,31.3,-109.0,34.5; "
                  "temporal 2023-01-01..2025-12-31; selected the lowest-CMR-CloudCover scenes whose footprint "
                  "contains Globe-Miami (-110.85,33.4), Ray (-110.98,33.16) or Morenci (-109.36,33.08)"),
        "processing": ("None. Swath NetCDFs kept whole (already regional, ~100 MB each granule). Data are in "
                       "sensor (downtrack x crosstrack) geometry and are NOT orthorectified: use the GLT "
                       "(location/glt_x, glt_y and the GeoTransform/spatial_ref global attributes) to place pixels, "
                       "see documentationUrl. Values: group_1/2_mineral_id index mineral_metadata/name; band depth "
                       "is a spectral-feature strength, not mass concentration, ore grade or tonnage."),
        "granules": granules_meta,
        "notes": ("Surface spectral signature of exposed material only. CloudCover is the whole-scene CMR value; "
                  "always apply the L2A mask before aggregating. UK not fetched (vegetated/cloudy, little value)."),
        "files": [file_entry(p, out) for p in sorted(out.glob("*.nc"))],
    }
    write_source(out, rec)


def fetch_emit_l3():
    coll = collection_meta("EMITL3ASA", "002")
    tmp = TMP / "GEO-01-l3"
    out = RAW / "GEO-01" / "global"
    res = earthaccess.search_data(short_name="EMITL3ASA", version="002")
    assert len(res) == 1
    g = res[0]
    sums = cmr_checksums(g)
    paths = download([g], tmp)
    out.mkdir(parents=True, exist_ok=True)
    checks = {}
    for p in paths:
        checks[p.name] = verify(p, sums)
        shutil.move(str(p), out / p.name)
    shutil.rmtree(tmp, ignore_errors=True)
    u = g["umm"]
    rec = base_record("GEO-01-emitl3asa", "GEO-01", coll, "global", "satellite_retrieval",
                      "https://lpdaac.usgs.gov/documents/2262/EMITL3ASA_User_Guide_V2.pdf", coll["title"])
    rec |= {
        "accessUrl": data_urls(g)[0],
        "licence": licence(coll),
        "query": "short_name=EMITL3ASA version=002 (single global granule)",
        "processing": "None (global 0.5 degree aggregate, < 100 MB, kept whole).",
        "granules": [{"granuleId": u["GranuleUR"],
                      "beginDateTime": u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
                      "endDateTime": u["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
                      "dataUrls": data_urls(g), "upstreamChecksum": checks}],
        "notes": "Aggregated spectral abundance at 0.5 degree; coarse, coverage limited to EMIT acquisitions.",
        "files": [file_entry(p, out) for p in sorted(out.glob("*.nc"))],
    }
    write_source(out, rec)


# ---------------------------------------------------------------- GEDI
def raster_stats(p):
    import numpy as np
    import rasterio
    with rasterio.open(p) as r:
        a = r.read(1, masked=True)
        v = a.compressed()
        v = v[v >= 0]
        if v.size == 0:
            return {"validPixels": 0, "totalPixels": int(a.size)}
        q = np.percentile(v, [1, 50, 99])
        return {"validPixels": int(v.size), "totalPixels": int(a.size), "min": float(v.min()),
                "p01": float(q[0]), "median": float(q[1]), "p99": float(q[2]), "max": float(v.max()),
                "crs": r.crs.to_string(), "nodata": r.nodata}


def fetch_gedi():
    coll = collection_meta(GEDI_SHORT)
    res = earthaccess.search_data(short_name=GEDI_SHORT)
    tmp = TMP / "LAND-04"
    per_region = {r: {"granules": [], "stats": {}} for r in REGIONS}
    for layer in GEDI_LAYERS:
        g = next(x for x in res if x["umm"]["GranuleUR"].endswith(f"_{layer}.tif"))
        paths = download([g], tmp)
        tif = next(p for p in paths if p.suffix == ".tif")
        side = next((p for p in paths if p.name.endswith(".sha256")), None)
        check = "no upstream checksum"
        if side:
            expected = side.read_text().split()[0].strip().lower()
            assert sha256(tif) == expected, f"checksum mismatch {tif.name}"
            check = "sha256 verified against ORNL .sha256 sidecar"
        for region, bbox in REGIONS.items():
            out = RAW / "LAND-04" / region
            out.mkdir(parents=True, exist_ok=True)
            dst = out / f"{tif.stem}_{region}.tif"
            subprocess.run([sys.executable, "-I", str(SCRIPTS / "clip_to_bbox.py"), "raster", str(tif), str(dst),
                            "--bbox", ",".join(map(str, bbox))], check=True)
            per_region[region]["stats"][layer] = raster_stats(dst)
            per_region[region]["granules"].append({
                "granuleId": g["umm"]["GranuleUR"], "layer": layer, "meaning": GEDI_LAYERS[layer],
                "beginDateTime": g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
                "endDateTime": g["umm"]["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
                "dataUrls": [u for u in data_urls(g) if u.endswith(".tif")],
                "upstreamBytes": tif.stat().st_size, "upstreamChecksum": check})
        shutil.rmtree(tmp, ignore_errors=True)  # delete the ~500 MB global original before the next layer
        print(layer, {r: per_region[r]["stats"][layer] for r in REGIONS})

    for region, bbox in REGIONS.items():
        out = RAW / "LAND-04" / region
        rec = base_record("LAND-04-gedil4b", "LAND-04", coll, region, "model_output",
                          "https://daac.ornl.gov/GEDI/guides/GEDI_L4B_Gridded_Biomass_V2_1.html",
                          "GEDI L4B Gridded Aboveground Biomass Density v2.1 (1 km): MU and SE layers")
        rec |= {
            "accessUrl": "https://data.ornldaac.earthdata.nasa.gov/protected/gedi/GEDI_L4B_Gridded_Biomass_V2_1/data/",
            "licence": licence(coll, "ORNL DAAC data use policy: "
                                     "https://science.nasa.gov/earth-science/earth-science-data/data-information-policy"),
            "query": f"short_name={GEDI_SHORT}; layers MU, SE; region={region}; bbox W,S,E,N={','.join(map(str, bbox))}",
            "processing": ("Global 1 km GeoTIFFs (EASE-Grid 2.0, EPSG:6933) clipped by scripts/clip_to_bbox.py "
                           "raster (native grid window of the box's projected bounds, deflate); global originals "
                           "deleted. Units Mg/ha; nodata -9999."),
            "granules": per_region[region]["granules"],
            "sanityStats": per_region[region]["stats"],
            "notes": ("GEDI samples only ~51.6 S to 51.6 N (ISS orbit) over Apr 2019 - Mar 2023. Cells north of "
                      "~51.6 N (most of the UK box) and unsampled cells are nodata = no coverage, never zero "
                      "biomass. Gridded mean of footprint estimates, model-based (L4A models), not a wall-to-wall "
                      "measurement; read SE (and the QF/NS layers, not fetched) before use."),
            "files": [file_entry(p, out) for p in sorted(out.glob("*.tif"))],
        }
        write_source(out, rec)


# ---------------------------------------------------------------- GRACE
def fetch_grace_mascon():
    sn = "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"
    coll = collection_meta(sn)
    res = earthaccess.search_data(short_name=sn)
    nc = [g for g in res]
    assert len(nc) == 1, len(nc)
    g = nc[0]
    tmp = TMP / "WATER-02-mascon"
    out = RAW / "WATER-02" / "global"
    out.mkdir(parents=True, exist_ok=True)
    sums = cmr_checksums(g)
    checks = {}
    for p in download([g], tmp):
        if p.suffix != ".nc":
            continue
        checks[p.name] = verify(p, sums)
        shutil.move(str(p), out / p.name)
    shutil.rmtree(tmp, ignore_errors=True)
    u = g["umm"]
    import xarray as xr
    f = next(out.glob("*.nc"))
    with xr.open_dataset(f) as ds:
        last = ds["lwe_thickness"].isel(time=-1)
        lon0 = (REGIONS["arizona"][0] % 360, REGIONS["arizona"][2] % 360)
        az = last.sel(lat=slice(31.3, 34.5), lon=slice(*lon0))
        stats = {"lastTime": str(ds.time.values[-1])[:10], "nTimes": int(ds.sizes["time"]),
                 "arizonaLweCmMin": float(az.min()), "arizonaLweCmMax": float(az.max())}
    print("mascon", stats)
    rec = base_record("WATER-02-mascon", "WATER-02", coll, "global", "satellite_retrieval",
                      "https://grace.jpl.nasa.gov/data/get-data/jpl_global_mascons/", coll["title"])
    rec |= {
        "accessUrl": next(x for x in data_urls(g) if x.endswith(".nc")),
        "licence": licence(coll, "Collection citation in CMR still cites RL06 v02 text; cite the DOI above."),
        "query": f"short_name={sn} (single whole-record granule)",
        "processing": "None (global ~44 MB NetCDF, kept whole).",
        "granules": [{"granuleId": u["GranuleUR"],
                      "beginDateTime": u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
                      "endDateTime": u["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
                      "upstreamChecksum": checks}],
        "sanityStats": stats,
        "notes": ("Monthly terrestrial water storage anomaly (equivalent water height, cm) relative to the "
                  "2004.0-2009.999 mean, 0.5 deg grid of ~3 deg equal-area mascons (CRI-filtered). Very coarse: "
                  "apply the scale factors/land mask per the product docs; not a kilometre-scale aquifer measure. "
                  "Gap months (e.g. GRACE to GRACE-FO 2017-2018) are absent, not zero."),
        "files": [file_entry(p, out) for p in sorted(out.glob("*.nc"))],
    }
    write_source(out, rec)


def fetch_grace_da():
    import numpy as np
    import xarray as xr
    sn = "GRACEDADM_CLSM025GL_7D"
    coll = collection_meta(sn, "3.0")
    res = earthaccess.search_data(short_name=sn, version="3.0", temporal=("2024-01-01", "2024-12-31"))
    print(len(res), "weekly granules")
    tmp = TMP / "WATER-02-gracedadm"
    paths = sorted(p for p in download(res, tmp) if p.suffix == ".nc4")
    assert len(paths) == len(res), (len(paths), len(res))
    upstream = {}
    for g in res:
        u = g["umm"]
        name = u["GranuleUR"].split(":")[-1]
        upstream[name] = {"granuleId": u["GranuleUR"],
                          "beginDateTime": u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
                          "endDateTime": u["TemporalExtent"]["RangeDateTime"]["EndingDateTime"],
                          "upstreamBytes": None}
    stats = {r: {} for r in REGIONS}
    for p in paths:
        upstream[p.name]["upstreamBytes"] = p.stat().st_size
        upstream[p.name]["upstreamSha256"] = sha256(p)
        with xr.open_dataset(p) as ds:
            missing = [v for v in GRACE_DA_VARS if v not in ds]
            assert not missing, f"{p.name}: missing {missing}; have {list(ds.data_vars)}"
            half = float(abs(ds.lat[1] - ds.lat[0])) / 2
            for region, (w, s, e, n) in REGIONS.items():
                lat = ds.lat
                lat_sl = slice(s - half, n + half) if lat[0] < lat[-1] else slice(n + half, s - half)
                sub = ds[GRACE_DA_VARS].sel(lat=lat_sl, lon=slice(w - half, e + half)).load()
                sub.attrs = dict(ds.attrs) | {
                    "subset": f"region={region}; bbox W,S,E,N={w},{s},{e},{n}; cells intersecting the box; "
                              f"variables {', '.join(GRACE_DA_VARS)}; by scripts/fetch_nasa_emit_gedi_grace.py"}
                out = RAW / "WATER-02" / region
                out.mkdir(parents=True, exist_ok=True)
                dst = out / f"{p.stem}_{region}.nc4"
                enc = {v: {"zlib": True, "complevel": 4} for v in GRACE_DA_VARS}
                sub.to_netcdf(dst, engine="netcdf4", encoding=enc)
                g = sub["gws_inst"].values
                stats[region][p.stem.split(".")[1]] = {
                    "gwsPctMin": float(np.nanmin(g)) if np.isfinite(g).any() else None,
                    "gwsPctMax": float(np.nanmax(g)) if np.isfinite(g).any() else None,
                    "validCells": int(np.isfinite(g).sum()), "cells": int(g.size)}
    shutil.rmtree(tmp, ignore_errors=True)

    for region, bbox in REGIONS.items():
        out = RAW / "WATER-02" / region
        rec = base_record("WATER-02-gracedadm", "WATER-02", coll, region, "model_output",
                          "https://docserver.gesdisc.eosdis.nasa.gov/public/project/hydrology/README_GRACEDADM3GL.pdf",
                          coll["title"])
        rec |= {
            "accessUrl": "https://hydro1.gesdisc.eosdis.nasa.gov/data/GRACEDA/GRACEDADM_CLSM025GL_7D.3.0/",
            "licence": licence(coll),
            "query": (f"short_name={sn} version=3.0; temporal 2024-01-01..2024-12-31 (53 weekly granules); "
                      f"region={region}; bbox W,S,E,N={','.join(map(str, bbox))}"),
            "processing": ("Each global weekly NetCDF-4 subset with xarray .sel to the 0.25 deg cells intersecting "
                           "the box (box padded by half a cell), keeping gws_inst (groundwater), rtzsm_inst "
                           "(root-zone soil moisture) and sfsm_inst (surface soil moisture) percentiles; global "
                           "originals deleted. Upstream size and sha256 recorded per granule."),
            "granules": [upstream[k] for k in sorted(upstream)],
            "sanityStats": {"gws_inst_percentile_by_week": stats[region]},
            "notes": ("Wetness percentiles (0-100) relative to the 1948-2014 open-loop Catchment model climatology, "
                      "from CLSM assimilating GRACE/GRACE-FO TWS: a drought indicator, not a volume or allocatable "
                      "supply. Ocean/no-data cells are missing, not zero."),
            "files": [file_entry(p, out) for p in sorted(out.glob("*.nc4"))],
        }
        write_source(out, rec)
        wk = stats[region]
        print(region, "e.g.", next(iter(wk.items())))


STEPS = {"emit-search": emit_search, "emit": fetch_emit, "emit-l3": fetch_emit_l3, "gedi": fetch_gedi,
         "grace-mascon": fetch_grace_mascon, "grace-da": fetch_grace_da}

if __name__ == "__main__":
    which = sys.argv[1:] or ["all"]
    earthaccess.login(strategy="netrc")
    for step in (["emit", "emit-l3", "gedi", "grace-mascon", "grace-da"] if which == ["all"] else which):
        STEPS[step]()
    if TMP.exists() and not any(TMP.iterdir()):
        TMP.rmdir()
