"""Per-frame annotated JPEG persistence for the split comparison viewer.

Every sampled frame is stored on disk under ``data/processed/{job_id}/frames/``
with a JSON manifest, so the original-vs-YOLO comparison survives restarts and
is available for past (already processed) clips.

Manifest shape:
    {
      "version": 1,
      "sample_rate_fps": 1.0,
      "video_fps": 25.0,
      "entries": [
        {"ordinal": 0, "frame_index": 0, "timestamp_s": 0.0, "detections": 2},
        ...
      ]
    }
``ordinal`` is the stable identifier used in URLs (zero-padded JPEG name).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import DetectionObservation, ProcessingJob
from app.services import video_service

log = get_logger(__name__)

MANIFEST_NAME = "manifest.json"
_FRAMES_SUBDIR = "frames"


def frames_dir(job_id: str) -> Path:
    return settings.processed_dir / job_id / _FRAMES_SUBDIR


def manifest_path(job_id: str) -> Path:
    return frames_dir(job_id) / MANIFEST_NAME


def frame_filename(ordinal: int) -> str:
    return f"{ordinal:04d}.jpg"


def frame_path(job_id: str, ordinal: int) -> Path:
    return frames_dir(job_id) / frame_filename(ordinal)


def write_manifest(
    job_id: str,
    entries: list[dict],
    sample_rate_fps: float,
    video_fps: float,
) -> Path:
    """Atomically write the manifest (tmp file + rename) so concurrent reads
    from the API never observe a half-written JSON during live streaming."""
    dest = manifest_path(job_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "sample_rate_fps": sample_rate_fps,
        "video_fps": video_fps,
        "entries": entries,
    }
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def read_manifest(job_id: str) -> dict | None:
    path = manifest_path(job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    return data


def save_frame(
    job_id: str,
    ordinal: int,
    frame_index: int,
    timestamp_s: float,
    frame,
    detections: list[dict],
) -> dict:
    """Draw detections onto one sampled frame, store it, return its entry."""
    dest = frame_path(job_id, ordinal)
    dest.parent.mkdir(parents=True, exist_ok=True)
    annotated = video_service.draw_detections(frame, detections, timestamp_s)
    import cv2

    cv2.imwrite(str(dest), annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return {
        "ordinal": ordinal,
        "frame_index": frame_index,
        "timestamp_s": round(timestamp_s, 3),
        "detections": len(detections),
    }


def ensure_frames(db: Session, job: ProcessingJob) -> list[dict] | None:
    """Return the manifest for a job, backfilling it for past processed clips.

    Backfill re-decodes the source video at the job's original sample rate and
    re-draws the detections already stored in the DB (no model inference).

    Returns None when frames cannot exist yet (job not completed).
    """
    existing = read_manifest(job.id)
    if existing is not None:
        return existing["entries"]

    if job.status != "completed":
        return None

    video_path = Path(job.video_path)
    if not video_path.is_file():
        log.warning("Job %s source video missing; cannot backfill frames", job.id)
        return None

    cfg = job.processing_config or {}
    sample_rate = float(cfg.get("sample_rate_fps", settings.default_sample_rate_fps))

    # Group stored detections by their frame timestamp (same rounding as worker)
    rows = db.scalars(
        select(DetectionObservation).where(DetectionObservation.job_id == job.id)
    ).all()
    by_ts: dict[float, list[dict]] = {}
    for obs in rows:
        key = round(obs.frame_timestamp_seconds, 3)
        by_ts.setdefault(key, []).append(
            {
                "class_name": obs.class_name,
                "confidence": obs.confidence,
                "bbox_xyxy": obs.bbox_xyxy,
                "mask": None,
            }
        )

    try:
        info = video_service.open_video(video_path)
    except video_service.VideoOpenError as exc:
        log.warning("Job %s backfill failed to open video: %s", job.id, exc)
        return None

    entries: list[dict] = []
    ordinal = 0
    for sample in video_service.iter_samples(video_path, sample_rate):
        dets = by_ts.get(round(sample.timestamp_s, 3), [])
        entries.append(
            save_frame(job.id, ordinal, sample.index, sample.timestamp_s, sample.frame, dets)
        )
        ordinal += 1

    write_manifest(job.id, entries, sample_rate_fps=sample_rate, video_fps=info.fps)
    log.info("Backfilled %d annotated frames for job %s", len(entries), job.id)
    return entries
