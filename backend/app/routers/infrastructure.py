"""Prepared infrastructure layers (datacenters, power plants, dams, grid, airports, ports) with provenance.

Files are produced by scripts/prepare_infrastructure.py and served from disk, so the layer keeps
working without any upstream service.
"""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app import regions
from app.config import settings

router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


def _dir() -> Path:
    return Path(settings.prepared_data_dir) / "infrastructure"


def _manifest() -> dict:
    path = _dir() / "source.json"
    if not path.exists():
        raise HTTPException(503, "Infrastructure data not prepared. Run scripts/prepare_infrastructure.py.")
    return json.loads(path.read_text())


@router.get("")
def manifest():
    """Provenance (per source), licence, limitations and coverage counts for the infrastructure layers.
    Each layer says whether its file is present, since the larger ones are rebuilt locally."""
    m = _manifest()
    for layer in m["layers"]:
        layer["available"] = (_dir() / layer["file"]).exists()
    return m


@lru_cache(maxsize=12)
def _tagged_file(path: Path, _mtime: float) -> bytes:
    """Layer GeoJSON with country/admin-1 tags added from the boundary packs (when prepared).
    Keyed on mtime so re-running the prepare script takes effect without a restart."""
    fc = json.loads(path.read_text())
    if regions.available():
        for f in fc["features"]:
            p = f["properties"]
            p.update(regions.tag(p["lon"], p["lat"]))
    return json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode()


def _tagged(layer_id: str) -> bytes:
    entry = next((layer for layer in _manifest()["layers"] if layer["id"] == layer_id), None)
    if entry is None:
        raise HTTPException(404, f"Unknown infrastructure layer: {layer_id}")
    path = _dir() / entry["file"]
    if not path.exists():
        raise HTTPException(503, f"{layer_id} not prepared. Run scripts/prepare_infrastructure.py.")
    return _tagged_file(path, path.stat().st_mtime)


@router.get("/{layer_id}")
def layer(layer_id: str):
    return Response(
        _tagged(layer_id),
        media_type="application/geo+json",
        headers={"Cache-Control": "no-cache"},
    )
