"""
P15 — regression coverage for two real races this phase's concurrency audit
found and fixed, neither previously tested:

1. `mcp_gateway.py`'s AUTONOMOUS-tier completion write used to unconditionally
   overwrite `capability_requests.status`/`result` with whatever
   `_execute_capability` returned, with no check that the row had already
   been independently resolved while that call was still genuinely in
   flight (no lock is held across it, by design — see P9). The periodic
   reconciliation pass (`orchestrate/runtime/capability_reconcile.py::
   mark_stalled_executions_unknown`) can mark a row `outcome_unknown` while
   the ADOS process that owns it is still alive and working, not crashed —
   any call slower than the stall bound is enough. `runtime_approvals.py`'s
   approve path already guarded against exactly this (its own Phase 3
   comment); the autonomous path did not, until this phase found the
   asymmetry.

2. `IntegrationHub.invoke()`'s admission-control block used to leak the
   local, in-process capability slot forever (nothing else ever resets
   `AdmissionControl._current_capability`) if the global Postgres acquire —
   or any one of the global release calls in `finally` — raised. Not an
   authorization bypass (a leak only ever makes the gate MORE restrictive),
   but a real, reproducible availability defect: a transient database
   outage during admission control would permanently shrink this process's
   effective concurrency ceiling. See integrations/hub.py's own comment at
   the fix site.

Both fixes are covered here; see scripts/p15_multiprocess_concurrency_proof.py
for the same two races reproduced across real, separate OS processes.
"""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from contracts import CallStatus, Capability, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from db.engine import async_session_factory
from db.models.admission_lease import AdmissionLeaseRow
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.admission_control import AdmissionControl
from integrations.connectors.base import Connector
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import IntegrationHub, default_hub
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown
from orchestrate.runtime.capability_execution import STATUS_EXECUTING, STATUS_OUTCOME_UNKNOWN
from orchestrate.runtime.prime import token_expiry


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests, admission_leases CASCADE"))
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
        monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})
    return present


async def _session(capability="NotifyITHelpdesk"):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="race", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
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


async def _row(request_id) -> CapabilityRequestRow:
    async with async_session_factory() as db:
        return await db.get(CapabilityRequestRow, uuid.UUID(str(request_id)))


# --- Finding #1: late autonomous completion vs. reconciliation ---------------


async def test_late_autonomous_completion_does_not_overwrite_a_row_reconciliation_already_resolved(
    _as_runtime, monkeypatch,
):
    gate = asyncio.Event()

    async def _slow_execute_capability(capability, arguments, *, mission_id, tier, request_id):
        await gate.wait()
        return {"outcome_status": "executed", "capability": capability, "outcome": {"status": "succeeded"}}

    monkeypatch.setattr(mcp_gateway, "_execute_capability", _slow_execute_capability)

    _, _, token = await _session()
    _as_runtime(token)

    task = asyncio.create_task(request_capability.fn("NotifyITHelpdesk", {"summary": "slow"}))

    request_id = None
    for _ in range(500):
        async with async_session_factory() as db:
            rows = (await db.execute(select(CapabilityRequestRow))).scalars().all()
        if rows and rows[0].status == STATUS_EXECUTING:
            request_id = rows[0].request_id
            break
        await asyncio.sleep(0.01)
    assert request_id is not None, "row never reached the durable executing checkpoint"

    # Reconciliation runs while the connector call above is still blocked on
    # `gate` -- the row is genuinely, currently in flight, not abandoned by a
    # dead process. stall_seconds=0 is the test's way of forcing "this has
    # been executing long enough" without a real sleep.
    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)
    assert any(s.request_id == request_id for s in stalled)

    row = await _row(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN
    reconciled_reason = row.reason
    assert reconciled_reason and "outcome unknown" in reconciled_reason

    # Now let the "still in flight" call finally complete successfully.
    gate.set()
    result = await task

    # The late completion must report, and leave durable, reconciliation's
    # own decision -- not silently reverse it back to "executed".
    assert result["status"] == "outcome_unknown"
    row = await _row(request_id)
    assert row.status == STATUS_OUTCOME_UNKNOWN
    assert row.reason == reconciled_reason, "the row's reconciled reason must survive the late completion untouched"
    assert row.decided_by != "policy:autonomous", "the late completion must not claim to have decided this row"


async def test_ordinary_autonomous_completion_with_no_race_is_unaffected(_as_runtime, monkeypatch):
    """Regression guard: the new check must not change behavior for the
    overwhelming common case where nothing else touches the row."""
    calls = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC1"}})

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(_handler))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    _, _, token = await _session()
    _as_runtime(token)

    done = await request_capability.fn("NotifyITHelpdesk", {"summary": "ordinary"})
    assert done["status"] == "executed"
    assert len(calls) == 1

    row = await _row(done["request_id"])
    assert row.status == "executed"
    assert row.decided_by == "policy:autonomous"


# --- Finding #2: admission-control local-slot leak on a DB failure -----------


class _SpyConnector(Connector):
    """Minimal connector: proves the local capability slot is available
    again for a SECOND call after the first call's global acquire raised —
    the leak this fix closes would make the second call's local acquire
    fail even though only one call is nominally "in flight" (the first one
    already returned, having failed fast)."""

    def __init__(self, capability: Capability):
        self.name = "spy-connector"
        self.capabilities = {capability}

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)


def _call() -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR, input={}, requested_by="test:completion-race",
        incident_id=str(uuid.uuid4()), governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def test_a_failing_global_acquire_does_not_leak_the_local_capability_slot(monkeypatch):
    """Simulates a transient database outage exactly at the global-acquire
    step. Before the P15 fix, this exception propagated out of invoke()
    with the local slot (max=1 here) never released -- every subsequent
    call would then be wrongly refused by the LOCAL gate forever, even
    though nothing is actually in flight."""
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1, session_factory=async_session_factory)

    async def _raise(*args, **kwargs):
        raise ConnectionRefusedError("simulated: database unreachable")

    monkeypatch.setattr(ac, "try_acquire_capability_slot_global", _raise)

    hub = IntegrationHub(admission_control=ac)
    hub.registry.register(_SpyConnector(Capability.NOTIFY_OPERATOR))

    first = await hub.invoke(_call())
    assert first.status.value == "failed"
    assert "admission control" in (first.error or "")
    assert ac.current_capability_executions == 0, "the local slot must be released even though the global acquire raised"

    # Restore normal (non-raising) global acquire behavior and prove a
    # second call is admitted -- it would wrongly be refused by the LOCAL
    # gate (max=1) if the first call's slot had leaked.
    monkeypatch.undo()
    second = await hub.invoke(_call())
    assert second.status.value == "succeeded"


async def test_a_failing_global_release_does_not_prevent_the_local_capability_release(monkeypatch):
    """Same failure mode, at release time instead of acquire time: a real
    DB error deleting the global lease row must not skip the local
    release that comes after it in `finally`.

    The global lease row itself IS left behind when its own DELETE
    genuinely fails -- nothing can un-leak a row a failed DELETE didn't
    delete, and that row's cleanup is exactly what the periodic
    admission_lease_reclaim.py sweep exists for (simulated below by
    deleting it directly, standing in for that sweep's next tick). What
    this fix actually guarantees, and what this test proves, is narrower
    and unconditional: the LOCAL, in-process slot -- the one nothing else
    ever resets -- is released regardless of whether the global release
    succeeded."""
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1, session_factory=async_session_factory)

    async def _raise(*args, **kwargs):
        raise ConnectionRefusedError("simulated: database unreachable during release")

    monkeypatch.setattr(ac, "release_capability_slot_global", _raise)

    hub = IntegrationHub(admission_control=ac)
    hub.registry.register(_SpyConnector(Capability.NOTIFY_OPERATOR))

    first = await hub.invoke(_call())
    assert first.status.value == "succeeded"
    assert ac.current_capability_executions == 0, "the local slot must still be released even though the global release raised"

    # The global lease genuinely leaked (its DELETE really did fail) -- a
    # second call is correctly refused by the GLOBAL check specifically,
    # not the local one. Fail-safe (less concurrency than configured),
    # never fail-open.
    monkeypatch.undo()
    second = await hub.invoke(_call())
    assert second.status.value == "failed"
    assert "admission control" in (second.error or "")

    async with async_session_factory() as db:
        leaked = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(leaked) == 1, "the one genuinely-failed-to-delete lease row, not zero and not more"

    # Standing in for admission_lease_reclaim.py's next periodic tick.
    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM admission_leases"))
        await db.commit()
    third = await hub.invoke(_call())
    assert third.status.value == "succeeded", "once the leaked lease is reclaimed, capacity is available again"
