"""
Integration tests for backend/app/routers/langgraph_agents.py — the API
surface that actually makes orchestrate/langgraph_agents/ reachable,
rather than only tested in isolation (tests/test_langgraph_executive_copilot.py,
tests/test_langgraph_itsm_agent.py cover the graphs themselves).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from conftest import admin_auth_header
from knowledge.local_llm_client import local_llm_client

ADMIN_AUTH = admin_auth_header()


def _auditor_auth_header() -> dict:
    auditor = User(
        user_id="test-auditor",
        username="test-auditor",
        display_name="Test Auditor",
        role=Role.AUDITOR,
        approval_limit_usd=0.0,
    )
    return {"Authorization": f"Bearer {create_access_token(auditor)}"}


AUDITOR_AUTH = _auditor_auth_header()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def test_copilot_ask_requires_auth(client):
    response = client.post("/agents/executive-copilot/ask", json={"query": "how are we doing?"})
    assert response.status_code == 401


def test_itsm_ask_requires_auth(client):
    response = client.post("/agents/itsm/ask", json={"query": "open a ticket"})
    assert response.status_code == 401


def test_copilot_ask_not_configured_by_default(client):
    # conftest's autouse fixture forces local_llm_client.is_configured()
    # False for every test unless a test opts back in.
    response = client.post("/agents/executive-copilot/ask", json={"query": "how are we doing?"}, headers=ADMIN_AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


def test_copilot_ask_reads_live_kpis_in_process(client, monkeypatch):
    """Confirms the router wired in_process_tools (not the HTTP tools) —
    if it were still the HTTP path, this would 401 against real RBAC auth
    (see tools.py's in_process_tools docstring) and this test would fail."""
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "TOOL: get_ados_executive_kpis"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Here's the current status."},
            ]
        ),
    )
    response = client.post("/agents/executive-copilot/ask", json={"query": "how's MTTR?"}, headers=ADMIN_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["answer"] == "Here's the current status."
    assert body["toolsCalled"] == ["get_ados_executive_kpis"]


def test_itsm_ask_forbidden_for_auditor(client):
    response = client.post("/agents/itsm/ask", json={"query": "open a ticket"}, headers=AUDITOR_AUTH)
    assert response.status_code == 403


def test_itsm_ask_create_incident_pauses_for_approval(client, monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)  # deterministic console fallback
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {
                    "status": "live_llm_generated",
                    "model_used": "fake",
                    "text": "CREATE_INCIDENT: Printer broken|Jammed since this morning.",
                }
            ]
        ),
    )
    response = client.post(
        "/agents/itsm/ask", json={"query": "open a ticket for the broken printer"}, headers=ADMIN_AUTH
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["requestId"]
    assert body["proposedIncident"]["short_description"] == "Printer broken"


def test_itsm_approve_then_reject_unknown_request_id_404s(client):
    response = client.post("/agents/itsm/does-not-exist/approve", headers=ADMIN_AUTH)
    assert response.status_code == 404


def test_itsm_full_ask_then_approve_round_trip(client, monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {
                    "status": "live_llm_generated",
                    "model_used": "fake",
                    "text": "CREATE_INCIDENT: Printer broken|Jammed since this morning.",
                },
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Ticket created."},
            ]
        ),
    )
    ask_response = client.post(
        "/agents/itsm/ask", json={"query": "open a ticket for the broken printer"}, headers=ADMIN_AUTH
    )
    request_id = ask_response.json()["requestId"]

    approve_response = client.post(f"/agents/itsm/{request_id}/approve", headers=ADMIN_AUTH)
    assert approve_response.status_code == 200
    body = approve_response.json()
    assert body["status"] == "ok"
    assert body["approvalDecision"] == "approved"
    assert body["toolsCalled"] == ["create_incident"]
    assert body["answer"] == "Ticket created."

    # Consumed exactly once — the pending proposal can't be double-approved.
    replay = client.post(f"/agents/itsm/{request_id}/approve", headers=ADMIN_AUTH)
    assert replay.status_code == 404


def test_itsm_reject_is_forbidden_for_auditor(client, monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake", "text": "CREATE_INCIDENT: Printer broken|Jammed."}]
        ),
    )
    ask_response = client.post("/agents/itsm/ask", json={"query": "open a ticket"}, headers=ADMIN_AUTH)
    request_id = ask_response.json()["requestId"]

    response = client.post(f"/agents/itsm/{request_id}/reject", headers=AUDITOR_AUTH)
    assert response.status_code == 403
