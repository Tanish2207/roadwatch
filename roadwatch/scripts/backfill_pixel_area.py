"""Recompute hazard pixel-area summaries (map marker sizing).

Hazards aggregated before bounding-box areas were tracked have no
``pixel_area_summary``, so their markers cannot be sized from the YOLO bbox.
This backfill:

  1. records the source frame size on each job (probed from its video) when
     the processing config does not have it yet,
  2. rebuilds every hazard's summary from its linked observations.

Safe to re-run: summaries are recomputed from scratch, never accumulated.

Usage (from roadwatch/):
    python scripts/backfill_pixel_area.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import DetectionObservation, Hazard, ProcessingJob  # noqa: E402
from app.services.aggregation_service import summarize_bbox_areas  # noqa: E402


def probe_frame_size(video_path: str) -> tuple[int, int] | None:
    """Decode one frame to learn the (width, height) bboxes were drawn in."""
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        return int(frame.shape[1]), int(frame.shape[0])
    finally:
        cap.release()


def main() -> None:
    db = SessionLocal()
    try:
        # 1. Frame size per job (missing only for pre-existing jobs).
        probed = 0
        for job in db.scalars(select(ProcessingJob)).all():
            cfg = job.processing_config or {}
            if cfg.get("frame_width") and cfg.get("frame_height"):
                continue
            size = probe_frame_size(job.video_path)
            if size is None:
                print(f"  ! no frames readable for {job.original_filename} ({job.id[:8]})")
                continue
            job.processing_config = {**cfg, "frame_width": size[0], "frame_height": size[1]}
            probed += 1
        db.commit()
        print(f"frame size recorded for {probed} job(s)")

        # 2. Rebuild each hazard's area summary.
        updated = 0
        hazards = db.scalars(select(Hazard)).all()
        for hazard in hazards:
            linked = db.scalars(
                select(DetectionObservation).where(
                    DetectionObservation.candidate_hazard_id == hazard.id
                )
            ).all()
            summary = summarize_bbox_areas(linked)
            if summary != hazard.pixel_area_summary:
                hazard.pixel_area_summary = summary
                updated += 1
        db.commit()

        print(f"area summary rebuilt for {updated}/{len(hazards)} hazard(s)")
        for hazard in sorted(hazards, key=lambda h: h.id):
            frac = (hazard.pixel_area_summary or {}).get("mean_area_frac")
            if frac is None:
                print(f"  {hazard.id[:8]}  mean_area_frac=unknown")
            else:
                print(f"  {hazard.id[:8]}  mean_area_frac={frac * 100:.3f}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
