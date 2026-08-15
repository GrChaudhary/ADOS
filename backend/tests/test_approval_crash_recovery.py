"""
P9 — the approval-path crash window, and its recovery.

THE FAILURE THIS CLOSES
------------------------
`approve_capability_request` used to hold one open transaction across the
ENTIRE decision, including the real external call: nothing durable was
written until the very end. An ADOS crash any time after the external system
had already acted, but before that final commit, rolled the whole decision
back to `pending_approval` — indistinguishable from a request that had never
been decided, and therefore approvable, and executable, a second time. See
docs/prime-agent-integration/18-production-readiness-review.md §9.

THE CRITICAL PROOF
---------------------
`test_a_crash_after_the_real_external_effect_but_before_commit_is_recovered_
without_a_duplicate` is the scenario the P9 instructions singled out by name:
a real external effect happens, ADOS "dies" before recording it, and recovery
proves the effect occurred exactly once — never a silent duplicate, and never
a false "nothing happened" either.

No external writes: ServiceNow is an `httpx.MockTransport` throughout.
"""

import asyncio
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.rbac import Role, User, create_access_token
from backend.app.routers.runtime_approvals import approve_capability_request
from contracts import PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub
from orchestrate.runtime.capability_execution import STATUS_EXECUTED, STATUS_EXECUTING, STATUS_OUTCOME_UNKNOWN
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown, reconcile_outcome_unknown
from orchestrate.runtime.prime import token_expiry

EXPENSIVE = {"summary": "Root cause: pool exhaustion", "_estimated_cost_usd": 300_000.0}


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


def _headers(role=Role.EXECUTIVE, limit=1_000_000.0, username="approver-1"):
    user = User(
        user_id=f"u-{username}", username=username, display_name=username,
        role=role, approval_limit_usd=limit,
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _user(username="approver-1") -> User:
    return User(
        user_id=f"u-{username}", username=username, display_name=username,
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0,
    )


class _FakeRequest:
    class app:
        class state:
            pass


async def _mission_and_session(capability="NotifyITHelpdesk"):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="approval crash recovery", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            # P10: matches the real creation path (every session has had a
            # token expiry since P6-D) — see
            # test_null_expiry_session_cannot_authorize_approval below for
            # the fixture that deliberately leaves this NULL.
            token_expires_at=token_expiry(1800.0),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


@pytest.fixture
def _as_runtime(monkeypatch):
    def present(token):
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )
    return present


def _install_servicenow(monkeypatch, handler):
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


async def _park(_as_runtime, token, capability="NotifyITHelpdesk", args=None) -> str:
    _as_runtime(token)
    parked = await request_capability.fn(capability, dict(args or EXPENSIVE))
    assert parked["status"] == "pending_approval", parked
    return parked["request_id"]


async def _row(request_id: str) -> CapabilityRequestRow:
    async with async_session_factory() as db:
        return await db.get(CapabilityRequestRow, uuid.UUID(request_id))


async def _approve(request_id: str, *, username="approver-1"):
    async with async_session_factory() as db:
        return await approve_capability_request(
            request_id, _FakeRequest(), current_user=_user(username), session=db,
        )


class _FakeServiceNow(ServiceNowConnector):
    """Stands in for reconciliation's real ServiceNow lookup — see
    test_capability_reconcile.py for the module-level unit tests of that
    mechanism; this file only needs it to complete the recovery scenario."""

    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    async def find_by_request_id(self, table, request_id):
        return self._answer


# --- the critical proof ---------------------------------------------------------

async def test_a_crash_after_the_real_external_effect_but_before_commit_is_recovered_without_a_duplicate(
    _as_runtime, monkeypatch,
):
    """external side effect succeeds -> ADOS dies before local commit ->
    restart/reconcile -> the external side effect occurred exactly once.

    The crash is injected by wrapping the REAL `_execute_capability` so the
    REAL (mocked-transport) external call still happens — a genuine ticket is
    created — and only THEN raises, before `approve_capability_request`'s
    phase 3 ever runs. That is exactly the window P8 found open: the real
    effect landed, and nothing durable recorded it.
    """
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, session_id, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    real_execute = mcp_gateway._execute_capability

    async def crash_after_success(*args, **kwargs):
        result = await real_execute(*args, **kwargs)  # the REAL external call happens
        raise asyncio.CancelledError("simulated ADOS crash: after external success, before commit")

    monkeypatch.setattr("backend.app.routers.runtime_approvals._execute_capability", crash_after_success)

    with pytest.raises(asyncio.CancelledError):
        await _approve(request_id)

    # The real effect happened exactly once.
    assert len(calls) == 1

    # And ADOS's own bookkeeping does NOT yet know it — durably `executing`,
    # not silently reset to `pending_approval` and not falsely `executed`.
    row = await _row(request_id)
    assert row.status == STATUS_EXECUTING
    assert row.decided_by == "user:approver-1", "who decided is preserved even though the outcome is not yet known"

    # Automatic re-execution is refused RIGHT NOW, before any reconciliation
    # — the row is `executing`, not `pending_approval`, so a retried approval
    # cannot reach `_execute_capability` a second time. This is what actually
    # prevents the duplicate; everything below only resolves the ambiguity.
    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409

    monkeypatch.undo()  # restore the real _execute_capability for recovery below

    # "Restart": the row is stuck `executing`. Recovery is two ordinary,
    # already-tested passes — nothing bespoke to this scenario.
    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)
    assert len(stalled) == 1
    row = await _row(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN

    # Still refused automatically, now as `outcome_unknown`.
    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409

    # Reconciliation: the real record IS there (the mocked POST really ran),
    # found by this row's own canonical request_id — never agent-authored text.
    fake_servicenow = _FakeServiceNow((True, [
        {"sys_id": "s1", "number": "INC1", "description": f"Capability request: {request_id}"},
    ]))
    resolved = await reconcile_outcome_unknown(async_session_factory, connector=fake_servicenow)
    assert len(resolved) == 1 and resolved[0].resolved

    row = await _row(request_id)
    assert row.status == STATUS_EXECUTED
    assert row.result["reconciled_match"]["number"] == "INC1"

    # And even now — resolved, terminal — a retry is refused. The external
    # effect that really happened, happened exactly once, proven by `calls`
    # never growing past 1 across this entire scenario.
    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409
    assert len(calls) == 1, "the external system was contacted more than once across the whole recovery"


async def test_a_crash_before_the_external_call_ever_starts_leaves_zero_side_effects(
    _as_runtime, monkeypatch,
):
    """The other half of the same window: nothing happened at all. Recovery
    must not invent a success — reconciliation finds nothing, and the row
    stays `outcome_unknown` rather than being guessed either way."""
    calls = _install_servicenow(
        monkeypatch, lambda r: httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})
    )
    _, _, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    async def crash_before_anything(*args, **kwargs):
        raise asyncio.CancelledError("simulated ADOS crash: before the external call ever started")

    monkeypatch.setattr("backend.app.routers.runtime_approvals._execute_capability", crash_before_anything)
    with pytest.raises(asyncio.CancelledError):
        await _approve(request_id)
    monkeypatch.undo()

    assert calls == [], "the external system must never have been contacted"
    row = await _row(request_id)
    assert row.status == STATUS_EXECUTING

    await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)
    fake_servicenow = _FakeServiceNow((True, []))  # a real, negative search result
    outcomes = await reconcile_outcome_unknown(async_session_factory, connector=fake_servicenow)

    assert outcomes[0].resolved is False
    row = await _row(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN, "absence of a match must not be guessed at as success OR silently retried"


# --- decided-again refusals, at every intermediate state ----------------------

async def test_an_executing_request_cannot_be_approved_again(_as_runtime, monkeypatch):
    """Not a crash — just a request genuinely still in flight (a slow real
    call) when a second approval attempt arrives."""
    _install_servicenow(monkeypatch, lambda r: httpx.Response(201, json={"result": {}}))
    _, _, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        row.status = STATUS_EXECUTING
        row.decided_by = "user:approver-1"
        await db.commit()

    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409


async def test_an_outcome_unknown_request_cannot_be_approved_again(_as_runtime, monkeypatch):
    _install_servicenow(monkeypatch, lambda r: httpx.Response(201, json={"result": {}}))
    _, _, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        row.status = STATUS_OUTCOME_UNKNOWN
        row.decided_by = "user:approver-1"
        await db.commit()

    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409


async def test_an_already_reconciled_executed_request_cannot_be_approved_again(_as_runtime, monkeypatch):
    """Simulates the state reconciliation itself leaves behind: `executed`,
    with no further work for an approver to do — decided_by preserved from
    the ORIGINAL approval, not the reconciliation pass."""
    _install_servicenow(monkeypatch, lambda r: httpx.Response(201, json={"result": {}}))
    _, _, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        row.status = STATUS_EXECUTED
        row.decided_by = "user:approver-1"
        row.result = {"reconciled": True, "reconciled_match": {"number": "INC1"}}
        await db.commit()

    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409


# --- P10: a NULL token expiry is not proof of a live session --------------


async def test_a_null_expiry_session_cannot_authorize_approval(_as_runtime, monkeypatch):
    """Re-derivation during P10 found real, non-terminal `runtime_sessions`
    rows in the dev database with `token_expires_at IS NULL` — every
    session the real creation path writes has set this unconditionally
    since P6-D, so NULL means this row did not come from a currently-live
    mission, regardless of what `state` says. Two of those rows had a
    `pending_approval` request still sitting genuinely approvable through
    this exact endpoint. This is the regression test for the fix, not a
    reconciliation change — the session row itself (state, token_expires_at)
    is untouched; only approval's own liveness check was tightened.

    The `pending_approval` row is constructed directly here, not via
    `_park`/`request_capability` — P12 closed the same NULL-expiry gap one
    layer upstream, in `_resolve_session` itself (mcp_gateway.py), so a
    session shaped like this can no longer park a request through the real
    path at all (see the companion test below). This test is now
    specifically the defense-in-depth case P10's own dev-database finding
    actually was: a `pending_approval` row that already exists — however it
    got there, e.g. residue from before either guard existed — must still
    be refused by the approval endpoint's own independent check, not rely
    on the newer, earlier guard as the only line of defense."""
    _install_servicenow(monkeypatch, lambda r: httpx.Response(201, json={"result": {}}))
    async with async_session_factory() as db:
        mission = MissionRow(
            title="p10 null-expiry fossil", objective="o", domain="it",
            allowed_capabilities=["NotifyITHelpdesk"], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            # Deliberately NOT set — this is the exact fossil shape.
        )
        db.add(sess)
        await db.flush()
        row = CapabilityRequestRow(
            session_id=sess.session_id, mission_id=mission.mission_id,
            capability="NotifyITHelpdesk", arguments=dict(EXPENSIVE),
            status="pending_approval", policy_tier=int(PolicyTier.EXECUTIVE_APPROVAL),
        )
        db.add(row)
        await db.commit()
        request_id = str(row.request_id)

    with pytest.raises(HTTPException) as exc:
        await _approve(request_id)
    assert exc.value.status_code == 409
    assert "token expiry" in exc.value.detail

    # Reject must still work -- it is always safe (no side effect), and an
    # operator needs some way to close a stale request tied to a fossil
    # session without being blocked by the very check this test exists for.
    from backend.app.routers.runtime_approvals import reject_capability_request

    async with async_session_factory() as db:
        result = await reject_capability_request(
            request_id, _FakeRequest(), current_user=_user(), session=db, body={"reason": "cleanup"},
        )
    assert result["status"] == "denied"


async def test_a_null_expiry_session_cannot_call_request_capability(_as_runtime):
    """P12 — the gap the above test used to exercise upstream: `_resolve_
    session` (mcp_gateway.py), shared by every MCP tool including
    `request_capability`, now refuses a NULL-expiry session outright, the
    same proof-not-guess reasoning P10 gave the approval endpoint, extended
    to cover the autonomous auto-execute path too (which needs no human at
    all — the more serious half of the gap)."""
    async with async_session_factory() as db:
        mission = MissionRow(
            title="p12 null-expiry fossil — capability path", objective="o", domain="it",
            allowed_capabilities=["NotifyITHelpdesk"], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            # Deliberately NOT set — this is the exact fossil shape.
        )
        db.add(sess)
        await db.commit()

    _as_runtime(token)
    answer = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert answer["status"] == "denied"
    assert "expiry" in answer["reason"]

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text("SELECT count(*) FROM capability_requests WHERE mission_id = :m"),
                {"m": str(mission.mission_id)},
            )
        ).scalar_one()
    assert rows == 0, "a denied-at-_resolve_session call must never reach a connector or write a request row"


# --- an ordinary (non-crash) failure ends up unambiguously failed, not unknown -

async def test_an_ordinary_connector_failure_is_failed_not_outcome_unknown(_as_runtime, monkeypatch):
    """A 4xx ServiceNow actually answered with is a real, definite failure —
    conflating it with `outcome_unknown` would make every ordinary rejected
    request needlessly require manual reconciliation."""
    _install_servicenow(monkeypatch, lambda r: httpx.Response(400, text="Bad Request"))
    _, _, token = await _mission_and_session()
    request_id = await _park(_as_runtime, token)

    result = await _approve(request_id)

    assert result["status"] == "failed"
    row = await _row(request_id)
    assert row.status == "failed"
