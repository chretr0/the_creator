import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import geo
from app.config import settings
from app.db import pool
from app.routers import cells, features, hazards, infrastructure, layers, power, prepared, scenarios, sources


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


app = FastAPI(title="New Worlds API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cells.router)
app.include_router(scenarios.router)
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
