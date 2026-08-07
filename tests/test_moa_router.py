"""
Integration tests for backend/app/routers/moa.py — the API surface that
makes orchestrate/moa/ (the HR domain MOA vertical slice) reachable.
Mirrors tests/test_langgraph_agents_router.py's structure. The behavior
this suite exists to pin down beyond the graph-level tests
(tests/test_moa_hr_domain.py): the REST-layer RBAC gate actually blocks a
non-executive from deciding a Tier-2 action, on both approve and reject,
and pending tasks are consumed exactly once.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from conftest import admin_auth_header
from knowledge.local_llm_client import local_llm_client

ADMIN_AUTH = admin_auth_header()


def _auth_header(role: Role, approval_limit_usd: float) -> dict:
    user = User(
        user_id=f"test-{role.value}",
        username=f"test-{role.value}",
        display_name=f"Test {role.value.title()}",
        role=role,
        approval_limit_usd=approval_limit_usd,
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


AUDITOR_AUTH = _auth_header(Role.AUDITOR, 0.0)
MANAGER_AUTH = _auth_header(Role.MANAGER, 1_000_000.0)
EXECUTIVE_AUTH = _auth_header(Role.EXECUTIVE, 1_000_000.0)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def test_moa_create_task_requires_auth(client):
    response = client.post("/moa/tasks", json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard"})
    assert response.status_code == 401


def test_moa_create_task_forbidden_for_auditor(client):
    response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard"},
        headers=AUDITOR_AUTH,
    )
    assert response.status_code == 403


def test_moa_create_task_rejects_unsupported_domain(client):
    response = client.post(
        "/moa/tasks",
        json={"domain": "unsupported_domain_xyz", "employee_name": "Priya Nair", "instruction": "Offboard"},
        headers=ADMIN_AUTH,
    )
    assert response.status_code == 400


def test_moa_create_task_not_configured_by_default(client):
    response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard"},
        headers=ADMIN_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


def test_moa_create_task_autonomous_action_returns_ok_directly(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Manager notified."},
            ]
        ),
    )
    response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["toolsCalled"] == ["notify_manager"]


def test_moa_create_task_high_risk_action_pauses_for_approval(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"}]),
    )
    response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["taskId"]
    assert body["proposedAction"]["action_key"] == "stop_payroll"


def test_moa_approve_forbidden_for_manager_on_stop_payroll(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Payroll stopped."},
            ]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    task_id = ask_response.json()["taskId"]

    response = client.post(f"/moa/tasks/{task_id}/approve", headers=MANAGER_AUTH)
    assert response.status_code == 403

    # Still resumable — the failed authorization must not have consumed it.
    response2 = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert response2.status_code == 200


def test_moa_reject_forbidden_for_manager_on_stop_payroll(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"}]),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    task_id = ask_response.json()["taskId"]

    response = client.post(f"/moa/tasks/{task_id}/reject", headers=MANAGER_AUTH)
    assert response.status_code == 403


def test_moa_approve_allowed_for_executive_on_stop_payroll(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Payroll stopped."},
            ]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    task_id = ask_response.json()["taskId"]

    response = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["approvalDecision"] == "approved"
    assert body["toolsCalled"] == ["stop_payroll"]


def test_moa_full_ask_then_approve_round_trip_pop_once(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Payroll stopped."},
            ]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    task_id = ask_response.json()["taskId"]

    approve_response = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert approve_response.status_code == 200

    # Consumed exactly once — the pending task can't be double-approved.
    replay = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert replay.status_code == 404


def test_moa_unknown_task_id_404s(client):
    response = client.post("/moa/tasks/does-not-exist/approve", headers=ADMIN_AUTH)
    assert response.status_code == 404


def test_moa_pause_again_response_includes_next_proposed_action(client, monkeypatch):
    """A real offboarding usually pauses 2-3 times. The approve response
    for a task that immediately pauses AGAIN on its next action must carry
    that next action's proposedAction — originally it only returned
    {status, taskId}, forcing the client to guess what it was approving
    next (flagged in docs/PHASE6_ANTIGRAVITY_HANDOFF.md, fixed since)."""
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: disable_it_access"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Offboarding complete."},
            ]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    task_id = ask_response.json()["taskId"]
    assert ask_response.json()["proposedAction"]["action_key"] == "stop_payroll"

    second = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "pending_approval"
    assert body["taskId"] == task_id
    assert body["proposedAction"]["action_key"] == "disable_it_access"
    assert body["proposedAction"]["policy_tier"] == 1

    final = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert final.status_code == 200
    assert final.json()["status"] == "ok"
    assert final.json()["toolsCalled"] == ["stop_payroll", "disable_it_access"]


# ---------------------------------------------------------------------
# Approve request body (edited_arguments) — HTTP-layer parsing only.
# orchestrate/moa/graph.py's own tests (tests/test_moa_dynamic_action.py)
# cover the actual override/validation behavior against a real
# input_schema; stop_payroll here has no real parameters, so these only
# pin down that _parse_approval_body() in backend/app/routers/moa.py
# handles no-body/empty-body/malformed-body/wrong-shaped-body correctly.
# ---------------------------------------------------------------------

def _start_stop_payroll_task(client, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Payroll stopped."},
            ]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=ADMIN_AUTH,
    )
    return ask_response.json()["taskId"]


def test_moa_approve_with_no_body_behaves_exactly_as_before(client, monkeypatch):
    """The pre-existing contract every current caller relies on -- approve
    with zero request body must not start 422ing just because the endpoint
    now also accepts an optional one."""
    task_id = _start_stop_payroll_task(client, monkeypatch)
    response = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_moa_approve_with_empty_json_object_body_behaves_as_before(client, monkeypatch):
    task_id = _start_stop_payroll_task(client, monkeypatch)
    response = client.post(f"/moa/tasks/{task_id}/approve", json={}, headers=EXECUTIVE_AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_moa_approve_rejects_malformed_json_body(client, monkeypatch):
    task_id = _start_stop_payroll_task(client, monkeypatch)
    response = client.post(f"/moa/tasks/{task_id}/approve", content=b"not json", headers=EXECUTIVE_AUTH)
    assert response.status_code == 400

    # The bad body must not have consumed the pending task.
    retry = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert retry.status_code == 200


def test_moa_approve_rejects_edited_arguments_of_the_wrong_shape(client, monkeypatch):
    task_id = _start_stop_payroll_task(client, monkeypatch)
    response = client.post(
        f"/moa/tasks/{task_id}/approve", json={"edited_arguments": "not-an-object"}, headers=EXECUTIVE_AUTH,
    )
    assert response.status_code == 400

    retry = client.post(f"/moa/tasks/{task_id}/approve", headers=EXECUTIVE_AUTH)
    assert retry.status_code == 200


def test_moa_approve_with_edited_arguments_for_an_action_with_no_real_params_is_a_harmless_noop(client, monkeypatch):
    """stop_payroll has no input_schema -- an edited_arguments dict is
    accepted (nothing required to be missing) but has nothing meaningful
    to override; this only proves the plumbing doesn't error, not that a
    value changed anything (see tests/test_moa_dynamic_action.py for that)."""
    task_id = _start_stop_payroll_task(client, monkeypatch)
    response = client.post(
        f"/moa/tasks/{task_id}/approve", json={"edited_arguments": {"unused_field": "x"}}, headers=EXECUTIVE_AUTH,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
