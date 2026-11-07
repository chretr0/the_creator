"""Average electricity and water prices per H3 resolution-6 cell, for every land cell on the map.

Run from the repo root:

  uv run --no-project --with h3 --with shapely --with pyarrow --with numpy --with openpyxl --with babel \
    --with certifi     python -I scripts/prepare_utility_prices.py [--fetch]

`--fetch` (re)downloads the official tables into data/raw/PRICE-01/global/ and writes their source.json.
Without it the script uses the copies already there.

Inputs, highest priority first for each (area, metric):

1. US EIA Electric Power Annual table 2.10: average retail price per state, residential and commercial
   (revenue ÷ sales for the full year, so day/night, seasonal and tiered rates are already averaged).
2. Eurostat nrg_pc_204 / nrg_pc_205: household (all taxes) and non-household (excluding VAT) electricity,
   all consumption bands (TOT_KWH), averaged over the two latest semesters that have data.
3. data/reference/utility_prices/research.csv: country (or state/province) averages compiled from
   regulators, utilities and price surveys, one cited source per row. Day/night (time-of-use) tariffs are
   hours-weighted, tiered tariffs are taken at a typical consumption, seasonal tariffs annualised
   (rules in data/reference/utility_prices/README.md).
4. World Bank Doing Business 2020 "price of electricity" (2019, commercial warehouse, US cents/kWh):
   only as a last resort for business electricity.

Local prices are converted to USD with the World Bank official exchange rate (PA.NUS.FCRF, annual
average) for the price year. Prices newer than that series use the current rate from ExchangeRate-API
(open.er-api.com, dated in each basis line), so recent devaluations are not missed. Both the local price and the USD value
are kept in data/prepared/utility_prices/areas.csv.

Cells: each resolution-6 cell takes the price of the country (or, for the US, Canada and Australia,
the state/province) whose outline contains its centre; coastal cells whose centre is at sea but which
overlap land then take the overlapping area's price. Small islands with no cell centre inside get the
cell containing a representative point. Cells over open sea and uninhabited territories stay blank.
Zoomed-out hexagons show the mean of their resolution-6 cells (backend layer registry).

Writes:
  data/prepared/utility_prices/areas.csv        one row per priced area × metric (committed)
  data/prepared/utility_prices_h3r6.parquet     h3 (uint64, sorted), USD prices, area + basis strings
  data/prepared/utility_prices_h3r6.json        sidecar: period, sampling, caveats
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import itertools
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import mapping, shape
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "PRICE-01" / "global"
REF = ROOT / "data" / "reference" / "utility_prices"
BOUNDARIES = ROOT / "data" / "prepared" / "boundaries"
OUT_DIR = ROOT / "data" / "prepared" / "utility_prices"
OUT_PARQUET = ROOT / "data" / "prepared" / "utility_prices_h3r6.parquet"
RES = 6

METRICS = {
    "elec_household": ("Electricity, household", "kWh"),
    "elec_business": ("Electricity, business", "kWh"),
    "water_household": ("Water + wastewater, household", "m³"),
    "water_business": ("Water + wastewater, business", "m³"),
}
# Countries priced per state/province where a sub-national source exists (electricity only).
SUBNATIONAL = ("US", "CA", "AU")

FETCH = {
    "eurostat_nrg_pc_204.json": (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_204"
        "?format=JSON&lang=en&nrg_cons=TOT_KWH&unit=KWH&currency=EUR&sinceTimePeriod=2024-S1"
    ),
    "eurostat_nrg_pc_205.json": (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_205"
        "?format=JSON&lang=en&nrg_cons=TOT_KWH&unit=KWH&currency=EUR&sinceTimePeriod=2024-S1"
    ),
    "eia_epa_02_10.xlsx": "https://www.eia.gov/electricity/annual/xls/epa_02_10.xlsx",
    "worldbank_fx_PA.NUS.FCRF.json": (
        "https://api.worldbank.org/v2/country/all/indicator/PA.NUS.FCRF?format=json&per_page=20000&date=2019:2026"
    ),
    # Taiwan is not in World Bank data: Federal Reserve H.10 annual average, TWD per USD.
    "fred_AEXTAUS.csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=AEXTAUS",
    # Current rates for prices newer than the World Bank annual series (it lags a year or more, and misses
    # recent devaluations such as Malawi 2023, Ethiopia 2024).
    "exchangerate_api_latest_USD.json": "https://open.er-api.com/v6/latest/USD",
    "worldbank_db_electricity_price.json": (
        "https://api.worldbank.org/v2/country/all/indicator/IC.ELC.PRI.KH.DB1619?format=json&per_page=20000&mrnev=1"
    ),
}

# Eurostat uses EL for Greece and UK for the United Kingdom.
EUROSTAT_GEO = {"EL": "GR", "UK": "GB"}

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

# Natural Earth features without their own price, mapped to the country whose prices apply ("" = leave blank:
# uninhabited, or a de facto separate supply with no sourced price).
FEATURE_ALIAS = {
    "Somaliland": "SO",
    "Dhekelia Sovereign Base Area": "CY",
    "Akrotiri Sovereign Base Area": "CY",
    "Cyprus No Mans Area": "CY",
    "Aland": "FI",
    "Brazilian Island": "BR",
    "Baykonur Cosmodrome": "KZ",
    "Northern Cyprus": "",
    "US Naval Base Guantanamo Bay": "",
    "Ashmore and Cartier Islands": "",
    "Indian Ocean Territories": "",
    "Clipperton Island": "",
    "Antarctica": "",
    "Heard Island and McDonald Islands": "",
    "South Georgia and the Islands": "",
    "French Southern and Antarctic Lands": "",
    "British Indian Ocean Territory": "",
    "United States Minor Outlying Islands": "",
    "Bajo Nuevo Bank (Petrel Is.)": "",
    "Spratly Islands": "",
    "Scarborough Reef": "",
    "Siachen Glacier": "",
    "Bir Tawil": "",
    "Southern Patagonian Ice Field": "",
}
# Doing Business 2019 prices distorted by hyperinflation-era exchange rates.
DB_EXCLUDE = {"VE"}
# Area codes that borrow another area's price when they have none of their own.
AREA_FALLBACK = {"AX": "FI"}

# World Bank economies used for currencies shared by several countries or with no country of their own.
CURRENCY_ECONOMY = {
    "EUR": "EMU", "XOF": "SEN", "XAF": "CMR", "XCD": "ATG", "XPF": "PYF", "ANG": "CUW", "AUD": "AUS",
    "NZD": "NZL", "DKK": "DNK", "CHF": "CHE", "GBP": "GBR", "INR": "IND", "ZAR": "ZAF", "NOK": "NOR",
    "MAD": "MAR", "ILS": "ISR", "XCG": "CUW", "TWD": "TWN",
}
# Currencies at a fixed parity with another (or redenominated): code → (currency, units of it per one).
PEGGED = {
    "PAB": ("USD", 1.0), "GIP": ("GBP", 1.0), "FKP": ("GBP", 1.0), "SHP": ("GBP", 1.0), "JEP": ("GBP", 1.0),
    "GGP": ("GBP", 1.0), "IMP": ("GBP", 1.0), "SLL": ("SLE", 0.001),
}


# ---------------------------------------------------------------------------------------------
# Fetch


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fetch() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FETCH.items():
        req = urllib.request.Request(url, headers={"User-Agent": "new-worlds-data-prep/1.0"})
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        try:
            with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
                (RAW / name).write_bytes(r.read())
        except OSError as e:
            if not (RAW / name).exists():
                raise
            print(f"kept the existing {name} ({e})")
            continue
        print(f"fetched {name}")
    write_source_json()


def write_source_json() -> None:
    today = dt.date.today().isoformat()
    rec = {
        "id": f"PRICE-01-global-{today.replace('-', '')}",
        "catalogueSourceId": "PRICE-01",
        "provider": "U.S. EIA; Eurostat; World Bank; national regulators and utilities (research table)",
        "product": "Average end-user electricity and water prices by country / state",
        "version": today,
        "documentationUrl": "data/reference/utility_prices/README.md",
        "accessMethod": "download + compiled research table",
        "evidenceType": "reported",
        "licence": {
            "name": "Mixed: EIA public domain; Eurostat and World Bank CC BY 4.0; research table cites each source",
            "url": "https://ec.europa.eu/eurostat/about-us/policies/copyright",
            "attribution": "U.S. Energy Information Administration; Eurostat; World Bank WDI / Doing Business; "
                           "per-row sources in data/reference/utility_prices/research.csv",
            "reviewedAt": today,
            "notes": "Rows from price aggregators (named in source_name) are facts with citation; check their "
                     "terms before any commercial redistribution.",
        },
        "region": "global",
        "retrievedAt": today,
        "files": [
            {"path": name, "url": url, "bytes": (RAW / name).stat().st_size, "sha256": _sha256(RAW / name)}
            for name, url in FETCH.items() if (RAW / name).exists()
        ],
    }
    (RAW / "source.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------------------------
# Exchange rates


class FX:
    """LCU per USD: World Bank annual average (PA.NUS.FCRF) for the price year; a current rate for prices
    newer than that series."""

    def __init__(self):
        _, rows = json.loads((RAW / "worldbank_fx_PA.NUS.FCRF.json").read_text())
        self.by_economy: dict[str, dict[int, float]] = {}
        for r in rows:
            if r["value"] is not None:
                code = r["countryiso3code"] or r["country"]["id"]
                self.by_economy.setdefault(code, {})[int(r["date"])] = float(r["value"])
        twd = RAW / "fred_AEXTAUS.csv"
        if twd.exists():
            for line in twd.read_text().splitlines()[1:]:
                date, _, v = line.partition(",")
                if v.strip() and v.strip() != ".":
                    self.by_economy.setdefault("TWN", {})[int(date[:4])] = float(v)
        self._cur_economy = self._currency_economies()
        self.spot: dict[str, float] = {}
        self.spot_date = ""
        latest = RAW / "exchangerate_api_latest_USD.json"
        if latest.exists():
            d = json.loads(latest.read_text())
            self.spot = {k: float(v) for k, v in d.get("rates", {}).items()}
            self.spot_date = dt.datetime.fromtimestamp(d["time_last_update_unix"], dt.UTC).date().isoformat()

    def _currency_economies(self) -> dict[str, str]:
        from babel.numbers import get_territory_currencies

        out = dict(CURRENCY_ECONOMY)
        for a2, a3s in _iso2_to_iso3s().items():
            a3 = next((a for a in a3s if a in self.by_economy), None)
            try:
                curs = get_territory_currencies(a2, start_date=dt.date(2025, 1, 1))
            except Exception:
                continue
            if a3:
                for cur in curs:
                    out.setdefault(cur, a3)
        return out

    def rate(self, currency: str, year: int) -> tuple[float, str]:
        """(LCU per USD, label of the rate used: the year, or "spot <date>")."""
        if currency in PEGGED:
            base, per = PEGGED[currency]
            r, y = self.rate(base, year)
            return r / per, y
        if currency == "USD":
            return 1.0, str(year)
        econ = self._cur_economy.get(currency)
        years = self.by_economy.get(econ, {}) if econ else {}
        if year in years:
            return years[year], str(year)
        if (not years or year > max(years)) and currency in self.spot:
            return self.spot[currency], f"spot {self.spot_date}"
        if not years:
            raise KeyError(f"no exchange rate for {currency}")
        best = min(years, key=lambda y: (abs(y - year), -y))
        return years[best], str(best)


_ISO: dict[str, list[str]] | None = None


def _iso2_to_iso3s() -> dict[str, list[str]]:
    """ISO alpha-2 → alpha-3 codes of the Natural Earth features with it (e.g. BR → Brazil, Brazilian Island)."""
    global _ISO
    if _ISO is None:
        _ISO = {}
        fc = json.loads((BOUNDARIES / "countries.geojson").read_text())
        for f in fc["features"]:
            p = f["properties"]
            if p["iso2"] not in (None, "-99"):
                _ISO.setdefault(p["iso2"], []).append(p["iso"])
    return _ISO


# ---------------------------------------------------------------------------------------------
# Sources → rows


def row(code, metric, price, currency, year, *, source, method, tax_basis, url="", notes="", wastewater=""):
    return {
        "code": code, "metric": metric, "price": float(price), "currency": currency, "year": str(year),
        "tax_basis": tax_basis, "includes_wastewater": wastewater, "method": method,
        "source_name": source, "source_url": url, "notes": notes,
    }


def eurostat_rows() -> list[dict]:
    out = []
    spec = {
        "nrg_pc_204": ("elec_household", "I_TAX", "incl_tax"),
        "nrg_pc_205": ("elec_business", "X_VAT", "excl_vat"),
    }
    for ds, (metric, tax, basis) in spec.items():
        d = json.loads((RAW / f"eurostat_{ds}.json").read_text())
        ids = d["id"]
        dims = [list(d["dimension"][k]["category"]["index"]) for k in ids]
        series: dict[str, dict[str, float]] = {}
        for i, combo in enumerate(itertools.product(*dims)):
            v = d["value"].get(str(i))
            if v is None:
                continue
            c = dict(zip(ids, combo))
            if c["tax"] != tax or len(c["geo"]) != 2:
                continue
            series.setdefault(c["geo"], {})[c["time"]] = float(v)
        for geo, by_time in series.items():
            latest = sorted(by_time)[-2:]
            # Skip stale series (e.g. the UK stopped reporting in 2020).
            if not latest or latest[-1] < "2025":
                continue
            price = sum(by_time[t] for t in latest) / len(latest)
            period = latest[0] if len(latest) == 1 else f"{latest[0]}–{latest[-1]}"
            out.append(row(
                EUROSTAT_GEO.get(geo, geo), metric, round(price, 4), "EUR", period,
                source=f"Eurostat {ds}", tax_basis=basis,
                method="all consumption bands, mean of latest two semesters",
                url=f"https://ec.europa.eu/eurostat/databrowser/view/{ds}/default/table",
            ))
    return out


def eia_rows() -> list[dict]:
    import openpyxl

    ws = openpyxl.load_workbook(RAW / "eia_epa_02_10.xlsx", read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    year_hdr = rows[3]
    year = int(re.search(r"(\d{4})", str(year_hdr[1])).group(1))
    out = []
    for r in rows[4:]:
        name = (r[0] or "").strip()
        code = "US" if name == "U.S. Total" else (f"US-{US_STATES[name]}" if name in US_STATES else None)
        if code is None:
            continue
        for metric, col in (("elec_household", 1), ("elec_business", 3)):
            v = r[col]
            if isinstance(v, (int, float)):
                out.append(row(
                    code, metric, round(v / 100, 4), "USD", year, source="U.S. EIA Electric Power Annual table 2.10",
                    tax_basis="unknown", url="https://www.eia.gov/electricity/annual/html/epa_02_10.html",
                    method=f"{'residential' if col == 1 else 'commercial'} sector revenue ÷ sales, full year",
                    notes="Annual revenue-weighted average: day/night and seasonal rates already averaged.",
                ))
    return out


def research_rows() -> list[dict]:
    p = REF / "research.csv"
    if not p.exists():
        return []
    out = []
    with p.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                price = float(r["price"])
            except (TypeError, ValueError):
                continue
            # Zero is kept: it is a sourced price (e.g. Ireland has no household water charges), not a gap.
            if price < 0 or r["metric"] not in METRICS:
                continue
            out.append({**r, "price": price, "code": r["code"].strip().upper()})
    return out


def db_rows() -> list[dict]:
    """World Bank Doing Business 2020 electricity price (2019): last-resort business electricity."""
    _, rows = json.loads((RAW / "worldbank_db_electricity_price.json").read_text())
    a3_to_a2 = {a3: a2 for a2, a3s in _iso2_to_iso3s().items() for a3 in a3s}
    by: dict[str, list[float]] = {}
    year = {}
    for r in rows:
        a2 = a3_to_a2.get(r["countryiso3code"])
        if a2 and r["value"] is not None:
            by.setdefault(a2, []).append(float(r["value"]))  # some economies report two cities
            year[a2] = r["date"]
    return [
        row(a2, "elec_business", round(sum(v) / len(v) / 100, 4), "USD", year[a2],
            source="World Bank Doing Business 2020 (IC.ELC.PRI.KH.DB1619)", tax_basis="unknown",
            method="commercial warehouse tariff, mean of surveyed cities",
            url="https://data.worldbank.org/indicator/IC.ELC.PRI.KH.DB1619",
            notes="2019 survey; last-resort fallback")
        for a2, v in by.items() if a2 not in DB_EXCLUDE
    ]


def resolve(fx: FX) -> list[dict]:
    """One row per (area, metric): the highest-priority source that converts to USD."""
    candidates: dict[tuple[str, str], list[dict]] = {}
    for rows in (eia_rows(), eurostat_rows(), research_rows(), db_rows()):
        for r in rows:
            candidates.setdefault((r["code"], r["metric"]), []).append(r)
    out = []
    for (code, metric), rows in sorted(candidates.items()):
        for r in rows:
            try:
                m = re.match(r"\d{4}", str(r["year"]))
                rate, fx_year = fx.rate(r["currency"].strip().upper(), int(m.group()) if m else dt.date.today().year)
            except KeyError as e:
                print(f"  {code} {metric}: {e}; trying the next source")
                continue
            out.append({**r, "usd": round(r["price"] / rate, 4), "fx_rate": rate, "fx_year": fx_year})
            break
    return out


# ---------------------------------------------------------------------------------------------
# Cells


def _features(level: str) -> list[dict]:
    return json.loads((BOUNDARIES / f"{level}.geojson").read_text())["features"]


def _cells(geom, mode: str) -> set[int]:
    cells = set()
    for part in getattr(geom, "geoms", [geom]):
        if part.geom_type != "Polygon" or part.is_empty:
            continue
        shp = h3.geo_to_h3shape(mapping(part))
        if mode == "center":
            got = h3.h3shape_to_cells(shp, RES)
            if not got:  # small island: no cell centre inside
                p = part.representative_point()
                got = [h3.latlng_to_cell(p.y, p.x, RES)]
        else:
            got = h3.h3shape_to_cells_experimental(shp, RES, contain="overlap")
        cells.update(h3.str_to_int(c) for c in got)
    return cells


def _area_shapes() -> list[tuple[str, str, object]]:
    """(price area code, display name, geometry): sub-national areas first so they win."""
    out = []
    for f in _features("admin1"):
        p = f["properties"]
        if p.get("iso2") in SUBNATIONAL and p.get("iso"):
            g = shape(f["geometry"])
            out.append((p["iso"], f"{p['country']} · {p['name']}", g if g.is_valid else make_valid(g)))
    for f in _features("countries"):
        p = f["properties"]
        code = FEATURE_ALIAS.get(p["name"], p["iso2"])
        if not code or code == "-99":
            continue
        g = shape(f["geometry"])
        out.append((code, p["name"], g if g.is_valid else make_valid(g)))
    return out


def assign_cells(areas: list[tuple[str, str, object]]) -> dict[int, int]:
    """Cell → index into `areas`. Centre containment first; then coastal/border cells overlapping land."""
    owner: dict[int, int] = {}
    for mode in ("center", "overlap"):
        for i, (code, name, geom) in enumerate(areas):
            for c in _cells(geom, mode):
                owner.setdefault(c, i)
        print(f"  {mode}: {len(owner):,} cells", flush=True)
    return owner


# ---------------------------------------------------------------------------------------------
# Main


def _basis(r: dict) -> str:
    unit = METRICS[r["metric"]][1]
    tax = {"incl_tax": "incl. taxes", "excl_vat": "excl. VAT", "excl_tax": "excl. taxes"}.get(
        r.get("tax_basis", ""), "tax basis unknown")
    if r["metric"].startswith("water"):
        tax += {"no": " · water only, no wastewater", "unknown": " · wastewater not stated"}.get(
            r.get("includes_wastewater", ""), "")
    local = "" if r["currency"] == "USD" else f"{r['currency']} {r['price']:g}/{unit} → "
    fx = "" if r["currency"] == "USD" else f" (FX {r['fx_year']})"
    return f"{local}USD {r['usd']:g}/{unit}{fx} · {r['year']} · {r['source_name']} · {r['method']} · {tax}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="download the official tables first")
    args = ap.parse_args()
    if args.fetch or not (RAW / "source.json").exists():
        fetch()

    fx = FX()
    resolved = resolve(fx)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["code", "metric", "price", "currency", "year", "usd", "fx_rate", "fx_year", "tax_basis",
              "includes_wastewater", "method", "source_name", "source_url", "notes"]
    with (OUT_DIR / "areas.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(resolved)
    print(f"areas.csv: {len(resolved)} area × metric prices")

    price = {(r["code"], r["metric"]): r for r in resolved}

    def lookup(code: str, metric: str) -> dict | None:
        r = price.get((code, metric))
        if r is None and "-" in code:  # state/province without its own price → country
            r = price.get((code.split("-")[0], metric))
        if r is None and code in AREA_FALLBACK:
            r = price.get((AREA_FALLBACK[code], metric))
        return r

    areas = _area_shapes()
    print(f"assigning resolution-{RES} cells to {len(areas)} areas …", flush=True)
    owner = assign_cells(areas)

    keys = np.fromiter(owner.keys(), dtype=np.uint64, count=len(owner))
    idx = np.fromiter(owner.values(), dtype=np.int32, count=len(owner))
    order = np.argsort(keys)
    keys, idx = keys[order], idx[order]

    cols: dict[str, pa.Array] = {"h3": pa.array(keys, pa.uint64())}
    area_code = np.array([a[0] for a in areas], dtype=object)
    area_name = np.array([a[1] for a in areas], dtype=object)
    for metric in METRICS:
        per_area = [lookup(code, metric) for code, _, _ in areas]
        vals = np.array([np.nan if r is None else r["usd"] for r in per_area], dtype=np.float32)
        basis = np.array([None if r is None else _basis(r) for r in per_area], dtype=object)
        cols[metric] = pa.array(vals[idx], pa.float32(), from_pandas=True)
        cols[f"{metric}_basis"] = pa.array(basis[idx], pa.string()).dictionary_encode()
        print(f"  {metric}: {int(np.isfinite(vals[idx]).sum()):,} cells priced")
    cols["price_area"] = pa.array(area_code[idx], pa.string()).dictionary_encode()
    cols["price_area_name"] = pa.array(area_name[idx], pa.string()).dictionary_encode()
    tbl = pa.table(cols)
    tbl = tbl.replace_schema_metadata({
        "units": "USD",
        "long_name": "Average end-user electricity and water prices",
        "definition": "Average price paid per kWh of electricity or per m³ of water (drinking water plus "
                      "wastewater where the source includes it), by country or state, converted to USD.",
    })
    pq.write_table(tbl, OUT_PARQUET, compression="zstd", row_group_size=128_000)

    years = sorted({m.group() for r in resolved if (m := re.match(r"\d{4}", str(r["year"])))})
    sidecar = {
        "id": "utility_prices",
        "title": "Average electricity and water prices",
        "evidenceType": "reported",
        "units": {"electricity": "USD/kWh", "water": "USD/m³"},
        "period": {"label": f"Latest available per area ({years[0]}–{years[-1]}); see areas.csv"},
        "nativeResolution": "Country, or state/province for the US, Canada and Australia (electricity)",
        "sampling": "Each resolution-6 cell takes the price of the area containing its centre (coastal cells: the "
                    "overlapping area). Zoomed-out hexagons show the mean.",
        "aggregation": {"toRes6": "area value repeated in every cell", "coarser": "mean"},
        "averaging": [
            "Day/night (time-of-use) tariffs: hours-weighted average of the periods.",
            "Tiered tariffs: effective price at a typical household use (~250 kWh, ~15 m³ per month), fixed charges "
            "included where known.",
            "Seasonal tariffs: annual average. Official statistics (EIA, Eurostat) are revenue ÷ sales averages "
            "over all tariffs, so they already include these.",
        ],
        "caveats": [
            "One average per country or state: real tariffs vary by utility, city, customer size and contract.",
            "Water prices are mostly the capital or largest utility's tariff; some exclude wastewater (see basis).",
            "Converted to USD at the World Bank annual average exchange rate; volatile currencies distort comparisons.",
            "Sources differ in year and tax treatment; read each cell's basis line before comparing.",
        ],
        "builtAt": dt.date.today().isoformat(),
        "cells": int(len(keys)),
    }
    (OUT_PARQUET.with_suffix(".json")).write_text(json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT_PARQUET.relative_to(ROOT)}: {len(keys):,} cells")


if __name__ == "__main__":
    sys.exit(main())
