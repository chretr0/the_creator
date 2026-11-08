import h3
from fastapi import APIRouter, Depends, HTTPException, Query

from app import geo
from app.bodies import Body
from app.models import CellInfo
from app.routers.bodies import body_query

router = APIRouter(prefix="/api/cells", tags=["cells"])


@router.get("/locate", response_model=CellInfo, response_model_by_alias=True)
def locate(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(),
    resolution: int = Query(default=geo.SIMULATION_RESOLUTION, ge=0, le=geo.MAX_RESOLUTION),
    body: Body = Depends(body_query),
):
    """Return the cell containing a coordinate (default: the resolution-6 simulation cell)."""
    try:
        lat, lng = geo.validate_coordinate(latitude, longitude)
    except geo.InvalidCoordinate as exc:
        raise HTTPException(422, str(exc)) from exc

    return geo.describe_cell(h3.latlng_to_cell(lat, lng, resolution), body)


@router.get("/{h3_id}", response_model=CellInfo, response_model_by_alias=True)
def get_cell(h3_id: str, body: Body = Depends(body_query)):
    try:
        return geo.describe_cell(h3_id, body)
    except geo.InvalidCell as exc:
        raise HTTPException(404, str(exc)) from exc
