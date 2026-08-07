"""
GET /governance/circuit-breaker + POST /governance/circuit-breaker/clear
(backend/app/routers/governance.py). There is no single global
CascadeCircuitBreaker in ADOS — orchestrate/moa/graph.py creates one PER
MOA task (see that module's own docstring: "One instance per
incident/task"). These endpoints report an honest AGGREGATE over the
currently-live per-task breakers held in app.state.moa_pending_tasks
(populated only while a task is paused awaiting a human), not a
fabricated global counter — these tests drive real MOA tasks through the
real router to produce that live state, rather than constructing a
breaker directly and bypassing the thing under test.
"""

from backend.app.rbac import Role, User, create_access_token
from knowledge.local_llm_client import local_llm_client


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def _auditor_auth_header() -> dict:
    auditor = User(
        user_id="test-auditor-cb", username="test-auditor-cb", display_name="Test Auditor",
        role=Role.AUDITOR, approval_limit_usd=0.0,
    )
    return {"Authorization": f"Bearer {create_access_token(auditor)}"}


def test_circuit_breaker_status_closed_when_no_active_moa_tasks(client, auth_headers):
    response = client.get("/governance/circuit-breaker", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "CLOSED"
    assert body["auto_approved_count"] == 0
    assert body["active_tasks"] == 0
    assert body["open_task_ids"] == []


def test_circuit_breaker_requires_auth(client):
    response = client.get("/governance/circuit-breaker")
    assert response.status_code == 401


def test_circuit_breaker_reflects_live_task_open_state(client, auth_headers, monkeypatch):
    """Default threshold is 4. Scripting 5 consecutive autonomous-tier
    actions: the first 4 auto-execute (the 4th crosses the threshold and
    flips the breaker OPEN), the 5th is escalated to a pause instead of
    executing — same mechanics tests/test_moa_hr_domain.py's
    test_cascade_breaker_forces_escalation_after_threshold pins down at
    the graph level; this confirms the REST status endpoint actually
    reflects that live state, not just the graph internals."""
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"} for _ in range(5)]
        ),
    )
    ask_response = client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    )
    assert ask_response.json()["status"] == "pending_approval"
    task_id = ask_response.json()["taskId"]

    status = client.get("/governance/circuit-breaker", headers=auth_headers).json()
    assert status["state"] == "OPEN"
    assert status["auto_approved_count"] == 4
    assert status["active_tasks"] == 1
    assert status["open_task_ids"] == [task_id]


def test_circuit_breaker_clear_forbidden_for_auditor(client):
    response = client.post("/governance/circuit-breaker/clear", headers=_auditor_auth_header())
    assert response.status_code == 403


def test_circuit_breaker_clear_closes_an_open_breaker(client, auth_headers, monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"} for _ in range(5)]
        ),
    )
    client.post(
        "/moa/tasks",
        json={"domain": "hr", "employee_name": "Priya Nair", "instruction": "Offboard Priya"},
        headers=auth_headers,
    )
    assert client.get("/governance/circuit-breaker", headers=auth_headers).json()["state"] == "OPEN"

    clear_response = client.post("/governance/circuit-breaker/clear", headers=auth_headers)
    assert clear_response.status_code == 200
    assert clear_response.json()["breakers_cleared"] == 1

    status = client.get("/governance/circuit-breaker", headers=auth_headers).json()
    assert status["state"] == "CLOSED"
    assert status["auto_approved_count"] == 0
