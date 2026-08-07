"""
LangGraph executive copilot — orchestrate/langgraph_agents/executive_copilot.py.
Replaces orchestrate/ados_executive_copilot.agent.yaml (formerly hosted on
IBM watsonx Orchestrate, now removed — see that module's docstring).
"""

import pytest

from knowledge.local_llm_client import local_llm_client
from orchestrate.langgraph_agents import executive_copilot, tools


def _fake_generate(responses):
    """Returns a stand-in for local_llm_client._generate_text that yields
    one queued response per call, so a test can script a multi-turn
    reason -> act -> reason conversation deterministically."""
    calls = iter(responses)

    def _generate(prompt, max_tokens, temperature):
        return next(calls)

    return _generate


@pytest.mark.asyncio
async def test_not_configured_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: False)
    result = await executive_copilot.ask_copilot("how are we doing?")
    assert result["status"] == "not_configured"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_calls_a_tool_then_answers_citing_its_result(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake-model", "text": "TOOL: get_ados_executive_kpis"},
                {
                    "status": "live_llm_generated",
                    "model_used": "fake-model",
                    "text": "ANSWER: MTTR is currently 42 minutes.",
                },
            ]
        ),
    )
    monkeypatch.setitem(tools.TOOLS, "get_ados_executive_kpis", lambda: {"mttr_avg_minutes": 42})

    result = await executive_copilot.ask_copilot("what's our MTTR?")
    assert result["status"] == "ok"
    assert result["final_answer"] == "MTTR is currently 42 minutes."
    assert result["tools_called"] == ["get_ados_executive_kpis"]
    assert "42" in result["transcript"][0]


@pytest.mark.asyncio
async def test_answers_immediately_without_a_tool_call_when_model_chooses_to(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake-model", "text": "ANSWER: I don't have enough context to answer that."}]
        ),
    )
    result = await executive_copilot.ask_copilot("what's the meaning of life?")
    assert result["status"] == "ok"
    assert result["tools_called"] == []


@pytest.mark.asyncio
async def test_unparseable_model_response_is_a_hard_failure_not_a_guess(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake-model", "text": "sure, let me think about that..."}]),
    )
    result = await executive_copilot.ask_copilot("what's our MTTR?")
    assert result["status"] == "error"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_unknown_tool_name_is_a_hard_failure_not_a_guess(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "live_llm_generated", "model_used": "fake-model", "text": "TOOL: delete_all_incidents"}]),
    )
    result = await executive_copilot.ask_copilot("what's our MTTR?")
    assert result["status"] == "error"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_llm_backend_error_surfaces_cleanly(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate([{"status": "error", "model_used": None, "text": None, "error": "rate limited"}]),
    )
    result = await executive_copilot.ask_copilot("what's our MTTR?")
    assert result["status"] == "error"
    assert result["final_answer"] is None


@pytest.mark.asyncio
async def test_stops_after_max_iterations_instead_of_looping_forever(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    # Always asks for the same tool, never answers — must not loop forever.
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [{"status": "live_llm_generated", "model_used": "fake-model", "text": "TOOL: get_ados_executive_kpis"}] * 10
        ),
    )
    monkeypatch.setitem(tools.TOOLS, "get_ados_executive_kpis", lambda: {"mttr_avg_minutes": 42})

    result = await executive_copilot.ask_copilot("what's our MTTR?")
    assert result["status"] == "max_iterations_exceeded"
    assert result["final_answer"] is None
    assert result["iteration"] == executive_copilot.MAX_ITERATIONS


@pytest.mark.asyncio
async def test_tool_execution_failure_is_recorded_not_crashed(monkeypatch):
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        local_llm_client,
        "_generate_text",
        _fake_generate(
            [
                {"status": "live_llm_generated", "model_used": "fake-model", "text": "TOOL: get_ados_pending_approvals"},
                {"status": "live_llm_generated", "model_used": "fake-model", "text": "ANSWER: I couldn't reach the approvals system."},
            ]
        ),
    )

    def _boom():
        raise RuntimeError("backend unreachable")

    monkeypatch.setitem(tools.TOOLS, "get_ados_pending_approvals", _boom)

    result = await executive_copilot.ask_copilot("any approvals pending?")
    assert result["status"] == "ok"
    assert "FAILED" in result["transcript"][0]
    assert "backend unreachable" in result["transcript"][0]
