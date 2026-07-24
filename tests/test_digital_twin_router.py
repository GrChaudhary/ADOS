"""
Unit & integration tests for Digital Twin REST Router (GET /digital-twin/lines).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from knowledge import DigitalTwinStore


@pytest.fixture
def client():
    return TestClient(app)


def test_digital_twin_store_all_lines():
    store = DigitalTwinStore()
    lines = store.get_all_line_states()
    assert len(lines) == 4
    line_ids = {l.line_id for l in lines}
    assert line_ids == {"Line 1", "Line 2", "Line 3", "Warehouse"}

    line3 = store.get_line_state("Line 3")
    assert line3 is not None
    assert line3.status == "DEGRADED"


def test_get_digital_twin_lines_unauthorized(client):
    response = client.get("/digital-twin/lines")
    assert response.status_code == 401


def test_get_digital_twin_lines_success(client):
    response = client.get(
        "/digital-twin/lines",
        headers={"Authorization": "Bearer dev-local-only-token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4

    line_ids = [item["lineId"] for item in data]
    assert "Line 1" in line_ids
    assert "Line 2" in line_ids
    assert "Line 3" in line_ids
    assert "Warehouse" in line_ids

    line3 = next(item for item in data if item["lineId"] == "Line 3")
    assert line3["status"] == "DEGRADED"
