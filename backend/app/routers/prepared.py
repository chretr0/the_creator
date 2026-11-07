"""Static prepared layers: administrative boundaries and submarine cables, with provenance."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app import regions
from app.config import settings

router = APIRouter(prefix="/api", tags=["reference"])


def _manifest(group: str) -> dict:
    path = Path(settings.prepared_data_dir) / group / "source.json"
    if not path.exists():
        raise HTTPException(503, f"{group} data not prepared. Run scripts/prepare_reference.py.")
    return json.loads(path.read_text())


def _file(group: str, layer_id: str) -> FileResponse:
    entry = next((layer for layer in _manifest(group)["layers"] if layer["id"] == layer_id), None)
    if entry is None:
        raise HTTPException(404, f"Unknown {group} layer: {layer_id}")
    return FileResponse(
        Path(settings.prepared_data_dir) / group / entry["file"],
        media_type="application/geo+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/boundaries")
def boundaries_manifest():
    return _manifest("boundaries")


@router.get("/boundaries/{layer_id}")
def boundaries_layer(layer_id: str):
    return _file("boundaries", layer_id)


@router.get("/cables")
def cables_manifest():
    return _manifest("cables")


@router.get("/cables/{layer_id}")
def cables_layer(layer_id: str):
    return _file("cables", layer_id)


@router.get("/regions/locate")
def locate_region(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180)):
    """Country, admin-1 and (US only) county containing a point, from simplified outlines."""
    if not regions.available():
        raise HTTPException(503, "Boundary data not prepared.")
    return {
        **regions.locate(longitude, latitude),
        "note": "Simplified outlines: points within a few hundred metres of a border may resolve to the neighbour.",
    }


@router.get("/regions/search-index")
def region_search_index():
    """Region names, bounding boxes and label points for keyless local place search."""
    if not regions.available():
        raise HTTPException(503, "Boundary data not prepared.")
    return regions.search_index()
