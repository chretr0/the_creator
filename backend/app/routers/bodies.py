"""Planetary bodies the app can map (Earth, Moon) and a shared `?body=` query parameter."""

from fastapi import APIRouter, HTTPException, Query

from app import bodies
from app.bodies import Body

router = APIRouter(prefix="/api", tags=["bodies"])


def body_query(
    body: str = Query(default="earth", description=f"Body whose radius sizes cells: {' | '.join(bodies.BODY_IDS)}"),
) -> Body:
    """FastAPI dependency: resolve `?body=` to a registered Body (422 for unknown ids)."""
    try:
        return bodies.get(body)
    except bodies.UnknownBody as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/bodies")
def list_bodies():
    return [b.to_api() for b in bodies.BODIES.values()]
