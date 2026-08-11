"""
P9 — the durable execution state machine and canonical idempotency key.

WHAT WAS MISSING
------------------
`request_capability`'s autonomous path went straight from `pending_approval`
to a terminal status with nothing durable recorded until AFTER the real
external call returned — so an ADOS crash mid-call left the row exactly where
it started, indistinguishable from a request that had simply never been
picked up. Separately, the old `idempotency_key` was caller-supplied and
optional; nothing reachable from a real mission ever set one (P8's finding).
See docs/prime-agent-integration/18-production-readiness-review.md §9 and
orchestrate/runtime/capability_execution.py.

WHAT THESE TESTS PIN
----------------------
* a successful autonomous call passes through `executing` on its way to
  `executed` — durably, not just in memory
* a connector reporting `CallStatus.UNKNOWN` (ServiceNow: a transport error
  that may have already reached the server) resolves the row to
  `outcome_unknown`, never `failed` and never `executed`
* two calls with identical capability+arguments in the same session are
  recognised as the same request WITHOUT either caller supplying anything —
  the second is a replay, the connector is invoked exactly once
* two calls with different arguments are NOT conflated
* a genuine concurrency race for the same canonical key is resolved by the
  database's own unique index, not by a hope that nobody collides
* the canonical key is computed from session+capability+real arguments only —
  governance hints (`_confidence`, `_estimated_cost_usd`) do not change it

No external writes: ServiceNow is an `httpx.MockTransport` throughout.
"""

import asyncio
import json
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub
from orchestrate.runtime.capability_execution import (
    STATUS_EXECUTED,
    STATUS_EXECUTING,
    STATUS_OUTCOME_UNKNOWN,
    canonical_idempotency_key,
)


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "not-a-real-password")


@pytest.fixture
def _as_runtime(monkeypatch):
    def present(token):
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )
    return present


async def _session(capability="NotifyITHelpdesk"):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="state", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


def _install_servicenow(monkeypatch, handler):
    """Wires a MockTransport ServiceNow connector into the real hub, exactly
    as the existing approval/grant regression suites do."""
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content or b"{}"))
        return handler(request)

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(wrapped))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)
    return calls


async def _row(request_id: str) -> CapabilityRequestRow:
    async with async_session_factory() as db:
        return await db.get(CapabilityRequestRow, uuid.UUID(request_id))


# --- executing is a real, durable checkpoint ----------------------------------

async def test_a_successful_autonomous_call_ends_at_executed(_as_runtime, monkeypatch):
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _session()
    _as_runtime(token)

    done = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert done["status"] == "executed"
    assert len(calls) == 1

    row = await _row(done["request_id"])
    assert row.status == STATUS_EXECUTED
    assert row.result["outcome_status"] == STATUS_EXECUTED


async def test_a_crash_between_marking_executing_and_the_connector_call_leaves_it_durably_executing(
    _as_runtime, monkeypatch,
):
    """Simulates the process dying in exactly the P8 window: the phase-1
    commit (durably `executing`) has happened; the external call never runs
    at all.

    Raises `asyncio.CancelledError` rather than an ordinary `Exception`,
    deliberately: `request_capability`'s own `except Exception` around the
    call to `_execute_capability` is a real, pre-existing guard (it converts
    an unexpected exception into a FAILED-shaped result rather than leaving
    the row stranded) and would otherwise catch a simulated crash here too,
    proving nothing. A real process death is not a Python exception any
    handler gets a chance to run for — `CancelledError` is a `BaseException`,
    not an `Exception`, so it is the one thing this test can raise that
    genuinely escapes that guard the same way a killed process would.
    """
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )

    async def _crash(*args, **kwargs):
        raise asyncio.CancelledError("simulated ADOS crash (P9 controlled test)")

    _, _, token = await _session()
    _as_runtime(token)

    monkeypatch.setattr(mcp_gateway, "_execute_capability", _crash)
    with pytest.raises(asyncio.CancelledError):
        await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})

    assert calls == [], "the external system must never have been contacted"

    async with async_session_factory() as db:
        rows = (await db.execute(select(CapabilityRequestRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == STATUS_EXECUTING, (
        "a process death between the durable checkpoint and the external call "
        "must leave the row exactly there — not silently reset to pending_approval"
    )


async def test_a_connector_reporting_unknown_resolves_to_outcome_unknown_not_failed(
    _as_runtime, monkeypatch,
):
    """The connector-level half of P9: a transport error that may have
    already reached ServiceNow must never be indistinguishable from an
    ordinary, safely-retryable failure."""
    def _timeout(request: httpx.Request):
        raise httpx.ReadTimeout("simulated: request may have reached the server", request=request)

    calls = _install_servicenow(monkeypatch, _timeout)
    _, _, token = await _session()
    _as_runtime(token)

    done = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert done["status"] == "outcome_unknown"

    row = await _row(done["request_id"])
    assert row.status == STATUS_OUTCOME_UNKNOWN
    assert row.status != "failed", "an ambiguous outcome must never be recorded as a safe-to-retry failure"


async def test_a_retry_against_an_outcome_unknown_request_replays_it_instead_of_executing_again(
    _as_runtime, monkeypatch,
):
    """The agent's own retry (same capability, same arguments) after seeing
    `outcome_unknown` must be intercepted by the same idempotency lookup
    every other replay goes through — never re-reach the connector."""
    def _timeout(request: httpx.Request):
        raise httpx.ReadTimeout("simulated: ambiguous", request=request)

    calls = _install_servicenow(monkeypatch, _timeout)
    _, _, token = await _session()
    _as_runtime(token)

    first = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert first["status"] == "outcome_unknown"

    second = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})

    assert second["status"] == "outcome_unknown"
    assert second.get("replayed") is True
    assert second["request_id"] == first["request_id"]
    assert len(calls) == 1, "a retry against an unresolved ambiguous request must never re-contact the external system"


async def test_a_connector_that_never_reached_the_server_is_a_real_failure(
    _as_runtime, monkeypatch,
):
    """The other half of the same distinction: a connection that never left
    this process IS safely FAILED — retrying costs nothing new."""
    def _refused(request: httpx.Request):
        raise httpx.ConnectError("simulated: connection refused", request=request)

    _install_servicenow(monkeypatch, _refused)
    _, _, token = await _session()
    _as_runtime(token)

    done = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert done["status"] == "failed"


# --- idempotency is automatic, canonical, and unforgeable ---------------------

async def test_a_repeated_identical_call_replays_instead_of_executing_twice(_as_runtime, monkeypatch):
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _session()
    _as_runtime(token)

    first = await request_capability.fn("NotifyITHelpdesk", {"summary": "identical message"})
    second = await request_capability.fn("NotifyITHelpdesk", {"summary": "identical message"})

    assert len(calls) == 1, "the second, identical call must not have reached the external system"
    assert second["request_id"] == first["request_id"]
    assert second.get("replayed") is True
    assert second["status"] == first["status"] == "executed"


async def test_different_arguments_are_never_conflated(_as_runtime, monkeypatch):
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _session()
    _as_runtime(token)

    first = await request_capability.fn("NotifyITHelpdesk", {"summary": "message A"})
    second = await request_capability.fn("NotifyITHelpdesk", {"summary": "message B"})

    assert len(calls) == 2
    assert first["request_id"] != second["request_id"]


async def test_governance_hints_do_not_change_the_canonical_key(_as_runtime, monkeypatch):
    """`_confidence`/`_estimated_cost_usd` steer the tier decision, not the
    identity of the real action — two calls that agree on everything else
    must dedupe even if they disagree about their own claimed cost."""
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _session()
    _as_runtime(token)

    first = await request_capability.fn(
        "NotifyITHelpdesk", {"summary": "same", "_estimated_cost_usd": 0.0}
    )
    second = await request_capability.fn(
        "NotifyITHelpdesk", {"summary": "same", "_estimated_cost_usd": 999.0}
    )

    assert len(calls) == 1
    assert second["request_id"] == first["request_id"]


async def test_two_genuinely_concurrent_identical_calls_execute_exactly_once(_as_runtime, monkeypatch):
    """Not the sequential replay above — two callers racing for the SAME
    canonical key with no prior row to find yet. The database's own unique
    index (alembic revision d1e2f3a4b5c6) is the backstop; without it this
    is a classic TOCTOU and both could win."""
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _session()
    _as_runtime(token)

    results = await asyncio.gather(
        request_capability.fn("NotifyITHelpdesk", {"summary": "race"}),
        request_capability.fn("NotifyITHelpdesk", {"summary": "race"}),
    )

    assert len(calls) == 1, f"the external system was contacted {len(calls)} times for one logical request"
    request_ids = {r["request_id"] for r in results}
    assert len(request_ids) == 1, "both callers must resolve to the SAME row"

    async with async_session_factory() as db:
        rows = (
            await db.execute(select(CapabilityRequestRow).where(CapabilityRequestRow.capability == "NotifyITHelpdesk"))
        ).scalars().all()
    assert len(rows) == 1, f"a race created {len(rows)} rows for one canonical request"


# --- the key itself -------------------------------------------------------------

def test_canonical_key_is_deterministic():
    a = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x"})
    b = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x"})
    assert a == b


def test_canonical_key_differs_by_session():
    a = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x"})
    b = canonical_idempotency_key("sess-2", "NotifyITHelpdesk", {"summary": "x"})
    assert a != b


def test_canonical_key_differs_by_capability():
    a = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x"})
    b = canonical_idempotency_key("sess-1", "CreateChangeRequest", {"summary": "x"})
    assert a != b


def test_canonical_key_ignores_underscore_prefixed_governance_hints():
    a = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x", "_confidence": 0.5})
    b = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x", "_confidence": 0.99})
    assert a == b


def test_canonical_key_is_order_independent_over_argument_keys():
    a = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"summary": "x", "urgency": "low"})
    b = canonical_idempotency_key("sess-1", "NotifyITHelpdesk", {"urgency": "low", "summary": "x"})
    assert a == b
