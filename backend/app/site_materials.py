"""Where a building's raw materials could come from, read from the hexagons (no user input).

Each declared material (``BuildingStats.materials``) is matched by name to one or more raw-material
classes (concrete → aggregate + limestone, steel → iron ore, …). For each class the source hexagons
are the resolution-6 cells that hold a record of it:

- USGS MRDS mineral sites [GEO-06], snapped to their res-6 cell. Producers, past producers and
  plants count as *producing* sources; occurrences and prospects only as *recorded deposits*.
- EMIT L3 surface mineral abundance [GEO-01] at the building's own cell (calcite/dolomite for
  limestone, kaolinite/montmorillonite for clay, gypsum): a surface exposure, never a quarry.
- WorldCover tree cover [LAND-02] for timber: cells with at least ``FOREST_SHARE`` tree cover.

Raw materials can be shipped, unlike land, water or a grid connection, so these checks are
**advisory** (``required = False``): they say whether a class is available within its typical haul
distance (``reach_km``; bulk aggregates travel less than metals) or would have to be brought in,
and never make a site unbuildable. Hexagon records show where a material occurs, not how many tonnes
can be supplied, so quantities are not compared and other scenario buildings do not use them up.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import h3
import h3.api.numpy_int as h3n
import numpy as np
import pyarrow.parquet as pq

from app import features, h3store, layers, regions
from app.building_models import CheckResult, SiteResource, SiteResourcePart

PRODUCING = {"Producer", "Past Producer", "Plant"}
FOREST_SHARE = 0.3  # WorldCover tree share for a cell to count as a timber source
EARTH_KM = 6371.0088


@dataclass(frozen=True)
class MaterialClass:
    key: str
    label: str
    names: tuple[str, ...]  # words in a material's name that select this class
    mrds: tuple[str, ...] = ()  # MRDS commodity prefixes (case-insensitive)
    emit: tuple[str, ...] = ()  # EMIT columns whose summed abundance indicates a surface exposure
    emit_min: float = 0.0
    forest: bool = False
    reach_km: float = 300.0


# Typical economic haul distance (km) is an implementation default shown with every result:
# bulk construction minerals are rarely trucked further than ~50–100 km; ores and metals are traded
# regionally. Order matters only for display.
CLASSES = (
    MaterialClass("aggregate", "Sand, gravel and crushed stone",
                  ("sand", "gravel", "aggregate", "crushed stone", "ballast", "fill", "concrete", "asphalt", "rock"),
                  ("Sand and Gravel; Construction", "Stone; Crushed", "Sand", "Gravel", "Stone", "Granite",
                   "Volcanic Materials", "Pumice", "Basalt", "Trap Rock", "Sandstone"), reach_km=50.0),
    MaterialClass("limestone", "Limestone (cement and lime)",
                  ("cement", "concrete", "lime", "limestone", "clinker", "mortar", "chalk"),
                  ("Limestone", "Calcium", "Cement", "Dolomite", "Marble", "Chalk"),
                  emit=("calcite", "dolomite"), emit_min=0.25, reach_km=150.0),
    MaterialClass("clay", "Clay (bricks, ceramics)", ("clay", "brick", "ceramic", "tile", "kaolin", "bentonite"),
                  ("Clay", "Fire Clay", "Ball Clay", "Kaolin", "Bentonite", "Shale"),
                  emit=("kaolinite", "montmorillonite"), emit_min=0.1, reach_km=100.0),
    MaterialClass("gypsum", "Gypsum (plaster, plasterboard)", ("gypsum", "plaster", "drywall", "plasterboard"),
                  ("Gypsum",), emit=("gypsum",), emit_min=0.1, reach_km=150.0),
    MaterialClass("silica", "Silica sand (glass, solar panels)", ("glass", "silica", "quartz", "silicon", "solar panel", "pv module"),
                  ("Silica", "Sand and Gravel; Industrial", "Quartz", "Silicon"), reach_km=300.0),
    MaterialClass("iron", "Iron ore (steel)", ("steel", "iron", "rebar"), ("Iron",), reach_km=300.0),
    MaterialClass("copper", "Copper", ("copper", "cable", "wiring"), ("Copper",), reach_km=300.0),
    MaterialClass("aluminium", "Aluminium (bauxite)", ("aluminium", "aluminum", "bauxite"), ("Aluminum", "Bauxite"),
                  reach_km=300.0),
    MaterialClass("uranium", "Uranium", ("uranium", "nuclear fuel"), ("Uranium",), reach_km=300.0),
    MaterialClass("timber", "Timber", ("timber", "wood", "lumber", "plywood", "glulam", "clt"), forest=True,
                  reach_km=100.0),
)
BY_KEY = {c.key: c for c in CLASSES}

# Any other material named exactly like an MRDS commodity ("Zinc", "Lithium", "Salt") is matched to it.
GENERIC_REACH_KM = 300.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _word_in(word: str, text: str) -> bool:
    return re.search(rf"(^| ){re.escape(word)}s?( |$)", text) is not None


@lru_cache(maxsize=1)
def _commodity_names() -> dict[str, str]:
    """Lower-case → as-written MRDS commodity tokens (split on ';' where the token is a single name)."""
    idx = _mrds_index()
    return {} if idx is None else {t.lower(): t for t in idx.tokens}


def classes_for(name: str) -> list[MaterialClass]:
    """Raw-material classes a declared material draws on. Empty = not a mapped raw material."""
    n = _norm(name)
    out = [c for c in CLASSES if any(_word_in(_norm(w), n) for w in c.names)]
    if out:
        return out
    token = _commodity_names().get(n) or _commodity_names().get(n.rstrip("s"))
    if token:
        return [MaterialClass(f"mrds:{token.lower()}", token, (n,), (token,), reach_km=GENERIC_REACH_KM)]
    return []


# --- hexagon index of MRDS sites --------------------------------------------------------------


@dataclass
class _MrdsIndex:
    cells: np.ndarray  # res-6 cell of every site
    lat: np.ndarray
    lon: np.ndarray
    producing: np.ndarray  # bool
    commodities: list[str]  # lower-case primary commodities "a; b"
    names: list[str]
    tokens: tuple[str, ...]


@lru_cache(maxsize=2)
def _load_mrds(path: str, _mtime: float) -> _MrdsIndex:
    t = pq.read_table(path, columns=["lat", "lon", "name", "commodities", "primaryCommodities", "devStatus"])
    lat = t.column("lat").to_numpy(zero_copy_only=False).astype(np.float64)
    lon = t.column("lon").to_numpy(zero_copy_only=False).astype(np.float64)
    cells = np.array([h3n.latlng_to_cell(a, b, h3store.SIM_RES) for a, b in zip(lat, lon)], dtype=np.uint64)
    # Match on what a site mainly produces: its primary commodities, else the first one listed. A gold
    # mine that lists iron as a by-product is not an iron-ore source.
    primary = t.column("primaryCommodities").to_pylist()
    commodities = [(p or (c or "").split(";")[0]).lower() for p, c in zip(primary, t.column("commodities").to_pylist())]
    status = t.column("devStatus").to_pylist()
    tokens = sorted({x.strip() for c in t.column("commodities").to_pylist() for x in (c or "").split(";") if x.strip()})
    return _MrdsIndex(
        cells=cells, lat=lat, lon=lon,
        producing=np.array([s in PRODUCING for s in status]),
        commodities=commodities, names=[n or "(unnamed)" for n in t.column("name").to_pylist()],
        tokens=tuple(tokens),
    )


def _mrds_index() -> _MrdsIndex | None:
    meta = features.layer_meta("mrds")
    if meta is None or not features.available(meta):
        return None
    p = features.file_path(meta)
    return _load_mrds(str(p), p.stat().st_mtime)


@lru_cache(maxsize=64)
def _class_sites(key: str, mrds: tuple[str, ...]) -> np.ndarray:
    """Indexes of MRDS sites listing any of the class's commodities."""
    idx = _mrds_index()
    if idx is None or not mrds:
        return np.zeros(0, dtype=np.intp)
    prefixes = tuple(m.lower() for m in mrds)
    hit = [i for i, c in enumerate(idx.commodities)
           if any(part.strip().startswith(prefixes) for part in c.split(";"))]
    return np.array(hit, dtype=np.intp)


@lru_cache(maxsize=4)
def _forest_cells(_key: tuple) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Res-6 cells (with centres) whose WorldCover tree share is ≥ FOREST_SHARE, all prepared regions."""
    root = Path(layers.settings.prepared_data_dir)
    keys, shares = [], []
    for r in layers.REGIONS:
        p = root / f"worldcover_{r}_h3r6.parquet"
        if p.exists():
            t = pq.read_table(p, columns=["h3", "frac_tree"])
            k = t.column("h3").to_numpy(zero_copy_only=False).astype(np.int64).view(np.uint64)
            v = t.column("frac_tree").to_numpy(zero_copy_only=False).astype(np.float64)
            keys.append(k[v >= FOREST_SHARE])
            shares.append(v[v >= FOREST_SHARE])
    if not keys:
        return np.zeros(0, dtype=np.uint64), np.zeros(0), np.zeros(0)
    cells = np.concatenate(keys)
    ll = np.array([h3.cell_to_latlng(h3store.cell_hex(c)) for c in cells]).reshape(-1, 2)
    return cells, ll[:, 0], ll[:, 1]


def _forest() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    root = Path(layers.settings.prepared_data_dir)
    key = tuple((r, (root / f"worldcover_{r}_h3r6.parquet").stat().st_mtime)
                for r in layers.REGIONS if (root / f"worldcover_{r}_h3r6.parquet").exists())
    return _forest_cells(key)


# --- nearest source per centre cell -----------------------------------------------------------


def _nearest(lats: np.ndarray, lons: np.ndarray, s_lat: np.ndarray, s_lon: np.ndarray,
             reach_km: float) -> tuple[np.ndarray, np.ndarray]:
    """(distance km, index into sources) of the nearest source within reach; inf / -1 when none.

    Distances are between hexagon centres (great-circle). Sources are pre-filtered to the centres'
    bounding box plus the reach, and centres are processed in chunks to bound memory."""
    n = len(lats)
    dist = np.full(n, np.inf)
    which = np.full(n, -1, dtype=np.intp)
    if n == 0 or len(s_lat) == 0:
        return dist, which
    dlat = reach_km / 111.0
    coslat = max(0.05, math.cos(math.radians(min(85.0, max(abs(lats.min()), abs(lats.max())) + dlat))))
    dlon = min(180.0, reach_km / (111.0 * coslat))
    keep = (s_lat >= lats.min() - dlat) & (s_lat <= lats.max() + dlat)
    if dlon < 180.0 and lons.max() - lons.min() < 180.0:
        keep &= (s_lon >= lons.min() - dlon) & (s_lon <= lons.max() + dlon)
    cand = np.flatnonzero(keep)
    if not len(cand):
        return dist, which
    la2, lo2 = np.radians(s_lat[cand]), np.radians(s_lon[cand])
    step = max(1, 4_000_000 // len(cand))
    for a in range(0, n, step):
        la1 = np.radians(lats[a:a + step])[:, None]
        lo1 = np.radians(lons[a:a + step])[:, None]
        h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        d = 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
        j = np.argmin(d, axis=1)
        best = d[np.arange(len(j)), j]
        ok = best <= reach_km
        dist[a:a + step] = np.where(ok, best, np.inf)
        which[a:a + step] = np.where(ok, cand[j], -1)
    return dist, which


@dataclass
class ClassAvailability:
    cls: MaterialClass
    prod_km: np.ndarray  # nearest producing source within reach (inf = none)
    prod_name: list[str | None]
    deposit_km: np.ndarray  # nearest recorded deposit (occurrence/prospect) within reach
    deposit_name: list[str | None]
    surface: np.ndarray  # EMIT summed abundance at the cell (NaN = not imaged)
    us: np.ndarray  # cell is in the United States, where MRDS records are thorough
    has_data: bool


def _cell_centres(cells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ll = np.array([h3.cell_to_latlng(h3store.cell_hex(c)) for c in cells], dtype=np.float64).reshape(-1, 2)
    return ll[:, 0], ll[:, 1]


def availability(cls: MaterialClass, cells: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> ClassAvailability:
    """Nearest source hexagon of one raw-material class for each centre cell."""
    n = len(cells)
    c_lat, c_lon = _cell_centres(cells) if n else (np.zeros(0), np.zeros(0))
    none_km, none_names = np.full(n, np.inf), [None] * n
    surface = np.full(n, np.nan)
    us = np.zeros(n, dtype=bool)
    has_data = False
    prod_km, prod_name, dep_km, dep_name = none_km, none_names, none_km.copy(), list(none_names)

    if cls.forest:
        f_cells, f_lat, f_lon = _forest()
        has_data = len(f_cells) > 0
        d, w = _nearest(c_lat, c_lon, f_lat, f_lon, cls.reach_km)
        prod_km = d
        prod_name = [None if j < 0 else f"hexagon {h3store.cell_hex(f_cells[j])}" for j in w]
    elif cls.mrds:
        idx = _mrds_index()
        if idx is not None:
            has_data = True
            sites = _class_sites(cls.key, cls.mrds)
            # Snap sites to their hexagon: distances are measured between cell centres.
            s_cells = idx.cells[sites]
            s_lat, s_lon = _cell_centres(s_cells) if len(sites) else (np.zeros(0), np.zeros(0))
            prod = idx.producing[sites]
            d, w = _nearest(c_lat, c_lon, s_lat[prod], s_lon[prod], cls.reach_km)
            ps = sites[prod]
            prod_km, prod_name = d, [None if j < 0 else idx.names[ps[j]] for j in w]
            d2, w2 = _nearest(c_lat, c_lon, s_lat[~prod], s_lon[~prod], cls.reach_km)
            ds = sites[~prod]
            dep_km, dep_name = d2, [None if j < 0 else idx.names[ds[j]] for j in w2]
            us = np.array([iso == "USA" for iso in regions.country_iso(c_lat, c_lon)], dtype=bool)
    if cls.emit:
        src = layers.BY_ID.get("emit_minerals")
        vals = []
        for col in cls.emit:
            try:
                s = layers.source_for(src, src.slice(col)) if src else None
            except KeyError:
                s = None
            vals.append(np.full(n, np.nan) if s is None or n == 0
                        else h3store.lookup(s, h3store.SIM_RES, cells).astype(np.float64))
        surface = np.sum(vals, axis=0) if n else np.zeros(0)
    return ClassAvailability(cls, prod_km, prod_name, dep_km, dep_name, surface, us, has_data)


# --- checks -----------------------------------------------------------------------------------

PASS, FAIL, UNKNOWN = 0, 1, 2
_STATUS = ("pass", "fail", "unknown")
SOURCES = {
    "mrds": "USGS Mineral Resources Data System sites [GEO-06], snapped to their resolution-6 hexagon",
    "emit": "EMIT L3 surface mineral abundance [GEO-01] at this hexagon",
    "forest": f"ESA WorldCover 2021 tree cover ≥ {FOREST_SHARE * 100:.0f}% per hexagon [LAND-02]",
}


def class_status(a: ClassAvailability) -> np.ndarray:
    """pass = producing source within reach; unknown = only a deposit/surface exposure, or outside
    MRDS's thorough coverage; fail = none within reach where the records are thorough."""
    local = np.isfinite(a.prod_km)
    hint = np.isfinite(a.deposit_km) | (np.nan_to_num(a.surface) >= a.cls.emit_min if a.cls.emit else False)
    if a.cls.forest:
        covered = np.ones(len(local), dtype=bool) if a.has_data else np.zeros(len(local), dtype=bool)
    else:
        covered = a.us & a.has_data
    return np.where(local, PASS, np.where(hint | ~covered, UNKNOWN, FAIL)).astype(np.int8)


def _class_text(a: ClassAvailability, i: int, st: str) -> tuple[str, str]:
    c = a.cls
    reach = f"~{c.reach_km:.0f} km"
    if st == "pass":
        what = "forest" if c.forest else "producing site"
        text = f"{c.label}: {what} {a.prod_name[i]} ~{a.prod_km[i]:.0f} km away (within {reach})"
    else:
        bits = []
        if np.isfinite(a.deposit_km[i]):
            bits.append(f"a recorded deposit ({a.deposit_name[i]}, never produced) ~{a.deposit_km[i]:.0f} km away")
        if c.emit and not np.isnan(a.surface[i]) and a.surface[i] >= c.emit_min:
            bits.append(f"surface exposure here ({' + '.join(c.emit)} abundance {a.surface[i]:.2f}, surface only)")
        found = "; only " + " and ".join(bits) if bits else ""
        if st == "fail":
            text = f"{c.label}: no producing source within {reach}{found} — would be shipped in"
        elif not a.has_data:
            text = f"{c.label}: no hexagon data for this material"
        elif not c.forest and not a.us[i]:
            text = (f"{c.label}: no producing source recorded within {reach}{found} — MRDS records are incomplete "
                    "outside the United States, so a local source may exist")
        else:
            text = f"{c.label}: no producing source within {reach}{found} — likely shipped in"
    src = [SOURCES["forest"]] if c.forest else [SOURCES["mrds"]] + ([SOURCES["emit"]] if c.emit else [])
    return text, "; ".join(src)


@dataclass
class MaterialCheck:
    kind: str
    label: str
    status: np.ndarray
    build: object  # Callable[[int], CheckResult]
    required: bool = False


def material_checks(materials: list[tuple[str, str, float | None]], cells: np.ndarray, lats: np.ndarray,
                    lons: np.ndarray) -> tuple[list[MaterialCheck], list[str], dict[str, ClassAvailability]]:
    """One advisory check per declared material. Returns (checks, materials not mapped, availability by class)."""
    cache: dict[str, ClassAvailability] = {}
    checks: list[MaterialCheck] = []
    unmapped: list[str] = []
    seen: set[str] = set()
    for name, phase, qty in materials:
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        classes = classes_for(name)
        if not classes:
            unmapped.append(name)
            continue
        avs = []
        for c in classes:
            if c.key not in cache:
                cache[c.key] = availability(c, cells, lats, lons)
            avs.append(cache[c.key])
        per = np.stack([class_status(a) for a in avs])
        # The material is local only if every raw material it needs is; a fail outranks unknown.
        status = np.where((per == FAIL).any(axis=0), FAIL,
                          np.where((per == UNKNOWN).any(axis=0), UNKNOWN, PASS)).astype(np.int8)
        label = f"{name}: raw materials sourced nearby"

        def build(i: int, name=name, phase=phase, qty=qty, avs=avs, per=per, status=status, label=label) -> CheckResult:
            st = _STATUS[status[i]]
            texts, srcs = zip(*[_class_text(a, i, _STATUS[per[k, i]]) for k, a in enumerate(avs)])
            amount = "" if qty is None else f" ({qty:,.0f} kg, {phase})"
            head = {"pass": f"{name}{amount} can be sourced locally.",
                    "fail": f"{name}{amount} would have to be shipped in.",
                    "unknown": f"{name}{amount}: a local source is uncertain."}[st]
            return CheckResult(
                criterion_id=f"auto-material-{_norm(name).replace(' ', '-')[:40]}", kind="site_material",
                label=label, required=False, status=st, actual=qty, unit="kg", source="; ".join(dict.fromkeys(srcs)),
                explanation=f"{head} " + ". ".join(texts) + ". Advisory only: raw materials can be transported, "
                "so this never blocks building here. Hexagon records show where a material occurs, not how "
                "many tonnes it can supply.")

        checks.append(MaterialCheck("site_material", label, status, build))
    return checks, unmapped, cache


def material_resource(materials: list[tuple[str, str, float | None]], checks: list[MaterialCheck],
                      unmapped: list[str], i: int) -> SiteResource | None:
    """Summary of local sourcing for the site panel (advisory)."""
    if not materials:
        return None
    built = [c.build(i) for c in checks]
    local = sum(c.status == "pass" for c in built)
    shipped = [c.label.split(":")[0] for c in built if c.status == "fail"]
    parts = [SiteResourcePart(label=c.label.split(":")[0], text={"pass": "local source",
                                                                  "fail": "shipped in",
                                                                  "unknown": "uncertain"}[c.status])
             for c in built]
    parts += [SiteResourcePart(label=n, text="not a mapped raw material") for n in unmapped]
    if not built:
        status = "none"
    elif shipped:
        status = "advisory"
    elif local == len(built):
        status = "pass"
    else:
        status = "unknown"
    reaches = sorted({int(a.reach_km) for n, _, _ in materials for a in classes_for(n)})
    return SiteResource(
        key="materials", label="Raw materials nearby", unit="materials", available=float(local),
        needed=float(len(built)) if built else None, status=status, advisory=True,
        reach=(f"~{reaches[0]}" + (f"–{reaches[-1]}" if reaches[-1] != reaches[0] else "") + " km haul")
        if reaches else "n/a",
        parts=parts,
        note=("Raw materials can be shipped: shown for planning, never blocks building." +
              (f" Shipped in: {', '.join(shipped)}." if shipped else "")),
    )
