"""
MOA (Main Orchestrating Agent) HR domain pod — orchestrate/moa/graph.py.
Mirrors tests/test_langgraph_itsm_agent.py's structure. The behaviors this
suite exists to pin down: dynamic per-action tiering actually produces
three different governance tiers from the same loop, a write never
auto-executes above its computed tier, and the cascade breaker (wired in
for the first time by this milestone) actually forces escalation once its
threshold is crossed.
"""

import pytest

from contracts import PolicyTier
from integrations import IntegrationHub
from integrations.connectors.console import ConsoleConnector
from knowledge.local_llm_client import local_llm_client
from orchestrate.cascade_breaker import CascadeCircuitBreaker
from orchestrate.moa import graph as moa_graph


def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def _console_hub() -> IntegrationHub:
    hub = IntegrationHub()
    hub.registry.register(ConsoleConnector())
    return hub


def _tracking_hub():
    hub = _console_hub()
    calls_made = []
    original_invoke = hub.invoke

    async def _tracking_invoke(call):
        calls_made.append(call)
        return await original_invoke(call)

    hub.invoke = _tracking_invoke
    return hub, calls_made


@pytest.mark.asyncio
async def test_not_configured_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: False)
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=_console_hub())
    assert result["status"] == "not_configured"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_autonomous_action_executes_without_pausing(monkeypatch):
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
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=_console_hub())
    assert result is not None  # never paused
    assert result["status"] == "ok"
    assert result["tools_called"] == ["notify_manager"]
    assert any("AUTO-EXECUTED" in entry for entry in result["transcript"])


@pytest.mark.asyncio
async def test_high_risk_action_pauses_and_requires_executive_approval_tier(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"}]),
    )
    hub, calls_made = _tracking_hub()
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub)

    assert result is None  # paused, not a terminal result
    assert calls_made == []  # nothing invoked before approval
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["policy_tier"] == PolicyTier.EXECUTIVE_APPROVAL.value
    assert proposed["action_key"] == "stop_payroll"


@pytest.mark.asyncio
async def test_medium_cost_action_pauses_at_approval_required_not_executive(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: disable_it_access"}]),
    )
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=_console_hub())

    assert result is None
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["policy_tier"] == PolicyTier.APPROVAL_REQUIRED.value


@pytest.mark.asyncio
async def test_rejected_high_risk_action_never_invokes_hub(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: stop_payroll"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Understood, not stopping payroll."},
            ]
        ),
    )
    hub, calls_made = _tracking_hub()
    _, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub)
    result, graph, config = await moa_graph.resume_moa_task(graph, config, decision="rejected", approved_by="admin-1")

    assert calls_made == []
    assert result["approval_decision"] == "rejected"
    assert result["tools_called"] == []
    assert any("REJECTED" in entry for entry in result["transcript"])


@pytest.mark.asyncio
async def test_approved_high_risk_action_invokes_hub_with_correct_governance(monkeypatch):
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
    hub, calls_made = _tracking_hub()
    _, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=hub)
    result, graph, config = await moa_graph.resume_moa_task(graph, config, decision="approved", approved_by="exec-1")

    assert result["status"] == "ok"
    assert result["tools_called"] == ["stop_payroll"]
    assert len(calls_made) == 1
    assert calls_made[0].governance.policy_tier == PolicyTier.EXECUTIVE_APPROVAL
    assert calls_made[0].governance.approved_by == "exec-1"


@pytest.mark.asyncio
async def test_cascade_breaker_forces_escalation_after_threshold(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"},
            ]
        ),
    )
    hub, calls_made = _tracking_hub()
    breaker = CascadeCircuitBreaker(threshold=2)
    result, graph, config = await moa_graph.run_moa_task(
        "Priya Nair", "Offboard Priya", hub=hub, cascade_breaker=breaker
    )

    # Actions 1-2 auto-execute (crossing the threshold on the 2nd); action 3
    # pauses even though its own raw tier is AUTONOMOUS.
    assert result is None
    assert len(calls_made) == 2
    proposed = graph.get_state(config).values["proposed_action"]
    assert proposed["action_key"] == "notify_manager"


@pytest.mark.asyncio
async def test_stops_after_max_iterations_instead_of_looping_forever(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    # notify_manager forever - the LLM never answers. A high cascade
    # threshold isolates this test to max-iterations behavior specifically
    # (the default threshold=4 would otherwise pause the loop for cascade
    # review before MAX_ITERATIONS=6 is ever reached).
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: notify_manager"} for _ in range(20)]
        ),
    )
    result, graph, config = await moa_graph.run_moa_task(
        "Priya Nair", "Offboard Priya", hub=_console_hub(), cascade_breaker=CascadeCircuitBreaker(threshold=100)
    )
    assert result["status"] == "max_iterations_exceeded"


@pytest.mark.asyncio
async def test_unparseable_model_response_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "uh, sure, I'll do something"}]),
    )
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=_console_hub())
    assert result["status"] == "error"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_unknown_action_key_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "ACTION: fire_everyone"}]),
    )
    result, graph, config = await moa_graph.run_moa_task("Priya Nair", "Offboard Priya", hub=_console_hub())
    assert result["status"] == "error"
    assert result["final_answer"] is None
