"""GLOBAL MODE (opt-in). Not part of the default data scope: big datasets are kept for the arizona/uk
regions only (data/README.md §0.1). Kept for reference and for deliberate global runs.

Aggregate a FIRMS annual country-archive (VIIRS 375 m) to H3 resolution 6 with DuckDB.

Run:
  uv run --no-project --with duckdb --with pyarrow python -I scripts/aggregate_firms_h3.py \
      data/raw/LAND-05/archive_2024/unzipped/viirs-snpp/2024 \
      data/prepared/firms_viirs_snpp_2024_h3r6.parquet

Input: the per-country CSVs from firms.modaps.eosdis.nasa.gov/data/country/zips/ (unzipped).
Columns: latitude, longitude, ..., acq_date, acq_time, satellite, instrument, confidence (h/n/l),
version, ..., frp (MW), daynight, type (0 vegetation fire, 1 volcano, 2 other static land source, 3 offshore).

Exact duplicate rows across country files (border detections) are removed before counting.
Output: one row per H3 r6 cell (cell id as UBIGINT `h3_r6`, plus hex string `h3_r6_hex`).
"""
import sys

import duckdb

src_dir, out_path = sys.argv[1], sys.argv[2]
con = duckdb.connect()
con.execute("INSTALL h3 FROM community; LOAD h3;")

csv_glob = f"{src_dir.rstrip('/')}/*.csv"
con.execute(f"""
CREATE TEMP TABLE det AS
SELECT DISTINCT latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite,
       instrument, confidence, version, bright_ti5, frp, daynight, type
FROM read_csv('{csv_glob}', header=true, union_by_name=true,
     types={{'latitude':'DOUBLE','longitude':'DOUBLE','acq_date':'DATE','acq_time':'VARCHAR',
             'confidence':'VARCHAR','frp':'DOUBLE','type':'INTEGER','version':'VARCHAR'}})
""")
raw_rows = con.execute(f"SELECT count(*) FROM read_csv('{csv_glob}', header=true, union_by_name=true)").fetchone()[0]
n, conf, typ, ver = con.execute("""
SELECT count(*),
       string_agg(DISTINCT confidence, ','),
       string_agg(DISTINCT CAST(type AS VARCHAR), ','),
       string_agg(DISTINCT version, ',')
FROM det""").fetchone()
print(f"rows read {raw_rows}, distinct detections {n}, confidence={conf}, type={typ}, version={ver}")

con.execute(f"""
COPY (
  SELECT h3_latlng_to_cell(latitude, longitude, 6)::UBIGINT AS h3_r6,
         h3_h3_to_string(h3_latlng_to_cell(latitude, longitude, 6)) AS h3_r6_hex,
         count(*)::INTEGER AS detections,
         count(*) FILTER (WHERE confidence = 'h')::INTEGER AS conf_high,
         count(*) FILTER (WHERE confidence = 'n')::INTEGER AS conf_nominal,
         count(*) FILTER (WHERE confidence = 'l')::INTEGER AS conf_low,
         count(*) FILTER (WHERE type = 0)::INTEGER AS type0_vegetation_fire,
         count(*) FILTER (WHERE type = 1)::INTEGER AS type1_volcano,
         count(*) FILTER (WHERE type = 2)::INTEGER AS type2_static_land_source,
         count(*) FILTER (WHERE type = 3)::INTEGER AS type3_offshore,
         round(sum(frp), 2)::DOUBLE AS frp_sum_mw,
         max(frp)::DOUBLE AS frp_max_mw,
         round(sum(frp) FILTER (WHERE type = 0), 2)::DOUBLE AS frp_sum_mw_type0,
         count(DISTINCT acq_date)::SMALLINT AS days_with_detection,
         min(acq_date) AS first_acq_date,
         max(acq_date) AS last_acq_date
  FROM det
  GROUP BY 1, 2
  ORDER BY 1
) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)
""")
cells, total = con.execute(f"SELECT count(*), sum(detections) FROM read_parquet('{out_path}')").fetchone()
print(f"wrote {out_path}: {cells} cells, {total} detections")
