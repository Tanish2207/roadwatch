"""Route registry + alert query for the vehicle simulation.

Routes are plain JSON-friendly records so they can later be stored in the
database or loaded from GPX without changing the API contract.

The alert query (brief §12) lives here as a pure-ish function so it can be
unit tested independently of HTTP: Haversine radius filter, optional forward
corridor (heading-angle threshold), resolved hazards excluded, and session
dedup so one hazard alerts at most once per run.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Hazard
from app.schemas.simulation import SimulationAlert, SimulationAlertRequest
from app.utils.geometry import angle_between_headings, bearing_deg, haversine_m

# route_id -> {"name", "description", "points": [{lat, lon, timestamp_seconds}]}
_ROUTES: dict[str, dict] = {}


def load_demo_routes() -> None:
    """(Re)load seeded routes from data/demo/routes/*.json (idempotent).

    Rebuilds a fresh dict and swaps it in atomically so route files can be
    added or edited while the server is running (no restart required).
    """
    demo_routes_dir = settings.demo_dir / "routes"
    if not demo_routes_dir.is_dir():
        return
    import json

    loaded: dict[str, dict] = {}
    for path in sorted(demo_routes_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        route_id = payload.get("id") or path.stem
        loaded[route_id] = payload
    global _ROUTES
    _ROUTES = loaded


def list_routes() -> list[dict]:
    # Always re-scan: cheap (a handful of small JSON files) and lets users
    # drop new route files into data/demo/routes/ without restarting.
    load_demo_routes()
    return [
        {
            "id": rid,
            "name": r.get("name", rid),
            "description": r.get("description", ""),
            "is_synthetic": bool(r.get("is_synthetic", True)),
            "distance_m": float(r.get("distance_m", 0.0)),
            "point_count": len(r.get("points", [])),
        }
        for rid, r in _ROUTES.items()
    ]


def get_route(route_id: str) -> dict | None:
    if route_id not in _ROUTES:
        load_demo_routes()
    return _ROUTES.get(route_id)


def route_exists(route_id: str) -> bool:
    return get_route(route_id) is not None


def get_route_detail(route_id: str) -> dict | None:
    """Full route payload including the coordinate array (for map playback)."""
    route = get_route(route_id)
    if route is None:
        return None
    points = [
        {
            "lat": p.get("lat"),
            "lon": p.get("lon"),
            "timestamp_seconds": float(p.get("timestamp_seconds", 0.0)),
        }
        for p in route.get("points", [])
        if p.get("lat") is not None and p.get("lon") is not None
    ]
    return {
        "id": route_id,
        "name": route.get("name", route_id),
        "description": route.get("description", ""),
        "is_synthetic": bool(route.get("is_synthetic", True)),
        "distance_m": float(route.get("distance_m", 0.0)),
        "point_count": len(points),
        "points": points,
    }


def query_alerts(
    db: Session,
    req: SimulationAlertRequest,
    alerted_hazard_ids: list[str],
    corridor_angle_deg: float | None = None,
) -> list[SimulationAlert]:
    """Return hazards that just entered the alert zone for this tick.

    Filter chain (brief §12):
      1. skip hazards already alerted this session (dedup — no repeats);
      2. skip resolved hazards;
      3. Haversine distance <= warning radius;
      4. if heading is known, require the hazard inside the forward corridor
         (|angle between vehicle heading and bearing-to-hazard| <= threshold).
         The corridor is approximate and flagged as such in the response.

    Returns new alerts sorted by distance (nearest first).
    """
    angle = corridor_angle_deg if corridor_angle_deg is not None else settings.sim_corridor_angle_deg
    already = set(alerted_hazard_ids)

    rows = db.scalars(select(Hazard).where(Hazard.status != "resolved")).all()
    results: list[SimulationAlert] = []
    for h in rows:
        if h.id in already:
            continue
        distance = haversine_m(req.latitude, req.longitude, h.latitude, h.longitude)
        if distance > req.warning_distance_m:
            continue
        bearing = bearing_deg(req.latitude, req.longitude, h.latitude, h.longitude)
        corridor = False
        # Within 1 m the vehicle is on top of the hazard — heading is
        # meaningless, so skip the corridor filter for that case.
        if req.heading_deg is not None and distance >= 1.0:
            if angle_between_headings(req.heading_deg, bearing) > angle:
                continue
            corridor = True
        results.append(
            SimulationAlert(
                hazard_id=h.id,
                latitude=h.latitude,
                longitude=h.longitude,
                status=h.status,
                report_count=h.report_count,
                confidence_avg=h.confidence_avg,
                distance_m=round(distance, 1),
                bearing_deg=round(bearing, 1),
                corridor_filtered=corridor,
            )
        )
    results.sort(key=lambda a: a.distance_m)
    return results
