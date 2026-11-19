"""Schemas for route simulation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RoutePoint(BaseModel):
    lat: float
    lon: float
    timestamp_seconds: float = 0.0


class RouteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    is_synthetic: bool = True
    distance_m: float = 0.0
    point_count: int = 0


class RouteDetail(RouteSummary):
    """Full route including coordinate array for playback rendering."""

    points: list[RoutePoint] = Field(default_factory=list)


class RouteListResponse(BaseModel):
    items: list[RouteSummary]


class SimulationStartRequest(BaseModel):
    route_id: str
    speed_mps: float = Field(default=10.0, ge=1.0, le=60.0)
    warning_distance_m: float = Field(default=150.0, ge=20.0, le=1000.0)


class SimulationState(BaseModel):
    running: bool = False
    route_id: str | None = None
    speed_mps: float = 10.0
    warning_distance_m: float = 150.0
    elapsed_seconds: float = 0.0
    alerted_hazard_ids: list[str] = Field(default_factory=list)


class SimulationAlertRequest(BaseModel):
    """One playback tick: where the simulated vehicle is right now.

    The frontend interpolates position locally (brief §12 allows frontend
    simulation for the MVP) and asks the backend for eligible alerts, which
    keeps the hazard-query logic in one reusable, testable place.
    """

    route_id: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    heading_deg: float | None = Field(default=None, ge=0.0, le=360.0)
    warning_distance_m: float = Field(default=150.0, ge=20.0, le=1000.0)


class SimulationAlert(BaseModel):
    """A hazard that just became eligible for an alert this tick."""

    hazard_id: str
    latitude: float
    longitude: float
    status: str
    report_count: int
    confidence_avg: float | None = None
    distance_m: float
    bearing_deg: float
    # True when the heading corridor filter was applied (approximate).
    corridor_filtered: bool = False


class SimulationAlertResponse(BaseModel):
    alerts: list[SimulationAlert] = Field(default_factory=list)
    # Full dedup set for this session; echoed so the client can resync.
    alerted_hazard_ids: list[str] = Field(default_factory=list)
    vehicle_heading_deg: float | None = None
    # Labels the corridor filter as approximate (brief §12).
    corridor_applied: bool = False
    corridor_note: str = "Approximate forward corridor (heading-angle filter)."
