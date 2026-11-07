import logging
import math
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import geo
from app.config import settings
from app.db import pool
from app.routers import buildings, cells, features, hazards, infrastructure, layers, power, prepared, scenarios, sources


def warm_default_layer() -> None:
    from app import h3store, layers as layer_registry

    try:
        layer = layer_registry.BY_ID["solar_ghi"]
        src = layer_registry.source_for(layer, layer.slice(None))
        if src:
            for res in range(h3store.SIM_RES + 1):
                h3store.level(src, res)
    except Exception:  # warming is an optimisation only
        logging.getLogger(__name__).exception("H3 cache warm-up failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open(wait=True, timeout=10)
    # Build the default choropleth's cache in the background so the first map view is quick.
    threading.Thread(target=warm_default_layer, daemon=True).start()
    try:
        yield
    finally:
        pool.close()


MAX_BODY_BYTES = 1_000_000  # every request body is a small JSON document


class BodySizeLimit:
    """Reject request bodies over `max_bytes` with 413, whether or not Content-Length is sent."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        too_large = JSONResponse({"detail": f"request body too large (limit {self.max_bytes:,} bytes)"}, 413)
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            return await too_large(scope, receive, send)
        # Read the whole body here (bounded), then hand it to the app unchanged.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # client disconnected
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > self.max_bytes:
                return await too_large(scope, receive, send)
            if not message.get("more_body"):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)


def _json_safe(value):
    """Python's json parser accepts NaN / Infinity; echoing them back in a 422 must not fail."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


app = FastAPI(title="New Worlds API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


app.add_middleware(BodySizeLimit)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cells.router)
app.include_router(scenarios.router)
app.include_router(buildings.router)
app.include_router(infrastructure.router)
app.include_router(prepared.router)
app.include_router(hazards.router)
app.include_router(power.router)
app.include_router(sources.router)
app.include_router(layers.router)
app.include_router(features.router)


@app.get("/api/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "simulationResolution": geo.SIMULATION_RESOLUTION}
