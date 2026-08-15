"""
P11 — the two DB-backed admission gates in backend/app/mcp_gateway.py::
request_capability: approval-queue depth (a Postgres advisory-lock-
serialized COUNT, checked before a request is committed as
pending_approval) and per-session activity/repeat-attempt (a `FOR UPDATE`
row lock on RuntimeSessionRow.capability_request_count).

Both are proven under REAL concurrent Postgres transactions
(asyncio.gather), not simulated sequentially — the concurrent-race tests
below are the actual acceptance evidence for "concurrent race -> limit
cannot be bypassed" against real transactional behavior, matching this
phase's own evidence requirement.
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.app import mcp_gateway, metrics
from backend.app.config import settings
from backend.app.mcp_gateway import hash_token, request_capability
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub
from orchestrate.runtime.prime import token_expiry

EXPENSIVE = {"_estimated_cost_usd": 300_000.0}  # forces EXECUTIVE_APPROVAL (parks) — see orchestrate/governance.py


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "pw")


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


def _install_ok_servicenow(monkeypatch):
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"result": {"sys_id": "abc", "number": "INC0000001"}})

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(ok_handler))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)


async def _mission_and_session(capability="NotifyITHelpdesk", allowed=None):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="admission gate test", objective="o", domain="it",
            allowed_capabilities=allowed or [capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            token_expires_at=token_expiry(1800.0),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


async def _pending_count() -> int:
    async with async_session_factory() as db:
        rows = (
            await db.execute(text("SELECT COUNT(*) FROM capability_requests WHERE status = 'pending_approval'"))
        ).scalar_one()
        return rows


# --- approval queue depth: below / at / over ------------------------------------

async def test_approval_queue_below_limit_allowed(monkeypatch):
    monkeypatch.setattr(settings, "max_pending_approvals", 2)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    result = await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))
    assert result["status"] == "pending_approval"


async def test_approval_queue_at_and_over_limit_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "max_pending_approvals", 2)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    first = await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": "one"})
    second = await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": "two"})
    assert first["status"] == "pending_approval"
    assert second["status"] == "pending_approval"
    assert await _pending_count() == 2

    before = metrics.admission_rejections_total.labels(gate="approval_queue")._value.get()
    third = await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": "three"})
    assert third["status"] == "denied"
    assert "approval queue is at capacity" in third["reason"]
    assert await _pending_count() == 2, "a refused park must not have been committed as pending_approval"
    assert metrics.admission_rejections_total.labels(gate="approval_queue")._value.get() == before + 1


async def test_approval_queue_rejection_never_reaches_a_connector(monkeypatch):
    """Parking never calls a connector regardless — this pins that a queue-
    capacity refusal follows the exact same no-side-effect shape as an
    ordinary park, not some new path that might one day grow one."""
    monkeypatch.setattr(settings, "max_pending_approvals", 1)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": "one"})
    result = await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": "two"})
    assert result["status"] == "denied"

    async with async_session_factory() as db:
        rows = (await db.execute(text("SELECT status FROM capability_requests ORDER BY created_at"))).scalars().all()
    assert set(rows) == {"pending_approval", "denied"}
    assert "executing" not in rows and "executed" not in rows


async def test_approval_queue_concurrent_race_cannot_bypass_limit(monkeypatch):
    """Real Postgres, real concurrency: 8 genuinely concurrent park attempts
    (distinct idempotency keys via distinct argument content, same session)
    against a limit of 3. The advisory lock must serialize the count-check-
    then-park sequence so the final pending count never exceeds 3 — a plain
    check-then-act COUNT would not guarantee this under real overlap."""
    monkeypatch.setattr(settings, "max_pending_approvals", 3)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    import asyncio

    async def attempt(i: int):
        return await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": f"concurrent-{i}"})

    results = await asyncio.gather(*[attempt(i) for i in range(8)])
    parked = [r for r in results if r["status"] == "pending_approval"]
    denied = [r for r in results if r["status"] == "denied"]

    assert len(parked) == 3, f"expected exactly 3 admitted under real concurrency, got {len(parked)}"
    assert len(denied) == 5
    assert await _pending_count() == 3, "the real pending_approval row count must match the configured limit exactly"


# --- per-session activity: below / at / over ------------------------------------

async def test_session_activity_below_limit_allowed(monkeypatch):
    monkeypatch.setattr(settings, "max_capability_requests_per_session", 5)
    _install_ok_servicenow(monkeypatch)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    result = await request_capability.fn("NotifyITHelpdesk", {"summary": "a"})
    assert result["status"] != "denied"


async def test_session_activity_at_and_over_limit_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "max_capability_requests_per_session", 2)
    _install_ok_servicenow(monkeypatch)
    _, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    first = await request_capability.fn("NotifyITHelpdesk", {"summary": "one"})
    second = await request_capability.fn("NotifyITHelpdesk", {"summary": "two"})
    assert first["status"] != "denied"
    assert second["status"] != "denied"

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        assert row.capability_request_count == 2

    before = metrics.admission_rejections_total.labels(gate="session_activity")._value.get()
    third = await request_capability.fn("NotifyITHelpdesk", {"summary": "three"})
    assert third["status"] == "denied"
    assert "capability request limit" in third["reason"]
    assert metrics.admission_rejections_total.labels(gate="session_activity")._value.get() == before + 1

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        assert row.capability_request_count == 2, "a refused request must not have incremented the durable counter"


async def test_session_activity_concurrent_race_cannot_bypass_limit(monkeypatch):
    """Real Postgres row lock: 6 concurrent calls from the SAME session
    against a limit of 2 must admit exactly 2, proven by the durable
    counter and the actual denial count, not by timing assumptions."""
    monkeypatch.setattr(settings, "max_capability_requests_per_session", 2)
    _install_ok_servicenow(monkeypatch)
    _, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    import asyncio

    async def attempt(i: int):
        return await request_capability.fn("NotifyITHelpdesk", {"summary": f"concurrent-{i}"})

    results = await asyncio.gather(*[attempt(i) for i in range(6)])
    admitted = [r for r in results if r["status"] != "denied"]
    denied = [r for r in results if r["status"] == "denied"]

    assert len(admitted) == 2, f"expected exactly 2 admitted under real concurrency, got {len(admitted)}"
    assert len(denied) == 4

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        assert row.capability_request_count == 2


async def test_session_activity_server_side_only(monkeypatch):
    """An agent-supplied argument cannot raise its own ceiling."""
    monkeypatch.setattr(settings, "max_capability_requests_per_session", 1)
    _install_ok_servicenow(monkeypatch)
    _, _, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    first = await request_capability.fn("NotifyITHelpdesk", {"summary": "one"})
    assert first["status"] != "denied"

    second = await request_capability.fn(
        "NotifyITHelpdesk",
        {"summary": "two", "_max_capability_requests_per_session": 999, "capability_request_count": -1},
    )
    assert second["status"] == "denied"
