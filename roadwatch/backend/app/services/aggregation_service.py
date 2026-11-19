"""Detection -> observation -> hazard aggregation pipeline.

Observation: one model output tied to a frame/job/GPS match.
Hazard:      aggregated map entity, many observations, deduplicated by radius.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import DetectionObservation, Hazard, HazardStatusHistory, utcnow
from app.utils.geometry import bbox_area, haversine_m

log = get_logger(__name__)

# Status derivation thresholds (documented heuristics, not safety claims)
CONFIRMED_MIN_REPORTS = 3
STALE_AFTER_DAYS = 30


def _aware(dt: datetime | None) -> datetime | None:
    """Ensure naive-DB datetimes compare as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def derive_status(report_count: int, current: str) -> str:
    """New -> Observed -> Confirmed (prototype) as corroboration grows.

    Resolved is manual-only and never overwritten here.
    """
    if current == "resolved":
        return "resolved"
    if report_count >= CONFIRMED_MIN_REPORTS:
        return "confirmed"
    if report_count >= 2:
        return "observed"
    return "new"


def is_stale(hazard: Hazard, now: datetime | None = None) -> bool:
    now = now or utcnow()
    last = _aware(hazard.last_seen_at)
    if last is None:
        return True
    age_days = (now - last).total_seconds() / 86_400
    return age_days > STALE_AFTER_DAYS


def find_nearby_hazard(
    db: Session, lat: float, lon: float, radius_m: float | None = None
) -> Hazard | None:
    """Return an existing hazard within radius_m of a point (Haversine scan)."""
    radius = radius_m if radius_m is not None else settings.aggregation_radius_m
    candidates = db.scalars(
        select(Hazard).where(Hazard.status != "resolved").limit(2000)
    ).all()
    best: Hazard | None = None
    best_d = radius
    for h in candidates:
        d = haversine_m(lat, lon, h.latitude, h.longitude)
        if d <= best_d:
            best, best_d = h, d
    return best


def aggregate_observations(
    db: Session,
    observations: list[DetectionObservation],
    radius_m: float | None = None,
) -> dict:
    """Group GPS-tagged observations into hazards (intra-job spatial clustering).

    Observations without coordinates are skipped (they must not be mapped).
    Returns stats: {merged, created, skipped_no_gps}.
    """
    radius = radius_m if radius_m is not None else settings.aggregation_radius_m
    created = merged = skipped = 0

    for obs in observations:
        if obs.gps_lat is None or obs.gps_lon is None:
            skipped += 1
            continue

        # Ensure the observation is persisted so linking/centroid queries see it
        db.add(obs)
        db.flush()

        # Prefer the hazard this observation is already linked to (stable
        # identity): prevents double-counting when centroids drift between
        # aggregation runs, and keeps publish idempotent.
        hazard = None
        if obs.candidate_hazard_id:
            prev = db.get(Hazard, obs.candidate_hazard_id)
            if (
                prev is not None
                and prev.status != "resolved"
                and haversine_m(obs.gps_lat, obs.gps_lon, prev.latitude, prev.longitude)
                <= radius
            ):
                hazard = prev

        if hazard is None:
            hazard = find_nearby_hazard(db, obs.gps_lat, obs.gps_lon, radius)
        if hazard is None:
            hazard = Hazard(
                latitude=obs.gps_lat,
                longitude=obs.gps_lon,
                status="new",
                report_count=0,
                first_seen_at=obs.created_at or utcnow(),
                last_seen_at=obs.created_at or utcnow(),
                location_uncertainty_m=_estimate_uncertainty(obs),
            )
            db.add(hazard)
            db.flush()  # assign id
            created += 1
        else:
            merged += 1

        _absorb(db, hazard, obs)

    db.commit()
    return {"created": created, "merged": merged, "skipped_no_gps": skipped}


def _estimate_uncertainty(obs: DetectionObservation) -> float | None:
    """Location uncertainty grows with GPS match error (rough prototype rule)."""
    if obs.gps_match_delta_seconds is None:
        return None
    # ~3 m/s vehicle-speed assumption on timestamp error + 10 m GPS CEP floor
    return round(10.0 + 3.0 * obs.gps_match_delta_seconds, 1)


def summarize_bbox_areas(
    observations: list[DetectionObservation],
) -> dict | None:
    """Aggregate the YOLO bounding-box areas of a hazard's observations.

    Areas are pixel counts from ``bbox_xyxy``. When the source frame size is
    known (recorded on the job at processing time) the area is also expressed
    as a fraction of the frame, which keeps hazards recorded at different video
    resolutions comparable — that fraction is what sizes the map marker.
    Returns None when no usable bounding box is present.
    """
    areas: list[float] = []
    fracs: list[float] = []
    for obs in observations:
        area = bbox_area(obs.bbox_xyxy)
        if area is None:
            continue
        areas.append(area)
        frame_area = _frame_area_px(obs)
        if frame_area:
            fracs.append(area / frame_area)

    if not areas:
        return None
    summary: dict = {
        "count": len(areas),
        "mean_area_px": round(sum(areas) / len(areas), 1),
        "max_area_px": round(max(areas), 1),
    }
    if fracs:
        summary["frac_count"] = len(fracs)
        summary["mean_area_frac"] = round(sum(fracs) / len(fracs), 6)
        summary["max_area_frac"] = round(max(fracs), 6)
    return summary


def _frame_area_px(obs: DetectionObservation) -> float | None:
    """Frame pixel area stored on the observation's job, if it was recorded."""
    job = obs.job
    if job is None:
        return None
    cfg = job.processing_config or {}
    try:
        width = int(cfg.get("frame_width") or 0)
        height = int(cfg.get("frame_height") or 0)
    except (TypeError, ValueError):
        return None
    return float(width * height) if width > 0 and height > 0 else None


def _absorb(db: Session, hazard: Hazard, obs: DetectionObservation) -> None:
    """Fold one observation into a hazard's aggregates.

    Idempotent: an observation already linked to this hazard does not inflate
    report_count again (publish may re-run over the same observations).
    """
    already_linked = obs.candidate_hazard_id == hazard.id
    obs.candidate_hazard_id = hazard.id
    if already_linked:
        return
    hazard.report_count += 1

    # Confidence aggregates
    if hazard.confidence_avg is None:
        hazard.confidence_avg = obs.confidence
        hazard.confidence_max = obs.confidence
    else:
        n = hazard.report_count
        hazard.confidence_avg = round(
            (hazard.confidence_avg * (n - 1) + obs.confidence) / n, 4
        )
        hazard.confidence_max = max(hazard.confidence_max or 0.0, obs.confidence)

    seen = _aware(obs.created_at) or utcnow()
    first = _aware(hazard.first_seen_at)
    last = _aware(hazard.last_seen_at)
    if first is None or seen < first:
        hazard.first_seen_at = seen
    if last is None or seen > last:
        hazard.last_seen_at = seen

    # Recompute centroid from linked observations
    linked = db.scalars(
        select(DetectionObservation).where(
            DetectionObservation.candidate_hazard_id == hazard.id,
            DetectionObservation.gps_lat.is_not(None),
        )
    ).all()
    if linked:
        hazard.latitude = sum(o.gps_lat for o in linked) / len(linked)
        hazard.longitude = sum(o.gps_lon for o in linked) / len(linked)
        # Rebuilt from the full linked set on every absorb, so replaying a
        # publish can never double-count an area sample.
        hazard.pixel_area_summary = summarize_bbox_areas(linked)

    new_status = derive_status(hazard.report_count, hazard.status)
    if new_status != hazard.status:
        _set_status(db, hazard, new_status, note="auto-corroboration rule")


def _set_status(db: Session, hazard: Hazard, new_status: str, note: str | None) -> None:
    db.add(
        HazardStatusHistory(
            hazard_id=hazard.id,
            previous_status=hazard.status,
            new_status=new_status,
            note=note,
        )
    )
    hazard.status = new_status


def set_hazard_status(
    db: Session, hazard: Hazard, status: str, note: str | None = None
) -> None:
    """Manual status change (with audit history + resolved bookkeeping)."""
    if status == hazard.status:
        return
    _set_status(db, hazard, status, note=note)
    if status == "resolved":
        hazard.resolved_at = utcnow()
        hazard.resolved_note = note
    else:
        hazard.resolved_at = None
        hazard.resolved_note = None
    db.commit()
