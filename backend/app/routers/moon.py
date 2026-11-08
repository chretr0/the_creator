"""Moon module: prepared reference layers, heritage keep-out rings, cell context and credits.

H3 layer values live under /api/moon/h3 (app.routers.moon_layers), not here.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import geo, moon_reference

router = APIRouter(prefix="/api/moon", tags=["moon"])


@router.get("")
def manifest():
    """data/prepared/moon/source.json with `available` per layer."""
    try:
        return moon_reference.manifest()
    except moon_reference.NotPrepared as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/sources")
def sources():
    """Moon credits in the /api/sources item shape (works before the data is prepared)."""
    return moon_reference.sources()


@router.get("/keepout")
def keepout():
    """Heritage keep-out rings (NASA 2011, MOON-SITE-06) around every landed object that has one."""
    try:
        return moon_reference.keepout()
    except moon_reference.NotPrepared as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/layers/{layer_id}")
def layer(layer_id: str):
    try:
        path, media_type = moon_reference.layer_file(layer_id)
    except moon_reference.UnknownLayer as exc:
        raise HTTPException(404, str(exc)) from exc
    except moon_reference.NotPrepared as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


@router.get("/cells/{h3_id}/context")
def cell_context(h3_id: str):
    try:
        return moon_reference.cell_context(h3_id)
    except geo.InvalidCell as exc:
        raise HTTPException(404, str(exc)) from exc
    except moon_reference.NotPrepared as exc:
        raise HTTPException(503, str(exc)) from exc
