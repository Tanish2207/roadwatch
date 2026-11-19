"""M6/M7 tests: hazard filters, detail/status update, simulation alert query."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base, engine
from app.db.models import Hazard
from app.main import app
from app.schemas.simulation import SimulationAlertRequest
from app.services.simulation_service import query_alerts

UTC = timezone.utc
ANCHOR_LAT, ANCHOR_LON = -4.275002, 21.542498  # demo route start


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    # Simulations are module-global; always reset so tests stay isolated.
    c.post("/api/simulation/stop")
    # This file inserts hazards into the shared test DB — remove them so
    # later files (e.g. smoke tests asserting empty lists) stay valid.
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        for h in db.query(Hazard).all():
            db.delete(h)
        db.commit()


def _make_hazards(db: Session) -> dict[str, str]:
    """Three hazards near the route start: ahead, behind, and far away."""
    now = datetime.now(UTC).replace(tzinfo=None)
    specs = {
        # ~56 m north of the anchor (ahead when heading north)
        "ahead": dict(latitude=ANCHOR_LAT + 0.0005, longitude=ANCHOR_LON),
        # ~56 m south of the anchor (behind when heading north)
        "behind": dict(latitude=ANCHOR_LAT - 0.0005, longitude=ANCHOR_LON),
        # ~556 m north — outside the 150 m default, inside the 1000 m max
        "far": dict(latitude=ANCHOR_LAT + 0.005, longitude=ANCHOR_LON),
    }
    ids: dict[str, str] = {}
    for name, pos in specs.items():
        h = Hazard(
            **pos,
            status="new",
            report_count=2,
            confidence_avg=0.5,
            confidence_max=0.6,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(h)
        db.flush()
        ids[name] = h.id
    db.commit()
    return ids


def _req(lat: float, lon: float, heading: float | None, warning: float = 150.0) -> SimulationAlertRequest:
    return SimulationAlertRequest(
        route_id="potholed-road",
        latitude=lat,
        longitude=lon,
        heading_deg=heading,
        warning_distance_m=warning,
    )


# ---------------------------------------------------------------------------
# M6: hazard query filters
# ---------------------------------------------------------------------------
def test_hazard_min_reports_filter(client: TestClient) -> None:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        now = datetime.now(UTC).replace(tzinfo=None)
        db.add(Hazard(latitude=1.0, longitude=1.0, status="new", report_count=1,
                      first_seen_at=now, last_seen_at=now))
        db.add(Hazard(latitude=2.0, longitude=2.0, status="confirmed", report_count=5,
                      first_seen_at=now, last_seen_at=now))
        db.commit()

    res = client.get("/api/hazards", params={"min_reports": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["report_count"] == 5


def test_hazard_seen_within_hours_filter(client: TestClient) -> None:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        fresh = datetime.now(UTC).replace(tzinfo=None)
        stale = fresh - timedelta(hours=48)
        db.add(Hazard(latitude=1.0, longitude=1.0, status="new", report_count=1,
                      first_seen_at=fresh, last_seen_at=fresh))
        db.add(Hazard(latitude=2.0, longitude=2.0, status="new", report_count=1,
                      first_seen_at=stale, last_seen_at=stale))
        db.commit()

    res = client.get("/api/hazards", params={"seen_within_hours": 24})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["latitude"] == pytest.approx(1.0)


def test_hazard_seen_within_hours_validation(client: TestClient) -> None:
    res = client.get("/api/hazards", params={"seen_within_hours": -1})
    assert res.status_code == 422


def test_hazard_list_exposes_bbox_area_frac(client: TestClient) -> None:
    """Marker sizing input (bbox area / frame area) rides on list + detail."""
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        now = datetime.now(UTC).replace(tzinfo=None)
        db.add(Hazard(latitude=1.0, longitude=1.0, status="new", report_count=1,
                      first_seen_at=now, last_seen_at=now,
                      pixel_area_summary={"count": 3, "mean_area_frac": 0.045,
                                          "mean_area_px": 9000.0, "max_area_px": 12000.0}))
        db.add(Hazard(latitude=2.0, longitude=2.0, status="new", report_count=1,
                      first_seen_at=now, last_seen_at=now, pixel_area_summary=None))
        db.commit()

    res = client.get("/api/hazards")
    assert res.status_code == 200
    items = {i["latitude"]: i for i in res.json()["items"]}

    assert items[1.0]["bbox_area_frac"] == pytest.approx(0.045)
    assert items[1.0]["pixel_area_summary"]["count"] == 3
    # Hazards without an area summary fall back to the default marker size
    assert items[2.0]["bbox_area_frac"] is None

    hid = next(
        i["id"] for i in res.json()["items"] if i["latitude"] == pytest.approx(1.0)
    )
    detail = client.get(f"/api/hazards/{hid}").json()
    assert detail["bbox_area_frac"] == pytest.approx(0.045)


# ---------------------------------------------------------------------------
# M6: detail + status update
# ---------------------------------------------------------------------------
def test_hazard_detail_and_status_update(client: TestClient) -> None:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        ids = _make_hazards(db)
    hid = ids["ahead"]

    # Detail: shape includes M6 fields
    res = client.get(f"/api/hazards/{hid}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == hid
    assert detail["observations_total"] == 0
    assert detail["observations"] == []
    assert detail["status_history"] == []
    assert detail["is_stale"] is False

    # Status update -> resolved, with history recorded
    res = client.patch(f"/api/hazards/{hid}", json={"status": "resolved", "note": "repaired"})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "resolved"
    assert updated["resolved_note"] == "repaired"
    assert updated["resolved_at"] is not None
    assert len(updated["status_history"]) == 1
    assert updated["status_history"][0]["new_status"] == "resolved"
    assert updated["status_history"][0]["note"] == "repaired"

    # Resolved hazards no longer appear in the default active list? (they do —
    # status filter is opt-in) but are excluded from simulation alerts below.
    res = client.get("/api/hazards", params={"status": "resolved"})
    assert res.json()["total"] == 1

    # Invalid status -> 422
    res = client.patch(f"/api/hazards/{hid}", json={"status": "bogus"})
    assert res.status_code == 422

    # 404 for unknown hazard
    assert client.patch("/api/hazards/nope", json={"status": "resolved"}).status_code == 404


# ---------------------------------------------------------------------------
# M7: route detail
# ---------------------------------------------------------------------------
def test_route_detail_includes_points(client: TestClient) -> None:
    res = client.get("/api/simulation/routes/potholed-road")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "potholed-road"
    assert body["point_count"] == len(body["points"])
    assert body["point_count"] > 10
    assert "lat" in body["points"][0] and "lon" in body["points"][0]

    assert client.get("/api/simulation/routes/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# M7: alert query (service level — reusable, testable logic per brief §12)
# ---------------------------------------------------------------------------
def test_alerts_radius_filter() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _make_hazards(db)
        # Heading north, 150 m radius: only the hazard ahead qualifies
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=0.0), [])
        got = {a.hazard_id for a in alerts}
        assert got == {ids["ahead"]}
        assert alerts[0].distance_m == pytest.approx(55.6, abs=2.0)
        assert alerts[0].corridor_filtered is True

        # No heading -> corridor skipped, both nearby hazards alert
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None), [])
        assert {a.hazard_id for a in alerts} == {ids["ahead"], ids["behind"]}
        assert all(a.corridor_filtered is False for a in alerts)

        # Wider radius reaches the far hazard
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None, warning=1000.0), [])
        assert {a.hazard_id for a in alerts} == set(ids.values())


def test_alerts_corridor_filter() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _make_hazards(db)
        # Heading south -> the hazard north is behind the vehicle
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=180.0), [])
        got = {a.hazard_id for a in alerts}
        assert ids["ahead"] not in got
        assert got == {ids["behind"]}

        # Heading east -> both are ~90 deg off to the side: outside a 60 deg
        # half-angle corridor, so nothing alerts
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=90.0), [])
        assert alerts == []


def test_alerts_dedup_no_repeats() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _make_hazards(db)
        first = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None), [])
        assert {a.hazard_id for a in first} == {ids["ahead"], ids["behind"]}

        # Same tick again with the alerted set filled -> no repeats (brief §12)
        alerted = [a.hazard_id for a in first]
        second = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None), alerted)
        assert second == []


def test_alerts_skip_resolved() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ids = _make_hazards(db)
        resolved = db.get(Hazard, ids["ahead"])
        resolved.status = "resolved"
        db.commit()

        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None), [])
        assert ids["ahead"] not in {a.hazard_id for a in alerts}
        assert {a.hazard_id for a in alerts} == {ids["behind"]}


def test_alerts_sorted_nearest_first() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _make_hazards(db)
        alerts = query_alerts(db, _req(ANCHOR_LAT, ANCHOR_LON, heading=None, warning=1000.0), [])
        distances = [a.distance_m for a in alerts]
        assert distances == sorted(distances)


# ---------------------------------------------------------------------------
# M7: alert endpoint session semantics
# ---------------------------------------------------------------------------
def test_alert_endpoint_requires_active_session(client: TestClient) -> None:
    payload = {"route_id": "potholed-road", "latitude": ANCHOR_LAT, "longitude": ANCHOR_LON}
    # No session yet -> 409
    assert client.post("/api/simulation/alerts", json=payload).status_code == 409

    # Unknown route -> 404 on start
    res = client.post("/api/simulation/start", json={"route_id": "nope"})
    assert res.status_code == 404

    # Start a real session, then alerts flow
    res = client.post(
        "/api/simulation/start",
        json={"route_id": "potholed-road", "speed_mps": 8.0, "warning_distance_m": 150.0},
    )
    assert res.status_code == 200
    assert res.json()["running"] is True

    res = client.post("/api/simulation/alerts", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["alerts"], list)
    assert body["corridor_applied"] is False  # no heading sent
    assert body["alerted_hazard_ids"] == [a["hazard_id"] for a in body["alerts"]]

    # Wrong route for the active session -> 409
    res = client.post("/api/simulation/alerts", json={**payload, "route_id": "other"})
    assert res.status_code == 409

    # Validation: out-of-range coordinates -> 422
    res = client.post(
        "/api/simulation/alerts", json={**payload, "latitude": 999.0}
    )
    assert res.status_code == 422

    # Stop clears the session and the dedup set
    res = client.post("/api/simulation/stop")
    assert res.json()["running"] is False
    assert res.json()["alerted_hazard_ids"] == []
    assert client.post("/api/simulation/alerts", json=payload).status_code == 409


def test_alert_endpoint_dedups_across_ticks(client: TestClient) -> None:
    from app.db.database import SessionLocal

    with SessionLocal() as db:
        _make_hazards(db)

    client.post("/api/simulation/start", json={"route_id": "potholed-road"})
    payload = {"route_id": "potholed-road", "latitude": ANCHOR_LAT, "longitude": ANCHOR_LON}

    first = client.post("/api/simulation/alerts", json=payload).json()
    assert len(first["alerts"]) >= 1
    second = client.post("/api/simulation/alerts", json=payload).json()
    assert second["alerts"] == []  # no re-alerts within one session
    assert second["alerted_hazard_ids"] == first["alerted_hazard_ids"]

    # Reset (stop + start) allows alerts again — dedup is per session
    client.post("/api/simulation/stop")
    client.post("/api/simulation/start", json={"route_id": "potholed-road"})
    third = client.post("/api/simulation/alerts", json=payload).json()
    assert len(third["alerts"]) == len(first["alerts"])
