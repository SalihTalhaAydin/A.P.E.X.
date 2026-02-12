"""Tests for brain.server FastAPI app."""

import pytest
from brain.server import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI TestClient. Lifespan runs; DB and HA use test env from conftest."""
    with TestClient(app) as c:
        yield c


def test_health_returns_200(client):
    """GET /health returns 200 and status online."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "model" in data
    assert "ha_reachable" in data


def test_debug_ha_returns_ha_reachable(client):
    """GET /api/debug/ha returns ha_reachable and ha_url."""
    response = client.get("/api/debug/ha")
    assert response.status_code == 200
    data = response.json()
    assert "ha_reachable" in data
    assert "ha_url" in data
