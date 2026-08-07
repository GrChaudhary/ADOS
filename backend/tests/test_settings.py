"""
LLM provider settings API — backend/app/routers/settings.py. Network
health checks (knowledge/local_llm_client.py's _health_status) are
monkeypatched out for every test here — this suite exercises persistence
(does a saved key survive, is it visible to a second request, does
delete clear it), not live provider connectivity, and an unmocked network
call in a unit test is exactly the kind of incident
tests/test_itsm_connector.py's docstring already warns about elsewhere in
this repo.
"""

import pytest

from backend.app.rbac import Role, User, create_access_token
from knowledge.local_llm_client import local_llm_client


@pytest.fixture(autouse=True)
def _no_live_health_checks(monkeypatch):
    monkeypatch.setattr(
        local_llm_client, "_health_status",
        lambda provider: {"status": "Not Configured", "connected": False},
    )


def test_get_llm_providers_returns_all_key_providers_and_ollama(client, auth_headers):
    resp = client.get("/settings/llm-providers", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    provider_names = {p["provider"] for p in body["providers"]}
    assert provider_names == {"nemotron", "openai", "anthropic"}
    assert "ollama" in body


def test_put_saves_a_key_and_it_is_reflected_immediately(client, auth_headers):
    resp = client.put("/settings/llm-providers/openai", json={"apiKey": "sk-test-key-123456"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["masked_key"] == "sk-t...3456"


def test_put_key_survives_a_second_request(client, auth_headers):
    """Distinct from the immediate-response check above: reads it back via
    a separate GET, exercising the actual property this migration exists
    for — the saved key outlives the request that wrote it, not just the
    response object of that same request."""
    client.put("/settings/llm-providers/anthropic", json={"apiKey": "anthropic-test-key-abcdef"}, headers=auth_headers)

    resp = client.get("/settings/llm-providers", headers=auth_headers)
    anthropic_status = next(p for p in resp.json()["providers"] if p["provider"] == "anthropic")
    assert anthropic_status["configured"] is True


def test_put_preserves_existing_model_when_not_resent(client, auth_headers):
    client.put(
        "/settings/llm-providers/openai",
        json={"apiKey": "sk-test-key-first", "model": "gpt-4o"},
        headers=auth_headers,
    )
    resp = client.put("/settings/llm-providers/openai", json={"apiKey": "sk-test-key-second"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["model"] == "gpt-4o"


def test_delete_clears_a_saved_key(client, auth_headers):
    client.put("/settings/llm-providers/openai", json={"apiKey": "sk-test-key-123456"}, headers=auth_headers)
    resp = client.delete("/settings/llm-providers/openai", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_put_unknown_provider_is_rejected(client, auth_headers):
    resp = client.put("/settings/llm-providers/made-up-provider", json={"apiKey": "x"}, headers=auth_headers)
    assert resp.status_code == 400


def test_put_requires_admin_role(client):
    manager = User(
        user_id="test-manager", username="test-manager", display_name="Test Manager",
        role=Role.MANAGER, approval_limit_usd=100_000.0,
    )
    headers = {"Authorization": f"Bearer {create_access_token(manager)}"}
    resp = client.put("/settings/llm-providers/openai", json={"apiKey": "sk-test-key-123456"}, headers=headers)
    assert resp.status_code == 403
