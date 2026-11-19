"""Hazard map query endpoints (aggregation/publish implemented in M5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Hazard
from app.schemas.hazards import (
    HazardDetail,
    HazardListResponse,
    HazardStatusUpdate,
    HazardSummary,
    StatusHistoryOut,
)
from app.services.aggregation_service import is_stale, set_hazard_status

router = APIRouter(prefix="/hazards", tags=["hazards"])


@router.get("", response_model=HazardListResponse)
def list_hazards(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    min_confidence: float | None = Query(None, ge=0, le=1),
    min_reports: int | None = Query(None, ge=0),
    seen_within_hours: float | None = Query(None, gt=0),
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    db: Session = Depends(get_db),
) -> HazardListResponse:
    query = select(Hazard)
    count_query = select(func.count()).select_from(Hazard)

    if status:
        query = query.where(Hazard.status == status)
        count_query = count_query.where(Hazard.status == status)
    if min_confidence is not None:
        query = query.where(Hazard.confidence_avg >= min_confidence)
        count_query = count_query.where(Hazard.confidence_avg >= min_confidence)
    if min_reports is not None:
        query = query.where(Hazard.report_count >= min_reports)
        count_query = count_query.where(Hazard.report_count >= min_reports)
    if seen_within_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=seen_within_hours)
        # Stored datetimes are naive-UTC; strip tz for a consistent compare.
        cutoff = cutoff.replace(tzinfo=None)
        query = query.where(Hazard.last_seen_at >= cutoff)
        count_query = count_query.where(Hazard.last_seen_at >= cutoff)
    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="bbox must be minLon,minLat,maxLon,maxLat") from exc
        bounds = (
            Hazard.longitude >= min_lon,
            Hazard.longitude <= max_lon,
            Hazard.latitude >= min_lat,
            Hazard.latitude <= max_lat,
        )
        query = query.where(*bounds)
        count_query = count_query.where(*bounds)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Hazard.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = []
    for r in rows:
        s = HazardSummary.model_validate(r)
        s.is_stale = is_stale(r)
        items.append(s)
    return HazardListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def _detail_of(hazard: Hazard) -> HazardDetail:
    """Build a hazard detail with capped observation/history lists."""
    detail = HazardDetail.model_validate(hazard)
    detail.is_stale = is_stale(hazard)
    # Lazy-load observations to count them, then cap the embedded list so a
    # heavily-reported hazard cannot bloat the detail payload.
    detail.observations_total = len(detail.observations)
    detail.observations = detail.observations[:50]
    detail.status_history = sorted(
        (StatusHistoryOut.model_validate(s) for s in hazard.status_history),
        key=lambda s: s.created_at,
        reverse=True,
    )[:20]
    return detail


@router.get("/{hazard_id}", response_model=HazardDetail)
def get_hazard(hazard_id: str, db: Session = Depends(get_db)) -> HazardDetail:
    hazard = db.get(Hazard, hazard_id)
    if hazard is None:
        raise HTTPException(status_code=404, detail="Hazard not found")
    return _detail_of(hazard)


@router.patch("/{hazard_id}", response_model=HazardDetail)
def update_hazard(
    hazard_id: str, update: HazardStatusUpdate, db: Session = Depends(get_db)
) -> HazardDetail:
    hazard = db.get(Hazard, hazard_id)
    if hazard is None:
        raise HTTPException(status_code=404, detail="Hazard not found")
    set_hazard_status(db, hazard, update.status.value, note=update.note)
    db.refresh(hazard)
    return _detail_of(hazard)
