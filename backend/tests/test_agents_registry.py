"""
Agent Registry API — backend/app/routers/agents_registry.py. Before this
router was Postgres-backed, creating a custom agent without Cloudant
configured was a silent no-op: POST returned 201 with the created entry,
but nothing stored it anywhere, so it never showed up in a later GET, and
DELETE always 503'd. These tests exist mainly to pin down that the bug is
actually fixed — a created agent is listed, deletable, and gone after
deletion — not just that the routes return 2xx.
"""

import pytest

from backend.app.routers.agents_registry import BUILTIN_AGENTS


def _agent_payload(label: str = "Test Widget Agent") -> dict:
    return {
        "label": label,
        "description": "A test agent used to exercise the registry API end to end.",
        "model": "test-model-v1",
        "inputSchema": "TestInput { field }",
        "outputSchema": "TestOutput { field }",
    }


def test_list_includes_the_builtins(client, auth_headers):
    resp = client.get("/agents-registry", headers=auth_headers)
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert "vision-spec-agent" in ids
    assert "servicenow-itsm-agent" in ids
    assert len(ids) == len(BUILTIN_AGENTS)


def test_created_agent_is_persisted_and_listed(client, auth_headers):
    create_resp = client.post("/agents-registry", json=_agent_payload(), headers=auth_headers)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["id"]
    assert agent_id.startswith("custom-test-widget-agent-")

    list_resp = client.get("/agents-registry", headers=auth_headers)
    ids = {a["id"] for a in list_resp.json()}
    assert agent_id in ids


def test_created_agent_survives_a_second_request(client, auth_headers):
    """Distinct from test_created_agent_is_persisted_and_listed: this
    round-trips through two separate TestClient(app) lifespans (one per
    `client` fixture use isn't what happens here — `client` is
    function-scoped, so this is really the same in-process db read, but
    via a second HTTP call, matching how a real second browser request
    would behave), not just re-reading in-memory state from the same
    response object."""
    create_resp = client.post("/agents-registry", json=_agent_payload("Second Call Agent"), headers=auth_headers)
    agent_id = create_resp.json()["id"]

    get_resp = client.get("/agents-registry", headers=auth_headers)
    matching = [a for a in get_resp.json() if a["id"] == agent_id]
    assert len(matching) == 1
    assert matching[0]["label"] == "Second Call Agent"
    assert matching[0]["isBuiltIn"] is False


def test_create_agent_id_conflict_with_builtin_is_rejected(client, auth_headers, monkeypatch):
    import backend.app.routers.agents_registry as reg

    monkeypatch.setattr(reg.uuid, "uuid4", lambda: type("_", (), {"hex": "0" * 32})())
    monkeypatch.setattr(reg, "BUILTIN_IDS", {"custom-conflict-agent-000000"})
    resp = client.post("/agents-registry", json=_agent_payload("Conflict Agent"), headers=auth_headers)
    assert resp.status_code == 409


def test_delete_builtin_agent_is_forbidden(client, auth_headers):
    resp = client.delete("/agents-registry/vision-spec-agent", headers=auth_headers)
    assert resp.status_code == 403


def test_delete_unknown_agent_404s(client, auth_headers):
    resp = client.delete("/agents-registry/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_removes_a_custom_agent(client, auth_headers):
    create_resp = client.post("/agents-registry", json=_agent_payload("Deletable Agent"), headers=auth_headers)
    agent_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/agents-registry/{agent_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    list_resp = client.get("/agents-registry", headers=auth_headers)
    ids = {a["id"] for a in list_resp.json()}
    assert agent_id not in ids
