"""
The two properties Stage 2b exists to create, tested the only way that
actually proves them: by throwing away the process state that used to hold a
paused task and showing the task is still there.

Before this, `app.state.moa_pending_tasks` held `(graph, config, breaker)` in
memory. Both of the following were impossible:

  1. Restart the app mid-approval and still be able to approve.
  2. Approve through a *different* app instance than the one that started it.

A test that only exercised one long-lived TestClient would have passed
against the old code too, so each test here deliberately builds a second,
independent app instance — a stand-in for "the process died" and for "the
load balancer sent the approval to the other replica". Nothing is carried
over between them except the task_id and the shared database.

See docs/DESIGN_DURABLE_MOA_STATE.md.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from knowledge.local_llm_client import local_llm_client


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def _pause_then_answer(monkeypatch, answer="Payroll stopped."):
    """Scripts the LLM to propose one Tier-2 action (which pauses for
    approval), then give a final answer once it is approved."""
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([
            {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
            {"status": "live_llm_generated", "model_used": "fake", "text": f"ANSWER: {answer}"},
        ]),
    )


def test_paused_approval_survives_a_full_app_restart(client, auth_headers, monkeypatch):
    _pause_then_answer(monkeypatch)

    started = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    ).json()
    assert started["status"] == "pending_approval"
    task_id = started["taskId"]

    # The original app is gone. A brand-new TestClient runs lifespan again,
    # so app.state is rebuilt from scratch — under the old design this is
    # precisely where the pending task vanished.
    with TestClient(app) as restarted:
        approved = restarted.post(f"/moa/tasks/{task_id}/approve", headers=auth_headers)

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "ok"
    assert body["toolsCalled"] == ["stop_payroll"]
    assert body["approvalDecision"] == "approved"


def test_a_second_replica_can_approve_a_task_it_never_started(client, auth_headers, monkeypatch):
    """The multi-replica case. Two TestClients over one database stand in for
    two backend containers behind a load balancer."""
    _pause_then_answer(monkeypatch, answer="Handled by the other replica.")

    started = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    ).json()
    task_id = started["taskId"]

    with TestClient(app) as replica_b:
        # Replica B sees the paused task in the shared governance aggregate...
        status = replica_b.get("/governance/circuit-breaker", headers=auth_headers).json()
        assert task_id in status["open_task_ids"] or status["active_tasks"] >= 1

        # ...and can act on it.
        approved = replica_b.post(f"/moa/tasks/{task_id}/approve", headers=auth_headers)

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "ok"


def test_rejecting_after_a_restart_still_never_invokes_the_connector(client, auth_headers, monkeypatch):
    """Restart survival must preserve the governance decision, not just the
    ability to respond. A rejection that silently executed the action anyway
    would be the worst possible way for this to 'work'."""
    _pause_then_answer(monkeypatch, answer="Understood, not stopping payroll.")

    started = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    ).json()
    task_id = started["taskId"]

    with TestClient(app) as restarted:
        rejected = restarted.post(f"/moa/tasks/{task_id}/reject", headers=auth_headers)

    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["approvalDecision"] == "rejected"
    assert body["toolsCalled"] == []


def test_a_resolved_task_stops_being_resumable(client, auth_headers, monkeypatch):
    """The breaker row is deleted when a task reaches a final answer, so a
    second approval of the same task must 404 rather than re-execute it.
    This is the durable equivalent of the old dict's pop-once behaviour, and
    it is what stops a retried or duplicated request from running a Tier-2
    action twice."""
    _pause_then_answer(monkeypatch)

    started = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    ).json()
    task_id = started["taskId"]

    assert client.post(f"/moa/tasks/{task_id}/approve", headers=auth_headers).status_code == 200

    with TestClient(app) as restarted:
        again = restarted.post(f"/moa/tasks/{task_id}/approve", headers=auth_headers)
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_cascade_streak_is_restored_rather_than_reset(client, auth_headers, monkeypatch):
    """The quiet one. The breaker's streak of auto-approved actions is what
    stops many individually-safe steps adding up to something nobody
    reviewed. Rebuilding a graph on resume with a FRESH breaker would reset
    that count with no error and no failing assertion anywhere else — the
    system would still report itself as protected. This pins the count
    surviving a restart.
    """
    from backend.app import moa_breaker_store
    from db.engine import async_session_factory
    from orchestrate.cascade_breaker import CascadeCircuitBreaker, CascadeState

    task_id = "durability-streak-task"
    breaker = CascadeCircuitBreaker(threshold=4)
    breaker.record_auto_approved("RevokeBuildingAccess", "revoked badge")
    breaker.record_auto_approved("DisableITAccess", "disabled SSO")

    async with async_session_factory() as session:
        await moa_breaker_store.save(session, task_id, breaker, domain="hr")
        await session.commit()

    # Nothing of the original object survives; this is a cold read.
    async with async_session_factory() as session:
        restored = await moa_breaker_store.load(session, task_id)

    assert restored is not None
    assert len(restored.review_batch()) == 2, "the streak reset — cascade protection would be silently off"
    assert [a.capability for a in restored.review_batch()] == ["RevokeBuildingAccess", "DisableITAccess"]
    assert restored.threshold == 4
    assert restored.state is CascadeState.CLOSED

    # And it still trips at the ORIGINAL threshold, two actions later rather
    # than four — proving the restored streak is actually being counted.
    restored.record_auto_approved("StopPayroll", "stopped payroll")
    assert restored.state is CascadeState.CLOSED
    restored.record_auto_approved("NotifyManager", "notified manager")
    assert restored.state is CascadeState.OPEN
