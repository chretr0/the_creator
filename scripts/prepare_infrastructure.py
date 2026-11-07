"""Prepare the OSM-derived datacenter and dam layers bundled with God's Eye View.

Reads the GeoJSON Lines snapshots from a local gods-eye-view checkout and writes normalised
FeatureCollections plus a provenance manifest to data/prepared/infrastructure/.

    cd backend && uv run python ../scripts/prepare_infrastructure.py ../../gods-eye-view

What this does and does not claim:
- Ownership fields are copied from OSM tags. `operator` (who runs the site) and `owner` (who
  owns it) are kept separate; neither is filled in from the other.
- Power values are *capacity* ratings as tagged (kW), never consumption. A data-centre
  `data_center:power` tag is a rated capacity, a `generator:output:electricity` tag on a data
  centre is an on-site generator rating, and a dam's `plant:output:electricity` is nameplate
  generation capacity. Values that cannot be parsed stay null with the raw text kept.
- No consumption (kWh, m³) is reported by this source. Those fields are written as null.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import h3

RESOLUTION = 6
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "prepared" / "infrastructure"

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


def main(gev_root: Path) -> None:
    data = gev_root / "src" / "data" / "local_data"
    sources = {
        "datacenters": data / "datacenters" / "datacenters.geojsonl",
        "dams": data / "dams" / "dams.geojsonl",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    commit = git_commit(gev_root)
    manifest_layers = []

    for layer, path in sources.items():
        features = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = normalise(json.loads(line), layer)
                if f:
                    features.append(f)

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

        # Facilities-per-company counts (within this dataset only).
        counts: dict[str, int] = {}
        for f in features:
            k = company_key(f["properties"])
            if k:
                counts[k] = counts.get(k, 0) + 1
        for f in features:
            k = company_key(f["properties"])
            f["properties"]["companyKey"] = k
            f["properties"]["companyFacilityCount"] = counts.get(k) if k else None

        out = OUT_DIR / f"{layer}.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")))

        props = [f["properties"] for f in features]
        stats = {
            "features": len(features),
            "withOperator": sum(1 for p in props if p["operator"]),
            "withOwner": sum(1 for p in props if p["owner"]),
            "withPowerRating": sum(1 for p in props if p["powerRatings"]),
            "withParsedPowerRatingKw": sum(1 for p in props if any(r["kw"] is not None for r in p["powerRatings"])),
            "withConsumption": 0,
        }
        print(f"{layer}: {stats}")
        manifest_layers.append({"id": layer, "file": out.name, "stats": stats})

    manifest = {
        "id": "INFRA-OSM-GEV",
        "provider": "OpenStreetMap contributors (via the gods-eye-view bundled snapshot)",
        "product": "OSM telecom=data_center and dam features",
        "upstream": {
            "repository": "https://github.com/bilawalsidhu/gods-eye-view",
            "commit": commit,
            "paths": ["src/data/local_data/datacenters/", "src/data/local_data/dams/"],
            "notes": [
                "Original OSM extraction date and query were not recorded by the upstream snapshot.",
                "Dams were extracted by upstream from OpenInfraMap/PostGIS layers (waterway=dam, man_made=dam, building=dam).",
                "Upstream removed contact tags (email, phone, fax) before release.",
            ],
        },
        "licence": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors (ODbL). Dams also credit Open Infrastructure Map.",
        "evidenceType": "reported_record",
        "spatialSupport": "OSM building footprint polygon or point; representative point = outer-ring vertex average",
        "retrievedAt": dt.date.today().isoformat(),
        "observationPeriod": None,
        "limitations": [
            "Coverage is whatever OSM volunteers mapped; absence of a facility is not evidence it does not exist.",
            "operator and owner are free-text OSM tags and may be stale, abbreviated or a brand rather than the legal entity.",
            "Power values are tagged capacity ratings (kW), not measured consumption or generation.",
            "No electricity or water consumption is reported by this source.",
        ],
        "simulationResolution": RESOLUTION,
        "layers": manifest_layers,
    }
    (OUT_DIR / "source.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_DIR}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: prepare_infrastructure.py <path-to-gods-eye-view>")
    main(Path(sys.argv[1]).resolve())
