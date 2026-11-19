"""Schemas for hazards and map queries."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class HazardStatus(str, Enum):
    new = "new"
    observed = "observed"
    confirmed = "confirmed"
    resolved = "resolved"


class HazardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    latitude: float
    longitude: float
    status: HazardStatus
    report_count: int
    confidence_avg: float | None = None
    confidence_max: float | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    location_uncertainty_m: float | None = None
    is_stale: bool = False


class HazardListResponse(BaseModel):
    items: list[HazardSummary]
    total: int
    page: int
    page_size: int


class HazardObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    frame_timestamp_seconds: float
    class_name: str
    confidence: float
    gps_lat: float | None = None
    gps_lon: float | None = None
    created_at: datetime


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    previous_status: str | None = None
    new_status: str
    note: str | None = None
    created_at: datetime


class HazardDetail(HazardSummary):
    resolved_at: datetime | None = None
    resolved_note: str | None = None
    pixel_area_summary: dict | None = None
    physical_area_m2: float | None = None
    observations: list[HazardObservationOut] = Field(default_factory=list)
    observations_total: int = 0
    status_history: list[StatusHistoryOut] = Field(default_factory=list)


class HazardStatusUpdate(BaseModel):
    status: HazardStatus
    note: str | None = None
