"""Smoke tests for M1 skeleton: health, settings, list endpoints, DB schema."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import Base, engine


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def test_health_ok(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["backend"] == "ok"
    assert "ready" in body["model"]


def test_settings_shape(client: TestClient) -> None:
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["app"]["name"] == "RoadWatch"
    assert body["privacy"]["local_inference"] is True
    assert body["defaults"]["confidence_threshold"] > 0
    assert ".mp4" in body["limits"]["allowed_video_extensions"]


def test_jobs_list_empty(client: TestClient) -> None:
    res = client.get("/api/jobs")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_hazards_list_empty(client: TestClient) -> None:
    res = client.get("/api/hazards")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []


def test_hazard_bbox_validation(client: TestClient) -> None:
    res = client.get("/api/hazards", params={"bbox": "not-a-bbox"})
    assert res.status_code == 422


def test_simulation_routes_list(client: TestClient) -> None:
    res = client.get("/api/simulation/routes")
    assert res.status_code == 200
    assert "items" in res.json()


def test_job_404(client: TestClient) -> None:
    res = client.get("/api/jobs/does-not-exist")
    assert res.status_code == 404


def test_root_route(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["health"] == "/api/health"
