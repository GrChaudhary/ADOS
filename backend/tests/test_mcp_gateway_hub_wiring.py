"""
P13 — `backend/app/mcp_gateway.py::_execute_capability` now uses the real
app's properly-configured `app.state.integration_hub` (via the module-level
`_active_hub`, set for the lifetime of a real lifespan run) instead of
calling `default_hub()` fresh on every single call.

THE BUG THIS CLOSES, PROVEN HERE
-----------------------------------
`default_hub()` with no arguments constructs a BRAND NEW `IntegrationHub` —
and therefore a brand new `AdmissionControl` with `session_factory=None`
and a zeroed local counter — every time `_execute_capability` ran. Every
in-mission Prime Agent capability call (the runtime calling back into ADOS
for `FetchIncidentEvidence`/`NotifyITHelpdesk`/etc.) went through exactly
this path, meaning admission control's `capability_concurrency` ceiling
never actually bounded any of that traffic, in ANY deployment — a genuine,
pre-existing correctness gap, not something P13 introduced. Fixed
additively: outside a real app lifespan (every other test file's own
`default_hub()`/bare-`IntegrationHub()` construction, unchanged), nothing
here changes at all.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.main import app
from backend.app.mcp_gateway import hash_token, request_capability
from contracts import CallStatus, Capability, CapabilityResponse
from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from integrations.connectors.base import Connector
from orchestrate.runtime.prime import token_expiry


@pytest.fixture(autouse=True)
async def _clean():
    # app.state.integration_hub is wired with the real, Postgres-backed
    # global admission layer (session_factory=async_session_factory) --
    # unlike every other test file's bare-constructed AdmissionControl,
    # a leftover lease row here would contaminate this file's own
    # deliberately-tiny limit=1 test. See db/models/admission_lease.py.
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE admission_leases CASCADE"))
        await db.commit()
    yield


class _HoldableSpy(Connector):
    def __init__(self, capability: Capability, hold: asyncio.Event):
        self.name = "p13-spy-connector"
        self.capabilities = {capability}
        self._hold = hold
        self.execute_calls = 0

    async def execute(self, call) -> CapabilityResponse:
        self.execute_calls += 1
        await self._hold.wait()
        return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)


async def _session(capability: str):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="p13 hub wiring test", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        db.add(RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            token_expires_at=token_expiry(1800.0),
        ))
        await db.commit()
        return token


def test_active_hub_is_the_real_apps_integration_hub_during_a_lifespan(client):
    """The identity check: the same object app.state.integration_hub
    points at is what _execute_capability will use -- not a coincidence,
    not a lookalike, the literal same instance."""
    assert mcp_gateway._active_hub is not None
    assert mcp_gateway._active_hub is app.state.integration_hub


def test_active_hub_is_none_outside_a_lifespan():
    """Every test file that constructs its own bare hub, or calls
    request_capability.fn without a real TestClient lifespan running,
    must keep getting default_hub()'s prior behavior unchanged."""
    assert mcp_gateway._active_hub is None


async def test_concurrent_in_mission_capability_calls_are_now_actually_bounded(client, monkeypatch):
    """The functional proof: two concurrent request_capability.fn() calls,
    through a REAL TestClient(app) lifespan, against a deliberately tiny
    capability_concurrency limit set on the REAL app.state.integration_hub.
    Before P13, each call constructed its own fresh AdmissionControl and
    both would have been silently admitted regardless of the limit."""
    hub = app.state.integration_hub
    original_limit = hub.admission_control._max_capability
    hub.admission_control._max_capability = 1
    hold = asyncio.Event()
    spy = _HoldableSpy(Capability.NOTIFY_IT_HELPDESK, hold)
    monkeypatch.setattr(hub.registry, "connectors_for", lambda cap: [spy])

    try:
        token = await _session("NotifyITHelpdesk")

        async def _call(arg_marker: str):
            monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})
            return await request_capability.fn("NotifyITHelpdesk", {"summary": arg_marker})

        t1 = asyncio.create_task(_call("first"))
        for _ in range(200):  # poll until the first call reaches connector.execute() and blocks on `hold`
            if spy.execute_calls >= 1:
                break
            if t1.done():
                raise AssertionError(f"first call finished early, before reaching the connector: {t1.result()}")
            await asyncio.sleep(0.01)
        assert spy.execute_calls == 1

        second = await _call("second")
        assert second["status"] == "failed", (
            f"expected the second concurrent call to be refused by admission control, got {second}"
        )
        assert "admission control" in (second["result"].get("error") or "")
        assert spy.execute_calls == 1, "the refused second call must never have reached the connector"

        hold.set()
        first = await t1
        assert first["status"] == "executed"
    finally:
        hub.admission_control._max_capability = original_limit
