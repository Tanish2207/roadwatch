"""RoadWatch FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_health,
    routes_hazards,
    routes_jobs,
    routes_settings,
    routes_simulation,
)
from app.core.config import settings
from app.core.logging import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.db.database import init_db

    init_db()
    from app.ml.model_registry import model_status

    log.info("RoadWatch API starting (env=%s)", settings.environment)
    status = model_status()
    if status["ready"]:
        log.info("Model weights ready: %s (%s)", status["filename"], status["source"])
    else:
        log.warning("Model weights not found — image/video inference will be unavailable")
    yield
    log.info("RoadWatch API shutting down")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Local-first road-hazard detection and mapping platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
def root() -> dict:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
    }


api_routes = [
    routes_health,
    routes_jobs,
    routes_hazards,
    routes_simulation,
    routes_settings,
]
for module in api_routes:
    app.include_router(module.router, prefix="/api")
