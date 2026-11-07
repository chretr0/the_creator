"""Prepare reference layers bundled with God's Eye View: administrative boundaries and submarine cables.

    cd backend && uv run python ../scripts/prepare_reference.py ../../gods-eye-view

Writes:
  data/prepared/boundaries/{countries,admin1,us_counties}.geojson + source.json
  data/prepared/cables/{cables,landing_points}.geojson + source.json

Boundary polygons in the upstream packs are simplified, delta-encoded integer rings (see each
file's meta.schema). They are decoded here to plain GeoJSON. Simplification tolerance is kept in
the provenance: these outlines are for display, region lookup and aggregation, not legal limits.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prepared"


def decode_ring(ring: list[int], decimals: int) -> list[list[float]]:
    scale = 10**decimals
    x, y = ring[0], ring[1]
    pts = [[x / scale, y / scale]]
    for i in range(2, len(ring), 2):
        x += ring[i]
        y += ring[i + 1]
        pts.append([round(x / scale, decimals), round(y / scale, decimals)])
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def decode_polygons(polygons, decimals: int) -> dict:
    parts = [[decode_ring(r, decimals) for r in poly] for poly in polygons]
    parts = [p for p in parts if p and len(p[0]) >= 4]
    return {"type": "MultiPolygon", "coordinates": parts}


def bbox(geometry: dict) -> list[float]:
    xs, ys = [], []
    for poly in geometry["coordinates"]:
        for x, y in poly[0]:
            xs.append(x)
            ys.append(y)
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def write(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")))


def boundaries(gev: Path, commit: str | None) -> None:
    data = gev / "src" / "data" / "local_data"
    specs = {
        "countries": (data / "natural_earth" / "countries.json", "country"),
        "admin1": (data / "natural_earth" / "states_provinces.json", "admin1"),
        "us_counties": (data / "us_census_counties" / "counties.json", "us_county"),
    }
    layers = []
    for layer_id, (path, level) in specs.items():
        raw = json.loads(path.read_text())
        meta = raw["meta"]
        features = []
        for f in raw["features"]:
            # England/Scotland/Wales/Northern Ireland overlap the United Kingdom outline; keep one
            # country per point so lookups and per-country totals are unambiguous.
            if level == "country" and f.get("type") == "Constituent country":
                continue
            geom = decode_polygons(f["polygons"], f.get("d", meta["decimals"]))
            if not geom["coordinates"]:
                continue
            if level == "country":
                rid = f"country:{f.get('iso') or f['name']}"
                props = {"name": f["name"], "country": f.get("country") or f["name"], "iso": f.get("iso"), "iso2": f.get("iso2")}
            elif level == "admin1":
                rid = f"admin1:{f.get('iso') or f['country'] + '/' + f['name']}"
                props = {"name": f.get("nameEn") or f["name"], "country": f["country"], "iso": f.get("iso"), "iso2": f.get("iso2"), "kind": f.get("type")}
            else:
                rid = f"us_county:{f['geoid']}"
                props = {"name": f.get("full") or f["name"], "country": "United States of America", "state": f["state"], "st": f["st"], "geoid": f["geoid"], "iso2": "US"}
            props |= {"id": rid, "level": level, "bbox": bbox(geom)}
            if f.get("label"):
                props["label"] = f["label"]
            features.append({"type": "Feature", "id": rid, "geometry": geom, "properties": props})
        write(OUT / "boundaries" / f"{layer_id}.geojson", features)
        layers.append({
            "id": layer_id,
            "level": level,
            "file": f"{layer_id}.geojson",
            "features": len(features),
            "upstream": {k: meta.get(k) for k in ("title", "source", "url", "sha256", "commit", "license") if meta.get(k)},
            "simplification": meta.get("curation"),
        })
        print(f"boundaries/{layer_id}: {len(features)}")

    manifest = {
        "id": "BOUNDARIES-GEV",
        "provider": "Natural Earth (countries, admin-1); U.S. Census Bureau (counties)",
        "product": "Simplified boundary packs bundled with gods-eye-view",
        "licence": "Public domain",
        "attribution": "Made with Natural Earth · U.S. Census Bureau cartographic boundary files",
        "evidenceType": "reference_geometry",
        "retrievedAt": dt.date.today().isoformat(),
        "upstream": {"repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": commit},
        "limitations": [
            "Outlines are simplified (see simplification tolerances) and are not legal or surveyed boundaries.",
            "Natural Earth reflects de facto control for some disputed areas; check before using for anything jurisdictional.",
            "US counties cover the US and its territories only.",
        ],
        "layers": layers,
    }
    (OUT / "boundaries" / "source.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def cables(gev: Path, commit: str | None) -> None:
    src = gev / "src" / "data" / "local_data" / "telegeography_submarine_cables"
    upstream = json.loads((src / "source.json").read_text())

    cable_features = []
    for f in json.loads((src / "cable-geo.json").read_text())["features"]:
        p = f["properties"]
        cable_features.append({
            "type": "Feature",
            "id": f"cable:{p['feature_id']}",
            "geometry": f["geometry"],
            "properties": {"id": p["id"], "featureId": p["feature_id"], "name": p["name"], "colour": p.get("color"),
                           "url": f"https://www.submarinecablemap.com/submarine-cable/{p['id']}"},
        })
    landing = []
    for f in json.loads((src / "landing-point-geo.json").read_text())["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        landing.append({
            "type": "Feature",
            "id": f"landing:{p['id']}",
            "geometry": f["geometry"],
            "properties": {"id": p["id"], "name": p["name"], "isTbd": bool(p.get("is_tbd")), "lon": lon, "lat": lat,
                           "url": f"https://www.submarinecablemap.com/landing-point/{p['id']}"},
        })
    write(OUT / "cables" / "cables.geojson", cable_features)
    write(OUT / "cables" / "landing_points.geojson", landing)
    print(f"cables: {len(cable_features)} segments, {len(landing)} landing points")

    manifest = {
        "id": "CABLES-TELEGEOGRAPHY",
        "provider": "TeleGeography",
        "product": "Submarine Cable Map public GeoJSON (cable routes and landing points)",
        "licence": "CC BY-NC-SA 3.0",
        "licenceUrl": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
        "attribution": "© TeleGeography — submarinecablemap.com",
        "commercialUse": False,
        "evidenceType": "reported_record",
        "retrievedAt": upstream.get("downloaded_at"),
        "upstream": {"repository": "https://github.com/bilawalsidhu/gods-eye-view", "commit": commit, "files": upstream.get("files")},
        "limitations": [
            "NonCommercial licence: remove this layer (data/prepared/cables) before any commercial use, or license it from TeleGeography.",
            "ShareAlike: redistributed or adapted copies of this data must stay under CC BY-NC-SA 3.0.",
            "Routes are schematic map geometry, not surveyed seabed positions.",
            "Owners, capacity and ready-for-service dates are not in the public GeoJSON (TeleGeography licenses them separately).",
        ],
        "layers": [
            {"id": "cables", "file": "cables.geojson", "features": len(cable_features)},
            {"id": "landing_points", "file": "landing_points.geojson", "features": len(landing)},
        ],
    }
    (OUT / "cables" / "source.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: prepare_reference.py <path-to-gods-eye-view>")
    gev_root = Path(sys.argv[1]).resolve()
    sha = git_commit(gev_root)
    boundaries(gev_root, sha)
    cables(gev_root, sha)
