"""Health and readiness endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.database import engine
from app.ml.model_registry import model_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    model = model_status()

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "backend": "ok",
        "database": "ok" if db_ok else "error",
        "model": model,
        "environment": settings.environment,
        "time": datetime.now(timezone.utc).isoformat(),
    }
