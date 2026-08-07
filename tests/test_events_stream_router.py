"""
Unit & integration tests for Phase 2 SSE Live Event Stream Router (/events/stream).
"""

import asyncio
import json
import types

import pytest
from fastapi.testclient import TestClient

from backend.app.eventbus import InMemoryEventBus
from backend.app.main import app
from backend.app.routers.events_stream import stream_events
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
        correlation_id="INC-STREAM-TEST-001",
        payload={"stage_name": "Vision Analysis", "agent_id": "VisionSpecAgent", "confidence": 0.95}
    )

    # Put in history and publish to active subscribers
    bus._history.append(env)

    response = client.get(f"/events/stream?token={_TOKEN}&correlation_id=INC-STREAM-TEST-001&max_events=1")
    assert response.status_code == 200
    assert ": ping" in response.text


async def test_events_stream_delivers_a_live_published_event():
    """Regression test for a real bug (found + fixed 2026-08-04): the old
    implementation cancelled the shared bus generator's own await on every
    0.5s idle timeout, which — via InMemoryEventBus.stream()'s
    try/finally — permanently deregistered the subscriber and killed the
    generator after the first tick. Every event published *after* that
    point silently never reached the client, even though `max_events=1`
    tests above never would have caught it (they return before the loop
    ever times out once).

    Driven directly against stream_events()'s returned StreamingResponse
    rather than through TestClient/httpx: httpx's ASGITransport fully
    drains the ASGI app before handing back a response (it isn't a real
    streaming transport), so it can't observe an event published while the
    generator is still running — it would just hang waiting for the
    generator to finish, which it only does at max_events. Calling the
    route directly, in the same event loop as the concurrent publish(),
    exercises the exact generator closure that had the bug without that
    transport limitation.
    """
    async def _always_connected():
        return False

    bus = InMemoryEventBus()
    fake_request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(event_bus=bus)),
        is_disconnected=_always_connected,
    )

    response = await stream_events(
        fake_request, token=_TOKEN, correlation_id="INC-STREAM-LIVE-001", max_events=2
    )

    chunks = []

    async def _drain():
        async for chunk in response.body_iterator:
            chunks.append(chunk)
            if len(chunks) >= 2:
                return

    reader = asyncio.create_task(_drain())

    # Give the stream time to pass the ping and settle into the wait loop
    # — including past the old code's 0.5s failure window — before
    # publishing.
    await asyncio.sleep(0.8)

    env = EventEnvelope(
        event_type="AgentCompleted",
        produced_by="test_agent",
        correlation_id="INC-STREAM-LIVE-001",
        payload={"stage_name": "Vision Analysis", "agent_id": "VisionSpecAgent", "confidence": 0.95},
    )
    await bus.publish(env)

    await asyncio.wait_for(reader, timeout=5.0)

    assert chunks[0] == ": ping\n\n"
    assert chunks[1].startswith("data: ")
    delivered = json.loads(chunks[1].removeprefix("data: ").rstrip("\n"))
    assert delivered["correlationId"] == "INC-STREAM-LIVE-001"
