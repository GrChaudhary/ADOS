"""
LangGraph ITSM agent — orchestrate/langgraph_agents/itsm_agent.py. Replaces
orchestrate/ados_itsm_agent.agent.yaml (formerly hosted on IBM watsonx
Orchestrate, now removed — see that module's docstring). The behavior this
suite exists to pin down: ticket creation must never auto-execute, and it
must go through the real, governed IntegrationHub — not a bespoke,
ungoverned ServiceNow client.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from integrations import IntegrationHub
from integrations.connectors.console import ConsoleConnector
from knowledge.local_llm_client import local_llm_client
from orchestrate.langgraph_agents import itsm_agent

# Shared saver: build_graph() makes a fresh InMemorySaver per call by
# design, so a test that resumes must hand the same one back in.
_saver = InMemorySaver()



def _fake_generate(responses):
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


def _console_hub() -> IntegrationHub:
    hub = IntegrationHub()
    hub.registry.register(ConsoleConnector())
    return hub


@pytest.mark.asyncio
async def test_not_configured_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: False)
    result, graph, config = await itsm_agent.ask_itsm_agent("open a ticket for a broken printer", hub=_console_hub(), checkpointer=_saver)
    assert result["status"] == "not_configured"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_lookup_then_answer(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake", "text": "TOOL: get_incident INC0010023"},
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: INC0010023 is currently open."},
            ]
        ),
    )
    monkeypatch.setattr(itsm_agent, "get_incident", lambda number: {"number": number, "state": "open"})

    result, graph, config = await itsm_agent.ask_itsm_agent("what's the status of INC0010023?", hub=_console_hub(), checkpointer=_saver)
    assert result["status"] == "ok"
    assert result["final_answer"] == "INC0010023 is currently open."
    assert result["tools_called"] == ["get_incident"]


@pytest.mark.asyncio
async def test_create_incident_pauses_for_approval_instead_of_auto_executing(monkeypatch):
    """The core safety property: a write must never fire before the graph
    pauses and something explicit approves it."""
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {
                    "status": "live_llm_generated",
                    "model_used": "fake",
                    "text": "CREATE_INCIDENT: Printer on 3rd floor broken|The printer near marketing has been jammed since this morning.",
                }
            ]
        ),
    )
    calls_made = []
    hub = _console_hub()
    original_invoke = hub.invoke

    async def _tracking_invoke(call):
        calls_made.append(call)
        return await original_invoke(call)

    hub.invoke = _tracking_invoke

    result, graph, config = await itsm_agent.ask_itsm_agent("open a ticket for the broken printer", hub=hub, checkpointer=_saver)
    assert result is None  # paused, not a terminal result
    assert calls_made == []  # nothing was actually created yet


@pytest.mark.asyncio
async def test_approved_resume_actually_creates_via_the_governed_hub(monkeypatch):
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
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: I've opened the ticket for you."},
            ]
        ),
    )
    hub = _console_hub()
    _, graph, config = await itsm_agent.ask_itsm_agent("open a ticket for the broken printer", hub=hub, checkpointer=_saver)

    result, graph, config = await itsm_agent.resume_itsm_agent(config["configurable"]["thread_id"], decision="approved", approved_by="admin-1", hub=hub, checkpointer=_saver)
    assert result["status"] == "ok"
    assert result["approval_decision"] == "approved"
    assert result["tools_called"] == ["create_incident"]
    assert any("SUCCEEDED" in entry for entry in result["transcript"])
    assert result["final_answer"] == "I've opened the ticket for you."


@pytest.mark.asyncio
async def test_rejected_resume_never_calls_the_hub(monkeypatch):
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
                {"status": "live_llm_generated", "model_used": "fake", "text": "ANSWER: Understood, I won't open a ticket."},
            ]
        ),
    )
    hub = _console_hub()
    calls_made = []
    original_invoke = hub.invoke

    async def _tracking_invoke(call):
        calls_made.append(call)
        return await original_invoke(call)

    hub.invoke = _tracking_invoke

    _, graph, config = await itsm_agent.ask_itsm_agent("open a ticket for the broken printer", hub=hub, checkpointer=_saver)
    result, graph, config = await itsm_agent.resume_itsm_agent(config["configurable"]["thread_id"], decision="rejected", approved_by="admin-1", hub=hub, checkpointer=_saver)

    assert calls_made == []
    assert result["approval_decision"] == "rejected"
    assert result["tools_called"] == []
    assert any("REJECTED" in entry for entry in result["transcript"])


@pytest.mark.asyncio
async def test_unparseable_model_response_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake", "text": "sure, let me get on that"}]),
    )
    result, graph, config = await itsm_agent.ask_itsm_agent("open a ticket", hub=_console_hub(), checkpointer=_saver)
    assert result["status"] == "error"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_stops_after_max_iterations_instead_of_looping_forever(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake", "text": "TOOL: get_incident INC0010023"}] * 10
        ),
    )
    monkeypatch.setattr(itsm_agent, "get_incident", lambda number: {"number": number, "state": "open"})

    result, graph, config = await itsm_agent.ask_itsm_agent("status of INC0010023?", hub=_console_hub(), checkpointer=_saver)
    assert result["status"] == "max_iterations_exceeded"
    assert result["final_answer"] is None
