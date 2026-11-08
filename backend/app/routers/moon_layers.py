"""Moon H3 data layers (data/prepared/moon/h3): catalogue and per-cell values.

Included by app.main next to the other Moon routes; everything else under /api/moon lives in
routers/moon.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import moon_h3

router = APIRouter(prefix="/api/moon/h3", tags=["moon"])


class CellsRequest(BaseModel):
    cells: list[str] = Field(default_factory=list, max_length=moon_h3.MAX_CELLS)


@router.get("")
def list_moon_h3_layers() -> list[dict]:
    """layers.json "layers" (plus ``available``); an empty list when nothing is prepared."""
    return moon_h3.list_layers()


@router.post("/{layer_id}")
def moon_h3_values(layer_id: str, body: CellsRequest) -> dict:
    """Values for the requested cells, keyed by cell id.

    Cells finer than the layer's maxResolution resolve to their ancestor at maxResolution
    (``servedResolution`` says which resolution answered). No data is ``null``, never 0.
    """
    meta = moon_h3.layer(layer_id)
    if meta is None:
        raise HTTPException(404, f"Unknown Moon layer: {layer_id}")
    try:
        out = moon_h3.values(layer_id, body.cells)
    except moon_h3.InvalidCell as exc:
        raise HTTPException(422, str(exc)) from exc
    except moon_h3.UnknownLayer:
        raise HTTPException(404, f"Unknown Moon layer: {layer_id}") from None
    except moon_h3.LayerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"layerId": layer_id, "unit": meta.get("unit"), **out}
