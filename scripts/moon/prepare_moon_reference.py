"""Prepare the Moon reference layers: landed objects, IAU place names, mare outlines and planned missions.

    cd backend && uv run --with pyshp python ../scripts/moon/prepare_moon_reference.py [--refresh]

pyshp is pulled in for this run only (it is not a backend dependency); shapely comes from the backend
environment. Downloads are cached in data/raw/<SOURCE-ID>/ (gitignored apart from source.json);
--refresh downloads them again.

Inputs (IDs from CLAUDE-Moon-Data-Sources.md):
  MOON-SITE-01  LROC Anthropogenic Objects shapefile (Wagner et al. 2017, updated by LROC)
  MOON-PLACE-01 IAU/USGS Gazetteer of Planetary Nomenclature, Moon centre points
  MOON-PLACE-02 LROC global mare polygons (Nelson et al. 2014)
  MOON-SITE-02  planned missions and Artemis candidate regions, curated below from catalogue §9
  MOON-SITE-06  NASA 2011 lunar heritage recommendations Rev A (the keep-out rule; rings are drawn
                by the backend from the `heritage` property of each site)

Writes (contract: data/prepared/moon/ section of the Moon module brief):
  data/prepared/moon/sites/anthropogenic_objects.geojson
  data/prepared/moon/places/gazetteer.json
  data/prepared/moon/regions/mare.geojson
  data/prepared/moon/missions/planned.geojson
  data/prepared/moon/source.json
  data/raw/MOON-SITE-01/source.json, data/raw/MOON-PLACE-01/source.json, data/raw/MOON-PLACE-02/source.json

Conventions: IAU_2015:30100 Moon Mean-Earth frame on the R = 1737.4 km sphere, planetocentric,
longitude east-positive and normalised to [-180, 180). GeoJSON coordinates are [lon, lat]. Missing
values are null, never 0. Approximate positions are flagged, and no coordinate is made up: every
point comes from an upstream file, the catalogue, or a cited NASA page.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import math
import re
import ssl
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import shapefile  # pyshp, provided by `uv run --with pyshp`
import shapely
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "prepared" / "moon"

MOON_RADIUS_M = 1_737_400.0
MOON_RADIUS_KM = MOON_RADIUS_M / 1000.0
AS_OF = "2026-11-08"  # date the curated planned-mission list (catalogue §9) describes
CATALOGUE = "CLAUDE-Moon-Data-Sources.md"
USER_AGENT = "the-creator-prepare-moon-reference/1.0"

SITES_URL = ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/"
             "ANTHROPOGENIC_OBJECTS/ANTHROPOGENIC_OBJECTS_180.ZIP")
GAZETTEER_URL = "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip"
MARE_URL = ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/"
            "LROC_GLOBAL_MARE/LROC_GLOBAL_MARE_180.ZIP")
HERITAGE_URL = "https://www.nasa.gov/wp-content/uploads/2017/10/617743main_nasa-usg_lunar_historic_sites_reva-508.pdf"
NSSDCA_USSR_URL = "https://nssdc.gsfc.nasa.gov/planetary/lunar/lunarussr.html"
NSSDCA_SURVEYOR_URL = "https://nssdc.gsfc.nasa.gov/planetary/lunar/surveyor.html"
NSSDCA_LUNA23_URL = "https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=1974-084A"
ARTEMIS_REGIONS_URL = "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/"

# Mare outlines: Douglas-Peucker tolerance in degrees (1° = 30.32 km on the Moon, so 0.015° ≈ 455 m
# at the equator, less in longitude towards ±65°) and the coordinate grid the result is snapped to.
MARE_SIMPLIFY_DEG = 0.015
MARE_GRID_DEG = 0.001
MARE_MAX_BYTES = 3_000_000
GAZETTEER_MAX_BYTES = 2_000_000

# Heritage keep-out radii (NASA 2011 Rev A, §A1-3 descent/landing boundary). The backend draws the
# rings; they are listed here so source.json records the parameters next to the rule.
HERITAGE_RADIUS_M = {"landing": 2000, "impact": 500}


# --------------------------------------------------------------------------------------------------
# Small helpers


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm_lon(lon: float, decimals: int | None = None) -> float:
    """Longitude in [-180, 180), optionally rounded (a value that rounds up to 180 wraps to -180)."""
    x = ((float(lon) + 180.0) % 360.0) - 180.0
    if decimals is not None:
        x = round(x, decimals)
        if x >= 180.0:
            x -= 360.0
    return x + 0.0  # turns -0.0 into 0.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on the 1737.4 km Moon sphere (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * MOON_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def destination(lat: float, lon: float, east_km: float, north_km: float) -> tuple[float, float]:
    """Point at local offset (east, north) from (lat, lon) in an azimuthal equidistant frame on the Moon.

    The offset is turned into a distance and an azimuth from the centre and walked along the great
    circle, so a box stays square on the ground even next to the pole, where naive lat/lon deltas
    would collapse the east-west extent.
    """
    d = math.hypot(east_km, north_km) / MOON_RADIUS_KM
    if d == 0:
        return lat, lon
    az = math.atan2(east_km, north_km)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(az))
    l2 = l1 + math.atan2(math.sin(az) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def join_names(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def natural_key(text: str) -> list:
    """Sort 'Luna 9' before 'Luna 13'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ssl_context() -> ssl.SSLContext:
    # uv-managed Pythons may not see the system CA store; certifi (via httpx) is in the backend env.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(source_id: str, url: str, filename: str, refresh: bool) -> dict:
    """Download `url` into data/raw/<source_id>/<filename> unless it is cached. Returns file facts.

    A cached file keeps the retrieval time and redirect target from the previous source.json when its
    checksum still matches; otherwise the file's modification time stands in for the retrieval time.
    """
    folder = RAW / source_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    previous = {}
    record = folder / "source.json"
    if record.exists():
        try:
            previous = json.loads(record.read_text())
        except json.JSONDecodeError:
            previous = {}
    if refresh or not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        tmp = path.with_name(path.name + ".part")
        with urllib.request.urlopen(req, timeout=300, context=ssl_context()) as r, tmp.open("wb") as fh:
            resolved = r.geturl()  # LROC's PDS host redirects to pds.mcp.nasa.gov
            while chunk := r.read(1 << 20):
                fh.write(chunk)
        tmp.replace(path)
        retrieved = now_iso()
        print(f"downloaded {url}\n        -> {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.2f} MB)")
    else:
        prev_file = next((f for f in previous.get("files", []) if f.get("path") == filename), {})
        digest = sha256(path)
        if prev_file.get("sha256") == digest:
            retrieved, resolved = previous.get("retrievedAt"), prev_file.get("resolvedUrl")
        else:
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).replace(microsecond=0)
            retrieved, resolved = mtime.isoformat().replace("+00:00", "Z"), None
        print(f"cached   {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.2f} MB)")
    return {"path": filename, "url": url, "resolvedUrl": resolved, "bytes": path.stat().st_size,
            "sha256": sha256(path), "retrievedAt": retrieved, "local": path}


def read_shapefile(zip_path: Path, base: str, encoding: str) -> shapefile.Reader:
    """Open <base>.shp/.shx/.dbf from a zip without extracting it (member names matched case-blind)."""
    z = zipfile.ZipFile(zip_path)
    members = {n.lower(): n for n in z.namelist()}

    def part(ext: str) -> io.BytesIO:
        return io.BytesIO(z.read(members[f"{base}.{ext}".lower()]))

    return shapefile.Reader(shp=part("shp"), shx=part("shx"), dbf=part("dbf"), encoding=encoding)


def zip_text(zip_path: Path, suffix: str) -> str | None:
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.upper().endswith(suffix.upper()):
                return z.read(n).decode("utf-8", errors="replace")
    return None


def write_json(path: Path, obj, pretty: bool = False) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    else:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def write_raw_record(source_id: str, record: dict, file_info: dict) -> None:
    files = [{k: v for k, v in file_info.items() if k not in ("local", "retrievedAt")}]
    stamp = (file_info["retrievedAt"] or now_iso())[:10].replace("-", "")
    out = {"id": f"{source_id}-global-{stamp}", "catalogueSourceId": source_id, "body": "moon", **record,
           "region": "global", "retrievedAt": file_info["retrievedAt"], "preparedAt": now_iso(), "files": files}
    write_json(RAW / source_id / "source.json", out, pretty=True)


# --------------------------------------------------------------------------------------------------
# MOON-SITE-01: LROC anthropogenic objects

# Kind, from the LROC `OBJECT` description (checked against all 71 rows of the 2026-08-14 release):
#   "Descent stage of Lunar Module …"                     -> crewed_landing (Apollo LMs)
#   anything mentioning "impact"                           -> impact (Ranger, S-IVB, LM ascent stages,
#                                                             Surveyor retro-rockets, crashed landers, boosters)
#   "… rover" / "Lunar Roving Vehicle"                    -> rover (incl. "Retroreflector: Lunokhod 1 rover")
#   "Lander" / "… lander"                                  -> soft_landing (incl. "Retroreflector: Blue Ghost lander")
#   "Retroreflector"                                       -> retroreflector (Apollo 11/14/15 LRRR arrays)
#   anything else (ALSEP, seismometers, SEP experiment)    -> other
# The order matters: impact is tested before rover/lander so a crashed lander or a booster that
# carried landers is an impact.
def classify_kind(obj: str) -> str | None:
    o = obj.lower()
    if o.startswith("descent stage of lunar module"):
        return "crewed_landing"
    if "impact" in o:
        return "impact"
    if "rover" in o or "roving vehicle" in o:
        return "rover"
    if re.search(r"\blander\b", o):
        return "soft_landing"
    if o.startswith("retroreflector"):
        return "retroreflector"
    return None


# Heritage keep-out (MOON-SITE-06, NASA 2011 "Recommendations to space-faring entities" Rev A, §A1-3):
#   heritage = "landing" (2.0 km descent/landing boundary) for every soft or crewed landing, i.e. the
#     landed vehicle itself: Apollo LM descent stages, Surveyor/Luna/Chang'e/… landers, including the
#     landers that carried rovers (Luna 17, Luna 21, Chang'e 3). Rovers get "landing" too: the
#     document lists "Apollo lunar surface landing and roving hardware" as heritage, and a rover can
#     end up kilometres from its lander (Lunokhod 2 is ~15 km from Luna 21), outside the lander's ring.
#   heritage = "impact" (0.5 km) for every impact site (Ranger, S-IVB, LM ascent stages, LCROSS, …).
#   heritage = null for retroreflectors and other deployed payloads (ALSEP, seismometers): they stand
#     within a few hundred metres of their LM, inside its 2.0 km ring (checked below), so a ring of
#     their own would only duplicate it.
# The NASA document covers U.S. government artifacts only; applying the same radii to every nation's
# landing and impact sites is our modelling choice (recorded in the MOON-SITE-06 limitations).
HERITAGE_BY_KIND = {"crewed_landing": "landing", "soft_landing": "landing", "rover": "landing",
                    "impact": "impact", "retroreflector": None, "other": None}
LANDING_KINDS = ("crewed_landing", "soft_landing")

# Catalogue §9 "Soft landings, measured coordinates" (lat, lon east): every one must match an LROC
# lander within 0.1 km, or it is added as a supplement row from the catalogue coordinate.
CATALOGUE_SOFT_LANDINGS = [
    ("Apollo 11", 0.6742, 23.4731), ("Apollo 12", -3.0128, -23.4219), ("Apollo 14", -3.6459, -17.4719),
    ("Apollo 15", 26.1324, 3.6333), ("Apollo 16", -8.9734, 15.5011), ("Apollo 17", 20.1911, 30.7723),
    ("Chang'e 3", 44.1214, -19.5117), ("Chang'e 4", -45.4562, 177.5886), ("Chang'e 5", 43.0576, -51.9161),
    ("Chang'e 6", -41.6383, -153.9857), ("Chandrayaan-3", -69.3740, 32.3187), ("SLIM", -13.3160, 25.2510),
    ("IM-1", -80.1276, 1.4367), ("Blue Ghost Mission 1", 18.5622, 61.8102), ("IM-2", -84.7906, 29.1957),
]
# Listed in §9 by name only (no coordinate in the catalogue): checked for presence, cannot be supplemented.
CATALOGUE_SOFT_LANDINGS_NAMED = ["Surveyor 1", "Surveyor 3", "Surveyor 5", "Surveyor 6", "Surveyor 7",
                                 "Luna 16", "Luna 17", "Luna 20", "Luna 21", "Luna 23", "Luna 24"]

# Landing dates from NASA NSSDCA pages (retrieved 2026-11-08). LROC's DATE field is documented as the
# arrival date, but for these missions it holds the launch date (catalogue MOON-SITE-01 gotcha 1).
# Luna 23: the Soviet-missions page lists only the launch (28 Oct 1974, "Lunar Lander - Mare Crisium");
# the landing date (6 Nov 1974) is from the NSSDCA Master Catalog entry that page links to (1974-084A).
NSSDCA_LANDING_DATES = {
    "Luna 9": ("1966-02-03", NSSDCA_USSR_URL), "Luna 13": ("1966-12-24", NSSDCA_USSR_URL),
    "Luna 16": ("1970-09-20", NSSDCA_USSR_URL), "Luna 17": ("1970-11-17", NSSDCA_USSR_URL),
    "Luna 20": ("1972-02-21", NSSDCA_USSR_URL), "Luna 21": ("1973-01-15", NSSDCA_USSR_URL),
    "Luna 23": ("1974-11-06", NSSDCA_LUNA23_URL), "Luna 24": ("1976-08-18", NSSDCA_USSR_URL),
    "Surveyor 1": ("1966-06-02", NSSDCA_SURVEYOR_URL),
}

# Soft landings the catalogue names as missing from LROC (gotcha 3: never located from orbit). The
# catalogue suggests Wikipedia; NASA NSSDCA gives the same reported positions in the public domain.
# NSSDCA prints them as "7.08 N, 295.63 E" and "18.87 N, 297.95 E" (0-360 east longitudes).
NSSDCA_MISSING_LANDINGS = [
    {"id": "Luna9", "name": "Luna 9 Lander", "mission": "Luna 9", "lat": 7.08, "lon360": 295.63,
     "reported": "7.08 N, 295.63 E"},
    {"id": "Luna13", "name": "Luna 13 Lander", "mission": "Luna 13", "lat": 18.87, "lon360": 297.95,
     "reported": "18.87 N, 297.95 E"},
]


def luna_number(mission: str) -> int | None:
    m = re.fullmatch(r"Luna (\d+)", mission.strip())
    return int(m.group(1)) if m else None


def date_note(mission: str, date: str | None) -> str | None:
    landing = NSSDCA_LANDING_DATES.get(mission)
    if date and landing and date < landing[0]:
        return (f"LROC DATE is the launch date, not the landing date (catalogue MOON-SITE-01 gotcha 1); "
                f"NASA NSSDCA gives the landing as {landing[0]}.")
    n = luna_number(mission)
    if date and n is not None and n <= 24:
        return ("Luna dates are launch dates (LROC record, catalogue MOON-SITE-01 gotcha 1); "
                "the landing was several days later.")
    return None


def elevation_m(radius) -> float | None:
    """LROC RADIUS is the distance from the Moon's centre in metres (README). Elevation is relative to
    the 1737.4 km reference sphere. A value in km (~1737) would be converted; anything else is null."""
    if radius is None:
        return None
    r = float(radius)
    if 1_700.0 < r < 1_760.0:
        r *= 1000.0
    if not 1_700_000.0 < r < 1_760_000.0:
        print(f"  ! RADIUS {radius!r} is not a plausible lunar radius; elevation left null")
        return None
    return round(r - MOON_RADIUS_M, 1)


def uncertainty_text(value, coord_src: str | None) -> str | None:
    if value is None:
        return None
    src = f" ({coord_src})" if coord_src else ""
    if float(value) == 0.0:
        return f"LROC lists 0 m: laser-ranging position, centimetre-level{src}"
    return f"±{float(value):g} m{src}"


def build_sites(zip_path: Path) -> tuple[list[dict], dict]:
    reader = read_shapefile(zip_path, "ANTHROPOGENIC_OBJECTS_180", "utf-8")
    fields = [f.name for f in reader.fields[1:]]
    updated = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", zip_text(zip_path, "_README.TXT") or "")
    release = updated.group(1) if updated else None
    print(f"MOON-SITE-01: {len(reader)} records (README 'Last updated: {release}'); fields {fields}")
    features: list[dict] = []
    unknown_objects = []
    launch_dated: set[str] = set()
    for sr in reader.iterShapeRecords():
        rec = sr.record.as_dict()
        lon_s, lat_s = sr.shape.points[0]
        lat, lon = float(rec["LATITUDE"]), float(rec["LONGITUDE"])
        if abs(lat - lat_s) > 1e-6 or abs(norm_lon(lon) - norm_lon(lon_s)) > 1e-6:
            print(f"  ! {rec['OBJECT_ID']}: attribute and geometry coordinates differ; using the attributes")
        kind = classify_kind(rec["OBJECT"] or "")
        if kind is None:
            unknown_objects.append(rec["OBJECT"])
            kind = "other"
        mission = (rec["MISSION"] or "").strip() or None
        date = rec["DATE"].isoformat() if isinstance(rec["DATE"], dt.date) else None
        vehicle = (rec["VEHCL_NAME"] or "").strip() or None
        props = {
            "id": rec["OBJECT_ID"],
            # SHORT_NAME ("Apollo 11 Lunar Module") is always filled; VEHCL_NAME ("Eagle") is empty for
            # 25 of 71 rows (ALSEPs, retroreflectors, S-IVBs), so it is kept separately as `vehicle`.
            "name": (rec["SHORT_NAME"] or "").strip() or vehicle or rec["OBJECT_ID"],
            "mission": mission,
            "kind": kind,
            "date": date,
            "dateNote": date_note(mission or "", date),
            "elevationM": elevation_m(rec["RADIUS"]),
            "uncertainty": uncertainty_text(rec["UNCERTAIN"], (rec["COORD_SRC"] or "").strip() or None),
            "heritage": HERITAGE_BY_KIND[kind],
            "evidenceType": "reported_record",
            "sourceId": "MOON-SITE-01",
            "note": None,
            "vehicle": vehicle,
            "object": (rec["OBJECT"] or "").strip() or None,
            "coordSource": (rec["COORD_SRC"] or "").strip() or None,
            "radiusSource": (rec["RAD_SRC"] or "").strip() or None,
        }
        features.append({"type": "Feature", "id": props["id"],
                         "geometry": {"type": "Point", "coordinates": [norm_lon(lon, 7), round(lat, 7)]},
                         "properties": props})
        if props["dateNote"]:
            launch_dated.add(mission)
            if mission not in NSSDCA_LANDING_DATES:
                print(f"  ! {props['id']}: launch-dated {mission} row has no NSSDCA landing date (generic dateNote)")
    if unknown_objects:
        print(f"  kind=other for OBJECT values: {sorted(set(unknown_objects))}")

    def pos(f: dict) -> tuple[float, float]:
        lon_, lat_ = f["geometry"]["coordinates"]
        return lat_, lon_

    landers = [f for f in features if f["properties"]["kind"] in LANDING_KINDS]

    # Cross-check against catalogue §9; add anything missing as a supplement from the catalogue coordinate.
    supplements = []
    catalogue_added, nssdca_added = [], []
    for label, lat, lon in CATALOGUE_SOFT_LANDINGS:
        best = min(landers, key=lambda f: distance_km(lat, lon, *pos(f)))
        d = distance_km(lat, lon, *pos(best))
        if d <= 0.1:
            print(f"  §9 {label:<22} matches {best['id']:<12} ({d * 1000:.0f} m)")
            continue
        print(f"  §9 {label:<22} NOT in LROC (nearest lander {best['id']} at {d:.1f} km): adding a supplement")
        catalogue_added.append(label)
        supplements.append({
            "type": "Feature", "id": f"{slug(label)}-catalogue",
            "geometry": {"type": "Point", "coordinates": [norm_lon(lon, 4), round(lat, 4)]},
            "properties": {
                "id": f"{slug(label)}-catalogue", "name": f"{label} lander", "mission": label,
                "kind": "crewed_landing" if label.startswith("Apollo") else "soft_landing",
                "date": None, "dateNote": None, "elevationM": None,
                "uncertainty": "Catalogue coordinate given to 4 decimal places (~3 m); uncertainty not stated",
                "heritage": "landing", "evidenceType": "reported_record", "sourceId": "MOON-SITE-01-SUPPLEMENT",
                "note": f"Missing from the LROC file; coordinate from {CATALOGUE} §9 (soft landings, measured coordinates).",
                "vehicle": None, "object": None, "coordSource": f"{CATALOGUE} §9", "radiusSource": None,
            },
        })
    missions_with_lander = {f["properties"]["mission"] for f in landers}
    for mission in CATALOGUE_SOFT_LANDINGS_NAMED:
        status = "present" if mission in missions_with_lander else "MISSING (no coordinate in the catalogue; not added)"
        print(f"  §9 {mission:<22} {status}")

    # Landings the catalogue says LROC never located (gotcha 3), from NASA NSSDCA.
    for row in NSSDCA_MISSING_LANDINGS:
        if row["mission"] in missions_with_lander:
            print(f"  {row['mission']} is now in the LROC file; supplement skipped")
            continue
        landing_date = NSSDCA_LANDING_DATES[row["mission"]][0]
        nssdca_added.append(row["mission"])
        supplements.append({
            "type": "Feature", "id": row["id"],
            "geometry": {"type": "Point", "coordinates": [norm_lon(row["lon360"], 4), round(row["lat"], 4)]},
            "properties": {
                "id": row["id"], "name": row["name"], "mission": row["mission"], "kind": "soft_landing",
                "date": landing_date, "dateNote": "Landing date (NASA NSSDCA).", "elevationM": None,
                "uncertainty": ("Reported landing position given to 0.01° (~0.3 km); the lander has not been "
                                "located in LROC images, so the true error is not known"),
                "heritage": "landing", "evidenceType": "reported_record", "sourceId": "MOON-SITE-01-SUPPLEMENT",
                "note": (f"Not in the LROC list: never located from orbit ({CATALOGUE} §9, MOON-SITE-01 gotcha 3). "
                         f"Position and landing date from NASA NSSDCA 'Soviet Missions to the Moon' "
                         f"({NSSDCA_USSR_URL}, retrieved {AS_OF}): {row['reported']}."),
                "vehicle": None, "object": "Lander", "coordSource": "NASA NSSDCA (reported)", "radiusSource": None,
            },
        })
        print(f"  supplement {row['id']}: {row['name']} from NSSDCA")
    features += supplements

    # Payloads left without a ring must sit inside a landing ring of the same mission.
    rings = [f for f in features if f["properties"]["heritage"] == "landing"]
    for f in features:
        if f["properties"]["heritage"] is None:
            same = [r for r in rings if r["properties"]["mission"] == f["properties"]["mission"]] or rings
            d = min(distance_km(*pos(f), *pos(r)) for r in same)
            flag = "" if d * 1000 <= HERITAGE_RADIUS_M["landing"] else "  ! OUTSIDE every landing ring"
            print(f"  heritage=null {f['id']:<12} {d * 1000:6.0f} m from its mission's landing ring centre{flag}")

    counts = collections.Counter(f["properties"]["kind"] for f in features)
    heritage = collections.Counter(f["properties"]["heritage"] or "null" for f in features)
    print(f"  kinds {dict(counts)}; heritage {dict(heritage)}; supplements {len(supplements)}")
    return features, {"kinds": dict(counts), "heritage": dict(heritage), "lrocRows": len(reader), "release": release,
                      "supplements": [s["id"] for s in supplements], "nssdcaSupplements": nssdca_added,
                      "catalogueSupplements": catalogue_added, "launchDated": sorted(launch_dated, key=natural_key),
                      "fields": fields}


# --------------------------------------------------------------------------------------------------
# MOON-PLACE-01: IAU / USGS Gazetteer of Planetary Nomenclature


def place_type(raw: str) -> str:
    """Singular descriptor: 'Crater, craters' -> 'Crater'; 'Astronaut-named features' -> 'Astronaut-named
    feature'. 'Satellite Feature' -> 'Lettered crater': the IAU descriptor-term list says lunar satellite
    features are the 'Lettered Craters' (e.g. 'Cabeus B'), and every one of them carries a letter suffix."""
    t = (raw or "").split(",")[0].strip()
    return {"Astronaut-named features": "Astronaut-named feature", "Satellite Feature": "Lettered crater"}.get(t, t)


def sig3(x: float) -> float:
    """Round to 3 significant figures (64.0 km, 25.1 km, 2.9 km, 0.457 km): nominal diameters."""
    k = 2 - math.floor(math.log10(abs(x)))
    return round(x, k) if k > 0 else float(round(x, k))


def approval_text(raw: str | None) -> str | None:
    """'1970/01/01 00:00:00' -> '1970'. Most dates are placeholders on 1 January, i.e. the year only."""
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", raw or "")
    if not m:
        return None
    y, mo, d = m.groups()
    return y if (mo, d) == ("01", "01") else f"{y}-{mo}-{d}"


def build_gazetteer(zip_path: Path) -> tuple[list[dict], dict]:
    reader = read_shapefile(zip_path, "MOON_nomenclature_center_pts", "utf-8")
    fields = [f.name for f in reader.fields[1:]]
    recs = [r.as_dict() for r in reader.records()]
    print(f"MOON-PLACE-01: {len(recs)} records; fields {fields}")
    approvals = collections.Counter(r["approval"] for r in recs)
    print(f"  approval status {dict(approvals)}")
    places: list[dict] = []
    zero_diameter = []
    for r in recs:
        if (r["approval"] or "").strip() != "Adopted by IAU":
            continue  # keep approved, current names only
        link = (r["link"] or "").strip() or None  # kept as published (http://…; the site redirects to https)
        m = re.search(r"/Feature/(\d+)", link or "")
        diameter = r["diameter"]
        if diameter is None or diameter <= 0:
            if diameter is not None:
                zero_diameter.append(r["name"])
            diameter = None  # the gazetteer stores "unknown" as 0
        else:
            diameter = sig3(float(diameter))
        places.append({
            # The USGS Feature ID (the number in the link) is the gazetteer's own stable key.
            "id": m.group(1) if m else f"iau-{slug(r['name'])}",
            "name": r["name"].strip(),
            "type": place_type(r["type"]),
            "diameterKm": diameter,
            "lat": round(float(r["center_lat"]), 4) + 0.0,
            "lon": norm_lon(r["center_lon"], 4),
            "quad": (r["quad_code"] or "").strip() or None,
            "approved": approval_text(r["approvaldt"]),
            "origin": (r["origin"] or "").strip() or None,
            "link": link,
        })
    ids = collections.Counter(p["id"] for p in places)
    assert all(n == 1 for n in ids.values()), "duplicate gazetteer ids"
    places.sort(key=lambda p: p["name"].casefold())
    shared = drop_repeated_origins(places)
    types = collections.Counter(p["type"] for p in places)
    print(f"  kept {len(places)}; diameter 0 -> null: {zero_diameter}; lettered-crater origins left to "
          f"their parent: {shared}; types {dict(types)}")
    return places, {"records": len(recs), "kept": len(places), "approval": dict(approvals),
                    "diameterZeroToNull": zero_diameter, "originsLeftToParent": shared,
                    "types": dict(types), "fields": fields}


def drop_repeated_origins(places: list[dict]) -> int:
    """A lettered crater ('Reiner M') repeats its parent crater's eponym text word for word; that text is
    kept on the parent entry only and the lettered crater's origin is null. This keeps the file under
    2 MB (the repeated text is ~0.3 MB) without losing information. Returns how many were cleared."""
    by_name = {p["name"]: p for p in places}
    n = 0
    for p in places:
        if p["type"] != "Lettered crater" or not p["origin"]:
            continue
        parent = by_name.get(re.sub(r"\s+[A-Z]{1,2}$", "", p["name"]))
        if parent and parent is not p and parent["origin"] == p["origin"]:
            p["origin"] = None
            n += 1
    return n


# --------------------------------------------------------------------------------------------------
# MOON-PLACE-02: LROC global mare polygons

# The DBF stores names in plain ASCII with accented letters dropped, plus two typos. Restored to the
# IAU spelling (each fixed base name is checked against the gazetteer at run time).
MARE_NAME_FIXES = {
    "Chrtien": "Chrétien",
    "Von Krmn": "Von Kármán",
    "Crger": "Crüger",
    "Crger East": "Crüger East",
    "Crger North": "Crüger North",
    "Crger F": "Crüger F",
    "Kohlschtter": "Kohlschütter",
    "Lacus Somniorium": "Lacus Somniorum",
    "Lacus Perseveramtiae": "Lacus Perseverantiae",
}


def polygons_of(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in geom.geoms for p in polygons_of(g)]
    return []  # lines/points left over from make_valid


def polygon_coords(obj, decimals: int):
    """Round polygon vertices. Longitudes are clamped rather than wrapped: the _180 file stops just short
    of the antimeridian, and wrapping a vertex that rounds to 180 would tear the ring across the map."""
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            lon = min(max(round(obj[0], decimals), -180.0), 180.0 - 10.0 ** -decimals)
            return [lon + 0.0, round(obj[1], decimals) + 0.0]
        return [polygon_coords(x, decimals) for x in obj]
    return obj


def build_mare(zip_path: Path, gazetteer_names: set[str]) -> tuple[list[dict], dict]:
    reader = read_shapefile(zip_path, "LROC_GLOBAL_MARE_180", "latin-1")
    fields = [f.name for f in reader.fields[1:]]
    groups: dict[str, list] = collections.defaultdict(list)
    area: dict[str, float] = collections.defaultdict(float)
    invalid = 0
    vertices_in = 0
    for sr in reader.iterShapeRecords():
        rec = sr.record.as_dict()
        name = (rec["MARE_NAME"] or "").strip()
        name = MARE_NAME_FIXES.get(name, name)
        geom = shape(sr.shape.__geo_interface__)
        vertices_in += len(sr.shape.points)
        if not geom.is_valid:
            invalid += 1
            geom = make_valid(geom)
        groups[name].extend(polygons_of(geom))
        if rec.get("Area_km") is not None:
            area[name] += float(rec["Area_km"])
    print(f"MOON-PLACE-02: {len(reader)} polygons, {len(groups)} names, {invalid} invalid (repaired), "
          f"{vertices_in} vertices; fields {fields}")

    unmatched = []
    for name in groups:
        base = re.sub(r"\s+(-\s+)?(east|west|north|south)$", "", name, flags=re.IGNORECASE)
        if name not in gazetteer_names and base not in gazetteer_names:
            unmatched.append(name)
    print(f"  names with no gazetteer feature of that name (LROC unit names, kept as published): {unmatched}")

    features = []
    vertices_out = 0
    for name in sorted(groups, key=str.casefold):
        merged = unary_union(groups[name])
        simple = merged.simplify(MARE_SIMPLIFY_DEG, preserve_topology=True)
        if not simple.is_valid:
            simple = make_valid(simple)
        parts = polygons_of(simple)
        geom = shapely.set_precision(shapely.MultiPolygon(parts), MARE_GRID_DEG)  # keeps output valid
        parts = polygons_of(geom)
        if not parts:
            print(f"  ! {name}: nothing left after simplification; skipped")
            continue
        geom = parts[0] if len(parts) == 1 else shapely.MultiPolygon(parts)
        # RFC 7946 winding: exterior rings counter-clockwise.
        geom = orient(geom, 1.0) if geom.geom_type == "Polygon" else shapely.MultiPolygon([orient(p, 1.0) for p in geom.geoms])
        vertices_out += int(shapely.get_num_coordinates(geom))
        gj = mapping(geom)
        gj = {"type": gj["type"], "coordinates": polygon_coords(gj["coordinates"], 3)}
        if not shape(gj).is_valid:
            print(f"  ! {name}: geometry invalid after rounding")
        mid = slug(name)  # "mare-imbrium", "oceanus-procellarum", "von-karman"
        features.append({"type": "Feature", "id": mid, "geometry": gj,
                         "properties": {"id": mid, "name": name,
                                        "areaKm2": round(area[name]) if name in area else None}})
    print(f"  {len(features)} features, {vertices_out} vertices after simplification")
    return features, {"polygonsIn": len(reader), "names": len(groups), "invalidRepaired": invalid,
                      "verticesIn": vertices_in, "verticesOut": vertices_out, "fields": fields,
                      "nameFixes": MARE_NAME_FIXES, "namesNotInGazetteer": unmatched}


# --------------------------------------------------------------------------------------------------
# MOON-SITE-02: planned missions and Artemis candidate regions (catalogue §9, as of 2026-11-08)

# The nine Artemis candidate regions (NASA, Oct 2024; still current per LPSC 2026) on seven anchor
# features. Anchor = centre of the named feature, as listed in the catalogue; `gazetteer` names the
# IAU feature used to cross-check it.
ARTEMIS_ANCHORS = [
    {"anchor": "Peak near Cabeus B", "gazetteer": "Cabeus B", "lat": -82.26, "lon": -54.59,
     "regions": ["Peak near Cabeus B"]},
    {"anchor": "Haworth", "gazetteer": "Haworth", "lat": -87.45, "lon": -5.17, "regions": ["Haworth"]},
    {"anchor": "Malapert Massif", "gazetteer": "Mons Malapert", "lat": -85.98, "lon": -1.67,
     "regions": ["Malapert Massif"]},
    {"anchor": "Mons Mouton", "gazetteer": "Mons Mouton", "lat": -84.60, "lon": 31.00,
     "regions": ["Mons Mouton", "Mons Mouton Plateau"]},
    {"anchor": "Nobile", "gazetteer": "Nobile", "lat": -85.28, "lon": 53.27, "regions": ["Nobile Rim 1", "Nobile Rim 2"]},
    {"anchor": "de Gerlache", "gazetteer": "de Gerlache", "lat": -88.49, "lon": -88.35, "regions": ["de Gerlache Rim 2"]},
    {"anchor": "Slater", "gazetteer": "Slater", "lat": -88.08, "lon": 111.29, "regions": ["Slater Plain"]},
]
ARTEMIS_BOX_KM = 15.0

# Planned missions, catalogue §9 table. `coord` = a coordinate published in the catalogue;
# `feature` = gazetteer feature(s) whose centre stands in for the target; neither = geometry null.
PLANNED_MISSIONS = [
    {"name": "Griffin-1", "target": "Mons Mouton / Nobile", "date": "Jan 2027", "feature": ["Mons Mouton"],
     "note": "Target published as 'Mons Mouton / Nobile' (catalogue lists Griffin-1 among the Mons Mouton "
             "arrivals); point at the Mons Mouton gazetteer centre."},
    {"name": "IM-3", "target": "Reiner Gamma", "date": "Q1 2027", "coord": (7.4, -59.0),
     "note": "Catalogue coordinate ~7.4°N, 59.0°W (Reiner Gamma swirl)."},
    {"name": "Blue Moon MK1", "target": "Shackleton connecting ridge (~89.5°S)", "date": "Q1 2027",
     "feature": ["Shackleton"],
     "note": "Only the latitude (~89.5°S) is published for the Shackleton connecting ridge; point at the "
             "Shackleton crater gazetteer centre, not the landing site."},
    {"name": "IM-4", "target": "Mons Mouton", "date": "2027", "feature": ["Mons Mouton"],
     "note": "Point at the Mons Mouton gazetteer centre; the landing site within the massif is not published."},
    {"name": "Blue Ghost M2", "target": "far side", "date": "late 2027",
     "note": "Landing site published only as 'far side'; no point."},
    {"name": "Blue Moon + VIPER", "target": "south pole (Mons Mouton)", "date": "late 2027", "feature": ["Mons Mouton"],
     "note": "VIPER revived Sep 2025 on Blue Moon; point at the Mons Mouton gazetteer centre."},
    {"name": "Chang'e-7", "target": "Shackleton rim", "date": "2027", "coord": (-88.8, 123.4),
     "note": "Catalogue coordinate ~88.8°S, 123.4°E is unofficial (Aug 2026 launch scrubbed, now 2027)."},
    {"name": "Chandrayaan-4", "target": "near the Chandrayaan-3 landing site", "date": "2027–28", "site": "Vikram2",
     "note": "Published only as 'near the Chandrayaan-3 landing site'; point at the LROC position of the "
             "Chandrayaan-3 Vikram lander (Statio Shiv Shakti)."},
    {"name": "Artemis IV / V", "target": "south-pole Artemis regions", "date": "2028",
     "note": "First crewed landing is Artemis IV (2028), lander not assigned; the candidate regions are the "
             "artemis_region features in this layer."},
    {"name": "Blue Ghost M3", "target": "Gruithuisen Domes", "date": "2028",
     "feature": ["Mons Gruithuisen Gamma", "Mons Gruithuisen Delta"],
     "note": "'Gruithuisen Domes' is not an IAU name; point at the midpoint of the gazetteer centres of "
             "Mons Gruithuisen Gamma and Mons Gruithuisen Delta."},
    {"name": "PROMISE rover", "target": "south-pole PSRs", "date": "late 2028",
     "note": "Target published only as south-pole permanently shadowed regions; no point."},
    {"name": "LUPEX", "target": "south pole", "date": "2028", "note": "Landing site not published; no point."},
    {"name": "Chang'e-8", "target": "Leibnitz Beta (Mons Mouton plateau)", "date": "2028–29", "feature": ["Mons Mouton"],
     "note": "'Leibnitz Beta' is the informal name of the massif the IAU named Mons Mouton; point at its "
             "gazetteer centre."},
    {"name": "Lanyue (China crewed)", "target": "not announced", "date": "before 2030",
     "note": "Landing site not announced (Rimae Bode is an academic proposal only); no point."},
    {"name": "Fission Surface Power", "target": "site not published", "date": "by 2030", "note": "No point."},
    {"name": "ILRS", "target": "south pole", "date": "~2035", "note": "No site published; no point."},
]


def artemis_box(lat: float, lon: float, size_km: float, per_edge: int = 4) -> list[list[float]]:
    """Closed counter-clockwise ring of a size_km square centred on (lat, lon), built in the local
    azimuthal frame and densified so its edges stay straight on the ground when drawn in lon/lat."""
    h = size_km / 2.0
    corners = [(-h, -h), (h, -h), (h, h), (-h, h)]
    ring = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        for i in range(per_edge):
            t = i / per_edge
            plat, plon = destination(lat, lon, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            ring.append([norm_lon(plon, 5), round(plat, 5)])
    ring.append(ring[0])
    lons = [p[0] for p in ring]
    assert max(lons) - min(lons) < 180, "box crosses the antimeridian"
    pole_km = (90 - abs(lat)) * math.pi / 180 * MOON_RADIUS_KM
    assert pole_km > h * math.sqrt(2), "box would contain the pole"
    return ring


def build_missions(places: list[dict], sites: list[dict]) -> tuple[list[dict], dict]:
    by_name = {p["name"]: p for p in places}
    site_by_id = {f["properties"]["id"]: f for f in sites}
    features = []
    for a in ARTEMIS_ANCHORS:
        g = by_name.get(a["gazetteer"])
        if g:
            d = distance_km(a["lat"], a["lon"], g["lat"], g["lon"])
            print(f"  Artemis anchor {a['anchor']:<20} vs gazetteer {a['gazetteer']:<14} {d:5.2f} km")
        else:
            print(f"  ! Artemis anchor {a['anchor']}: gazetteer feature {a['gazetteer']!r} not found")
        rid = f"artemis-{slug(a['anchor'])}"
        label = "Artemis regions" if len(a["regions"]) > 1 else "Artemis region"
        features.append({
            "type": "Feature", "id": rid,
            "geometry": {"type": "Polygon", "coordinates": [artemis_box(a["lat"], a["lon"], ARTEMIS_BOX_KM)]},
            "properties": {
                "id": rid, "name": f"{label}: {', '.join(a['regions'])}", "kind": "artemis_region",
                "mission": "Artemis IV / V", "target": a["anchor"], "date": "2028", "asOf": AS_OF,
                "evidenceType": "planned", "approximate": True,
                "note": (f"{len(a['regions'])} of NASA's nine Artemis candidate landing regions (Oct 2024; still "
                         f"current per LPSC 2026). NASA published no polygons: this {ARTEMIS_BOX_KM:g} × "
                         f"{ARTEMIS_BOX_KM:g} km box is centred on the anchor feature's centre "
                         f"({abs(a['lat']):.2f}°S, {abs(a['lon']):.2f}°{'W' if a['lon'] < 0 else 'E'}), "
                         "while the actual region lies on its rim or flank."),
                "sourceId": "MOON-SITE-02", "regions": a["regions"], "anchor": a["anchor"],
            },
        })
    placed = collections.Counter()
    for m in PLANNED_MISSIONS:
        geometry = None
        if m.get("coord"):
            lat, lon = m["coord"]
            geometry, how = {"type": "Point", "coordinates": [norm_lon(lon, 4), round(lat, 4)]}, "catalogue coordinate"
        elif m.get("site"):
            lon, lat = site_by_id[m["site"]]["geometry"]["coordinates"]
            geometry, how = {"type": "Point", "coordinates": [norm_lon(lon, 4), round(lat, 4)]}, "LROC site"
        elif m.get("feature"):
            found = [by_name[n] for n in m["feature"] if n in by_name]
            if len(found) == len(m["feature"]):
                if len(found) == 1:
                    lat, lon = found[0]["lat"], found[0]["lon"]
                else:  # midpoint of two nearby features (great-circle midpoint)
                    (la1, lo1), (la2, lo2) = [(math.radians(f["lat"]), math.radians(f["lon"])) for f in found]
                    bx = math.cos(la2) * math.cos(lo2 - lo1)
                    by = math.cos(la2) * math.sin(lo2 - lo1)
                    lat = math.degrees(math.atan2(math.sin(la1) + math.sin(la2), math.hypot(math.cos(la1) + bx, by)))
                    lon = math.degrees(lo1 + math.atan2(by, math.cos(la1) + bx))
                geometry, how = {"type": "Point", "coordinates": [norm_lon(lon, 4), round(lat, 4)]}, "gazetteer centre"
            else:
                how = "gazetteer feature missing"
                print(f"  ! {m['name']}: gazetteer feature(s) {m['feature']} not found; geometry null")
        else:
            how = "no published site"
        placed[how] += 1
        mid = slug(m["name"])
        features.append({
            "type": "Feature", "id": f"planned-{mid}", "geometry": geometry,
            "properties": {
                "id": f"planned-{mid}", "name": m["name"], "kind": "planned_mission", "mission": m["name"],
                "target": m["target"], "date": m["date"], "asOf": AS_OF, "evidenceType": "planned",
                # Every planned position is approximate: none of these missions has published a landing
                # coordinate; a null geometry means no site has been published at all.
                "approximate": True, "note": m["note"], "sourceId": "MOON-SITE-02",
            },
        })
        print(f"  planned {m['name']:<22} {how}")
    return features, {"artemisRegions": len(ARTEMIS_ANCHORS), "plannedMissions": len(PLANNED_MISSIONS),
                      "placement": dict(placed)}


# --------------------------------------------------------------------------------------------------
# Provenance


def sources_block(files: dict, stats: dict) -> dict:
    lroc_credit = "NASA/GSFC/Arizona State University"
    # MOON-SITE-01 sentences describe what this run parsed and added, not a fixed release.
    st = stats["sites"]
    nssdca, catalogue, launch_dated = st["nssdcaSupplements"], st["catalogueSupplements"], st["launchDated"]
    added = ([f"{join_names(nssdca)} {'are' if len(nssdca) > 1 else 'is'} added from NASA NSSDCA"] if nssdca else []) + \
            ([f"{join_names(catalogue)} {'are' if len(catalogue) > 1 else 'is'} added from {CATALOGUE} §9"]
             if catalogue else [])
    never_seen = ("impact sites never seen from orbit (Luna 2, Ranger 4, SMART-1, Lunar Prospector, most LM ascent "
                  "stages and spent stages) are not included.")
    site_limits = [
        "Only objects located in LROC NAC images are listed; "
        + (f"{' and '.join(added)} (MOON-SITE-01-SUPPLEMENT), while {never_seen}" if added else never_seen),
    ]
    if launch_dated:
        site_limits.append(f"DATE is documented as the arrival date, but for {join_names(launch_dated)} it holds the "
                           "launch date; affected rows carry a dateNote.")
    supplement_limits = []
    if nssdca:
        many = len(nssdca) > 1
        supplement_limits.append(
            f"Reported landing positions (0.01° precision), not measured from orbit: the {join_names(nssdca)} "
            f"lander{'s have' if many else ' has'} not been identified in LROC images, so "
            f"{'their true positions' if many else 'its true position'} may differ.")
        supplement_limits.append(
            f"Added because {CATALOGUE} §9 (MOON-SITE-01 gotcha 3) lists {'them' if many else 'it'} as missing"
            + ("." if catalogue else "; every §9 soft landing with a coordinate was found in the LROC file, so no "
               "catalogue coordinate had to be added."))
    if catalogue:
        supplement_limits.append(
            f"{join_names(catalogue)}: no LROC lander within 0.1 km of the {CATALOGUE} §9 coordinate, so that "
            "coordinate (4 decimals) is used; date and elevation are null.")
    landing_urls = list(dict.fromkeys(NSSDCA_LANDING_DATES[m][1] for m in nssdca + launch_dated
                                      if m in NSSDCA_LANDING_DATES))
    s = {
        "MOON-SITE-01": {
            "id": "MOON-SITE-01",
            "name": "LROC Anthropogenic Objects",
            "provider": "LROC Science Operations Center, Arizona State University (NASA Lunar Reconnaissance Orbiter), via NASA PDS",
            "licence": "U.S. public domain (NASA PDS); credit requested",
            "attribution": (f"{lroc_credit}. Wagner, R. V. et al. (2017) Coordinates of anthropogenic features on "
                            "the Moon. Icarus 283, 92-103, doi:10.1016/j.icarus.2016.05.011"),
            "evidenceType": "reported_record",
            "url": SITES_URL,
            "retrievedAt": files["MOON-SITE-01"]["retrievedAt"],
            "limitations": [
                *site_limits,
                "elevationM = RADIUS - 1 737 400 m: height above the reference sphere, not above a geoid or local terrain.",
                "Coordinate uncertainty is LROC's own figure (metres); 0 m means a laser-ranging position.",
                "kind is derived from LROC's OBJECT text by this project; heritage marks which NASA-2011 keep-out "
                "radius the backend draws (see MOON-SITE-06).",
            ],
            "commercialUse": True,
            "notes": (f"{st['lrocRows']} LROC rows ("
                      + (f"release of {st['release']}" if st["release"] else "no 'Last updated' date in the README")
                      + f") plus {len(st['supplements'])} supplement rows. Name = SHORT_NAME; VEHCL_NAME kept as `vehicle`."),
        },
        "MOON-SITE-01-SUPPLEMENT": {
            "id": "MOON-SITE-01-SUPPLEMENT",
            "name": "Soft landings missing from the LROC list (supplement)",
            "provider": "NASA Space Science Data Coordinated Archive (NSSDCA)",
            "licence": "U.S. public domain (NASA)",
            "attribution": "NASA NSSDCA, D. R. Williams: Soviet Missions to the Moon; Surveyor missions",
            "evidenceType": "reported_record",
            "url": NSSDCA_USSR_URL,
            "retrievedAt": AS_OF,
            "limitations": supplement_limits,
            "commercialUse": True,
            "notes": f"Rows: {', '.join(st['supplements']) or 'none'}. Landing dates (supplement rows and dateNotes) "
                     f"come from NASA NSSDCA: {', '.join(landing_urls) or 'none used'}.",
        },
        "MOON-PLACE-01": {
            "id": "MOON-PLACE-01",
            "name": "Gazetteer of Planetary Nomenclature (Moon centre points)",
            "provider": "IAU Working Group for Planetary System Nomenclature (WGPSN) / USGS Astrogeology Science Center",
            "licence": "U.S. public domain (USGS); names are IAU-approved nomenclature",
            "attribution": ("Gazetteer of Planetary Nomenclature, Planetary Geomatics Group of the USGS Astrogeology "
                            "Science Center, https://planetarynames.wr.usgs.gov. International Astronomical Union "
                            "(IAU) Working Group for Planetary System Nomenclature (WGPSN)"),
            "evidenceType": "reference_gazetteer",
            "url": GAZETTEER_URL,
            "retrievedAt": files["MOON-PLACE-01"]["retrievedAt"],
            "limitations": [
                "Centre points and nominal diameters only; names are labels, not surveyed boundaries.",
                "The file is rebuilt nightly upstream; this copy is a snapshot at retrievedAt.",
                "A diameter of 0 upstream (unknown, e.g. Statio landing-site names) is null here.",
                "approved is the IAU approval year (the gazetteer stores most dates as 1 January of that year) "
                "or the full date when one is given.",
                "A lettered crater's origin is null when it only repeats its parent crater's eponym; read it from "
                "the parent entry (same name without the letter).",
            ],
            "commercialUse": True,
            "notes": ("Approved ('Adopted by IAU') names only; longitudes converted from 0-360 to ±180; coordinates "
                      "rounded to 4 decimals (~3 m); diameters to 3 significant figures; id = USGS Feature ID; "
                      "type = singular descriptor ('Crater, craters' -> 'Crater'; 'Satellite Feature' -> "
                      "'Lettered crater', the IAU's own definition of lunar satellite features); approved = IAU "
                      f"approval year, or full date when not 1 January. origin is null on "
                      f"{stats['places']['originsLeftToParent']} lettered craters whose text repeats their parent "
                      "crater's word for word (the parent entry keeps it), to keep the file under 2 MB."),
        },
        "MOON-PLACE-02": {
            "id": "MOON-PLACE-02",
            "name": "LROC global mare boundaries (65°S-65°N)",
            "provider": "LROC Science Operations Center, Arizona State University (NASA Lunar Reconnaissance Orbiter), via NASA PDS",
            "licence": "U.S. public domain (NASA PDS); credit requested",
            "attribution": (f"{lroc_credit}. Nelson, D. M. et al. (2014) Mapping lunar maria extents and lobate "
                            "scarps using LROC image products. LPSC 45, abstract 2861"),
            "evidenceType": "reference_geometry",
            "url": MARE_URL,
            "retrievedAt": files["MOON-PLACE-02"]["retrievedAt"],
            "limitations": [
                "Covers 65°S-65°N only: no mare outlines near the poles.",
                "Digitised at 1:200,000-1:500,000 from WAC and Clementine mosaics, then simplified here "
                f"(Douglas-Peucker {MARE_SIMPLIFY_DEG}° ≈ {MARE_SIMPLIFY_DEG * math.pi / 180 * MOON_RADIUS_M:.0f} m, "
                f"coordinates snapped to {MARE_GRID_DEG}°): use for context and cell lookup, not for boundaries.",
                "Some names are LROC unit names rather than IAU features (e.g. 'Oceanus Procellarum - south', "
                "'Cognitum East').",
            ],
            "commercialUse": True,
            "notes": (f"{stats['mare']['polygonsIn']} polygons merged into {stats['mare']['features']} features by "
                      f"MARE_NAME; {stats['mare']['invalidRepaired']} self-intersecting polygons repaired "
                      "(shapely make_valid); simplification tolerance "
                      f"{MARE_SIMPLIFY_DEG}°; areaKm2 = sum of the upstream AREA_KM values; diacritics lost in "
                      "the DBF and two typos restored to IAU spelling."),
        },
        "MOON-SITE-02": {
            "id": "MOON-SITE-02",
            "name": "Planned missions and Artemis candidate regions, 2027-2030 (curated)",
            "provider": f"New Worlds project curation ({CATALOGUE} §9) from NASA, CNSA, ISRO, JAXA and company announcements",
            "licence": "Project compilation of public announcements (facts; no upstream licence)",
            "attribution": "Curated by the New Worlds project; Artemis regions: NASA (Oct 2024)",
            "evidenceType": "planned",
            "url": ARTEMIS_REGIONS_URL,
            "retrievedAt": AS_OF,
            "limitations": [
                f"Announced plans as of {AS_OF}; dates slip often and targets change.",
                "NASA published no polygons for the Artemis regions: each box is ~15 × 15 km centred on the anchor "
                "feature, while the real region sits on that feature's rim or flank.",
                "Mission points are approximate (catalogue coordinates or gazetteer feature centres); missions "
                "without a published site have no geometry.",
            ],
            "commercialUse": True,
            "notes": "url is NASA's Oct 2024 Artemis landing-regions update; mission rows follow the catalogue's §9 table.",
        },
        "MOON-SITE-06": {
            "id": "MOON-SITE-06",
            "name": ("NASA's Recommendations to Space-Faring Entities: How to Protect and Preserve the Historic and "
                     "Scientific Value of U.S. Government Lunar Artifacts (Rev A)"),
            "provider": "NASA",
            "licence": "U.S. public domain (NASA)",
            "attribution": "NASA (2011), Recommendations to Space-Faring Entities, Rev A, 28 Oct 2011",
            "evidenceType": "rule",
            "url": HERITAGE_URL,
            "retrievedAt": AS_OF,
            "limitations": [
                "Recommendations, not law: the document states it does not represent mandatory U.S. government or "
                "international requirements.",
                "Written for U.S. government artifacts; this app applies the same radii to every nation's landing "
                "and impact sites as a modelling choice.",
                "2.0 km around heritage landing and roving hardware and 0.5 km around heritage impact sites bound "
                "the descent/landing path; the Apollo 11 (75 m) and Apollo 17 (225 m) walking limits are not drawn.",
                "Rings are centred on each site's recorded coordinate; experiments and retroreflectors get no ring "
                "of their own because they lie inside their lunar module's 2.0 km ring.",
            ],
            "commercialUse": True,
            "parameters": {"heritage_landing": {"radiusM": HERITAGE_RADIUS_M["landing"]},
                           "heritage_impact": {"radiusM": HERITAGE_RADIUS_M["impact"]}},
            "notes": "Applied to sites whose heritage property is 'landing' or 'impact' in sites/anthropogenic_objects.geojson.",
        },
    }
    if not stats["sites"]["supplements"]:
        del s["MOON-SITE-01-SUPPLEMENT"]
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="download the upstream files again")
    args = ap.parse_args()

    files = {
        "MOON-SITE-01": fetch("MOON-SITE-01", SITES_URL, "ANTHROPOGENIC_OBJECTS_180.ZIP", args.refresh),
        "MOON-PLACE-01": fetch("MOON-PLACE-01", GAZETTEER_URL, "MOON_nomenclature_center_pts.zip", args.refresh),
        "MOON-PLACE-02": fetch("MOON-PLACE-02", MARE_URL, "LROC_GLOBAL_MARE_180.ZIP", args.refresh),
    }
    stats: dict = {}

    sites, stats["sites"] = build_sites(files["MOON-SITE-01"]["local"])
    places, stats["places"] = build_gazetteer(files["MOON-PLACE-01"]["local"])
    mare, stats["mare"] = build_mare(files["MOON-PLACE-02"]["local"], {p["name"] for p in places})
    stats["mare"]["features"] = len(mare)
    print("MOON-SITE-02:")
    missions, stats["missions"] = build_missions(places, sites)

    sizes = {
        "sites": write_json(OUT / "sites" / "anthropogenic_objects.geojson", {"type": "FeatureCollection", "features": sites}),
        "places": write_json(OUT / "places" / "gazetteer.json", places),
        "mare": write_json(OUT / "regions" / "mare.geojson", {"type": "FeatureCollection", "features": mare}),
        "missions": write_json(OUT / "missions" / "planned.geojson", {"type": "FeatureCollection", "features": missions}),
    }
    assert sizes["places"] <= GAZETTEER_MAX_BYTES, f"gazetteer.json is {sizes['places']} bytes"
    assert sizes["mare"] <= MARE_MAX_BYTES, f"mare.geojson is {sizes['mare']} bytes"

    manifest = {
        "body": "moon",
        "generatedAt": now_iso(),
        "generator": "scripts/moon/prepare_moon_reference.py",
        "frame": "IAU_2015:30100 Moon Mean-Earth, planetocentric, east-positive longitude in [-180, 180), R = 1737.4 km",
        "sources": sources_block(files, stats),
        "layers": [
            {"id": "moon_sites", "file": "sites/anthropogenic_objects.geojson", "source": "MOON-SITE-01", "count": len(sites)},
            {"id": "moon_places", "file": "places/gazetteer.json", "source": "MOON-PLACE-01", "count": len(places)},
            {"id": "moon_mare", "file": "regions/mare.geojson", "source": "MOON-PLACE-02", "count": len(mare),
             "simplification": {"method": "Douglas-Peucker (shapely, preserve_topology)", "toleranceDeg": MARE_SIMPLIFY_DEG,
                                "toleranceM": round(MARE_SIMPLIFY_DEG * math.pi / 180 * MOON_RADIUS_M),
                                "gridDeg": MARE_GRID_DEG}},
            {"id": "moon_missions", "file": "missions/planned.geojson", "source": "MOON-SITE-02", "count": len(missions)},
        ],
    }
    write_json(OUT / "source.json", manifest, pretty=True)

    lroc_licence = {"name": "U.S. public domain (NASA PDS)", "attribution": "NASA/GSFC/Arizona State University",
                    "notes": "US-government work, no copyright; credit requested (LROC). Cite the product paper.",
                    "reviewedAt": AS_OF}
    release, launch_dated = stats["sites"]["release"], stats["sites"]["launchDated"]
    write_raw_record("MOON-SITE-01", {
        "provider": "LROC Science Operations Center, Arizona State University (NASA LRO), via NASA PDS",
        "product": "LROC Anthropogenic Objects point shapefile, -180..180 longitude domain (ANTHROPOGENIC_OBJECTS_180)",
        "version": f"README 'Last updated: {release}'" if release else None,
        "documentationUrl": "https://doi.org/10.1016/j.icarus.2016.05.011",
        "accessUrl": SITES_URL,
        "accessMethod": "download (HTTPS; the LROC PDS host redirects to pds.mcp.nasa.gov)",
        "evidenceType": "reported_record",
        "licence": lroc_licence,
        "citation": ("Wagner, R. V., Nelson, D. M., Plescia, J. B., Robinson, M. S., Speyerer, E. J., & Mazarico, E. "
                     "(2017). Coordinates of anthropogenic features on the Moon. Icarus, 283, 92-103. "
                     "doi:10.1016/j.icarus.2016.05.011"),
        "frame": "GCS_Moon_2000 (sphere 1737400 m), planetocentric, east-positive, -180..180",
        "units": {"RADIUS": "metres from the Moon's centre", "UNCERTAIN": "metres",
                  "DATE": "UTC date" + (f" (launch date for {join_names(launch_dated)})" if launch_dated else "")},
        "processing": "scripts/moon/prepare_moon_reference.py -> data/prepared/moon/sites/anthropogenic_objects.geojson",
        "stats": stats["sites"],
    }, files["MOON-SITE-01"])
    write_raw_record("MOON-PLACE-01", {
        "provider": "IAU WGPSN / USGS Astrogeology Science Center (Planetary Geomatics Group)",
        "product": "Gazetteer of Planetary Nomenclature, Moon feature centre points (shapefile, rebuilt nightly)",
        "version": "nightly build as retrieved",
        "documentationUrl": "https://planetarynames.wr.usgs.gov/",
        "accessUrl": GAZETTEER_URL,
        "accessMethod": "download (HTTPS, USGS S3 bucket)",
        "evidenceType": "reference_gazetteer",
        "licence": {"name": "U.S. public domain (USGS)",
                    "attribution": ("Gazetteer of Planetary Nomenclature, Planetary Geomatics Group of the USGS "
                                    "Astrogeology Science Center, https://planetarynames.wr.usgs.gov. IAU WGPSN."),
                    "notes": "Feature names are IAU nomenclature; USGS data carry no copyright.", "reviewedAt": AS_OF},
        "frame": "Moon planetocentric, east-positive; center_lon in 0..360 (converted to ±180)",
        "processing": "scripts/moon/prepare_moon_reference.py -> data/prepared/moon/places/gazetteer.json",
        "stats": stats["places"],
    }, files["MOON-PLACE-01"])
    write_raw_record("MOON-PLACE-02", {
        "provider": "LROC Science Operations Center, Arizona State University (NASA LRO), via NASA PDS",
        "product": "LROC global mare boundaries polygon shapefile, 65°S-65°N, -180..180 (LROC_GLOBAL_MARE_180)",
        "version": "2017-09-01 (file dates in the archive)",
        "documentationUrl": "https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/SHAPEFILE/LROC_GLOBAL_MARE/",
        "accessUrl": MARE_URL,
        "accessMethod": "download (HTTPS; the LROC PDS host redirects to pds.mcp.nasa.gov)",
        "evidenceType": "reference_geometry",
        "licence": lroc_licence,
        "citation": ("Nelson, D. M., Koeber, S. D., Daud, K., Robinson, M. S., Watters, T. R., Banks, M. E., & "
                     "Williams, N. R. (2014). Mapping lunar maria extents and lobate scarps using LROC image products. "
                     "LPSC 45, abstract 2861."),
        "frame": "Moon 2000 geographic (sphere 1737400 m), -180..180",
        "processing": (f"scripts/moon/prepare_moon_reference.py: make_valid on invalid parts, union per MARE_NAME, "
                       f"Douglas-Peucker {MARE_SIMPLIFY_DEG}° (preserve topology), snap to {MARE_GRID_DEG}° grid "
                       "-> data/prepared/moon/regions/mare.geojson"),
        "stats": stats["mare"],
    }, files["MOON-PLACE-02"])

    print("\nwritten:")
    for key, path in (("sites", "sites/anthropogenic_objects.geojson"), ("places", "places/gazetteer.json"),
                      ("mare", "regions/mare.geojson"), ("missions", "missions/planned.geojson")):
        print(f"  data/prepared/moon/{path:<40} {sizes[key] / 1e6:6.3f} MB")
    print("  data/prepared/moon/source.json")
    print("  data/raw/MOON-SITE-01/source.json, data/raw/MOON-PLACE-01/source.json, data/raw/MOON-PLACE-02/source.json")


if __name__ == "__main__":
    sys.exit(main())
