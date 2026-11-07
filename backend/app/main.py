from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import geo
from app.config import settings
from app.db import pool
from app.routers import cells, hazards, infrastructure, power, prepared, scenarios, sources


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open(wait=True, timeout=10)
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


@app.get("/api/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "simulationResolution": geo.SIMULATION_RESOLUTION}
