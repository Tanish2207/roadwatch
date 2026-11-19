"""Tests for the split-viewer frame store: persistence, backfill, endpoints."""
from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.main import app
from app.services import frame_store

JOB_ID = "testframejob0001"
VIDEO_FRAMES = 6
VIDEO_FPS = 2.0  # sample_rate=1 fps -> samples at t=0.0, 1.0, 2.0 (3 frames)


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def frame_job(request):
    """A completed job with a tiny source video + two stored detections.

    Cleanup is registered as a finalizer BEFORE setup so it runs even when
    setup fails halfway (keeps the empty-list smoke assertions passing).
    """
    from app.db.models import DetectionObservation, ProcessingJob

    Base.metadata.create_all(bind=engine)

    job_dir = settings.processed_dir / JOB_ID

    def _cleanup() -> None:
        import shutil

        db = SessionLocal()
        try:
            job = db.get(ProcessingJob, JOB_ID)
            if job is not None:
                db.delete(job)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()
        shutil.rmtree(job_dir, ignore_errors=True)

    request.addfinalizer(_cleanup)

    shutil.rmtree(job_dir, ignore_errors=True)  # remove any stale leftovers
    job_dir.mkdir(parents=True, exist_ok=True)

    # Tiny 64x64 test video (6 frames @ 2 fps = 3 s)
    video_path = job_dir / "source.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), VIDEO_FPS, (64, 64)
    )
    assert writer.isOpened()
    import numpy as np

    for i in range(VIDEO_FRAMES):
        frame = np.full((64, 64, 3), i * 30, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    db = SessionLocal()
    try:
        job = ProcessingJob(
            id=JOB_ID,
            original_filename="tiny.mp4",
            video_path=str(video_path),
            status="completed",
            processing_config={"sample_rate_fps": 1.0, "confidence_threshold": 0.4},
        )
        db.add(job)
        # Detections on samples 0 (t=0.0) and 1 (t=1.0); sample 2 has none
        db.add_all(
            [
                DetectionObservation(
                    job_id=JOB_ID,
                    frame_timestamp_seconds=0.0,
                    class_name="Pothole",
                    class_id=0,
                    confidence=0.9,
                    bbox_xyxy=[4, 4, 40, 40],
                    gps_match_method="none",
                ),
                DetectionObservation(
                    job_id=JOB_ID,
                    frame_timestamp_seconds=1.0,
                    class_name="Pothole",
                    class_id=0,
                    confidence=0.6,
                    bbox_xyxy=[10, 10, 50, 50],
                    gps_match_method="none",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    yield JOB_ID
    # cleanup runs via the finalizer registered above (survives setup failures)


# ---------------------------------------------------------------------------
# Frame store unit behavior
# ---------------------------------------------------------------------------
def test_manifest_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "processed_dir", tmp_path)
    entries = [
        {"ordinal": 0, "frame_index": 0, "timestamp_s": 0.0, "detections": 2},
        {"ordinal": 1, "frame_index": 25, "timestamp_s": 1.0, "detections": 0},
    ]
    frame_store.write_manifest("jobx", entries, sample_rate_fps=1.0, video_fps=25.0)

    data = frame_store.read_manifest("jobx")
    assert data is not None
    assert data["entries"] == entries
    assert data["sample_rate_fps"] == 1.0
    assert data["video_fps"] == 25.0

    assert frame_store.read_manifest("missing-job") is None


def test_frame_filename_is_padded_and_safe() -> None:
    assert frame_store.frame_filename(0) == "0000.jpg"
    assert frame_store.frame_filename(259) == "0259.jpg"
    # ordinal is an int path segment — no traversal possible
    assert ".." not in frame_store.frame_filename(7)


def test_missing_manifest_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "processed_dir", tmp_path)
    assert frame_store.read_manifest("nope") is None


def test_manifest_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent readers must never see a partial manifest (live streaming)."""
    monkeypatch.setattr(settings, "processed_dir", tmp_path)
    entries = [{"ordinal": 0, "frame_index": 0, "timestamp_s": 0.0, "detections": 1}]
    frame_store.write_manifest("jobz", entries, sample_rate_fps=1.0, video_fps=25.0)

    assert frame_store.read_manifest("jobz")["entries"] == entries
    # No temp file left behind
    leftovers = list(frame_store.frames_dir("jobz").glob("*.tmp"))
    assert leftovers == []


def test_frames_stream_while_job_processing(client: TestClient) -> None:
    """A processing job serves whatever frames the worker has written so far."""
    from app.db.models import ProcessingJob

    db = SessionLocal()
    job = ProcessingJob(
        id="testframejob0003",
        original_filename="live.mp4",
        video_path=str(settings.processed_dir / "gone.mp4"),  # no video needed
        status="processing",
        processing_config={"sample_rate_fps": 1.0},
    )
    db.add(job)
    db.commit()
    db.close()
    try:
        # No manifest yet -> empty (not an error) while queued/processing
        res = client.get("/api/jobs/testframejob0003/frames")
        assert res.status_code == 200
        assert res.json()["total"] == 0

        # Worker writes the first frames mid-run -> immediately visible
        frame_store.write_manifest(
            "testframejob0003",
            [
                {"ordinal": 0, "frame_index": 0, "timestamp_s": 0.0, "detections": 2},
                {"ordinal": 1, "frame_index": 25, "timestamp_s": 1.0, "detections": 1},
            ],
            sample_rate_fps=1.0,
            video_fps=25.0,
        )
        res = client.get("/api/jobs/testframejob0003/frames")
        body = res.json()
        assert body["total"] == 2
        assert body["items"][1]["detections"] == 1
        # The image is fetchable the moment it exists on disk
        assert client.get(body["items"][0]["image_url"]).status_code == 404  # no JPEG yet
    finally:
        db = SessionLocal()
        try:
            j = db.get(ProcessingJob, "testframejob0003")
            if j is not None:
                db.delete(j)
            db.commit()
        finally:
            db.close()
        import shutil

        shutil.rmtree(frame_store.frames_dir("testframejob0003"), ignore_errors=True)


# ---------------------------------------------------------------------------
# Backfill for past processed clips
# ---------------------------------------------------------------------------
def test_backfill_persists_frames_for_past_job(frame_job: str) -> None:
    db = SessionLocal()
    try:
        from app.db.models import ProcessingJob

        job = db.get(ProcessingJob, frame_job)
        assert job is not None

        # No manifest yet -> backfill from stored detections
        assert frame_store.read_manifest(frame_job) is None
        entries = frame_store.ensure_frames(db, job)
    finally:
        db.close()

    assert entries is not None
    assert len(entries) == 3  # t = 0.0, 1.0, 2.0 (1 fps from a 2 fps clip)
    assert entries[0]["detections"] == 1
    assert entries[1]["detections"] == 1
    assert entries[2]["detections"] == 0

    # All JPEGs exist on disk (persistence for past clips)
    for e in entries:
        path = frame_store.frame_path(frame_job, e["ordinal"])
        assert path.is_file()
        assert path.stat().st_size > 0

    # Manifest now present; second call serves it without re-decoding
    cached = frame_store.read_manifest(frame_job)
    assert cached is not None and len(cached["entries"]) == 3


def test_backfill_refuses_incomplete_job(frame_job: str) -> None:
    from app.db.models import ProcessingJob

    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, frame_job)
        job.status = "processing"
        db.commit()
        assert frame_store.ensure_frames(db, job) is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
def test_frames_endpoint_backfills_and_serves(client: TestClient, frame_job: str) -> None:
    res = client.get(f"/api/jobs/{frame_job}/frames")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert body["sample_rate_fps"] == 1.0
    first = body["items"][0]
    assert first["ordinal"] == 0
    assert first["timestamp_s"] == 0.0
    assert first["image_url"] == f"/api/jobs/{frame_job}/frames/0"

    # Frame image
    img = client.get(first["image_url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    assert img.content[:2] == b"\xff\xd8"  # JPEG magic

    # Out-of-range ordinal -> 404
    assert client.get(f"/api/jobs/{frame_job}/frames/999").status_code == 404
    # Path-traversal-shaped segment never reaches the filesystem:
    # route won't match (404) or fails int validation (422) — both safe
    bad = client.get(f"/api/jobs/{frame_job}/frames/..%2F..%2Fsecret")
    assert bad.status_code in (404, 422)
    # Unknown job -> 404
    assert client.get("/api/jobs/nope/frames").status_code == 404


def test_source_video_endpoint(client: TestClient, frame_job: str) -> None:
    res = client.get(f"/api/jobs/{frame_job}/source")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("video/mp4")
    assert res.headers.get("accept-ranges") == "bytes"  # smooth seeking
    assert len(res.content) > 0

    assert client.get("/api/jobs/nope/source").status_code == 404


def test_frames_endpoint_empty_for_unfinished_job(client: TestClient) -> None:
    from app.db.models import ProcessingJob

    db = SessionLocal()
    job = ProcessingJob(
        id="testframejob0002",
        original_filename="x.mp4",
        video_path=str(settings.processed_dir / "nope.mp4"),
        status="queued",
    )
    db.add(job)
    db.commit()
    db.close()
    try:
        res = client.get("/api/jobs/testframejob0002/frames")
        assert res.status_code == 200
        assert res.json()["total"] == 0
        assert res.json()["items"] == []
    finally:
        db = SessionLocal()
        try:
            j = db.get(ProcessingJob, "testframejob0002")
            if j is not None:
                db.delete(j)
            db.commit()
        finally:
            db.close()


def test_frames_cleaned_up_with_job_delete(client: TestClient, frame_job: str) -> None:
    """DELETE removes the persisted frames directory (retention)."""
    client.get(f"/api/jobs/{frame_job}/frames")  # materialize frames
    assert frame_store.frames_dir(frame_job).is_dir()

    res = client.delete(f"/api/jobs/{frame_job}")
    assert res.status_code == 200
    assert not frame_store.frames_dir(frame_job).exists()
    # prevent fixture teardown from erroring on a missing row
    assert client.get(f"/api/jobs/{frame_job}").status_code == 404
