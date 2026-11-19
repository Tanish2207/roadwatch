"""Route simulation endpoints: registry, session control, alert queries."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.simulation import (
    RouteDetail,
    RouteListResponse,
    SimulationAlertRequest,
    SimulationAlertResponse,
    SimulationStartRequest,
    SimulationState,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])

# In-memory simulation state for the MVP (single local session).
_state = SimulationState()
# Guards _state against concurrent alert ticks (sync endpoints run in threads).
_lock = threading.Lock()


@router.get("/routes", response_model=RouteListResponse)
def list_routes() -> RouteListResponse:
    from app.services.simulation_service import list_routes as _list

    return RouteListResponse(items=_list())


@router.get("/routes/{route_id}", response_model=RouteDetail)
def get_route(route_id: str) -> RouteDetail:
    from app.services.simulation_service import get_route_detail

    detail = get_route_detail(route_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return RouteDetail(**detail)


@router.post("/start", response_model=SimulationState)
def start_simulation(req: SimulationStartRequest) -> SimulationState:
    from app.services.simulation_service import route_exists

    if not route_exists(req.route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    global _state
    with _lock:
        # A fresh run resets the dedup set: alerts may fire again after reset.
        _state = SimulationState(
            running=True,
            route_id=req.route_id,
            speed_mps=req.speed_mps,
            warning_distance_m=req.warning_distance_m,
        )
    return _state


@router.post("/alerts", response_model=SimulationAlertResponse)
def query_alerts(
    req: SimulationAlertRequest, db: Session = Depends(get_db)
) -> SimulationAlertResponse:
    """One playback tick: hazards that just became eligible for an alert."""
    from app.services.simulation_service import query_alerts as _query

    with _lock:
        if not _state.running or _state.route_id != req.route_id:
            raise HTTPException(
                status_code=409,
                detail="No active simulation for this route — POST /simulation/start first",
            )
        new_alerts = _query(db, req, _state.alerted_hazard_ids)
        _state.alerted_hazard_ids.extend(a.hazard_id for a in new_alerts)
        return SimulationAlertResponse(
            alerts=new_alerts,
            alerted_hazard_ids=list(_state.alerted_hazard_ids),
            vehicle_heading_deg=req.heading_deg,
            corridor_applied=req.heading_deg is not None,
        )


@router.post("/stop", response_model=SimulationState)
def stop_simulation() -> SimulationState:
    global _state
    with _lock:
        _state = SimulationState()
    return _state


@router.get("/state", response_model=SimulationState)
def simulation_state() -> SimulationState:
    with _lock:
        return _state
