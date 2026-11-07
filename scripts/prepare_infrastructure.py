"""Prepare the infrastructure layers served by /api/infrastructure.

Layers (all written to data/prepared/infrastructure/, with per-source provenance in source.json):

- datacenters, dams     OSM features bundled with God's Eye View (--gev <checkout>)
- power_plants          WRI Global Power Plant Database v1.3 (CC BY 4.0), global
- substations,          OSM power=substation / power=line|cable at >= 66 kV, from the raw Overpass tiles in
  transmission_lines    data/raw/GRID-OSM/<region>/ (scripts/prepare_power_grid.py --fetch), prepared regions only
- airports              OurAirports, large and medium airports (public domain), global
- ports                 Natural Earth 1:10m ports (public domain), global

    uv run --no-project --with h3 --with pyshp python -I scripts/prepare_infrastructure.py [--gev ../gods-eye-view] [--fetch]

Without --gev the existing datacenter and dam files are kept as they are.

What this does and does not claim:
- Ownership fields are copied from the source. `operator` (who runs the site) and `owner` (who
  owns it) are kept separate; neither is filled in from the other.
- Power values are *capacity* ratings as tagged (kW), never consumption. A data-centre
  `data_center:power` tag is a rated capacity, a `generator:output:electricity` tag on a data
  centre is an on-site generator rating, and a dam's `plant:output:electricity` is nameplate
  generation capacity. Values that cannot be parsed stay null with the raw text kept.
- No consumption (kWh, m³) is reported by these sources. Those fields are written as null.
- Voltages are OSM tags; a line or substation voltage is not spare capacity.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import subprocess
from pathlib import Path

import h3

RESOLUTION = 6
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "prepared" / "infrastructure"
RAW_DIR = ROOT / "data" / "raw"

# tag -> (meaning shown to users, whether it is a load-side or supply-side rating)
DATACENTER_POWER_TAGS = {
    "capacity:it_load": "Rated IT load capacity",
    "data_center:power": "Rated power capacity (basis not stated: IT or whole facility)",
    "plant:input:electricity": "Rated electrical input capacity",
    "power": "Power capacity (free-text tag)",
    "capacity": "Capacity (free-text tag; unit may not be power)",
    "generator:output:electricity": "On-site generator rating (backup/onsite supply, not consumption)",
}
DAM_POWER_TAGS = {
    "plant:output:electricity": "Nameplate generation capacity",
    "generator:output:electricity": "Generator nameplate capacity",
}

FREE_TEXT_TAGS = {"power", "capacity"}

UNIT_TO_KW ={"w": 1e-3, "kw": 1.0, "mw": 1e3, "gw": 1e6}
POWER_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(w|kw|mw|gw)\s*$", re.IGNORECASE)


def parse_kw(raw: str | None) -> float | None:
    """'77.4MW' -> 77400.0. Anything not an unambiguous number+unit returns None."""
    if not raw:
        return None
    m = POWER_RE.match(str(raw))
    if not m:
        return None
    return round(float(m.group(1).replace(",", ".")) * UNIT_TO_KW[m.group(2).lower()], 3)


def parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(m)?\s*$", str(raw))
    return float(m.group(1)) if m else None


def text(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s if s and s.lower() not in ("undefined", "null") else None


def round_coords(coords, nd=6):
    if isinstance(coords, (int, float)):
        return round(coords, nd)
    return [round_coords(c, nd) for c in coords]


def representative_point(geometry: dict) -> tuple[float, float] | None:
    """Vertex average of the outer ring (same rule as gods-eye-view featurePoint)."""
    t, c = geometry.get("type"), geometry.get("coordinates")
    ring = (
        [c] if t == "Point"
        else c if t == "LineString"
        else c[0] if t == "Polygon"
        else c[0][0] if t == "MultiPolygon"
        else None
    )
    if not ring:
        return None
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lon, lat


def osm_ref(osm_id, geometry_type: str) -> dict:
    """OSM element reference. The element type is inferred from the import convention
    (negative IDs are relations; points are nodes; other positive IDs are ways)."""
    if not isinstance(osm_id, int):
        return {"id": None, "type": None, "url": None}
    if osm_id < 0:
        kind, ident = "relation", -osm_id
    elif geometry_type == "Point":
        kind, ident = "node", osm_id
    else:
        kind, ident = "way", osm_id
    return {"id": ident, "type": kind, "url": f"https://www.openstreetmap.org/{kind}/{ident}"}


def power_ratings(tags: dict, catalogue: dict[str, str], extra: dict | None = None) -> list[dict]:
    out = []
    for tag, meaning in catalogue.items():
        raw = text(tags.get(tag)) or (text(extra.get(tag)) if extra else None)
        # Generic tags such as power=substation describe the feature, not a rating; keep them only
        # when they parse as a power quantity.
        if raw and (tag not in FREE_TEXT_TAGS or parse_kw(raw) is not None):
            out.append({"tag": tag, "meaning": meaning, "raw": raw, "kw": parse_kw(raw)})
    return out


def normalise(feature: dict, layer: str) -> dict | None:
    geometry = feature.get("geometry") or {}
    point = representative_point(geometry)
    if point is None:
        return None
    lon, lat = point
    props = feature.get("properties") or {}
    tags = props.get("tags") or {}

    name = text(props.get("name")) or text(tags.get("name")) or text(tags.get("name:en")) or text(tags.get("official_name"))
    osm = osm_ref(props.get("osm_id", feature.get("id")), geometry.get("type", ""))

    record = {
        "layer": layer,
        "name": name,
        "nameEn": text(tags.get("name:en")),
        "operator": text(tags.get("operator")),
        "operatorShort": text(tags.get("operator:short")),
        "operatorWikidata": text(tags.get("operator:wikidata")) or text(tags.get("wikidata:operator")),
        "owner": text(tags.get("owner")),
        "ownerWikidata": text(tags.get("owner:wikidata")),
        "lon": round(lon, 6),
        "lat": round(lat, 6),
        "h3Id": h3.latlng_to_cell(lat, lon, RESOLUTION),
        "osmId": osm["id"],
        "osmType": osm["type"],
        "osmUrl": osm["url"],
        "startDate": text(tags.get("start_date")),
        "website": text(tags.get("website")) or text(tags.get("contact:website")),
        "heightM": parse_number(tags.get("height")),
        "levels": parse_number(tags.get("building:levels")),
        # No consumption is reported in this source. Kept explicit so the UI shows "not reported".
        "electricityConsumptionKwhPerYear": None,
        "waterConsumptionM3PerYear": None,
    }
    if layer == "datacenters":
        record["powerRatings"] = power_ratings(tags, DATACENTER_POWER_TAGS)
    else:
        record["powerRatings"] = power_ratings(tags, DAM_POWER_TAGS, {"plant:output:electricity": props.get("output")})
        record["river"] = text(tags.get("associated_river")) or text(tags.get("river")) or text(tags.get("river:name"))
        record["plantSource"] = text(tags.get("plant:source")) or text(props.get("source"))

    return {
        "type": "Feature",
        "id": f"{layer}:{osm['type']}/{osm['id']}",
        "geometry": {"type": geometry["type"], "coordinates": round_coords(geometry["coordinates"])},
        "properties": record,
    }


def company_key(p: dict) -> str | None:
    """Grouping key for 'facilities by the same company': Wikidata QID when tagged, else name."""
    qid = p.get("operatorWikidata") or p.get("companyKeyInferred")
    if qid:
        return qid
    op = p.get("operator")
    return op.casefold() if op else None


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None




def assign_companies(features: list[dict]) -> None:
    """Group facilities by company within one layer and count facilities per company."""
    # Name-only records join the Wikidata group that uses the same operator name, so "CyrusOne"
    # with and without operator:wikidata count as one company.
    qid_by_name: dict[str, dict[str, int]] = {}
    for f in features:
        p = f["properties"]
        if p["operatorWikidata"] and p["operator"]:
            d = qid_by_name.setdefault(p["operator"].casefold(), {})
            d[p["operatorWikidata"]] = d.get(p["operatorWikidata"], 0) + 1
    for f in features:
        p = f["properties"]
        if not p["operatorWikidata"] and p["operator"] and p["operator"].casefold() in qid_by_name:
            d = qid_by_name[p["operator"].casefold()]
            p["companyKeyInferred"] = max(d, key=d.get)

    counts: dict[str, int] = {}
    for f in features:
        k = company_key(f["properties"])
        if k:
            counts[k] = counts.get(k, 0) + 1
    for f in features:
        p = f["properties"]
        k = company_key(p)
        p.pop("companyKeyInferred", None)
        p["companyKey"] = k
        p["companyFacilityCount"] = counts.get(k) if k else None


def base_record(layer: str, lon: float, lat: float, **kw) -> dict:
    """The fields every infrastructure record carries; unknown values stay null."""
    record = {
        "layer": layer,
        "name": None,
        "nameEn": None,
        "operator": None,
        "operatorShort": None,
        "operatorWikidata": None,
        "owner": None,
        "ownerWikidata": None,
        "lon": round(lon, 6),
        "lat": round(lat, 6),
        "h3Id": h3.latlng_to_cell(lat, lon, RESOLUTION),
        "osmId": None,
        "osmType": None,
        "osmUrl": None,
        "startDate": None,
        "website": None,
        "heightM": None,
        "levels": None,
        "powerRatings": [],
    }
    record.update(kw)
    return record


# Always written, even when null, so every record says what it does not know.
ALWAYS_KEPT = {"layer", "lon", "lat", "h3Id", "operator", "owner"}


def compact(props: dict) -> dict:
    """Drop null/empty fields to keep the big layers small; the frontend fills them back as null.
    (Datacenters and dams keep the full record for backwards compatibility.)"""
    return {k: v for k, v in props.items() if k in ALWAYS_KEPT or v not in (None, [], "")}


def write_layer(layer: str, features: list[dict], source_id: str, extra_stats: dict | None = None, **meta) -> dict:
    props = [f["properties"] for f in features]
    stats = {
        "features": len(features),
        "withOperator": sum(1 for p in props if p.get("operator")),
        "withOwner": sum(1 for p in props if p.get("owner")),
        "withPowerRating": sum(1 for p in props if p.get("powerRatings") or p.get("capacityMw")),
        "withParsedPowerRatingKw": sum(
            1 for p in props if p.get("capacityMw") or any(r["kw"] is not None for r in p.get("powerRatings", []))
        ),
        "withConsumption": 0,
        **(extra_stats or {}),
    }
    if layer not in ("datacenters", "dams"):
        features = [{**f, "properties": compact(f["properties"])} for f in features]
    out = OUT_DIR / f"{layer}.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")))
    print(f"{layer}: {stats} ({out.stat().st_size / 1e6:.1f} MB)")
    return {"id": layer, "file": out.name, "source": source_id, "stats": stats, **meta}


def sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, path: Path) -> None:
    import urllib.request

    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "the-creator-prepare-infrastructure/0.2"})
    with urllib.request.urlopen(req, timeout=120) as r:
        path.write_bytes(r.read())
    print(f"downloaded {url} -> {path} ({path.stat().st_size / 1e6:.1f} MB)")


def write_raw_source(path: Path, record: dict) -> None:
    (path.parent / "source.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")


# --- Datacenters and dams (OSM, via the gods-eye-view snapshot) -----------------------------------

GEV_SOURCE = {
    "id": "INFRA-OSM-GEV",
    "name": "OSM datacenters and dams",
    "provider": "OpenStreetMap contributors (via the gods-eye-view bundled snapshot)",
    "product": "OSM telecom=data_center and dam features",
    "licence": "ODbL-1.0",
    "licenceUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
    "attribution": "© OpenStreetMap contributors (ODbL). Dams also credit Open Infrastructure Map.",
    "evidenceType": "reported_record",
    "spatialSupport": "OSM building footprint polygon or point; representative point = outer-ring vertex average",
    "observationPeriod": None,
    "limitations": [
        "Coverage is whatever OSM volunteers mapped; absence of a facility is not evidence it does not exist.",
        "operator and owner are free-text OSM tags and may be stale, abbreviated or a brand rather than the legal entity.",
        "Power values are tagged capacity ratings (kW), not measured consumption or generation.",
        "No electricity or water consumption is reported by this source.",
    ],
}


def build_gev(gev_root: Path) -> tuple[list[dict], dict]:
    data = gev_root / "src" / "data" / "local_data"
    sources = {
        "datacenters": data / "datacenters" / "datacenters.geojsonl",
        "dams": data / "dams" / "dams.geojsonl",
    }
    entries = []
    for layer, path in sources.items():
        features = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = normalise(json.loads(line), layer)
                if f:
                    features.append(f)
        assign_companies(features)
        entries.append(write_layer(layer, features, GEV_SOURCE["id"], scope="global"))
    source = {
        **GEV_SOURCE,
        "retrievedAt": dt.date.today().isoformat(),
        "upstream": {
            "repository": "https://github.com/bilawalsidhu/gods-eye-view",
            "commit": git_commit(gev_root),
            "paths": ["src/data/local_data/datacenters/", "src/data/local_data/dams/"],
            "notes": [
                "Original OSM extraction date and query were not recorded by the upstream snapshot.",
                "Dams were extracted by upstream from OpenInfraMap/PostGIS layers (waterway=dam, man_made=dam, building=dam).",
                "Upstream removed contact tags (email, phone, fax) before release.",
            ],
        },
    }
    return entries, source


# --- Power plants (WRI Global Power Plant Database) -------------------------------------------------

GPPD_URL = "https://wri-dataportal-prod.s3.amazonaws.com/manual/global_power_plant_database_v_1_3.zip"
GPPD_ZIP = RAW_DIR / "INFRA-GPPD" / "global_power_plant_database_v_1_3.zip"


def build_power_plants(fetch: bool) -> tuple[list[dict], dict]:
    import csv
    import io
    import zipfile

    if fetch or not GPPD_ZIP.exists():
        download(GPPD_URL, GPPD_ZIP)
        write_raw_source(GPPD_ZIP, {
            "id": "INFRA-GPPD", "url": GPPD_URL, "file": GPPD_ZIP.name, "sha256": sha256(GPPD_ZIP),
            "licence": "CC BY 4.0", "retrievedAt": dt.date.today().isoformat(), "region": "global",
        })
    with zipfile.ZipFile(GPPD_ZIP) as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("global_power_plant_database.csv"), encoding="utf-8")))

    def num(v):
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    features = []
    for r in rows:
        lat, lon = num(r["latitude"]), num(r["longitude"])
        if lat is None or lon is None:
            continue
        mw = num(r["capacity_mw"])
        # Latest reported generation, else WRI's modelled estimate (flagged as such).
        gen = None
        for year in range(2019, 2012, -1):
            v = num(r.get(f"generation_gwh_{year}"))
            if v is not None and v >= 0:
                gen = {"gwh": round(v, 2), "year": year, "estimated": False}
                break
        if gen is None:
            for year in range(2017, 2012, -1):
                v = num(r.get(f"estimated_generation_gwh_{year}"))
                if v is not None and v >= 0:
                    gen = {"gwh": round(v, 2), "year": year, "estimated": True}
                    break
        year = num(r["commissioning_year"])
        other = [r[k] for k in ("other_fuel1", "other_fuel2", "other_fuel3") if r.get(k)]
        props = base_record(
            "power_plants", lon, lat,
            name=text(r["name"]),
            owner=text(r["owner"]),
            startDate=str(int(year)) if year else None,
            # Nameplate MW; the frontend shows it as a "Nameplate generation capacity" rating.
            capacityMw=mw if mw and mw > 0 else None,
            kind=text(r["primary_fuel"]),
            otherFuels=other or None,
            generation=gen,
            recordId=r["gppd_idnr"],
            recordSource=text(r["source"]),
            recordUrl=text(r["url"]),
        )
        features.append({
            "type": "Feature",
            "id": f"power_plants:{r['gppd_idnr']}",
            "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
            "properties": props,
        })
    # GPPD only has owners; group by owner name so "show all from this company" works.
    for f in features:
        p = f["properties"]
        p["companyKeyInferred"] = p["owner"].casefold() if p["owner"] else None
    assign_companies(features)
    fuels: dict[str, int] = {}
    for f in features:
        k = f["properties"]["kind"] or "Unknown"
        fuels[k] = fuels.get(k, 0) + 1
    entry = write_layer("power_plants", features, "INFRA-GPPD", {"withGeneration": sum(1 for f in features if f["properties"]["generation"])},
                        scope="global", kinds=dict(sorted(fuels.items(), key=lambda kv: -kv[1])))
    source = {
        "id": "INFRA-GPPD",
        "name": "Global Power Plant Database",
        "provider": "World Resources Institute (WRI) and partners",
        "product": "Global Power Plant Database v1.3.0",
        "licence": "CC BY 4.0",
        "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Global Energy Observatory, Google, KTH Royal Institute of Technology, Enipedia, World Resources Institute. "
                       "Global Power Plant Database v1.3.0 (2021). Published on Resource Watch and Google Earth Engine.",
        "evidenceType": "reported_record",
        "spatialSupport": "Plant location point as reported",
        "retrievedAt": dt.date.today().isoformat(),
        "observationPeriod": "Capacity as of ~2019-2020; generation 2013-2019",
        "url": "https://datasets.wri.org/dataset/globalpowerplantdatabase",
        "limitations": [
            "Last updated June 2021 and no longer maintained: newer plants are missing and some listed plants may have closed.",
            "Covers ~35,000 plants; small distributed generation (rooftop solar, small diesel) is largely absent.",
            "Capacity is nameplate (MW), not available or dispatched output.",
            "Generation figures are annual totals; 'estimated' values come from WRI's model, not metered data.",
            "Owner is as reported by the source database and may be out of date.",
        ],
    }
    return [entry], source


# --- Airports (OurAirports) ---------------------------------------------------------------------------

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV = RAW_DIR / "INFRA-OURAIRPORTS" / "airports.csv"
AIRPORT_KIND = {"large_airport": "Large airport", "medium_airport": "Medium airport"}


def build_airports(fetch: bool) -> tuple[list[dict], dict]:
    import csv

    if fetch or not AIRPORTS_CSV.exists():
        download(AIRPORTS_URL, AIRPORTS_CSV)
        write_raw_source(AIRPORTS_CSV, {
            "id": "INFRA-OURAIRPORTS", "url": AIRPORTS_URL, "file": AIRPORTS_CSV.name, "sha256": sha256(AIRPORTS_CSV),
            "licence": "Public domain", "retrievedAt": dt.date.today().isoformat(), "region": "global",
        })
    features = []
    with AIRPORTS_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["type"] not in AIRPORT_KIND:
                continue
            try:
                lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
            except ValueError:
                continue
            elev = parse_number(r["elevation_ft"])
            props = base_record(
                "airports", lon, lat,
                name=text(r["name"]),
                website=text(r["home_link"]) or text(r["wikipedia_link"]),
                kind=AIRPORT_KIND[r["type"]],
                iata=text(r["iata_code"]),
                icao=text(r["icao_code"]) or text(r["gps_code"]),
                municipality=text(r["municipality"]),
                scheduledService=r["scheduled_service"] == "yes",
                elevationM=round(elev * 0.3048) if elev is not None else None,
                recordId=r["ident"],
            )
            features.append({
                "type": "Feature",
                "id": f"airports:{r['ident']}",
                "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
                "properties": props,
            })
    assign_companies(features)
    kinds: dict[str, int] = {}
    for f in features:
        kinds[f["properties"]["kind"]] = kinds.get(f["properties"]["kind"], 0) + 1
    entry = write_layer("airports", features, "INFRA-OURAIRPORTS", scope="global", kinds=kinds)
    source = {
        "id": "INFRA-OURAIRPORTS",
        "name": "OurAirports",
        "provider": "OurAirports (David Megginson and contributors)",
        "product": "OurAirports airports.csv, large and medium airports only",
        "licence": "Public domain",
        "licenceUrl": "https://ourairports.com/data/",
        "attribution": "Airports: OurAirports (public domain)",
        "evidenceType": "reported_record",
        "spatialSupport": "Airport reference point",
        "retrievedAt": dt.date.today().isoformat(),
        "observationPeriod": None,
        "url": "https://ourairports.com/data/",
        "limitations": [
            "Community-maintained; size class (large/medium) is OurAirports' own classification, not traffic data.",
            "Small airfields, heliports, seaplane bases and closed airports are left out.",
            "No passenger, cargo or runway capacity figures are included.",
        ],
    }
    return [entry], source


# --- Seaports (Natural Earth) -----------------------------------------------------------------------

PORTS_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_ports.zip"
PORTS_ZIP = RAW_DIR / "INFRA-NE-PORTS" / "ne_10m_ports.zip"


def build_ports(fetch: bool) -> tuple[list[dict], dict]:
    import io
    import zipfile

    import shapefile  # pyshp

    if fetch or not PORTS_ZIP.exists():
        download(PORTS_URL, PORTS_ZIP)
        write_raw_source(PORTS_ZIP, {
            "id": "INFRA-NE-PORTS", "url": PORTS_URL, "file": PORTS_ZIP.name, "sha256": sha256(PORTS_ZIP),
            "licence": "Public domain", "retrievedAt": dt.date.today().isoformat(), "region": "global",
        })
    with zipfile.ZipFile(PORTS_ZIP) as z:
        reader = shapefile.Reader(
            shp=io.BytesIO(z.read("ne_10m_ports.shp")),
            shx=io.BytesIO(z.read("ne_10m_ports.shx")),
            dbf=io.BytesIO(z.read("ne_10m_ports.dbf")),
            encoding="utf-8",
        )
        fields = [f[0] for f in reader.fields[1:]]
        features = []
        for i, sr in enumerate(reader.iterShapeRecords()):
            rec = dict(zip(fields, sr.record))
            if not sr.shape.points:
                continue
            lon, lat = sr.shape.points[0]
            scale = rec.get("natlscale")
            props = base_record(
                "ports", lon, lat,
                name=text(rec.get("name")),
                website=text(rec.get("website")),
                kind="Major port" if scale and scale >= 30 else "Port",
                rank=int(scale) if scale else None,
                recordId=str(i),
            )
            features.append({
                "type": "Feature",
                "id": f"ports:{i}",
                "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
                "properties": props,
            })
    assign_companies(features)
    entry = write_layer("ports", features, "INFRA-NE-PORTS", scope="global")
    source = {
        "id": "INFRA-NE-PORTS",
        "name": "Natural Earth ports",
        "provider": "Natural Earth",
        "product": "Natural Earth 1:10m cultural vectors, ports (v5)",
        "licence": "Public domain",
        "licenceUrl": "https://www.naturalearthdata.com/about/terms-of-use/",
        "attribution": "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com.",
        "evidenceType": "reference_map",
        "spatialSupport": "Port point at cartographic scale (may be offset from the actual terminals)",
        "retrievedAt": dt.date.today().isoformat(),
        "observationPeriod": None,
        "url": "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/ports/",
        "limitations": [
            "A cartographic selection of ~1,000 notable ports, not a complete register of harbours or terminals.",
            "'Major port' means a higher Natural Earth display rank, not measured throughput.",
            "No cargo, berth, draught or operator information.",
        ],
    }
    return [entry], source


# --- Electricity grid: high-voltage lines and substations (OSM, prepared regions) --------------------

GRID_RAW = RAW_DIR / "GRID-OSM"
GRID_REGIONS = {"arizona": (-113.5, 31.3, -109.0, 34.5), "uk": (-8.7, 49.8, 1.9, 60.9)}
GRID_MIN_KV = 66.0
SIMPLIFY_DEG = 0.0003  # ~30 m


def parse_kv_list(raw) -> list[float]:
    return sorted({int(p) / 1000 for p in str(raw or "").split(";") if p.strip().isdigit()}, reverse=True)


def simplify(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker in degrees (display simplification only)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        best, idx = 0.0, None
        for i in range(a + 1, b):
            x, y = points[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm if norm else ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def osm_tags_record(layer: str, lon: float, lat: float, el: dict, t: dict, **kw) -> dict:
    return base_record(
        layer, lon, lat,
        name=text(t.get("name:en")) or text(t.get("name")),
        nameEn=text(t.get("name:en")),
        operator=text(t.get("operator")),
        operatorShort=text(t.get("operator:short")),
        operatorWikidata=text(t.get("operator:wikidata")),
        owner=text(t.get("owner")),
        ownerWikidata=text(t.get("owner:wikidata")),
        osmId=el["id"],
        osmType=el["type"],
        osmUrl=f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        startDate=text(t.get("start_date")),
        **kw,
    )


def build_grid() -> tuple[list[dict], dict]:
    lines, subs = [], []
    regions_used, retrieved = [], []
    for region, (w, s, e, n) in GRID_REGIONS.items():
        tiles = sorted((GRID_RAW / region).glob("tile_*.json"))
        if not tiles:
            print(f"grid: no raw tiles for {region}; run scripts/prepare_power_grid.py --fetch")
            continue
        regions_used.append(region)
        src = GRID_RAW / region / "source.json"
        if src.exists():
            retrieved.append(json.loads(src.read_text()).get("retrievedAt"))
        seen: set[tuple[str, int]] = set()
        for path in tiles:
            for el in json.loads(path.read_text()).get("elements", []):
                key = (el["type"], el["id"])
                if key in seen:
                    continue
                seen.add(key)
                t = el.get("tags", {})
                kind = t.get("power")
                kv = parse_kv_list(t.get("voltage"))
                if not kv or kv[0] < GRID_MIN_KV:
                    continue
                if kind in ("line", "cable"):
                    pts = [(p["lon"], p["lat"]) for p in el.get("geometry") or [] if p]
                    if len(pts) < 2:
                        continue
                    pts = simplify(pts, SIMPLIFY_DEG)
                    mid = pts[len(pts) // 2] if len(pts) > 2 else ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
                    length = sum(
                        math.hypot((x2 - x1) * 111.32 * math.cos(math.radians((y1 + y2) / 2)), (y2 - y1) * 110.57)
                        for (x1, y1), (x2, y2) in zip(pts, pts[1:])
                    )
                    circuits = parse_number(t.get("circuits"))
                    props = osm_tags_record(
                        "transmission_lines", mid[0], mid[1], el, t,
                        kind="Underground/submarine cable" if kind == "cable" else "Overhead line",
                        voltageKv=kv,
                        circuits=int(circuits) if circuits else None,
                        lengthKm=round(length, 2),
                        region=region,
                    )
                    lines.append({
                        "type": "Feature",
                        "id": f"transmission_lines:{el['type']}/{el['id']}",
                        "geometry": {"type": "LineString", "coordinates": round_coords([list(p) for p in pts], 5)},
                        "properties": props,
                    })
                elif kind == "substation":
                    c = el.get("center") or el
                    if "lat" not in c or not (s <= c["lat"] <= n and w <= c["lon"] <= e):
                        continue
                    props = osm_tags_record(
                        "substations", c["lon"], c["lat"], el, t,
                        kind=(text(t.get("substation")) or "substation").replace("_", " ").capitalize(),
                        voltageKv=kv,
                        region=region,
                    )
                    subs.append({
                        "type": "Feature",
                        "id": f"substations:{el['type']}/{el['id']}",
                        "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
                        "properties": props,
                    })
    assign_companies(lines)
    assign_companies(subs)
    meta = {"scope": "regions", "regions": regions_used, "minVoltageKv": GRID_MIN_KV}
    entries = [
        write_layer("transmission_lines", lines, "INFRA-GRID-OSM",
                    {"lengthKm": round(sum(f["properties"]["lengthKm"] for f in lines))}, **meta),
        write_layer("substations", subs, "INFRA-GRID-OSM", **meta),
    ]
    source = {
        "id": "INFRA-GRID-OSM",
        "name": "OSM high-voltage grid (prepared regions)",
        "provider": "OpenStreetMap contributors via Overpass API",
        "product": f"OSM power=line/cable and power=substation features at or above {GRID_MIN_KV:g} kV",
        "licence": "ODbL-1.0",
        "licenceUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": "© OpenStreetMap contributors",
        "evidenceType": "reported_record",
        "spatialSupport": "OSM way geometry (simplified ~30 m for display) or substation centre",
        "retrievedAt": min((r for r in retrieved if r), default=dt.date.today().isoformat()),
        "observationPeriod": None,
        "url": "https://wiki.openstreetmap.org/wiki/Power_networks",
        "limitations": [
            f"Prepared for the project regions only ({', '.join(regions_used)}); elsewhere use 'Load OSM power here' on a location.",
            f"Only features tagged with a voltage of {GRID_MIN_KV:g} kV or more; distribution lines and untagged substations are left out.",
            "Volunteer-mapped: routes and voltages may be incomplete or out of date.",
            "Lines show mapped routes, not thermal capacity, spare capacity or connection headroom.",
        ],
    }
    return entries, source


# --- Manifest -----------------------------------------------------------------------------------------

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gev", type=Path, help="gods-eye-view checkout; rebuilds datacenters and dams")
    ap.add_argument("--fetch", action="store_true", help="re-download the power plant, airport and port sources")
    ap.add_argument("--only", nargs="*", choices=["power_plants", "airports", "ports", "grid"],
                    help="rebuild only these (default: all)")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    path = OUT_DIR / "source.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    if old and "sources" not in old:
        # Pre-0.2 manifest: one OSM source at the top level, datacenters + dams only.
        old = {"sources": {old["id"]: {k: v for k, v in old.items() if k not in ("layers", "simulationResolution")}},
               "layers": [{**layer, "source": old["id"], "scope": "global"} for layer in old["layers"]]}
    sources: dict[str, dict] = dict(old.get("sources", {}))
    layers: dict[str, dict] = {layer["id"]: layer for layer in old.get("layers", [])}

    builders = []
    if args.gev:
        builders.append(lambda: build_gev(args.gev.resolve()))
    want = set(args.only or ["power_plants", "airports", "ports", "grid"])
    if "power_plants" in want:
        builders.append(lambda: build_power_plants(args.fetch))
    if "airports" in want:
        builders.append(lambda: build_airports(args.fetch))
    if "ports" in want:
        builders.append(lambda: build_ports(args.fetch))
    if "grid" in want:
        builders.append(build_grid)
    for build in builders:
        entries, source = build()
        sources[source["id"]] = source
        for entry in entries:
            layers[entry["id"]] = entry

    order = ["datacenters", "power_plants", "dams", "substations", "transmission_lines", "airports", "ports"]
    manifest = {
        "id": "INFRA",
        "product": "Prepared infrastructure layers",
        "simulationResolution": RESOLUTION,
        "sources": sources,
        "layers": sorted(layers.values(), key=lambda layer: order.index(layer["id"]) if layer["id"] in order else 99),
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
