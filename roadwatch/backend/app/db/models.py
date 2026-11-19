"""Database models: ProcessingJob, DetectionObservation, Hazard, HazardStatusHistory."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    original_filename: Mapped[str] = mapped_column(String(512))
    video_path: Mapped[str] = mapped_column(Text)
    gps_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    processing_config: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    detections_count: Mapped[int] = mapped_column(Integer, default=0)
    is_published: Mapped[bool] = mapped_column(default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    observations: Mapped[list["DetectionObservation"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class DetectionObservation(Base):
    __tablename__ = "detection_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("processing_jobs.id", ondelete="CASCADE"), index=True
    )

    frame_timestamp_seconds: Mapped[float] = mapped_column(Float)
    class_name: Mapped[str] = mapped_column(String(64))
    class_id: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float)
    bbox_xyxy: Mapped[list] = mapped_column(JSON)
    mask_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_match_method: Mapped[str] = mapped_column(String(16), default="none")
    gps_match_delta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    tracking_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_hazard_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("hazards.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[ProcessingJob] = relationship(back_populates="observations")
    hazard: Mapped["Hazard | None"] = relationship(back_populates="observations")


class Hazard(Base):
    __tablename__ = "hazards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)

    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    report_count: Mapped[int] = mapped_column(Integer, default=1)

    confidence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    physical_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixel_area_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    location_uncertainty_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    observations: Mapped[list[DetectionObservation]] = relationship(back_populates="hazard")
    status_history: Mapped[list["HazardStatusHistory"]] = relationship(
        back_populates="hazard", cascade="all, delete-orphan"
    )


class HazardStatusHistory(Base):
    __tablename__ = "hazard_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hazard_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("hazards.id", ondelete="CASCADE"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    hazard: Mapped[Hazard] = relationship(back_populates="status_history")
