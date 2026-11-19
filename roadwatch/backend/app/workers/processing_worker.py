"""In-process background worker: runs video jobs without blocking the API.

One job at a time (MVP), status persisted to the DB after each stage.
Progress is monotonic: extraction+inference 0-80%, aggregation 80-95%,
annotation/encode 95-100%.
"""
from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import SessionLocal
from app.db.models import DetectionObservation, ProcessingJob, utcnow
from app.services import aggregation_service, frame_store, gps_service, video_service
from app.services.video_service import DetectionAccumulator

log = get_logger(__name__)

_job_queue: "queue.Queue[str]" = queue.Queue()
_cancel_flags: dict[str, threading.Event] = {}
_worker_thread: threading.Thread | None = None
_start_lock = threading.Lock()


def enqueue(job_id: str) -> None:
    """Queue a job for processing (starts the worker thread if needed)."""
    global _worker_thread
    with _start_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="rw-worker")
            _worker_thread.start()
    _cancel_flags[job_id] = threading.Event()
    _job_queue.put(job_id)


def cancel(job_id: str) -> bool:
    flag = _cancel_flags.get(job_id)
    if flag is None:
        return False
    flag.set()
    return True


def is_busy() -> bool:
    return _job_queue.qsize() > 0 or any(
        f.is_set() is False for f in _cancel_flags.values()
    )


def queue_length() -> int:
    return _job_queue.qsize()


def _worker_loop() -> None:
    log.info("Processing worker started")
    while True:
        job_id = _job_queue.get()
        try:
            _process_job(job_id)
        except Exception:  # noqa: BLE001
            log.error("Worker crashed on job %s:\n%s", job_id, traceback.format_exc())
            _mark_failed(job_id, "Unexpected processing error. See server logs.")
        finally:
            _cancel_flags.pop(job_id, None)
            _job_queue.task_done()
    # unreachable: queue.get() blocks forever (daemon thread)


def _set_progress(db, job: ProcessingJob, percent: int, status: str | None = None) -> None:
    job.progress_percent = max(job.progress_percent, min(int(percent), 100))  # monotonic
    if status:
        job.status = status
    db.commit()


def _process_job(job_id: str) -> None:
    cancel_flag = _cancel_flags.get(job_id)
    should_cancel = lambda: bool(cancel_flag and cancel_flag.is_set())  # noqa: E731

    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        if job.status == "cancelled":
            return

        cfg = job.processing_config or {}
        sample_rate = float(cfg.get("sample_rate_fps", settings.default_sample_rate_fps))
        threshold = float(cfg.get("confidence_threshold", settings.default_confidence_threshold))
        image_size = int(cfg.get("image_size", settings.default_image_size))

        job.status = "processing"
        job.started_at = utcnow()
        job.progress_percent = 0
        job.error_message = None
        db.commit()

        # -- Model ----------------------------------------------------------
        from app.ml.predictor import ModelNotLoadedError, predictor

        try:
            predictor.ensure_loaded()
        except ModelNotLoadedError as exc:
            _set_progress(db, job, 100, "failed")
            job.error_message = str(exc)
            db.commit()
            return

        # -- GPS sidecar (optional) ----------------------------------------
        gps_points: list[gps_service.GpsPoint] = []
        gps_error: str | None = None
        if job.gps_file_path:
            try:
                gps_points = gps_service.load_gps_csv(Path(job.gps_file_path))
            except gps_service.GpsParseError as exc:
                gps_error = str(exc)
                log.warning("Job %s GPS parse failed: %s", job_id, exc)

        # -- Video probe ----------------------------------------------------
        video_path = Path(job.video_path)
        try:
            info = video_service.open_video(video_path)
        except video_service.VideoOpenError as exc:
            _set_progress(db, job, 100, "failed")
            job.error_message = str(exc)
            db.commit()
            return

        log.info(
            "Job %s: %s (%.1fs @ %.0f fps), gps_points=%d, sample=%.2f fps, conf>=%.2f",
            job_id, video_path.name, info.duration_s, info.fps,
            len(gps_points), sample_rate, threshold,
        )

        # -- Sample + infer --------------------------------------------------
        accumulator = DetectionAccumulator()
        observations: list[DetectionObservation] = []
        preview_saved = False
        preview_dir = settings.processed_dir / job_id
        frames_total = max(info.frame_count, 1)
        sampled = 0
        frame_entries: list[dict] = []  # persisted annotated frames (split viewer)
        # Rewrite the manifest ~once per second of video so the UI can show
        # annotations live while the job is still processing.
        manifest_every = max(1, int(round(sample_rate)))

        for sample in video_service.iter_samples(
            video_path, sample_rate, should_cancel=should_cancel
        ):
            if should_cancel():
                break

            detections = predictor.predict_frame(
                sample.frame, confidence=threshold, image_size=image_size
            )
            sampled += 1
            accumulator.add(sample.index, detections)

            # GPS association
            if gps_points:
                frame_time = _frame_absolute_time(gps_points, sample.timestamp_s)
                match = gps_service.match_gps(
                    frame_time, gps_points, settings.gps_max_tolerance_seconds
                )
            else:
                match = gps_service.GpsMatch(None, None, gps_service.MATCH_NONE, None)

            for det in detections:
                observations.append(
                    DetectionObservation(
                        job_id=job.id,
                        frame_timestamp_seconds=round(sample.timestamp_s, 3),
                        class_name=det["class_name"],
                        class_id=det["class_id"],
                        confidence=round(det["confidence"], 4),
                        bbox_xyxy=det["bbox_xyxy"],
                        gps_lat=match.lat,
                        gps_lon=match.lon,
                        gps_match_method=match.method,
                        gps_match_delta_seconds=match.delta_seconds,
                        vehicle_heading=match.heading_deg,
                        vehicle_speed=match.speed_mps,
                    )
                )

            # First detection frame -> preview image
            if detections and not preview_saved:
                video_service.save_preview_frame(
                    sample.frame, detections, sample.timestamp_s,
                    preview_dir / "preview.jpg",
                )
                preview_saved = True

            # Persist every sampled frame (annotated) for the split viewer
            frame_entries.append(
                frame_store.save_frame(
                    job_id, sampled - 1, sample.index,
                    sample.timestamp_s, sample.frame, detections,
                )
            )
            # Incremental manifest: lets the frontend stream frames live
            if len(frame_entries) % manifest_every == 0:
                frame_store.write_manifest(
                    job_id, frame_entries,
                    sample_rate_fps=sample_rate, video_fps=info.fps,
                )

            # Progress (0 -> 75 during inference)
            if sample.index % 10 == 0:
                pct = int(75 * min(sample.index / frames_total, 1.0))
                _set_progress(db, job, pct, "processing")
                job.frames_processed = sampled
                db.commit()

            if should_cancel():
                break

        job.frames_processed = sampled
        db.commit()

        # Persist the frame manifest (even on cancel: keep what we processed)
        try:
            frame_store.write_manifest(
                job_id, frame_entries,
                sample_rate_fps=sample_rate, video_fps=info.fps,
            )
        except OSError as exc:
            log.warning("Could not write frame manifest for job %s: %s", job_id, exc)

        if should_cancel():
            _set_progress(db, job, 100, "cancelled")
            return

        # -- Persist observations -------------------------------------------
        db.add_all(observations)
        job.detections_count = len(observations)
        db.commit()
        _set_progress(db, job, 80, "aggregating")

        # -- GPS quality summary --------------------------------------------
        if gps_error:
            job.error_message = f"GPS file ignored: {gps_error}"
        elif not gps_points:
            job.error_message = (
                "No GPS provided — detections cannot be mapped. "
                "Attach a GPS CSV to publish hazards."
            )
        db.commit()

        # -- Aggregate (only GPS-tagged observations) ------------------------
        stats = aggregation_service.aggregate_observations(db, observations)
        log.info("Job %s aggregation: %s", job_id, stats)
        _set_progress(db, job, 95, "aggregating")

        # -- Annotated video --------------------------------------------------
        try:
            out_path = preview_dir / "annotated.mp4"
            video_service.annotate_video(
                video_path,
                out_path,
                accumulator.by_index,
                should_cancel=should_cancel,
            )
        except video_service.VideoOpenError as exc:
            log.warning("Annotation failed for job %s: %s", job_id, exc)

        if should_cancel():
            _set_progress(db, job, 100, "cancelled")
            return

        job.status = "completed"
        job.progress_percent = 100
        job.completed_at = utcnow()
        db.commit()
        log.info(
            "Job %s completed: %d frames sampled, %d detections, %d mapped",
            job_id, sampled, len(observations),
            sum(1 for o in observations if o.gps_lat is not None),
        )
    finally:
        db.close()


def _frame_absolute_time(
    points: list[gps_service.GpsPoint], offset_s: float
) -> datetime:
    """Video time -> absolute UTC time using the first GPS fix as the anchor.

    The prototype assumes video t=0 coincides with the first GPS timestamp
    (documented in docs/gps-format.md).
    """
    from datetime import timedelta

    anchor = points[0].time
    return anchor + timedelta(seconds=offset_s)


def _mark_failed(job_id: str, message: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if job is not None:
            job.status = "failed"
            job.progress_percent = 100
            job.error_message = message
            job.completed_at = utcnow()
            db.commit()
    finally:
        db.close()
