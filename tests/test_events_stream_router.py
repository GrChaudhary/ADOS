"""
Unit & integration tests for Phase 2 SSE Live Event Stream Router (/events/stream).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import admin_auth_header
from contracts import EventEnvelope

_TOKEN = admin_auth_header()["Authorization"].removeprefix("Bearer ")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_events_stream_unauthorized_missing_token(client):
    response = client.get("/events/stream")
    assert response.status_code == 422


def test_events_stream_unauthorized_invalid_token(client):
    response = client.get("/events/stream?token=invalid-token")
    assert response.status_code == 401


def test_events_stream_connection_success(client):
    response = client.get(f"/events/stream?token={_TOKEN}&max_events=1")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert ": ping" in response.text


def test_events_stream_publishes_and_filters_by_incident(client):
    bus = app.state.event_bus

    env = EventEnvelope(
        event_type="AgentCompleted",
        produced_by="test_agent",
        incident_id="INC-STREAM-TEST-001",
        payload={"stage_name": "Vision Analysis", "agent_id": "VisionSpecAgent", "confidence": 0.95}
    )

    # Put in history and publish to active subscribers
    bus._history.append(env)

    response = client.get(f"/events/stream?token={_TOKEN}&incident_id=INC-STREAM-TEST-001&max_events=1")
    assert response.status_code == 200
    assert ": ping" in response.text
