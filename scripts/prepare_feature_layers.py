"""Prepare the vector / point / table feature layers the New Worlds app draws on the map.

Run (all layers, or a subset; the manifest keeps entries for layers not re-run):
  uv run --no-project --with geopandas --with pyogrio --with shapely --with pyarrow --with numpy \
    python -I scripts/prepare_feature_layers.py [--layers mrds,tri_facilities,...] [--data data]

Writes data/prepared/features/<layer>.(parquet|geojson|json) and data/prepared/features/manifest.json.

Conventions (shared with the backend/frontend):
- property keys are camelCase; every feature has a string `id`;
- points -> Parquet with columns id, lon, lat (WGS84 doubles), then the field columns;
- lines/polygons -> GeoJSON FeatureCollection, coordinates rounded to 5 decimals, properties are
  `id` plus the listed fields; polygon coverages are simplified with shapely.coverage_simplify so
  shared borders stay shared; each file is kept under ~15 MB;
- tables -> plain JSON;
- missing values are null, never 0 or "". Provider sentinels (e.g. Aqueduct -1/-9999) become null.

Layers: mrds (GEO-06), tri_facilities (IND-02), wqp_sites (WATER-04), nsta_wellbores (IND-04),
aqueduct_baseline + aqueduct_future (WATER-06), hydrorivers + hydrobasins_l6 (NET-01),
neso_carbon_intensity (IND-07). Each layer's caveats are written into the manifest `limitations`.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import glob
import io
import json
import math
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

NULLS = {"", "none", "null", "na", "n/a", "no data available", "nan"}
MAX_GEOJSON_MB = 15


# --------------------------------------------------------------------------- helpers
def clean(v):
    """Strip strings; map empty/'None'/'NA'-style placeholders to None."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        v = v.strip()
        return None if v.lower() in NULLS else v
    return v


def num(v):
    v = clean(v)
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def source(data: Path, rel: str) -> dict:
    return json.loads((data / "raw" / rel / "source.json").read_text())


def provenance(rec: dict, evidence: str) -> dict:
    lic = rec.get("licence", {})
    return {
        "provider": rec.get("provider"), "product": rec.get("product"), "licence": lic.get("name"),
        "attribution": lic.get("attribution"), "evidenceType": evidence,
        "retrievedAt": rec.get("retrievedAt"), "url": rec.get("documentationUrl") or lic.get("url"),
    }


def categories_of(values) -> list[str] | None:
    c = collections.Counter(v for v in map(clean, values) if v is not None)
    return [k for k, _ in c.most_common(12)] or None


def write_points(df: pd.DataFrame, out: Path, schema_types: dict) -> None:
    """df has id, lon, lat + fields. schema_types maps field -> 'string'|'double'|'int'."""
    cols = {"id": pa.array(df["id"].astype(str), pa.string()),
            "lon": pa.array(df["lon"].astype(float), pa.float64()),
            "lat": pa.array(df["lat"].astype(float), pa.float64())}
    for k, t in schema_types.items():
        vals = [clean(v) for v in df[k].tolist()]
        if t == "string":
            cols[k] = pa.array([None if v is None else str(v) for v in vals], pa.string())
        elif t == "int":
            cols[k] = pa.array([None if v is None else int(v) for v in vals], pa.int64())
        else:
            cols[k] = pa.array([None if v is None else float(v) for v in vals], pa.float64())
    pq.write_table(pa.table(cols), out, compression="zstd")


def round_geoms(geoms, nd=5):
    return shapely.transform(geoms, lambda c: np.round(c, nd))


def write_geojson(gdf: gpd.GeoDataFrame, out: Path, props: list[str]) -> None:
    feats = []
    geoms = round_geoms(gdf.geometry.values)
    for g, (_, row) in zip(geoms, gdf.iterrows()):
        p = {"id": str(row["id"])}
        for k in props:
            v = row[k]
            if isinstance(v, np.bool_):
                v = bool(v)
            elif isinstance(v, np.integer):
                v = int(v)
            elif isinstance(v, (np.floating, float)):
                v = None if not math.isfinite(float(v)) else float(v)
            p[k] = clean(v)
        feats.append({"type": "Feature", "id": p["id"], "geometry": json.loads(shapely.to_geojson(g)),
                      "properties": p})
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False))
    mb = out.stat().st_size / 1e6
    assert mb < MAX_GEOJSON_MB, f"{out.name} is {mb:.1f} MB (> {MAX_GEOJSON_MB} MB); tighten filter/simplify"


def simplify_coverage(geoms, tol: float):
    """Simplify a polygon coverage keeping shared edges; fall back to per-polygon simplify."""
    try:
        out = shapely.coverage_simplify(np.asarray(geoms), tol)
        if shapely.is_valid(out).all():
            return out, "coverage_simplify"
    except Exception as e:  # noqa: BLE001 — invalid coverage: fall back
        print(f"  coverage_simplify failed ({e}); falling back")
    return shapely.simplify(np.asarray(geoms), tol, preserve_topology=True), "simplify(preserve_topology)"


def bbox_of(lon, lat) -> list[float]:
    return [round(float(np.min(lon)), 5), round(float(np.min(lat)), 5),
            round(float(np.max(lon)), 5), round(float(np.max(lat)), 5)]


def entry(id_, name, source_id, geometry, file, regions, count, bbox, fields, prov, limitations,
          name_field=None, category_field=None, categories=None, value_field=None, value_units=None) -> dict:
    return {
        "id": id_, "name": name, "sourceId": source_id, "geometry": geometry, "file": file,
        "regions": regions, "count": int(count), "bbox": bbox, "nameField": name_field,
        "categoryField": category_field, "categories": categories, "valueField": value_field,
        "valueUnits": value_units, "fields": [{"key": k, "label": l, "units": u} for k, l, u in fields],
        **prov, "limitations": limitations,
    }


# --------------------------------------------------------------------------- GEO-06 MRDS
PROD_SIZE = {"Y": "Yes, production has occurred", "N": "No production", "S": "Small", "M": "Medium",
             "L": "Large", "U": "Unknown"}
COM_TYPE = {"M": "Metallic", "N": "Non-metallic", "B": "Metallic and non-metallic"}


def build_mrds(data: Path, out_dir: Path) -> dict:
    with zipfile.ZipFile(data / "raw" / "GEO-06" / "mrds" / "mrds-csv.zip") as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("mrds.csv"), encoding="utf-8", newline="")))
    recs, dropped = [], 0
    for r in rows:
        lat, lon = num(r["latitude"]), num(r["longitude"])
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            dropped += 1
            continue
        comms: list[str] = []
        for k in ("commod1", "commod2", "commod3"):
            for c in (clean(r[k]) or "").split(","):
                c = c.strip()
                if c and c not in comms:
                    comms.append(c)
        recs.append({
            "id": r["dep_id"], "lon": lon, "lat": lat, "name": clean(r["site_name"]),
            "commodities": "; ".join(comms) or None,
            "primaryCommodities": "; ".join(c.strip() for c in (clean(r["commod1"]) or "").split(",") if c.strip()) or None,
            "commodityType": COM_TYPE.get(clean(r["com_type"]) or ""),
            "devStatus": clean(r["dev_stat"]), "operType": clean(r["oper_type"]),
            "depositType": clean(r["dep_type"]), "model": clean(r["model"]), "workType": clean(r["work_type"]),
            "productionSize": PROD_SIZE.get(clean(r["prod_size"]) or ""),
            "country": clean(r["country"]), "state": clean(r["state"]), "county": clean(r["county"]),
            "recordUrl": clean(r["url"]) or f"https://mrdata.usgs.gov/mrds/show-mrds.php?dep_id={r['dep_id']}",
        })
    df = pd.DataFrame(recs)
    types = {k: "string" for k in df.columns if k not in ("id", "lon", "lat")}
    write_points(df, out_dir / "mrds.parquet", types)
    print(f"  mrds: {len(df):,} points ({dropped} dropped without valid coordinates)")
    rec = source(data, "GEO-06")
    fields = [("commodities", "Commodities (primary, secondary, tertiary)", None),
              ("primaryCommodities", "Primary commodities", None), ("commodityType", "Commodity type", None),
              ("devStatus", "Development status (as reported)", None), ("operType", "Operation type", None),
              ("depositType", "Deposit type", None), ("model", "Deposit model", None),
              ("workType", "Workings", None), ("productionSize", "Production size (as reported)", None),
              ("country", "Country", None), ("state", "State / province", None), ("county", "County", None),
              ("recordUrl", "USGS record", None)]
    return entry("mrds", "Mineral sites (USGS MRDS)", "GEO-06", "point", "mrds.parquet", ["global"], len(df),
                 bbox_of(df.lon, df.lat), fields, provenance(rec, "reported_record"), [
                     "MRDS is a legacy compilation; USGS stopped systematic updates in 2011 (extract dated 2016-03-15).",
                     "Development status, ownership and production describe the source reports, not current operations.",
                     "No reserves or resource estimates are implied; a 'Producer' may have closed long ago.",
                     "Coverage is thorough for the United States and incomplete elsewhere.",
                     f"{dropped} records without valid coordinates were dropped.",
                 ], name_field="name", category_field="devStatus", categories=categories_of(df.devStatus))


# --------------------------------------------------------------------------- IND-02 TRI
GRAMS_PER_LB = 453.59237


def build_tri(data: Path, out_dir: Path) -> dict:
    files = sorted(glob.glob(str(data / "raw" / "IND-02" / "arizona" / "tri_basic_*_AZ.csv")))
    by_fac: dict[str, dict[int, list[dict]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                r = {k.split(". ", 1)[-1]: v for k, v in r.items()}  # drop the "12. " column prefixes
                by_fac[r["TRIFD"]][int(r["YEAR"])].append(r)
    recs, grams_rows = [], 0
    for trifd, years in by_fac.items():
        year = max(years)
        rows = years[year]
        r0 = rows[0]
        tot = ons = 0.0
        chems, carc = set(), set()
        for r in rows:
            k = 1.0 / GRAMS_PER_LB if (r["UNIT OF MEASURE"] or "").strip().lower() == "grams" else 1.0
            grams_rows += k != 1.0
            tot += (num(r["TOTAL RELEASES"]) or 0.0) * k
            ons += (num(r["ON-SITE RELEASE TOTAL"]) or 0.0) * k
            chems.add(r["CHEMICAL"])
            if (r["CARCINOGEN"] or "").strip().upper() == "YES":
                carc.add(r["CHEMICAL"])
        lat, lon = num(r0["LATITUDE"]), num(r0["LONGITUDE"])
        if lat is None or lon is None:
            continue
        recs.append({
            "id": trifd, "lon": lon, "lat": lat, "name": clean(r0["FACILITY NAME"]), "city": clean(r0["CITY"]),
            "county": clean(r0["COUNTY"]), "industrySector": clean(r0["INDUSTRY SECTOR"]), "year": year,
            "chemicalCount": len(chems), "totalReleasesLb": round(tot, 3), "onSiteReleasesLb": round(ons, 3),
            "carcinogenChemicals": len(carc),
            "parentCompany": clean(r0["STANDARD PARENT CO NAME"]) or clean(r0["PARENT CO NAME"]),
        })
    df = pd.DataFrame(recs).sort_values("id")
    write_points(df, out_dir / "tri_facilities.parquet", {
        "name": "string", "city": "string", "county": "string", "industrySector": "string", "year": "int",
        "chemicalCount": "int", "totalReleasesLb": "double", "onSiteReleasesLb": "double",
        "carcinogenChemicals": "int", "parentCompany": "string"})
    print(f"  tri_facilities: {len(df):,} facilities")
    rec = source(data, "IND-02/arizona")
    years = sorted({int(Path(f).name.split("_")[2]) for f in files})
    fields = [("industrySector", "Industry sector", None), ("year", "Reporting year", None),
              ("totalReleasesLb", "Total releases", "lb/year"), ("onSiteReleasesLb", "On-site releases", "lb/year"),
              ("chemicalCount", "Chemicals reported", "count"),
              ("carcinogenChemicals", "Carcinogens reported (OSHA list)", "count"),
              ("parentCompany", "Parent company", None), ("city", "City", None), ("county", "County", None)]
    return entry("tri_facilities", "Toxics Release Inventory facilities", "IND-02", "point", "tri_facilities.parquet",
                 ["arizona"], len(df), bbox_of(df.lon, df.lat), fields, provenance(rec, "reported_record"), [
                     f"Self-reported by facilities to US EPA; reporting years {years[0]}–{years[-1]}, latest year kept per facility.",
                     "Only facilities above TRI thresholds in covered sectors report; absence is not evidence of no releases.",
                     "Totals sum all chemicals regardless of toxicity; a large total is not the same as a large hazard.",
                     f"{grams_rows} chemical rows reported in grams (dioxins) were converted to pounds before summing.",
                     "Covers the whole state of Arizona (state file), which is larger than the Arizona region box.",
                 ], name_field="name", category_field="industrySector",
                 categories=categories_of(df.industrySector), value_field="totalReleasesLb", value_units="lb/year")


# --------------------------------------------------------------------------- WATER-04 WQP
NO3_TO_N = 14.0067 / 62.0049
WQP = {  # key: (file stem, target unit, {unit: factor}, speciation rule)
    "nitrate": ("nitrate", "mg/L as N", {"mg/l": 1.0, "ug/l": 1e-3, "ppm": 1.0}, "nitrate"),
    "arsenic": ("arsenic", "µg/L", {"ug/l": 1.0, "mg/l": 1e3, "ppb": 1.0}, None),
    "tds": ("total_dissolved_solids", "mg/L", {"mg/l": 1.0, "ppm": 1.0, "ug/l": 1e-3, "g/l": 1e3}, None),
}


def wqp_factor(param: str, unit: str | None, spec: str | None) -> float | None:
    _, _, units, rule = WQP[param]
    f = units.get((unit or "").strip().lower())
    if f is None:
        return None
    if rule == "nitrate":
        s = (clean(spec) or "").lower()
        if s == "as n":
            return f
        if s == "as no3":
            return f * NO3_TO_N
        return None  # unknown speciation: N vs NO3 differ by 4.4x, so skip
    return f


def build_wqp(data: Path, out_dir: Path) -> dict:
    sites: dict[str, dict] = {}
    obs: dict[str, dict[str, list]] = collections.defaultdict(lambda: collections.defaultdict(list))
    stats = {}
    for p, (stem, _, _, _) in WQP.items():
        used = skipped_unit = no_value = 0
        f = data / "raw" / "WATER-04" / "arizona" / f"wqx3_{stem}_2020plus.csv"
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                loc = clean(r.get("Location_Identifier"))
                if not loc or clean(r.get("Activity_Media")) not in (None, "Water"):
                    continue
                if loc not in sites:
                    lat = num(r["Location_LatitudeStandardized"]) or num(r["Location_Latitude"])
                    lon = num(r["Location_LongitudeStandardized"]) or num(r["Location_Longitude"])
                    if lat is None or lon is None:
                        continue
                    sites[loc] = {"id": loc, "lon": lon, "lat": lat, "name": clean(r["Location_Name"]),
                                  "siteType": clean(r["Location_Type"]), "organization": clean(r["Org_FormalName"])}
                v = num(r["Result_Measure"])
                if v is None:
                    no_value += 1  # non-detects and blank results
                    continue
                k = wqp_factor(p, r["Result_MeasureUnit"], r["Result_MethodSpeciation"])
                if k is None:
                    skipped_unit += 1
                    continue
                used += 1
                obs[loc][p].append((clean(r["Activity_StartDate"]) or "", v * k))
        stats[p] = (used, skipped_unit, no_value)
    recs = []
    for loc, s in sites.items():
        row = dict(s)
        measured = []
        for p, (_, unit, _, _) in WQP.items():
            vals = obs[loc].get(p, [])
            if vals:
                measured.append(p)
                last = max(d for d, _ in vals)
                row |= {f"{p}Count": len(vals), f"{p}Latest": round(max(v for d, v in vals if d == last), 6),
                        f"{p}Max": round(max(v for _, v in vals), 6), f"{p}Units": unit, f"{p}LatestDate": last or None}
            else:
                row |= {f"{p}Count": None, f"{p}Latest": None, f"{p}Max": None, f"{p}Units": None, f"{p}LatestDate": None}
        row["measured"] = "; ".join(measured) or None
        recs.append(row)
    df = pd.DataFrame(recs).sort_values("id")
    types = {"name": "string", "siteType": "string", "organization": "string", "measured": "string"}
    for p in WQP:
        types |= {f"{p}Count": "int", f"{p}Latest": "double", f"{p}Max": "double", f"{p}Units": "string",
                  f"{p}LatestDate": "string"}
    write_points(df, out_dir / "wqp_sites.parquet", types)
    print(f"  wqp_sites: {len(df):,} sites; used/skipped-unit/no-value per characteristic: {stats}")
    rec = source(data, "WATER-04/arizona")
    labels = {"nitrate": "Nitrate (as N)", "arsenic": "Arsenic", "tds": "Total dissolved solids"}
    fields = [("siteType", "Site type", None), ("organization", "Organization", None),
              ("measured", "Characteristics measured", None)]
    for p, (_, unit, _, _) in WQP.items():
        fields += [(f"{p}Max", f"{labels[p]} max", unit), (f"{p}Latest", f"{labels[p]} latest", unit),
                   (f"{p}LatestDate", f"{labels[p]} latest date", None), (f"{p}Count", f"{labels[p]} results", "count"),
                   (f"{p}Units", f"{labels[p]} units", None)]
    lim = [
        "Results submitted by many organizations to the Water Quality Portal since 2020; methods, fractions (total vs dissolved) and sampling purposes differ.",
        "Max and latest pool all fractions and media subdivisions (surface water, groundwater) for a site.",
        "Values were converted to one unit per characteristic: arsenic µg/L, nitrate mg/L as N (NO3 values × 0.2259), TDS mg/L (ppm treated as mg/L).",
        f"Skipped results with incompatible or unknown units/speciation: nitrate {stats['nitrate'][1]}, arsenic {stats['arsenic'][1]}, TDS {stats['tds'][1]}.",
        f"Results without a numeric value (mostly non-detects) are not counted: nitrate {stats['nitrate'][2]}, arsenic {stats['arsenic'][2]}, TDS {stats['tds'][2]}.",
        "Some maxima look like unit-entry errors at source (e.g. 4,600 µg/L arsenic at a lake reported as 4.6 mg/L); values are kept as reported.",
        "A single high value may be a contaminated-site investigation sample, not drinking water; compare with the US EPA arsenic MCL of 10 µg/L and nitrate MCL of 10 mg/L as N only as context.",
    ]
    return entry("wqp_sites", "Water quality monitoring sites (nitrate, arsenic, TDS)", "WATER-04", "point",
                 "wqp_sites.parquet", ["arizona"], len(df), bbox_of(df.lon, df.lat), fields,
                 provenance(rec, "in_situ_observation"), lim, name_field="name", category_field="siteType",
                 categories=categories_of(df.siteType), value_field="arsenicMax", value_units="µg/L")


# --------------------------------------------------------------------------- IND-04 NSTA wellbores
def ms_date(v):
    v = clean(v)
    if v is None:
        return None
    return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).date().isoformat()


def plausible(v, lo, hi, bad: collections.Counter):
    """Depth in metres, or None when missing or outside (lo, hi] (entry errors: 0, negative TVDSS, 175 km)."""
    x = num(v)
    if x is not None and not (lo < x <= hi):
        bad["out_of_range"] += 1
        return None
    return round(x, 1) if x is not None else None


def build_nsta(data: Path, out_dir: Path) -> dict:
    bad = collections.Counter()
    gj = json.loads((data / "raw" / "IND-04" / "2026-11-07" / "nsta_offshore_wellbore_top_holes_wgs84.geojson").read_text())
    recs = []
    for f in gj["features"]:
        p, g = f["properties"], f["geometry"]
        if not g or g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        status = clean(p.get("WELLOPSTAT"))
        fluids = "; ".join(x.strip() for x in (clean(p.get("FLUIDTYPES")) or "").split(",") if x.strip()) or None
        recs.append({
            "id": clean(p["WELLREGNO"]) or str(p["OBJECTID"]), "lon": lon, "lat": lat,
            "name": clean(p.get("NAME")) or clean(p.get("WELLREGNO")), "wellRegNo": clean(p.get("WELLREGNO")),
            "status": "Decommissioned" if status == "Decomissioned" else status,
            "originStatus": clean(p.get("ORIGINSTAT")), "completionStatus": clean(p.get("COMPLESTAT")),
            "intent": clean(p.get("CURRWELLIN")), "operator": clean(p.get("RESWOP")),
            "operatorGroup": clean(p.get("RESWOPGRP")), "field": clean(p.get("TARGETFLD")), "fluidTypes": fluids,
            "deviation": clean(p.get("DEVIATTYP")), "spudDate": ms_date(p.get("SPUDDATE")),
            "completionDate": ms_date(p.get("COMPLEDATE")),
            "totalDepthMdM": plausible(p.get("TDMDDEPM"), 0, 13_000, bad),
            "totalDepthTvdssM": plausible(p.get("TDTVDSSM"), 0, 13_000, bad),
            "waterDepthM": plausible(p.get("WATDEP_M"), 0, 4_000, bad),
        })
    df = pd.DataFrame(recs).sort_values("id")
    types = {k: "string" for k in df.columns if k not in ("id", "lon", "lat")}
    types |= {"totalDepthMdM": "double", "totalDepthTvdssM": "double", "waterDepthM": "double"}
    write_points(df, out_dir / "nsta_wellbores.parquet", types)
    print(f"  nsta_wellbores: {len(df):,} wellbores; {bad['out_of_range']} implausible depth values nulled")
    rec = source(data, "IND-04")
    fields = [("status", "Well operational status", None), ("completionStatus", "Completion status", None),
              ("intent", "Current intent", None), ("operator", "Responsible operator", None),
              ("operatorGroup", "Operator group", None), ("field", "Target field", None),
              ("fluidTypes", "Fluids encountered", None), ("spudDate", "Spud date", None),
              ("completionDate", "Completion date", None), ("totalDepthMdM", "Total depth (measured)", "m"),
              ("totalDepthTvdssM", "Total depth (true vertical, below sea level)", "m"),
              ("waterDepthM", "Water depth", "m"), ("deviation", "Trajectory", None),
              ("originStatus", "Well origin status", None), ("wellRegNo", "Registration number", None)]
    prov = provenance(rec, "reported_record")
    prov["licence"] = ("Open Government Licence v3.0 per data.gov.uk listing; current NSTA layer may be under the "
                       "NSTA Open User Licence — confirm before public export")
    return entry("nsta_wellbores", "UK offshore wellbores (NSTA)", "IND-04", "point", "nsta_wellbores.parquet", ["uk"],
                 len(df), bbox_of(df.lon, df.lat), fields, prov, [
                     "Licence unresolved: the data.gov.uk OGL links return 403 and the live NSTA service references the 'NSTA Open User Licence'; confirm before any public export.",
                     "Points are top-hole (seabed) locations of offshore wellbores on the UK continental shelf; onshore wells are not included.",
                     "Status describes the wellbore (e.g. suspended, decommissioned), not whether a field is producing; it is not evidence of reserves.",
                     "Snapshot of a live service taken 2026-11-07; 'Decomissioned' was corrected to 'Decommissioned'.",
                     "Coverage extends far beyond the UK region box (whole UKCS).",
                     f"{bad['out_of_range']} implausible depth values (0 m, negative true vertical depth, or > 13 km) were set to null.",
                 ], name_field="name", category_field="status", categories=categories_of(df.status),
                 value_field="totalDepthMdM", value_units="m")


# --------------------------------------------------------------------------- WATER-06 Aqueduct
AQ_INDICATORS = [("bws", "Baseline water stress"), ("bwd", "Baseline water depletion"),
                 ("iav", "Interannual variability"), ("sev", "Seasonal variability"),
                 ("gtd", "Groundwater table decline"), ("rfr", "Riverine flood risk"),
                 ("cfr", "Coastal flood risk"), ("drr", "Drought risk")]


def aq_score(score, label):
    """Score, or None for sentinels: -9999 (no data / insignificant trend) and 'Arid and low water use'
    (category -1, which Aqueduct scores as 5). 'No Risk' coastal flood (category -1, score 0) is kept."""
    s = num(score)
    if s is None or s < 0 or "arid" in (clean(label) or "").lower():
        return None
    return round(s, 3)


def build_aqueduct(data: Path, out_dir: Path) -> list[dict]:
    regions = ["arizona", "uk"]
    base = pd.concat([gpd.read_file(data / "raw" / "WATER-06" / r / f"aqueduct40_{r}.gpkg", layer="baseline_annual")
                      for r in regions], ignore_index=True).drop_duplicates("string_id")
    base = gpd.GeoDataFrame(base, geometry="geometry", crs="EPSG:4326")
    base = base[~base.geometry.is_empty & base.geometry.notna()]
    geoms, how = simplify_coverage(shapely.make_valid(base.geometry.values), 0.005)
    out = gpd.GeoDataFrame({"id": base["string_id"].astype(str).values}, geometry=geoms, crs="EPSG:4326")
    out["name"] = [", ".join(x for x in (clean(a), clean(b)) if x) or None for a, b in zip(base.name_1, base.name_0)]
    out["pfafId"] = base["pfaf_id"].astype("Int64").astype(str).values
    out["aqid"] = base["aqid"].astype("Int64").astype(str).values
    out["country"] = base["name_0"].values
    out["admin1"] = base["name_1"].values
    out["areaKm2"] = base["area_km2"].round(1).values
    props = ["name", "pfafId", "aqid", "country", "admin1", "areaKm2"]
    for k, _ in AQ_INDICATORS:
        out[f"{k}Score"] = [aq_score(s, l) for s, l in zip(base[f"{k}_score"], base[f"{k}_label"])]
        out[f"{k}Label"] = [clean(x) for x in base[f"{k}_label"]]
        props += [f"{k}Score", f"{k}Label"]
    write_geojson(out, out_dir / "aqueduct_baseline.geojson", props)
    print(f"  aqueduct_baseline: {len(out)} polygons ({how})")
    rec = source(data, "WATER-06/arizona")
    fields = [("bwsLabel", "Baseline water stress", None), ("bwsScore", "Baseline water stress score", "0–5 score")]
    for k, label in AQ_INDICATORS[1:]:
        fields += [(f"{k}Label", label, None), (f"{k}Score", f"{label} score", "0–5 score")]
    fields += [("country", "Country", None), ("admin1", "State / region", None), ("areaKm2", "Area", "km²"),
               ("pfafId", "HydroBASINS level-6 Pfafstetter id", None), ("aqid", "Aquifer id", None)]
    tb = [round(float(x), 5) for x in out.total_bounds]
    entries = [entry("aqueduct_baseline", "Aqueduct 4.0 baseline water risk", "WATER-06", "polygon",
                     "aqueduct_baseline.geojson", regions, len(out), tb, fields, provenance(rec, "model_output"), [
                         "Modelled indicators (Aqueduct 4.0, baseline 1979–2019) on basin × state × aquifer units, not measurements.",
                         "Scores are null where Aqueduct marks 'Arid and low water use' (scored 5 by Aqueduct, category -1) or uses the -9999 sentinel ('No Data', groundwater 'Insignificant Trend'); the label is kept.",
                         "Polygons are whole units touching the region boxes, merged across regions and simplified (~500 m) with shared borders preserved.",
                         "A basin-level score cannot show local wells, transfers (e.g. the Central Arizona Project) or water rights.",
                     ], name_field="name", category_field="bwsLabel", categories=categories_of(out.bwsLabel),
                     value_field="bwsScore", value_units="0–5 score")]

    fut = pd.concat([gpd.read_file(data / "raw" / "WATER-06" / r / f"aqueduct40_{r}.gpkg", layer="future_annual")
                     for r in regions], ignore_index=True)
    fut["pfaf"] = fut["pfaf_id"].astype("Int64").astype(str)
    fut = gpd.GeoDataFrame(fut.drop_duplicates("pfaf"), geometry="geometry", crs="EPSG:4326")
    geoms, how = simplify_coverage(shapely.make_valid(fut.geometry.values), 0.005)
    fo = gpd.GeoDataFrame({"id": fut["pfaf"].values}, geometry=geoms, crs="EPSG:4326")
    fo["name"] = ["Basin " + p for p in fut["pfaf"]]
    fo["pfafId"] = fut["pfaf"].values
    props, ffields = ["name", "pfafId"], []
    scen = {"bau": ("Bau", "business as usual, SSP3 RCP7.0"), "opt": ("Opt", "optimistic, SSP1 RCP2.6"),
            "pes": ("Pes", "pessimistic, SSP5 RCP8.5")}
    for yy, year in (("30", 2030), ("50", 2050), ("80", 2080)):
        for s, (cap, desc) in scen.items():
            key = f"bws{year}{cap}"
            fo[f"{key}Score"] = [aq_score(a, b) for a, b in zip(fut[f"{s}{yy}_ws_x_s"], fut[f"{s}{yy}_ws_x_l"])]
            fo[f"{key}Label"] = [clean(x) for x in fut[f"{s}{yy}_ws_x_l"]]
            props += [f"{key}Score", f"{key}Label"]
            ffields += [(f"{key}Label", f"Water stress {year} ({desc})", None),
                        (f"{key}Score", f"Water stress score {year} ({desc})", "0–5 score")]
    write_geojson(fo, out_dir / "aqueduct_future.geojson", props)
    print(f"  aqueduct_future: {len(fo)} polygons ({how})")
    entries.append(entry("aqueduct_future", "Aqueduct 4.0 projected water stress", "WATER-06", "polygon",
                         "aqueduct_future.geojson", regions, len(fo), [round(float(x), 5) for x in fo.total_bounds],
                         ffields + [("pfafId", "HydroBASINS level-6 Pfafstetter id", None)],
                         provenance(rec, "model_output"), [
                             "Model projections for 2030/2050/2080 under three scenario pairs; not forecasts of what will happen.",
                             "Projections use HydroBASINS level-6 basins (coarser than the baseline units).",
                             "Scores are null where Aqueduct marks 'Arid and low water use' (scored 5 by Aqueduct, category -1); the label is kept.",
                             "Labels use Aqueduct's future-layer wording, which differs in capitalisation from the baseline labels.",
                         ], name_field="name", category_field="bws2050BauLabel",
                         categories=categories_of(fo.bws2050BauLabel), value_field="bws2050BauScore",
                         value_units="0–5 score"))
    return entries


# --------------------------------------------------------------------------- NET-01 HydroSHEDS
def build_hydrorivers(data: Path, out_dir: Path) -> dict:
    parts = []
    for r in ("arizona", "uk"):
        f = glob.glob(str(data / "raw" / "NET-01" / r / "HydroRIVERS_v10_*_hydrobox.gpkg"))[0]
        g = gpd.read_file(f, where="ORD_STRA >= 3 OR DIS_AV_CMS >= 1")
        parts.append(g)
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326").drop_duplicates("HYRIV_ID")
    tol = 0.001
    out = gpd.GeoDataFrame({"id": g["HYRIV_ID"].astype(str).values},
                           geometry=shapely.simplify(g.geometry.values, tol, preserve_topology=True), crs="EPSG:4326")
    out["hyrivId"] = g["HYRIV_ID"].astype(int).values
    out["nextDown"] = pd.Series([None if int(x) == 0 else int(x) for x in g["NEXT_DOWN"]], dtype=object).values
    out["mainRivId"] = g["MAIN_RIV"].astype(int).values
    out["ordStra"] = g["ORD_STRA"].astype(int).values
    out["disAvCms"] = g["DIS_AV_CMS"].round(3).values
    out["lengthKm"] = g["LENGTH_KM"].round(2).values
    out["uplandSkm"] = g["UPLAND_SKM"].round(1).values
    props = ["hyrivId", "ordStra", "disAvCms", "lengthKm", "uplandSkm", "mainRivId", "nextDown"]
    write_geojson(out, out_dir / "hydrorivers.geojson", props)
    print(f"  hydrorivers: {len(out):,} reaches")
    rec = source(data, "NET-01/uk")
    fields = [("disAvCms", "Long-term average discharge", "m³/s"), ("ordStra", "Strahler order", None),
              ("lengthKm", "Reach length", "km"), ("uplandSkm", "Upstream area", "km²"),
              ("hyrivId", "HydroRIVERS id", None), ("mainRivId", "Main river id (outlet reach)", None),
              ("nextDown", "Next downstream reach id", None)]
    return entry("hydrorivers", "Rivers (HydroRIVERS)", "NET-01", "line", "hydrorivers.geojson", ["arizona", "uk"],
                 len(out), [round(float(x), 5) for x in out.total_bounds], fields, provenance(rec, "model_output"), [
                     "Modelled river network derived from a 15 arc-second DEM; discharge is a long-term (1971–2000) model average, not a gauge reading.",
                     "Small streams were filtered out: only reaches with Strahler order >= 3 or mean discharge >= 1 m³/s are kept.",
                     "Covers the wider hydro boxes (Colorado/Gila/Sonora basins; Great Britain plus all of Ireland), not just the region boxes.",
                     f"Lines simplified with a {tol}° (~100 m) tolerance; reach end points are kept so the network stays connected.",
                     "nextDown is null at a river mouth or sink; a downstream reach may be absent if it was filtered out.",
                 ], value_field="disAvCms", value_units="m³/s")


def build_hydrobasins(data: Path, out_dir: Path) -> dict:
    parts = []
    for r in ("arizona", "uk"):
        f = glob.glob(str(data / "raw" / "NET-01" / r / "hybas_*_lev06_*.gpkg"))[0]
        parts.append(gpd.read_file(f))
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326").drop_duplicates("HYBAS_ID")
    geoms, how = simplify_coverage(shapely.make_valid(g.geometry.values), 0.005)
    out = gpd.GeoDataFrame({"id": g["HYBAS_ID"].astype("int64").astype(str).values}, geometry=geoms, crs="EPSG:4326")
    out["hybasId"] = g["HYBAS_ID"].astype("int64").values
    out["nextDown"] = pd.Series([None if int(x) == 0 else int(x) for x in g["NEXT_DOWN"]], dtype=object).values
    out["subArea"] = g["SUB_AREA"].round(1).values
    out["upArea"] = g["UP_AREA"].round(1).values
    out["pfafId"] = g["PFAF_ID"].astype(int).astype(str).values
    out["endorheic"] = [bool(int(x)) for x in g["ENDO"]]
    out["coastal"] = [bool(int(x)) for x in g["COAST"]]
    props = ["hybasId", "subArea", "upArea", "nextDown", "pfafId", "endorheic", "coastal"]
    write_geojson(out, out_dir / "hydrobasins_l6.geojson", props)
    print(f"  hydrobasins_l6: {len(out)} basins ({how})")
    rec = source(data, "NET-01/uk")
    fields = [("subArea", "Basin area", "km²"), ("upArea", "Upstream area incl. this basin", "km²"),
              ("hybasId", "HydroBASINS id", None), ("nextDown", "Next downstream basin id", None),
              ("pfafId", "Pfafstetter code", None), ("endorheic", "Endorheic (inland sink)", None),
              ("coastal", "Coastal basin", None)]
    return entry("hydrobasins_l6", "River basins, level 6 (HydroBASINS)", "NET-01", "polygon", "hydrobasins_l6.geojson",
                 ["arizona", "uk"], len(out), [round(float(x), 5) for x in out.total_bounds], fields,
                 provenance(rec, "model_output"), [
                     "Modelled basin boundaries derived from a 15 arc-second DEM; level 6 basins are a few thousand km² each.",
                     "Whole basins touching the hydro boxes are kept, so the layer extends beyond the region boxes.",
                     "Simplified (~500 m) with shared borders preserved; not suitable for parcel-scale decisions.",
                 ])


# --------------------------------------------------------------------------- IND-07 NESO
def build_neso(data: Path, out_dir: Path) -> dict:
    d = data / "raw" / "IND-07" / "uk"
    snaps = []
    for f in sorted(d.glob("regional_*.json")):
        x = json.loads(f.read_text())["data"][0]
        snaps.append((x["from"], f.name, x))
    frm, fname, latest = max(snaps)
    regions = [{
        "regionId": r["regionid"], "shortname": r["shortname"], "dnoregion": r["dnoregion"],
        "forecast": r["intensity"].get("forecast"), "index": r["intensity"].get("index"),
        "aggregate": r["shortname"] in ("England", "Scotland", "Wales", "GB"),
        "generationMix": [{"fuel": m["fuel"], "perc": m["perc"]} for m in r["generationmix"]],
    } for r in latest["regions"]]
    national = None
    gi = sorted(d.glob("intensity_*.json"))
    gg = sorted(d.glob("generation_*.json"))
    if gi:
        ser = json.loads(gi[-1].read_text())["data"]
        gen = json.loads(gg[-1].read_text())["data"] if gg else []
        mix: dict[str, list[float]] = collections.defaultdict(list)
        for row in gen:
            for m in row["generationmix"]:
                mix[m["fuel"]].append(m["perc"])
        act = [s["intensity"]["actual"] for s in ser if s["intensity"].get("actual") is not None]
        national = {
            "from": ser[0]["from"], "to": ser[-1]["to"], "source": gi[-1].name,
            "note": "Great Britain national half-hourly series for a different period than the regional snapshot.",
            "actualMean": round(sum(act) / len(act), 1) if act else None,
            "actualMin": min(act) if act else None, "actualMax": max(act) if act else None,
            "generationMixMean": [{"fuel": k, "perc": round(sum(v) / len(v), 1)} for k, v in mix.items()],
            "series": [{"from": s["from"], "forecast": s["intensity"].get("forecast"),
                        "actual": s["intensity"].get("actual"), "index": s["intensity"].get("index")} for s in ser],
        }
    doc = {"from": latest["from"], "to": latest["to"], "source": fname, "units": "gCO2/kWh",
           "regions": regions, "national": national}
    (out_dir / "neso_carbon_intensity.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    print(f"  neso_carbon_intensity: {len(regions)} regions, snapshot {latest['from']}–{latest['to']} ({fname})")
    rec = source(data, "IND-07/uk")
    fields = [("forecast", "Carbon intensity (forecast)", "gCO2/kWh"), ("index", "Intensity band", None),
              ("generationMix", "Generation mix", "%"), ("dnoregion", "Distribution network operator", None)]
    return entry("neso_carbon_intensity", "GB grid carbon intensity by region (NESO)", "IND-07", "table",
                 "neso_carbon_intensity.json", ["uk"], len(regions), [-8.65, 49.86, 1.77, 60.86], fields,
                 provenance(rec, "model_output"), [
                     f"One half-hour regional snapshot ({latest['from']} to {latest['to']}); values change every 30 minutes.",
                     "Regional values are NESO forecasts (no regional actuals), modelled from the generation mix and flows.",
                     "Great Britain only: Northern Ireland is a separate grid and is not covered.",
                     "Regions 15-18 (England, Scotland, Wales, GB) are aggregates of the 14 DNO regions (aggregate: true).",
                     "The 'national' block is a 1–14 Oct 2025 half-hourly series, not the same period as the snapshot.",
                     "Regions are DNO licence areas; there are no polygons in this file, so join by regionId or shortname.",
                 ], name_field="shortname", category_field="index",
                 categories=categories_of(r["index"] for r in regions), value_field="forecast", value_units="gCO2/kWh")


BUILDERS = {
    "mrds": build_mrds, "tri_facilities": build_tri, "wqp_sites": build_wqp, "nsta_wellbores": build_nsta,
    "aqueduct": build_aqueduct, "hydrorivers": build_hydrorivers, "hydrobasins_l6": build_hydrobasins,
    "neso_carbon_intensity": build_neso,
}
ORDER = ["mrds", "tri_facilities", "wqp_sites", "nsta_wellbores", "aqueduct_baseline", "aqueduct_future",
         "hydrorivers", "hydrobasins_l6", "neso_carbon_intensity"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layers", default=",".join(BUILDERS), help=f"comma list of {', '.join(BUILDERS)}")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    data = Path(a.data)
    out_dir = data / "prepared" / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path = out_dir / "manifest.json"
    layers = {l["id"]: l for l in json.loads(man_path.read_text())["layers"]} if man_path.exists() else {}
    for name in a.layers.split(","):
        print(name, flush=True)
        res = BUILDERS[name.strip()](data, out_dir)
        for e in res if isinstance(res, list) else [res]:
            layers[e["id"]] = e
    ordered = [layers[k] for k in ORDER if k in layers] + [v for k, v in layers.items() if k not in ORDER]
    man_path.write_text(json.dumps({"generatedAt": now_iso(), "layers": ordered}, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"manifest: {len(ordered)} layers -> {man_path}")
