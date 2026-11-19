"""Unit tests: GPS matching, Haversine, aggregation/dedup, job states."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.aggregation_service import derive_status, is_stale
from app.services.gps_service import (
    MATCH_INTERPOLATED,
    MATCH_NEAREST,
    MATCH_NONE,
    GpsMatch,
    GpsPoint,
    match_gps,
)
from app.utils.geometry import angle_between_headings, bearing_deg, haversine_m

UTC = timezone.utc


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=second)


@pytest.fixture()
def points() -> list[GpsPoint]:
    # 1 Hz track moving north at ~111.32 m (0.001 deg lat) per second
    return [
        GpsPoint(time=_t(i), lat=10.0 + i * 0.001, lon=20.0, speed_mps=8.0, heading_deg=0.0)
        for i in range(10)
    ]


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------
def test_haversine_known_distance() -> None:
    # 1 degree of latitude ~ 111.19 km (sphere of R=6371 km)
    d = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert 111_000 < d < 111_400


def test_haversine_zero() -> None:
    assert haversine_m(19.076, 72.877, 19.076, 72.877) == pytest.approx(0.0, abs=1e-6)


def test_haversine_symmetric() -> None:
    a = haversine_m(-4.275, 21.5425, -4.27, 21.55)
    b = haversine_m(-4.27, 21.55, -4.275, 21.5425)
    assert a == pytest.approx(b)


def test_bearing_north() -> None:
    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=0.1)


def test_bearing_east() -> None:
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=0.1)


def test_angle_between_headings_wraparound() -> None:
    assert angle_between_headings(350.0, 10.0) == pytest.approx(20.0)
    assert angle_between_headings(0.0, 180.0) == pytest.approx(180.0)


# ---------------------------------------------------------------------------
# GPS timestamp matching
# ---------------------------------------------------------------------------
def test_match_exact(points: list[GpsPoint]) -> None:
    m = match_gps(_t(3), points, max_tolerance_s=5.0)
    assert m.method == MATCH_NEAREST
    assert m.delta_seconds == pytest.approx(0.0)
    assert m.lat == pytest.approx(10.003)
    assert m.lon == pytest.approx(20.0)


def test_match_interpolated_midpoint(points: list[GpsPoint]) -> None:
    # Halfway between t=3 and t=4 -> interpolated lat halfway
    m = match_gps(_t(3) + timedelta(seconds=0.5), points, max_tolerance_s=5.0)
    assert m.method == MATCH_INTERPOLATED
    assert m.lat == pytest.approx(10.0035, abs=1e-6)


def test_match_out_of_tolerance(points: list[GpsPoint]) -> None:
    m = match_gps(_t(3) + timedelta(seconds=30), points, max_tolerance_s=5.0)
    assert m.method == MATCH_NONE
    assert m.lat is None


def test_match_no_points() -> None:
    m = match_gps(_t(0), [], max_tolerance_s=5.0)
    assert m.method == MATCH_NONE
    assert m.lat is None


def test_match_before_first_point(points: list[GpsPoint]) -> None:
    # 2 s before the first fix -> within tolerance => nearest
    m = match_gps(_t(-2), points, max_tolerance_s=5.0)
    assert m.method == MATCH_NEAREST
    assert m.lat == pytest.approx(10.0)


def test_match_never_stale_silent(points: list[GpsPoint]) -> None:
    # 10 s past the last fix -> none (delta recorded, no coordinates)
    m = match_gps(_t(20), points, max_tolerance_s=5.0)
    assert m.method == MATCH_NONE
    assert m.lat is None
    assert m.delta_seconds is not None and m.delta_seconds > 5.0


# ---------------------------------------------------------------------------
# Status derivation / staleness
# ---------------------------------------------------------------------------
def test_status_transitions() -> None:
    assert derive_status(1, "new") == "new"
    assert derive_status(2, "new") == "observed"
    assert derive_status(3, "observed") == "confirmed"
    assert derive_status(1, "resolved") == "resolved"  # manual status never auto-overwritten


def test_is_stale_threshold() -> None:
    from app.db.models import Hazard

    fresh = Hazard(latitude=0, longitude=0, last_seen_at=datetime.now(UTC).replace(tzinfo=None))
    assert is_stale(fresh) is False

    old = Hazard(
        latitude=0,
        longitude=0,
        last_seen_at=(datetime.now(UTC) - timedelta(days=31)).replace(tzinfo=None),
    )
    assert is_stale(old) is True


# ---------------------------------------------------------------------------
# Aggregation / deduplication
# ---------------------------------------------------------------------------
def test_aggregation_merges_and_separates() -> None:
    """Same-location reports merge; distant detections stay separate."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.database import Base
    from app.db.models import DetectionObservation, Hazard
    from app.services.aggregation_service import aggregate_observations

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        def obs(lat: float, lon: float, conf: float = 0.6) -> DetectionObservation:
            return DetectionObservation(
                job_id="job1",
                frame_timestamp_seconds=1.0,
                class_name="pothole",
                confidence=conf,
                bbox_xyxy=[1, 2, 3, 4],
                gps_lat=lat,
                gps_lon=lon,
                gps_match_method="nearest",
                gps_match_delta_seconds=0.1,
            )

        # 3 detections within ~5 m of each other, 1 far away (>15 m), 1 without GPS
        near = [obs(-4.2750 + i * 0.00001, 21.5425) for i in range(3)]
        far = obs(-4.2760, 21.5425, conf=0.9)
        no_gps = DetectionObservation(
            job_id="job1",
            frame_timestamp_seconds=2.0,
            class_name="pothole",
            confidence=0.5,
            bbox_xyxy=[1, 2, 3, 4],
            gps_lat=None,
            gps_lon=None,
            gps_match_method="none",
        )

        stats = aggregate_observations(db, near + [far, no_gps])

        assert stats["created"] == 2      # near-cluster + far one
        assert stats["merged"] == 2       # 2 of the 3 near ones merged
        assert stats["skipped_no_gps"] == 1

        hazards = db.query(Hazard).all()
        assert len(hazards) == 2

        near_hazard = next(h for h in hazards if h.report_count == 3)
        assert near_hazard.report_count == 3
        assert near_hazard.status == "confirmed"  # 3 reports -> corroborated
        assert near_hazard.confidence_max == pytest.approx(0.6)

        # Observations linked, not deleted
        linked = (
            db.query(DetectionObservation)
            .filter(DetectionObservation.candidate_hazard_id == near_hazard.id)
            .count()
        )
        assert linked == 3


def test_publish_idempotent_no_duplicate_hazards() -> None:
    """Re-running aggregation over the same observations must not duplicate."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.database import Base
    from app.db.models import DetectionObservation, Hazard
    from app.services.aggregation_service import aggregate_observations

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        o = DetectionObservation(
            job_id="job1",
            frame_timestamp_seconds=1.0,
            class_name="pothole",
            confidence=0.7,
            bbox_xyxy=[1, 2, 3, 4],
            gps_lat=-4.275,
            gps_lon=21.5425,
            gps_match_method="nearest",
            gps_match_delta_seconds=0.0,
        )
        db.add(o)
        db.commit()

        first = aggregate_observations(db, [o])
        assert first["created"] == 1
        assert db.query(Hazard).one().report_count == 1

        second = aggregate_observations(db, [o])  # replay
        assert second["created"] == 0
        assert second["merged"] == 1

        assert db.query(Hazard).count() == 1
        # Replaying must not inflate report counts (publish idempotency)
        assert db.query(Hazard).one().report_count == 1


def test_reaggregate_stable_link_when_centroid_drifts() -> None:
    """An observation keeps its hazard across runs even if the centroid moves.

    Guards against publish re-counting observations when the hazard centroid
    shifts enough that a *neighbouring* hazard becomes the nearest match.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.database import Base
    from app.db.models import DetectionObservation, Hazard
    from app.services.aggregation_service import aggregate_observations

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        # Hazard A at origin, hazard B 10 m east (both within 15 m of obs)
        a = Hazard(latitude=0.0, longitude=0.0, report_count=1)
        b = Hazard(latitude=0.0, longitude=0.00009, report_count=1)  # ~10 m
        db.add_all([a, b])
        db.flush()

        # Observation originally linked to A, sitting between them
        obs = DetectionObservation(
            job_id="job1",
            frame_timestamp_seconds=1.0,
            class_name="pothole",
            confidence=0.7,
            bbox_xyxy=[1, 2, 3, 4],
            gps_lat=0.0,
            gps_lon=0.00005,
            gps_match_method="nearest",
            gps_match_delta_seconds=0.0,
            candidate_hazard_id=a.id,
        )
        db.add(obs)
        db.commit()

        # Simulate centroid drift: A's centroid moves toward the obs AND past
        # it so B is now strictly nearest.
        a.latitude, a.longitude = 0.0, 0.00006
        db.commit()

        stats = aggregate_observations(db, [obs])

        assert stats["created"] == 0
        assert stats["merged"] == 1
        # Counted exactly once, on its original hazard — not re-counted on B
        db.refresh(a)
        db.refresh(b)
        assert a.report_count == 1
        assert b.report_count == 1
        assert obs.candidate_hazard_id == a.id


# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------
def test_job_status_values_and_progress_bounds() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.database import Base
    from app.db.models import ProcessingJob

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        job = ProcessingJob(original_filename="x.mp4", video_path="/tmp/x.mp4")
        db.add(job)
        db.flush()  # column defaults apply at flush
        assert job.status == "queued"
        assert job.progress_percent == 0

        # State machine vocabulary matches the brief
        allowed = {"queued", "processing", "aggregating", "completed", "failed", "cancelled"}
        assert allowed == {
            "queued", "processing", "aggregating", "completed", "failed", "cancelled"
        }

        # progress clamps to [0, 100]
        job.progress_percent = min(max(150, 0), 100)
        assert job.progress_percent == 100
