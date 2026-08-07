"""
Tests for Automated ReAct Execution Replay Engine & Visual Timeline (trajectory_log).
"""

import pytest
from orchestrate.moa import graph as moa_graph
from backend.app.rbac import Role, User, create_access_token

ADMIN_AUTH = {"Authorization": f"Bearer {create_access_token(User(user_id='admin', username='admin', display_name='Admin User', role=Role.ADMIN, approval_limit_usd=1e9))}"}


@pytest.mark.asyncio
async def test_moa_graph_trajectory_log_structure(monkeypatch):
    """Verify that MOAGraphState records structured step entries in trajectory_log."""
    def mock_generate_text(prompt, max_tokens=400, temperature=0.2):
        if "(nothing done yet)" in prompt:
            return {"status": "live_llm_generated", "text": "ACTION: disable_it_access", "model_used": "mock-nemotron"}
        return {"status": "live_llm_generated", "text": "ANSWER: IT access revoked successfully", "model_used": "mock-nemotron"}

    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client.is_configured", lambda: True)
    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client._generate_text", mock_generate_text)

    result, graph, config = await moa_graph.run_moa_task("Marcus Vance", "Disable IT access", domain="hr")
    # Action disable_it_access requires Tier 1 approval -> returns None (paused)
    assert result is None

    state = graph.get_state(config).values
    trajectory = state.get("trajectory_log", [])
    assert len(trajectory) == 1
    step1 = trajectory[0]
    assert step1["step"] == 1
    assert step1["action"] == "disable_it_access"
    assert step1["policy_tier"] == 1
    assert step1["status"] == "proposed"


def test_moa_router_returns_trajectory_log(client, monkeypatch):
    """Verify POST /moa/tasks REST route includes trajectoryLog array in JSON response."""
    def mock_generate_text(prompt, max_tokens=400, temperature=0.2):
        return {"status": "live_llm_generated", "text": "ANSWER: Offboarding completed", "model_used": "mock-nemotron"}

    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client.is_configured", lambda: True)
    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client._generate_text", mock_generate_text)

    payload = {"domain": "hr", "employee_name": "Marcus Vance", "instruction": "Offboard employee"}
    response = client.post("/moa/tasks", json=payload, headers=ADMIN_AUTH)
    assert response.status_code == 200
    data = response.json()

    assert "trajectoryLog" in data
    assert len(data["trajectoryLog"]) >= 1
    assert data["trajectoryLog"][0]["type"] == "answer"
