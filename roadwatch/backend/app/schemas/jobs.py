"""Schemas for processing jobs."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    aggregating = "aggregating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    status: JobStatus
    progress_percent: int
    frames_processed: int
    detections_count: int
    is_published: bool = False
    processing_config: dict = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    page: int
    page_size: int


class DetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    frame_timestamp_seconds: float
    class_name: str
    class_id: int
    confidence: float
    bbox_xyxy: list[float]
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_match_method: str
    gps_match_delta_seconds: float | None = None
    vehicle_heading: float | None = None
    vehicle_speed: float | None = None
    tracking_id: int | None = None


class DetectionListResponse(BaseModel):
    items: list[DetectionOut]
    total: int
    page: int
    page_size: int


class FrameEntry(BaseModel):
    """One persisted annotated frame in the split comparison viewer."""

    ordinal: int
    frame_index: int
    timestamp_s: float
    detections: int
    image_url: str


class FrameManifestResponse(BaseModel):
    items: list[FrameEntry]
    total: int
    sample_rate_fps: float
    video_fps: float
