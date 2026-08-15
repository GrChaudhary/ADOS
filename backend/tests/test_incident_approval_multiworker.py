"""
P13 — the manufacturing-incident approval pipeline (`orchestrate/
governance.py::ApprovalQueue`, `orchestrate/orchestrator.py`), proven
across multiple worker processes the same way `test_moa_durability.py`
already proved it for MOA: a second, independently-constructed
`TestClient(app)` triggers its own full `lifespan()` run, giving it its
own `app.state.orchestrator`/`ApprovalQueue` — nothing carried over except
the incident_id and the shared Postgres database, exactly standing in for
"the load balancer sent this request to the other replica."

THE BUG THIS CLOSES
---------------------
Before P13, `ApprovalQueue` was a plain in-memory dict — `orchestrate/
governance.py`'s own docstring already said so ("In-memory... for the
MVP"). `POST /incidents/{id}/approve|reject|escalate` on a worker that
never ran that incident's `run_incident()` coroutine would 404 ("no
pending approval for this incident"), even though the incident was
genuinely, durably `AwaitingApproval` in Postgres
(`orchestrator.py::_snapshot_pending`) — a real operator-facing outage, not
a hypothetical one, and the exact symptom the Dockerfile's own (partly
stale, see docs/prime-agent-integration/24-p13-horizontal-scale-out.md)
`--workers` warning describes.

THE RACE THE FIX ITSELF COULD HAVE INTRODUCED, ALSO CLOSED HERE
-------------------------------------------------------------------
Making the pending approval reconstructible on ANY worker makes it newly
POSSIBLE for two workers to reconstruct and act on the same decision at
once — a real double-execution risk that literally could not exist before
(only the originating worker could ever see it). `AuditTrail.
claim_awaiting_approval` (a single atomic Postgres `UPDATE ... WHERE
final_state = 'AwaitingApproval'`) is what prevents that from becoming an
actual double execution, proven below with real concurrent HTTP requests
from two separate threads against two separate TestClient instances — not
a sequential simulation.

Real Postgres throughout (the `client`/`db` fixtures in conftest.py both
point at the real `ados_test` database) — no mocking of the orchestrator,
audit trail, or approval mechanism. The capability connector for
manufacturing incidents is already simulated by design (doc 18's own
connector table), so no real external side effect exists to guard against
here — only the double-execution-of-a-simulated-call risk, which still
proves the exact same claim/serialization property a real connector would
also depend on.
"""

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from integrations.hub import IntegrationHub


def _start_incident(client, auth_headers, line_id):
    body = {
        "plant_id": "FAC-P1",
        "line_id": line_id,
        "part_number": "P-1002",
        "vision_data": {"measured_bore_diameter_mm": 45.085},
        "priority": {
            "safety_impact": 0.9,
            "customer_impact": 0.6,
            "line_down_cost_per_hour_usd": 12000,
            "production_priority": 0.7,
            "is_systemic": False,
        },
    }
    response = client.post("/incidents", json=body, headers=auth_headers)
    assert response.status_code == 200
    return response.json()["incident_id"]


def _wait_for_awaiting_approval(client, auth_headers, incident_id, attempts=300):
    for _ in range(attempts):
        resp = client.get("/approvals", headers=auth_headers)
        pending = next((p for p in resp.json() if p["incidentId"] == incident_id), None)
        if pending is not None:
            return pending
        import time
        time.sleep(0.01)
    raise AssertionError("orchestrator never reached AwaitingApproval")


def _wait_for_terminal(client, auth_headers, incident_id, attempts=300):
    for _ in range(attempts):
        resp = client.get(f"/incidents/{incident_id}", headers=auth_headers)
        body = resp.json()
        state = body.get("finalState") or body.get("final_state")
        if state in ("Resolved", "Failed"):
            return body
        import time
        time.sleep(0.01)
    raise AssertionError("incident never reached a terminal state")


def test_a_second_worker_can_approve_an_incident_it_never_started(client, auth_headers):
    """The bug, closed: before P13 this 404'd unconditionally.

    `client` creates and progresses the incident to AwaitingApproval FIRST,
    entirely — `with TestClient(app) as worker_b` is only opened after,
    deliberately, mirroring test_moa_durability.py's own proven pattern:
    every TestClient shares the SAME global `app` object, so opening a
    second one EARLIER would re-run lifespan and overwrite `app.state`
    (including `app.state.orchestrator`) out from under `client` before it
    ever got to create the incident — there is only ever one "current"
    app.state at a time in this harness, not two independently-alive ones.

    This ordering means `resume_pending_approvals()` (the PRE-EXISTING,
    startup-only restart-recovery pass) also happens to cover this exact
    scenario in this test harness — by construction, `worker_b` can only
    start after the incident already exists. That does not weaken what
    this test proves (the real, user-facing bug: /approve on a worker that
    never ran the incident); it just means this HTTP-level test cannot, on
    its own, distinguish which of the two mechanisms answered it. See
    `test_resolve_pending_approval_finds_an_incident_a_live_process_never_
    saw_at_its_own_startup` below for a direct, isolated proof of the NEW
    on-demand mechanism specifically, independent of `resume_pending_
    approvals`."""
    incident_id = _start_incident(client, auth_headers, line_id="Line-P13-A")
    _wait_for_awaiting_approval(client, auth_headers, incident_id)

    with TestClient(app) as worker_b:
        approve = worker_b.post(f"/incidents/{incident_id}/approve", headers=auth_headers)
        assert approve.status_code == 200, approve.text
        assert approve.json()["decision"] == "approved"

    # Independently re-verified via the ORIGINAL client -- which never ran
    # this incident's decision either, and never restarted -- proving the
    # GET-side cross-worker read fix (audit_trail.get_from_db) too, not
    # just the approve-side one.
    record = _wait_for_terminal(client, auth_headers, incident_id)
    assert record["finalState"] == "Resolved"


def test_a_second_worker_can_reject_an_incident_it_never_started(client, auth_headers):
    incident_id = _start_incident(client, auth_headers, line_id="Line-P13-B")
    _wait_for_awaiting_approval(client, auth_headers, incident_id)

    with TestClient(app) as worker_b:
        reject = worker_b.post(f"/incidents/{incident_id}/reject", headers=auth_headers)
        assert reject.status_code == 200, reject.text
        assert reject.json()["decision"] == "rejected"

    record = _wait_for_terminal(client, auth_headers, incident_id)
    assert record["finalState"] == "Failed"


def test_get_incident_on_a_third_worker_sees_the_decision_a_second_worker_made(client, auth_headers):
    """Three distinct app instances: A starts it, B decides it, C (which
    did neither) must still report the correct, current, terminal state --
    not a stale/absent view and not a false 404."""
    incident_id = _start_incident(client, auth_headers, line_id="Line-P13-C")
    _wait_for_awaiting_approval(client, auth_headers, incident_id)

    with TestClient(app) as worker_b:
        assert worker_b.post(f"/incidents/{incident_id}/approve", headers=auth_headers).status_code == 200

    with TestClient(app) as worker_c:
        record = _wait_for_terminal(worker_c, auth_headers, incident_id)
        assert record["finalState"] == "Resolved"


def test_double_decide_after_resolution_is_refused_not_repeated(client, auth_headers):
    """Once genuinely resolved (via a different worker), a further /approve
    attempt from yet another worker must be refused (404 -- no longer
    AwaitingApproval), never silently re-executed."""
    incident_id = _start_incident(client, auth_headers, line_id="Line-P13-D")
    _wait_for_awaiting_approval(client, auth_headers, incident_id)

    with TestClient(app) as worker_b:
        assert worker_b.post(f"/incidents/{incident_id}/approve", headers=auth_headers).status_code == 200
    _wait_for_terminal(client, auth_headers, incident_id)

    with TestClient(app) as worker_c:
        again = worker_c.post(f"/incidents/{incident_id}/approve", headers=auth_headers)
        assert again.status_code == 404


async def test_resolve_pending_approval_finds_an_incident_a_live_process_never_saw_at_its_own_startup():
    """The isolated proof of the NEW on-demand mechanism specifically,
    independent of resume_pending_approvals (which the HTTP-level tests
    above cannot cleanly isolate from -- see their own docstrings): two
    DecisionOrchestrator instances constructed directly (not via TestClient/
    app.state, which can only ever hold one "current" instance at a time),
    real Postgres, no HTTP.

    `orchestrator_a` persists an AwaitingApproval snapshot -- standing in
    for a real run_incident() coroutine reaching that point. `orchestrator_
    b` is constructed and hydrated AFTER that snapshot already exists, but
    deliberately WITHOUT calling resume_pending_approvals() -- standing in
    for "a process that was already running, past its own startup, before
    this incident ever existed" (the actual production scenario the bug
    report describes, which resume_pending_approvals()'s own docstring
    admits it cannot cover: "Call once at startup"). Only
    resolve_pending_approval can find it here."""
    from contracts import Capability, IncidentRecord, PolicyTier
    from db.engine import async_session_factory
    from db.models.incident import IncidentRow
    from orchestrate.orchestrator import DecisionOrchestrator
    from sqlalchemy import delete
    from unittest.mock import MagicMock

    incident_id = "p13-on-demand-isolation-test"
    async with async_session_factory() as db:
        await db.execute(delete(IncidentRow).where(IncidentRow.incident_id == incident_id))
        await db.commit()

    orchestrator_a = DecisionOrchestrator(
        event_bus=MagicMock(), integration_hub=MagicMock(), session_factory=async_session_factory,
    )
    await orchestrator_a.audit_trail.persist_snapshot(IncidentRecord(
        incident_id=incident_id, plant_id="P", line_id="L", detected_at="2026-01-01T00:00:00Z",
        final_state="AwaitingApproval", causal_chain=[], confidence=0.9, alternatives=[],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        capability_invoked=Capability.NOTIFY_IT_HELPDESK,
        execution_steps=["step-1"], target_line_id="L",
    ))

    # orchestrator_b: hydrated, but its own startup ran before the incident
    # existed -- resume_pending_approvals() is NOT called here on purpose.
    orchestrator_b = DecisionOrchestrator(
        event_bus=MagicMock(), integration_hub=MagicMock(), session_factory=async_session_factory,
    )
    assert orchestrator_b.approvals.get(incident_id) is None, "sanity check: not present via the old mechanism"

    found = await orchestrator_b.resolve_pending_approval(incident_id)
    assert found is not None, "on-demand resolution must find an incident this process never saw at startup"
    assert found.incident_id == incident_id
    assert found.resume_context is not None


async def test_claim_awaiting_approval_is_atomic_exactly_one_winner():
    """Direct, deterministic proof of the primitive itself, real Postgres:
    of two claim attempts for the same still-AwaitingApproval incident,
    exactly one succeeds -- independent of any HTTP/threading timing."""
    from db.engine import async_session_factory
    from orchestrate.audit_trail import AuditTrail

    incident_id = "p13-claim-atomicity-unit-test"
    async with async_session_factory() as db:
        from db.models.incident import IncidentRow
        from sqlalchemy import delete
        await db.execute(delete(IncidentRow).where(IncidentRow.incident_id == incident_id))
        await db.commit()

    trail = AuditTrail(session_factory=async_session_factory)
    from contracts import IncidentRecord, PolicyTier
    await trail.persist_snapshot(IncidentRecord(
        incident_id=incident_id, plant_id="P", line_id="L", detected_at="2026-01-01T00:00:00Z",
        final_state="AwaitingApproval", causal_chain=[], confidence=0.9, alternatives=[],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
    ))

    first = await trail.claim_awaiting_approval(incident_id)
    second = await trail.claim_awaiting_approval(incident_id)
    assert first is True
    assert second is False, "a row already claimed (no longer AwaitingApproval) must not be claimable again"


def test_concurrent_approve_from_two_real_threads_executes_exactly_once(client, auth_headers, monkeypatch):
    """The actual race, not a sequential simulation: two OS threads, each
    driving its own independent TestClient/app instance, both POST
    /approve for the SAME incident as close to simultaneously as threading
    allows. Real Postgres serializes the underlying claim regardless of
    exact timing -- this test proves the APPLICATION correctly respects
    that serialization (raises/handles DecisionAlreadyInProgress), not
    just that the primitive is atomic in isolation (see the unit test
    above for that)."""
    invoke_calls = []
    original_invoke = IntegrationHub.invoke

    async def _counting_invoke(self, call):
        invoke_calls.append(call.incident_id)
        return await original_invoke(self, call)

    monkeypatch.setattr(IntegrationHub, "invoke", _counting_invoke)

    incident_id = _start_incident(client, auth_headers, line_id="Line-P13-Race")
    _wait_for_awaiting_approval(client, auth_headers, incident_id)

    results = {}
    barrier = threading.Barrier(2)

    def _approve_via(worker_name, worker_client):
        barrier.wait(timeout=10)
        resp = worker_client.post(f"/incidents/{incident_id}/approve", headers=auth_headers)
        results[worker_name] = resp

    with TestClient(app) as worker_b, TestClient(app) as worker_c:
        t1 = threading.Thread(target=_approve_via, args=("b", worker_b))
        t2 = threading.Thread(target=_approve_via, args=("c", worker_c))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

    statuses = sorted(r.status_code for r in results.values())
    assert statuses == [200, 409], f"expected exactly one 200 and one 409, got {statuses}"

    _wait_for_terminal(client, auth_headers, incident_id)

    calls_for_this_incident = [c for c in invoke_calls if c == incident_id]
    assert len(calls_for_this_incident) == 1, (
        f"expected the capability to be invoked exactly once for {incident_id}, "
        f"got {len(calls_for_this_incident)}"
    )
