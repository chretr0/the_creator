"""Prepare the Moon elevation H3 layer from the LOLA LDEM 16 ppd global grid (MOON-TOPO-02).

Run (from the repo root's backend/ folder, which has numpy, pyarrow and h3):
  cd backend && uv run python ../scripts/moon/prepare_moon_elevation.py [--force-download]

Steps:
1. Download ``ldem_16_float.img`` (~66 MB) and its PDS3 label ``ldem_16_float.lbl`` from the PDS
   Geosciences Node into data/raw/MOON-TOPO-02/ (skipped when the file is already there with the size
   the label promises). Provenance goes to data/raw/MOON-TOPO-02/source.json (the only file there
   that is committed).
2. Parse the label: LINES, LINE_SAMPLES, SAMPLE_TYPE/SAMPLE_BITS (byte order), SCALING_FACTOR, OFFSET,
   UNIT, and the IMAGE_MAP_PROJECTION geometry (MAP_RESOLUTION, MAXIMUM_LATITUDE,
   WESTERNMOST_LONGITUDE, CENTER_LONGITUDE, LINE/SAMPLE_PROJECTION_OFFSET). Nothing about the grid is
   hard-coded; the two ways the label gives the geometry are cross-checked.
3. Height of every pixel in metres relative to the 1737.4 km reference sphere:
   ``(DN * SCALING_FACTOR + OFFSET - 1737.4) * metres_per_unit`` (OFFSET is the reference radius).
4. Every pixel centre (longitude normalised from 0..360 to [-180, 180)) goes to the H3 resolution-5
   cell containing it. Cell value = mean of its pixels weighted by pixel area (cos latitude, since the
   grid is equirectangular; within one res-5 cell the weights are almost equal). ``count`` = pixels.
5. Parents (res 4..0) are area-weighted means of all their pixels, i.e. children combined with the
   same weights (count alone would overweight high latitudes, where pixels are smaller).
6. Write data/prepared/moon/h3/elevation.parquet (h3 uint64, res uint8, value float32, count uint32;
   sorted by h3, zstd) and merge the layer + source into data/prepared/moon/h3/layers.json.

Missing pixels (non-finite or the label's MISSING_CONSTANT) are skipped, never treated as zero; a cell
with no valid pixel centre has no row (null in the API). Res 5 is the finest level: with ~1.9 km
pixels a res-6 cell (~2.7 km²) holds less than one pixel, so the backend serves res-6 requests from
the res-5 parent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import ssl
import struct
import sys
import time
import urllib.request
from itertools import repeat
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from h3.api.basic_int import cell_to_parent, get_num_cells, latlng_to_cell

REPO = Path(__file__).resolve().parents[2]
SOURCE_ID = "MOON-TOPO-02"
LAYER_ID = "elevation"
BASE_URL = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/float_img/"
IMG_NAME = "ldem_16_float.img"
LBL_NAME = "ldem_16_float.lbl"
MOON_RADIUS_KM = 1737.4  # IAU_2015:30100 reference sphere (contract)
MAX_RES = 5
CHUNK_ROWS = 64

RAW_DIR = REPO / "data" / "raw" / SOURCE_ID
OUT_DIR = REPO / "data" / "prepared" / "moon" / "h3"

LICENCE = "U.S. public domain (NASA PDS)"
ATTRIBUTION = "LOLA team, NASA/GSFC; Smith et al. 2010/2017"
CITATION = (
    "Smith, D. E., et al. (2010), Initial observations from the Lunar Orbiter Laser Altimeter (LOLA), "
    "Geophys. Res. Lett. 37, L18204, doi:10.1029/2010GL043751. Smith, D. E., et al. (2017), Summary of the "
    "results from the Lunar Orbiter Laser Altimeter after seven years in lunar orbit, Icarus 283, 70-91, "
    "doi:10.1016/j.icarus.2016.06.006."
)
LIMITATIONS = [
    "16 pixels/degree grid (≈1.9 km pixels at the equator): values exist down to H3 resolution 5 only "
    "(~19 km² cells, about 5 pixels each near the equator); resolution-6 cells inherit their res-5 parent's value.",
    "Heights are relative to the 1737.4 km reference sphere (planetary radius − 1737.4 km), not a geoid or "
    "equipotential surface.",
    "Display/demo product: far too coarse for slopes, roughness or landing-site work. Use SLDEM2015 "
    "(MOON-TOPO-01, 59 m, ±60°) or LOLA LDEM 128 ppd (237 m) for slopes.",
    "Gaps between LOLA ground tracks are interpolated by the producer (GMT 'surface'); the label warns of "
    "possible edge artifacts at the 45° latitude band boundaries.",
    "Pixel-centre assignment; cell values are pixel-area-weighted (cos latitude) means, and parent cells "
    "are area-weighted means of all their pixels.",
]

# (lat, lon, label) spot checks printed after the run and stored in source.json.
SPOT_CHECKS = [
    (-43.31, -11.36, "Tycho centre (floor)"),
    (-41.90, -11.36, "Tycho north rim (~1.4° N of centre)"),
    (-44.72, -11.36, "Tycho south rim (~1.4° S of centre)"),
    (33.0, -16.0, "Mare Imbrium"),
    (28.0, 17.5, "Mare Serenitatis"),
    (8.5, 31.4, "Mare Tranquillitatis"),
    (5.7, -159.0, "Engelhardt area (highest terrain)"),
    (-70.4, -172.0, "Antoniadi crater floor (South Pole–Aitken, lowest terrain)"),
    (-53.0, -169.0, "South Pole–Aitken basin interior"),
    (-89.9, 0.0, "Near the south pole (Shackleton)"),
]


# --------------------------------------------------------------------------------------------- label


def parse_pds3_label(text: str) -> dict:
    """Minimal PDS3 ODL parser: nested OBJECT groups become nested dicts of raw value strings."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    root: dict = {}
    stack = [root]
    pending = ""
    for line in text.splitlines():
        stmt = (pending + "\n" + line) if pending else line
        if not stmt.strip():
            continue
        if "=" not in stmt:
            if stmt.strip() == "END":
                break
            continue
        key, _, value = stmt.partition("=")
        value = value.strip()
        unquoted = re.sub(r'"[^"]*"', "", value)
        unbalanced = (
            value.count('"') % 2 == 1
            or unquoted.count("{") > unquoted.count("}")
            or unquoted.count("(") > unquoted.count(")")
            or value == ""
        )
        if unbalanced:
            pending = stmt
            continue
        pending = ""
        key = key.strip()
        if key in ("OBJECT", "GROUP"):
            child: dict = {}
            stack[-1][value.strip('"')] = child
            stack.append(child)
        elif key in ("END_OBJECT", "END_GROUP"):
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1][key] = value
    return root


def find_object(node: dict, name: str, must_have: str) -> dict:
    for k, v in node.items():
        if isinstance(v, dict):
            if k == name and must_have in v:
                return v
            hit = _find(v, name, must_have)
            if hit is not None:
                return hit
    raise ValueError(f"label has no {name} object with {must_have}")


def _find(node: dict, name: str, must_have: str) -> dict | None:
    try:
        return find_object(node, name, must_have)
    except ValueError:
        return None


def text_value(raw: str) -> str:
    return " ".join(raw.strip().strip('"').strip("'").split())


def num_value(raw: str) -> float:
    """'16 <pix/deg>' -> 16.0; also handles PDS hex (16#FF7FFFFB#) as IEEE float32 bits."""
    s = re.sub(r"<[^>]*>", "", raw).strip().strip('"')
    m = re.fullmatch(r"16#([0-9A-Fa-f]+)#", s)
    if m:
        return struct.unpack(">f", bytes.fromhex(m.group(1).zfill(8)))[0]
    return float(s)


def unit_of(raw: str) -> str | None:
    m = re.search(r"<([^>]*)>", raw)
    return m.group(1) if m else None


SAMPLE_DTYPES = {
    ("PC_REAL", 32): "<f4",
    ("PC_REAL", 64): "<f8",
    ("IEEE_REAL", 32): ">f4",
    ("IEEE_REAL", 64): ">f8",
    ("REAL", 32): ">f4",
    ("MAC_REAL", 32): ">f4",
    ("SUN_REAL", 32): ">f4",
    ("LSB_INTEGER", 16): "<i2",
    ("LSB_INTEGER", 32): "<i4",
    ("MSB_INTEGER", 16): ">i2",
    ("MSB_INTEGER", 32): ">i4",
    ("LSB_UNSIGNED_INTEGER", 16): "<u2",
    ("MSB_UNSIGNED_INTEGER", 16): ">u2",
}
UNIT_TO_M = {"KILOMETER": 1000.0, "KILOMETERS": 1000.0, "KM": 1000.0, "METER": 1.0, "METERS": 1.0, "M": 1.0}


def read_label(path: Path) -> dict:
    lbl = parse_pds3_label(path.read_text(errors="replace"))
    img = find_object(lbl, "IMAGE", "LINES")
    proj = find_object(lbl, "IMAGE_MAP_PROJECTION", "MAP_RESOLUTION")

    sample_type = text_value(img["SAMPLE_TYPE"])
    bits = int(num_value(img["SAMPLE_BITS"]))
    dtype = SAMPLE_DTYPES.get((sample_type, bits))
    if dtype is None:
        raise ValueError(f"unsupported SAMPLE_TYPE/SAMPLE_BITS {sample_type}/{bits}")
    for k in ("LINE_PREFIX_BYTES", "LINE_SUFFIX_BYTES"):
        if k in img and int(num_value(img[k])) != 0:
            raise ValueError(f"{k} != 0 is not supported")
    unit = text_value(img.get("UNIT", '"KILOMETER"')).upper()
    if unit not in UNIT_TO_M:
        raise ValueError(f"unsupported height UNIT {unit}")

    # ^IMAGE = "FILE.IMG" or ("FILE.IMG", <record>) or <record>: byte offset of the first line.
    pointer = lbl.get("^IMAGE") or (_find(lbl, "UNCOMPRESSED_FILE", "^IMAGE") or {}).get("^IMAGE") or ""
    offset_bytes = 0
    rec_match = re.search(r",\s*(\d+)\s*(<BYTES>)?\s*\)", pointer) or re.fullmatch(r"\s*(\d+)\s*(<BYTES>)?\s*", pointer)
    if rec_match:
        rec = int(rec_match.group(1))
        holder = lbl if "RECORD_BYTES" in lbl else (_find(lbl, "UNCOMPRESSED_FILE", "RECORD_BYTES") or {})
        if not rec_match.group(2) and "RECORD_BYTES" not in holder:
            raise ValueError("^IMAGE is a record pointer but the label has no RECORD_BYTES")
        offset_bytes = rec - 1 if rec_match.group(2) else (rec - 1) * int(num_value(holder["RECORD_BYTES"]))

    missing = None
    for k in ("MISSING_CONSTANT", "NULL", "INVALID_CONSTANT"):
        if k in img:
            missing = num_value(img[k])
            break

    out = {
        "productId": text_value(lbl.get("PRODUCT_ID", "")),
        "productVersionId": text_value(lbl.get("PRODUCT_VERSION_ID", "")),
        "dataSetId": text_value(lbl.get("DATA_SET_ID", "")),
        "productCreationTime": text_value(lbl.get("PRODUCT_CREATION_TIME", "")),
        "startTime": text_value(lbl.get("START_TIME", "")),
        "stopTime": text_value(lbl.get("STOP_TIME", "")),
        "lines": int(num_value(img["LINES"])),
        "lineSamples": int(num_value(img["LINE_SAMPLES"])),
        "sampleType": sample_type,
        "sampleBits": bits,
        "numpyDtype": dtype,
        "unit": unit,
        "scalingFactor": num_value(img.get("SCALING_FACTOR", "1")),
        "offset": num_value(img.get("OFFSET", "0")),
        "labelMinimum": num_value(img["MINIMUM"]) if "MINIMUM" in img else None,
        "labelMaximum": num_value(img["MAXIMUM"]) if "MAXIMUM" in img else None,
        "missingConstant": missing,
        "imageOffsetBytes": offset_bytes,
        "mapProjectionType": text_value(proj["MAP_PROJECTION_TYPE"]),
        "mapResolutionPixPerDeg": num_value(proj["MAP_RESOLUTION"]),
        "mapScaleKmPerPix": num_value(proj["MAP_SCALE"]) if "MAP_SCALE" in proj else None,
        "aAxisRadiusKm": num_value(proj["A_AXIS_RADIUS"]),
        "maximumLatitude": num_value(proj["MAXIMUM_LATITUDE"]),
        "minimumLatitude": num_value(proj["MINIMUM_LATITUDE"]),
        "westernmostLongitude": num_value(proj["WESTERNMOST_LONGITUDE"]),
        "easternmostLongitude": num_value(proj["EASTERNMOST_LONGITUDE"]),
        "centerLatitude": num_value(proj.get("CENTER_LATITUDE", "0")),
        "centerLongitude": num_value(proj["CENTER_LONGITUDE"]),
        "lineProjectionOffset": num_value(proj["LINE_PROJECTION_OFFSET"]) if "LINE_PROJECTION_OFFSET" in proj else None,
        "sampleProjectionOffset": num_value(proj["SAMPLE_PROJECTION_OFFSET"]) if "SAMPLE_PROJECTION_OFFSET" in proj else None,
        "positiveLongitudeDirection": text_value(proj.get("POSITIVE_LONGITUDE_DIRECTION", "EAST")).upper(),
        "coordinateSystemName": text_value(proj.get("COORDINATE_SYSTEM_NAME", "")),
    }
    return out


def grid_geometry(p: dict) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre latitudes (per line) and longitudes in [-180, 180) (per sample) from the label."""
    if p["mapProjectionType"] not in ("SIMPLE CYLINDRICAL", "EQUIRECTANGULAR") or p["centerLatitude"] != 0:
        raise ValueError(f"unsupported projection {p['mapProjectionType']} (centre lat {p['centerLatitude']})")
    if p["positiveLongitudeDirection"] != "EAST":
        raise ValueError("only POSITIVE_LONGITUDE_DIRECTION = EAST is supported")
    if abs(p["aAxisRadiusKm"] - MOON_RADIUS_KM) > 1e-6:
        print(f"warning: label radius {p['aAxisRadiusKm']} km != {MOON_RADIUS_KM} km", file=sys.stderr)
    ppd = p["mapResolutionPixPerDeg"]
    lines, samples = p["lines"], p["lineSamples"]
    # Pixel registration: line i (0-based) spans MAXIMUM_LATITUDE - [i, i+1] / ppd.
    lat = p["maximumLatitude"] - (np.arange(lines) + 0.5) / ppd
    lon360 = p["westernmostLongitude"] + (np.arange(samples) + 0.5) / ppd
    # Cross-check with the PDS projection-offset form: line = LOFF - lat*ppd, sample = SOFF + (lon - CLON)*ppd.
    if p["lineProjectionOffset"] is not None:
        alt_lat = (p["lineProjectionOffset"] - np.arange(lines)) / ppd
        assert np.allclose(lat, alt_lat, atol=0.01 / ppd), "LINE_PROJECTION_OFFSET disagrees with MAXIMUM_LATITUDE"
    if p["sampleProjectionOffset"] is not None:
        alt_lon = p["centerLongitude"] + (np.arange(samples) - p["sampleProjectionOffset"]) / ppd
        assert np.allclose(lon360, alt_lon, atol=0.01 / ppd), "SAMPLE_PROJECTION_OFFSET disagrees with WESTERNMOST_LONGITUDE"
    assert abs(lines / ppd - (p["maximumLatitude"] - p["minimumLatitude"])) < 1e-9, "LINES do not span the latitude range"
    assert abs(samples / ppd - (p["easternmostLongitude"] - p["westernmostLongitude"])) < 1e-9, "samples do not span the longitude range"
    lon = (lon360 + 180.0) % 360.0 - 180.0
    return lat, lon


# ------------------------------------------------------------------------------------------ download


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _ssl_context() -> ssl.SSLContext:
    # uv-managed Pythons may not see the system CA store; certifi (via httpx) is in the backend env.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url: str, dest: Path, attempts: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    ctx = _ssl_context()
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "newworlds-data-prep/1.0"})
            with urllib.request.urlopen(req, timeout=120, context=ctx) as r, tmp.open("wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
                    got += len(block)
                if total and got != total:
                    raise OSError(f"short read {got}/{total} bytes")
            tmp.replace(dest)
            print(f"downloaded {url} -> {dest.relative_to(REPO)} ({dest.stat().st_size:,} bytes)", flush=True)
            return
        except OSError as exc:
            print(f"download attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt == attempts:
                raise
            time.sleep(3 * attempt)


# --------------------------------------------------------------------------------------- aggregation

_RES_SHIFT = np.uint64(52)
_RES_MASK = np.uint64(0xF) << _RES_SHIFT


def parent_index(cells: np.ndarray, res: int) -> np.ndarray:
    """Vectorised H3 cell_to_parent for sorted uint64 cells at a finer resolution (order-preserving)."""
    low = (np.uint64(1) << np.uint64(3 * (15 - res))) - np.uint64(1)
    return (cells & ~_RES_MASK & ~low) | (np.uint64(res) << _RES_SHIFT) | low


def group_sums(keys: np.ndarray, *cols: np.ndarray) -> tuple[np.ndarray, ...]:
    """Sum each column per distinct key; keys need not be sorted."""
    if not np.all(keys[:-1] <= keys[1:]):
        order = np.argsort(keys, kind="stable")
        keys = keys[order]
        cols = tuple(c[order] for c in cols)
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    return (keys[starts], *(np.add.reduceat(c, starts) for c in cols))


def aggregate(heights_m: np.ndarray, lat: np.ndarray, lon: np.ndarray, missing_mask: np.ndarray) -> dict[int, tuple]:
    """Per-resolution (keys, sum_w*v, sum_w, n) for res MAX_RES..0."""
    lines, samples = heights_m.shape
    parts_k, parts_wv, parts_w, parts_n = [], [], [], []
    lon_list = lon.tolist()
    t0 = time.time()
    for r0 in range(0, lines, CHUNK_ROWS):
        r1 = min(lines, r0 + CHUNK_ROWS)
        block = heights_m[r0:r1]
        valid = ~missing_mask[r0:r1]
        lat_rows = lat[r0:r1]
        n_pix = (r1 - r0) * samples
        lat_flat = np.repeat(lat_rows, samples).tolist()
        lon_flat = lon_list * (r1 - r0)
        cells = np.fromiter(map(latlng_to_cell, lat_flat, lon_flat, repeat(MAX_RES)), dtype=np.uint64, count=n_pix)
        w = np.repeat(np.cos(np.radians(lat_rows)), samples)
        v = block.reshape(-1)
        ok = valid.reshape(-1)
        k, swv, sw, n = group_sums(cells[ok], w[ok] * v[ok], w[ok], np.ones(int(ok.sum()), dtype=np.int64))
        parts_k.append(k)
        parts_wv.append(swv)
        parts_w.append(sw)
        parts_n.append(n)
        if (r0 // CHUNK_ROWS) % 10 == 0:
            print(f"  rows {r0:>5}/{lines}  {time.time() - t0:5.1f}s", flush=True)
    keys, swv, sw, n = group_sums(np.concatenate(parts_k), np.concatenate(parts_wv), np.concatenate(parts_w), np.concatenate(parts_n))
    levels = {MAX_RES: (keys, swv, sw, n)}
    for res in range(MAX_RES - 1, -1, -1):
        pk = parent_index(keys, res)  # monotone, so still sorted
        levels[res] = group_sums(pk, swv, sw, n)
    return levels


# -------------------------------------------------------------------------------------------- output


def write_parquet(levels: dict[int, tuple], path: Path) -> pa.Table:
    ks, rs, vs, cs = [], [], [], []
    for res in sorted(levels):
        k, swv, sw, n = levels[res]
        ks.append(k)
        rs.append(np.full(len(k), res, dtype=np.uint8))
        vs.append(np.where(sw > 0, swv / np.where(sw > 0, sw, 1), np.nan).astype(np.float32))
        cs.append(n.astype(np.uint32))
    keys = np.concatenate(ks)
    order = np.argsort(keys, kind="stable")
    table = pa.table(
        {
            "h3": pa.array(keys[order], type=pa.uint64()),
            "res": pa.array(np.concatenate(rs)[order], type=pa.uint8()),
            "value": pa.array(np.concatenate(vs)[order], type=pa.float32()),
            "count": pa.array(np.concatenate(cs)[order], type=pa.uint32()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(
        table,
        tmp,
        compression="zstd",
        compression_level=9,
        use_dictionary=["res"],
        use_byte_stream_split=["value"],
        row_group_size=262_144,
    )
    tmp.replace(path)
    return table


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def lookup(levels: dict[int, tuple], res: int, cell: int) -> tuple[float | None, int]:
    k, swv, sw, n = levels[res]
    i = int(np.searchsorted(k, np.uint64(cell)))
    if i < len(k) and k[i] == cell and sw[i] > 0:
        return float(swv[i] / sw[i]), int(n[i])
    return None, 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force-download", action="store_true", help="download again even if the files exist")
    a = ap.parse_args()
    t_start = time.time()

    img_url, lbl_url = BASE_URL + IMG_NAME, BASE_URL + LBL_NAME
    img_path, lbl_path = RAW_DIR / IMG_NAME, RAW_DIR / LBL_NAME
    prev_source = {}
    if (RAW_DIR / "source.json").exists():
        try:
            prev_source = json.loads((RAW_DIR / "source.json").read_text())
        except ValueError:
            prev_source = {}

    if a.force_download or not lbl_path.exists():
        download(lbl_url, lbl_path)
    p = read_label(lbl_path)
    dtype = np.dtype(p["numpyDtype"])
    expected = p["imageOffsetBytes"] + p["lines"] * p["lineSamples"] * dtype.itemsize
    if a.force_download or not img_path.exists() or img_path.stat().st_size < expected:
        download(img_url, img_path)
    if img_path.stat().st_size < expected:
        sys.exit(f"{img_path} is {img_path.stat().st_size} bytes, label needs {expected}")
    t_dl = time.time()

    print("label:", json.dumps({k: p[k] for k in (
        "productId", "productVersionId", "lines", "lineSamples", "sampleType", "sampleBits", "unit",
        "scalingFactor", "offset", "missingConstant", "mapResolutionPixPerDeg", "maximumLatitude",
        "westernmostLongitude", "centerLongitude", "lineProjectionOffset", "sampleProjectionOffset")}))

    lat, lon = grid_geometry(p)
    dn = np.fromfile(img_path, dtype=dtype, count=p["lines"] * p["lineSamples"], offset=p["imageOffsetBytes"])
    dn = dn.reshape(p["lines"], p["lineSamples"]).astype(np.float64)
    missing = ~np.isfinite(dn)
    if p["missingConstant"] is not None:
        missing |= dn == p["missingConstant"]
    heights_m = (dn * p["scalingFactor"] + p["offset"] - MOON_RADIUS_KM) * UNIT_TO_M[p["unit"]]
    heights_m[missing] = np.nan
    print(f"pixels {dn.size:,}  missing {int(missing.sum()):,}  height range {np.nanmin(heights_m):.1f} .. {np.nanmax(heights_m):.1f} m")

    print(f"assigning pixel centres to H3 res {MAX_RES} …", flush=True)
    t_agg = time.time()
    levels = aggregate(heights_m, lat, lon, missing)
    t_agg = time.time() - t_agg

    # Spot-check the vectorised parent against h3 itself.
    k5 = levels[MAX_RES][0]
    sample = k5[:: max(1, len(k5) // 997)]
    for res in range(MAX_RES):
        assert np.array_equal(parent_index(sample, res), np.array([cell_to_parent(int(c), res) for c in sample], dtype=np.uint64))

    out_parquet = OUT_DIR / f"{LAYER_ID}.parquet"
    table = write_parquet(levels, out_parquet)

    v5 = levels[MAX_RES][1] / levels[MAX_RES][2]
    n5 = levels[MAX_RES][3]
    p1, p99 = (float(x) for x in np.quantile(v5, [0.01, 0.99]))
    rng = [math.floor(p1 / 10) * 10, math.ceil(p99 / 10) * 10]
    total5 = get_num_cells(MAX_RES)
    stats = {
        "pixels": int(dn.size),
        "missingPixels": int(missing.sum()),
        "pixelMinM": round(float(np.nanmin(heights_m)), 1),
        "pixelMaxM": round(float(np.nanmax(heights_m)), 1),
        "res5Cells": int(len(v5)),
        "res5CellsTotal": int(total5),
        "res5CellsWithoutPixel": int(total5 - len(v5)),
        "res5MinM": round(float(v5.min()), 1),
        "res5MaxM": round(float(v5.max()), 1),
        "res5P01M": round(p1, 1),
        "res5P99M": round(p99, 1),
        "res5MeanPixelsPerCell": round(float(n5.mean()), 2),
        "res5MinPixelsPerCell": int(n5.min()),
        "globalAreaWeightedMeanM": round(float(levels[0][1].sum() / levels[0][2].sum()), 1),
        "rows": table.num_rows,
        "rowsPerResolution": {str(r): int(len(levels[r][0])) for r in sorted(levels)},
    }

    spots = []
    for la, lo, name in SPOT_CHECKS:
        cell = latlng_to_cell(la, lo, MAX_RES)
        val, n = lookup(levels, MAX_RES, cell)
        i = min(p["lines"] - 1, max(0, int((p["maximumLatitude"] - la) * p["mapResolutionPixPerDeg"])))
        j = int(((lo - p["westernmostLongitude"]) % 360.0) * p["mapResolutionPixPerDeg"]) % p["lineSamples"]
        spots.append({"name": name, "lat": la, "lon": lo, "h3": format(cell, "x"),
                      "res5MeanM": None if val is None else round(val, 1), "pixels": n,
                      "pixelM": round(float(heights_m[i, j]), 1)})

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    files = []
    for path, url in ((img_path, img_url), (lbl_path, lbl_url)):
        files.append({"path": path.name, "url": url, "bytes": path.stat().st_size, "sha256": sha256_of(path)})
    prev_files = {f.get("path"): f.get("sha256") for f in prev_source.get("files", [])}
    unchanged = all(prev_files.get(f["path"]) == f["sha256"] for f in files)
    retrieved = prev_source.get("retrievedAt") if unchanged and prev_source.get("retrievedAt") else now

    source_record = {
        "id": f"{SOURCE_ID}-ldem16-global-{retrieved[:10].replace('-', '')}",
        "catalogueSourceId": SOURCE_ID,
        "body": "moon",
        "provider": "NASA PDS Geosciences Node; LRO Lunar Orbiter Laser Altimeter (LOLA) team, NASA GSFC",
        "product": "LOLA Gridded Data Record LDEM_16_FLOAT: global lunar DEM, 16 pixels/degree, float32 heights in km",
        "dataSetId": p["dataSetId"],
        "productId": p["productId"],
        "version": p["productVersionId"],
        "productCreationTime": p["productCreationTime"],
        "observationPeriod": [p["startTime"], p["stopTime"]],
        "documentationUrl": "https://pds-geosciences.wustl.edu/missions/lro/lola.htm",
        "accessUrl": img_url,
        "labelUrl": lbl_url,
        "accessMethod": "download (HTTPS, PDS Geosciences Node)",
        "evidenceType": "orbital_retrieval",
        "licence": {
            "name": LICENCE,
            "attribution": ATTRIBUTION,
            "notes": "US-government work, no copyright; credit requested. Cite the LOLA product papers.",
            "reviewedAt": now[:10],
        },
        "citation": CITATION,
        "region": "global",
        "frame": f"IAU_2015:30100 Moon Mean-Earth, planetocentric, east-positive (label: {p['coordinateSystemName']}), "
                 f"reference sphere {MOON_RADIUS_KM} km",
        "label": p,
        "processing": (
            "scripts/moon/prepare_moon_elevation.py: height_m = (DN*SCALING_FACTOR + OFFSET - 1737.4 km) * 1000; "
            "pixel centres from the label (pixel-registered simple cylindrical grid), longitudes normalised to "
            "[-180, 180); each pixel centre assigned to its H3 res-5 cell (h3-py latlng_to_cell); cell value = "
            "cos(latitude)-weighted mean of its pixels; res 4..0 = area-weighted means of all pixels below them. "
            "Missing pixels skipped, never zero."
        ),
        "outputs": [str(out_parquet.relative_to(REPO)), str((OUT_DIR / "layers.json").relative_to(REPO))],
        "stats": stats,
        "spotChecks": spots,
        "retrievedAt": retrieved,
        "preparedAt": now,
        "files": files,
    }
    write_json(RAW_DIR / "source.json", source_record)

    layer_entry = {
        "id": LAYER_ID,
        "name": "Elevation (LOLA)",
        "unit": "m",
        "description": (
            "Mean surface height in each H3 cell relative to the 1737.4 km lunar reference sphere, from the "
            "LOLA LDEM 16 pixels/degree global grid (≈1.9 km pixels)."
        ),
        "sourceId": SOURCE_ID,
        "evidenceType": "orbital_retrieval",
        "file": out_parquet.name,
        "maxResolution": MAX_RES,
        "nativeResolutionKm": round(p["mapScaleKmPerPix"] or (math.pi * MOON_RADIUS_KM / 180 / p["mapResolutionPixPerDeg"]), 2),
        "aggregation": "mean",
        "range": rng,
        "rangeMethod": "1st and 99th percentiles of the res-5 cell means, rounded outward to 10 m",
        "extent": [stats["res5MinM"], stats["res5MaxM"]],
        "palette": "terrain",
        "limitations": LIMITATIONS,
    }
    source_entry = {
        "id": SOURCE_ID,
        "name": f"LOLA LDEM 16 ppd global DEM ({p['productId']} {p['productVersionId']})",
        "provider": "NASA PDS Geosciences Node / LRO LOLA team (NASA GSFC)",
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "evidenceType": "orbital_retrieval",
        "url": img_url,
        "labelUrl": lbl_url,
        "retrievedAt": retrieved,
        "limitations": LIMITATIONS,
        "commercialUse": True,
    }
    layers_path = OUT_DIR / "layers.json"
    catalogue = {"layers": [], "sources": {}}
    if layers_path.exists():
        try:
            catalogue = json.loads(layers_path.read_text())
        except ValueError:
            pass
    catalogue["layers"] = sorted([l for l in catalogue.get("layers", []) if l.get("id") != LAYER_ID] + [layer_entry], key=lambda l: l["id"])
    catalogue.setdefault("sources", {})[SOURCE_ID] = source_entry
    write_json(layers_path, catalogue)

    print(json.dumps(stats, indent=1))
    print(f"{'spot check':<58} {'res-5 mean':>11} {'pixel':>9} {'n':>4}")
    for s in spots:
        mean = "null" if s["res5MeanM"] is None else f"{s['res5MeanM']:.0f} m"
        print(f"{s['name']:<58} {mean:>11} {s['pixelM']:>7.0f} m {s['pixels']:>4}")
    size = out_parquet.stat().st_size
    print(f"wrote {out_parquet.relative_to(REPO)} ({size / 1e6:.1f} MB, {table.num_rows:,} rows), "
          f"{layers_path.relative_to(REPO)}, {(RAW_DIR / 'source.json').relative_to(REPO)}")
    print(f"range {rng} m; download {t_dl - t_start:.1f}s, aggregation {t_agg:.1f}s, total {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
