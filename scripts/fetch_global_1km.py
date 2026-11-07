"""GLOBAL MODE (opt-in). Not part of the default data scope: big datasets are kept for the arizona/uk
regions only (data/README.md §0.1). Kept for reference and for deliberate global runs.

Download global 1 km SoilGrids 2.0 mean layers (SOIL-01) and the WorldPop R2025A 2025
1 km constrained population mosaic (CTX-04). Resumable (curl -C -), 6 parallel downloads, verifies SoilGrids
files against ISRIC's published checksum.sha256.txt.

Run:
  uv run --no-project python -I scripts/fetch_global_1km.py <repo>/data/raw
"""
import hashlib
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAW = Path(sys.argv[1]).resolve()
SG = "https://files.isric.org/soilgrids/latest/data_aggregated/1000m"
SG_VARS = ["phh2o", "soc", "clay", "sand", "nitrogen", "bdod"]
SG_DEPTHS = ["0-5cm", "15-30cm"]
WP = ("https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/"
      "0_Mosaicked/v1/1km/constrained/global_pop_2025_CN_1km_R2025A_v1.tif")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-C", "-", "-o", str(dest), url], check=True)
    print(f"{dest.name}  {dest.stat().st_size:,} B", flush=True)


sg_dir = RAW / "SOIL-01" / "soilgrids_1km"
expected, jobs = {}, []
for v in SG_VARS:
    sums = urllib.request.urlopen(f"{SG}/{v}/checksum.sha256.txt").read().decode()
    expected.update({ln.split()[1]: ln.split()[0] for ln in sums.splitlines() if ln.strip()})
    jobs += [(f"{SG}/{v}/{v}_{d}_mean_1000.tif", sg_dir / f"{v}_{d}_mean_1000.tif") for d in SG_DEPTHS]
jobs.append((WP, RAW / "CTX-04" / "worldpop_R2025A_1km" / WP.rsplit("/", 1)[1]))


def job(url_dest):
    url, dest = url_dest
    fetch(url, dest)
    got = sha256(dest)
    exp = expected.get(dest.name)
    status = "no published checksum" if exp is None else ("OK" if exp == got else f"MISMATCH (expected {exp})")
    print(f"  {dest.name} sha256 {got} {status}", flush=True)


with ThreadPoolExecutor(max_workers=6) as ex:
    list(ex.map(job, jobs))
print("done")
