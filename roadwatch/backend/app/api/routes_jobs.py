"""Job management: create (upload), poll, cancel, inspect, publish."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import get_db
from app.db.models import DetectionObservation, ProcessingJob, utcnow
from app.schemas.jobs import (
    DetectionListResponse,
    DetectionOut,
    FrameEntry,
    FrameManifestResponse,
    JobListResponse,
    JobSummary,
)
from app.services import frame_store
from app.utils.file_validation import save_upload
from app.workers import processing_worker

log = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


# --------------------------------------------------------------------------
# Create / list / detail
# --------------------------------------------------------------------------
@router.post("", response_model=JobSummary, status_code=202)
async def create_job(
    video: UploadFile = File(...),
    gps_csv: UploadFile | None = File(None),
    sample_rate_fps: float = Form(None),
    confidence_threshold: float = Form(None),
    image_size: int = Form(None),
    db: Session = Depends(get_db),
) -> JobSummary:
    """Accept a dashcam video (+ optional GPS sidecar) and queue it."""
    video_path = await save_upload(
        video, settings.uploads_dir, settings.video_extension_list
    )

    gps_path: Path | None = None
    if gps_csv is not None and gps_csv.filename:
        gps_path = await save_upload(gps_csv, settings.uploads_dir, settings.gps_extension_list)

    cfg = {
        "sample_rate_fps": sample_rate_fps or settings.default_sample_rate_fps,
        "confidence_threshold": confidence_threshold or settings.default_confidence_threshold,
        "image_size": image_size or settings.default_image_size,
    }

    job = ProcessingJob(
        original_filename=Path(video.filename or "video").name,
        video_path=str(video_path),
        gps_file_path=str(gps_path) if gps_path else None,
        status="queued",
        processing_config=cfg,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    log.info("Job %s created: %s (gps=%s)", job.id, job.original_filename, bool(gps_path))
    processing_worker.enqueue(job.id)
    return JobSummary.model_validate(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: Session = Depends(get_db),
) -> JobListResponse:
    query = select(ProcessingJob)
    count_query = select(func.count()).select_from(ProcessingJob)
    if status:
        query = query.where(ProcessingJob.status == status)
        count_query = count_query.where(ProcessingJob.status == status)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(ProcessingJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobListResponse(
        items=[JobSummary.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=JobSummary)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobSummary:
    job = _get_job_or_404(job_id, db)
    return JobSummary.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobSummary)
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> JobSummary:
    job = _get_job_or_404(job_id, db)
    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Job already {job.status}.")

    if job.status == "queued":
        # Not started yet: mark cancelled directly
        job.status = "cancelled"
        job.completed_at = utcnow()
        db.commit()
    else:
        processing_worker.cancel(job_id)
        # Worker will persist the cancelled state; nudge it if queued
        job.status = "cancelled"
        db.commit()
    return JobSummary.model_validate(job)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
@router.get("/{job_id}/detections", response_model=DetectionListResponse)
def list_detections(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> DetectionListResponse:
    _get_job_or_404(job_id, db)
    count_q = select(func.count()).select_from(DetectionObservation).where(
        DetectionObservation.job_id == job_id
    )
    total = db.scalar(count_q) or 0
    rows = db.scalars(
        select(DetectionObservation)
        .where(DetectionObservation.job_id == job_id)
        .order_by(DetectionObservation.frame_timestamp_seconds)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return DetectionListResponse(
        items=[DetectionOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}/preview")
def job_preview(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """First annotated frame (JPEG) for the UI."""
    _get_job_or_404(job_id, db)
    path = settings.processed_dir / job_id / "preview.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Preview not available yet.")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{job_id}/frames", response_model=FrameManifestResponse)
def job_frames(job_id: str, db: Session = Depends(get_db)) -> FrameManifestResponse:
    """Persisted YOLO-annotated frames for the split comparison viewer.

    Serves the manifest written during processing; for past clips processed
    before frame persistence existed, backfills on demand from stored
    detections (no model re-inference).
    """
    job = _get_job_or_404(job_id, db)
    cfg = job.processing_config or {}
    entries = frame_store.ensure_frames(db, job)
    if entries is None:
        # Job not completed (or source gone) — no frames can exist yet
        return FrameManifestResponse(
            items=[],
            total=0,
            sample_rate_fps=float(cfg.get("sample_rate_fps", settings.default_sample_rate_fps)),
            video_fps=0.0,
        )

    manifest = frame_store.read_manifest(job_id) or {}
    return FrameManifestResponse(
        items=[
            FrameEntry(
                ordinal=e["ordinal"],
                frame_index=e["frame_index"],
                timestamp_s=e["timestamp_s"],
                detections=e["detections"],
                image_url=f"/api/jobs/{job_id}/frames/{e['ordinal']}",
            )
            for e in entries
        ],
        total=len(entries),
        sample_rate_fps=float(manifest.get("sample_rate_fps", cfg.get("sample_rate_fps", 1.0))),
        video_fps=float(manifest.get("video_fps", 0.0)),
    )


@router.get("/{job_id}/frames/{ordinal}")
def job_frame_image(job_id: str, ordinal: int, db: Session = Depends(get_db)) -> FileResponse:
    """One annotated frame JPEG (ordinal is an int — no path traversal)."""
    _get_job_or_404(job_id, db)
    if ordinal < 0:
        raise HTTPException(status_code=404, detail="Frame not found")
    path = frame_store.frame_path(job_id, ordinal)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path, media_type="image/jpeg")


_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


@router.get("/{job_id}/source")
def job_source_video(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Original uploaded video for the left pane of the split viewer.

    Path is validated to stay inside the app's data directory — the endpoint
    never serves arbitrary filesystem paths.
    """
    job = _get_job_or_404(job_id, db)
    path = Path(job.video_path)
    try:
        path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Source video not available")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Source video not available")
    media_type = _VIDEO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/{job_id}/artifact")
def job_artifact(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Annotated video download (generated on demand if missing)."""
    job = _get_job_or_404(job_id, db)
    path = settings.processed_dir / job_id / "annotated.mp4"
    if not path.is_file():
        if job.status != "completed":
            raise HTTPException(status_code=404, detail="Artifact not ready yet.")
        _generate_artifact(job)
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"annotated_{Path(job.original_filename).stem}.mp4",
    )


@router.post("/{job_id}/publish")
def publish_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Create/merge map hazards from the job's observations.

    Idempotent: re-publishing returns the existing aggregates without
    duplicating hazards.
    """
    from app.services.aggregation_service import aggregate_observations

    job = _get_job_or_404(job_id, db)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Job must be completed before publishing.")

    observations = db.scalars(
        select(DetectionObservation).where(DetectionObservation.job_id == job_id)
    ).all()

    mappable = [o for o in observations if o.gps_lat is not None and o.gps_lon is not None]
    if not mappable:
        raise HTTPException(
            status_code=409,
            detail="No GPS-tagged detections to publish. Attach a GPS CSV and reprocess.",
        )

    if job.is_published:
        # Idempotent replay: recompute aggregates (hazard links already exist)
        stats = aggregate_observations(db, observations)
        return {
            "status": "already_published",
            "job_id": job_id,
            "published_hazards": _linked_hazard_count(db, job_id),
            "recompute": stats,
        }

    stats = aggregate_observations(db, observations)
    job.is_published = True
    job.published_at = utcnow()
    db.commit()

    count = _linked_hazard_count(db, job_id)
    log.info("Job %s published: %d hazards (%s)", job_id, count, stats)
    return {
        "status": "published",
        "job_id": job_id,
        "published_hazards": count,
        "stats": stats,
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
@router.delete("/{job_id}", status_code=200)
def delete_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Retention: remove a job and all its uploaded/processed artifacts."""
    import shutil

    job = _get_job_or_404(job_id, db)
    if job.status in {"processing"}:
        raise HTTPException(
            status_code=409, detail="Cancel the job before deleting it."
        )

    removed_files = 0
    # Uploaded source files (video + gps) are stored by UUID name
    for path_str in (job.video_path, job.gps_file_path):
        if not path_str:
            continue
        p = Path(path_str)
        # Only delete inside our own data dirs (never arbitrary paths)
        try:
            p.resolve().relative_to(settings.data_dir.resolve())
            if p.is_file():
                p.unlink()
                removed_files += 1
        except ValueError:
            pass  # outside data/ — leave it alone

    processed_dir = settings.processed_dir / job_id
    if processed_dir.is_dir():
        shutil.rmtree(processed_dir, ignore_errors=True)
        removed_files += 1

    db.delete(job)  # observations cascade
    db.commit()

    # Garbage-collect hazards that no longer have any linked observations
    from sqlalchemy import func, select

    from app.db.models import Hazard

    orphan_ids = db.scalars(
        select(Hazard.id)
        .outerjoin(DetectionObservation)
        .group_by(Hazard.id)
        .having(func.count(DetectionObservation.id) == 0)
    ).all()
    for hid in orphan_ids:
        h = db.get(Hazard, hid)
        if h is not None:
            db.delete(h)
    db.commit()

    log.info(
        "Job %s deleted (%d artifacts removed, %d orphan hazards swept)",
        job_id, removed_files, len(orphan_ids),
    )
    return {
        "status": "deleted",
        "job_id": job_id,
        "artifacts_removed": removed_files,
        "orphan_hazards_removed": len(orphan_ids),
    }


def _get_job_or_404(job_id: str, db: Session) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _linked_hazard_count(db: Session, job_id: str) -> int:
    from app.db.models import Hazard

    n = db.scalar(
        select(func.count(func.distinct(DetectionObservation.candidate_hazard_id))).where(
            DetectionObservation.job_id == job_id,
            DetectionObservation.candidate_hazard_id.is_not(None),
        )
    )
    return int(n or 0)


def _generate_artifact(job: ProcessingJob) -> None:
    """Render the annotated video on demand (e.g., when preview was skipped)."""
    from app.db.database import SessionLocal
    from app.services import video_service

    db = SessionLocal()
    try:
        info = video_service.open_video(Path(job.video_path))
        observations = db.scalars(
            select(DetectionObservation).where(DetectionObservation.job_id == job.id)
        ).all()
        by_index: dict[int, list[dict]] = {}
        for obs in observations:
            # Frame index = timestamp * real fps (keeps overlay aligned)
            frame_index = int(round(obs.frame_timestamp_seconds * info.fps))
            by_index.setdefault(frame_index, []).append(
                {
                    "class_name": obs.class_name,
                    "confidence": obs.confidence,
                    "bbox_xyxy": obs.bbox_xyxy,
                    "mask": None,
                }
            )
        video_service.annotate_video(
            Path(job.video_path),
            settings.processed_dir / job.id / "annotated.mp4",
            by_index,
        )
    finally:
        db.close()
