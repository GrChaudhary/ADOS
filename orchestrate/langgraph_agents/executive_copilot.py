"""
LangGraph replacement for orchestrate/ados_executive_copilot.agent.yaml —
the watsonx-hosted agent that answered plant-executive questions about
ADOS KPIs and pending approvals. See orchestrate/langgraph_agents/__init__.py
for why this exists and what it deliberately doesn't touch.

The watsonx version got tool-calling for free from IBM's agent runtime.
This codebase's actual LLM client (knowledge/local_llm_client.py) is
prompt-completion only — no native function-calling API, by design (see
its own docstring on why it replaced an earlier client that fabricated
provider labels). Rather than bolt on a second, separately-configured LLM
integration (e.g. LangChain's ChatOpenAI/ChatAnthropic with bind_tools())
just to get native tool-calling, this graph reasons in the same
strict-format-then-parse style already established elsewhere in this
codebase (local_llm_client._pick_and_justify's PICK:/REASON: convention,
the watsonx ITSM agent's RESULT: line): the model is asked to respond with
either "TOOL: <name>" or "ANSWER: <text>", never both, and an unparseable
or out-of-list tool name is treated as a hard failure rather than silently
guessed at — matching this codebase's existing rule that a model's output
must be validated before it's trusted to drive anything.

LangGraph is doing real work here even without native tool-calling: it's
the reason/act loop control flow (StateGraph, conditional routing, a
bounded iteration cap) — genuinely the same shape as a ReAct agent, just
with a text-protocol tool-selection step instead of a structured
tool_calls field on the model response.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from knowledge.local_llm_client import local_llm_client

from .tools import TOOL_DESCRIPTIONS, TOOLS

MAX_ITERATIONS = 4

_TOOL_PATTERN = re.compile(r"^\s*TOOL:\s*(\S+)", re.IGNORECASE)
_ANSWER_PATTERN = re.compile(r"^\s*ANSWER:\s*(.+)", re.IGNORECASE | re.DOTALL)


class CopilotGraphState(TypedDict, total=False):
    query: str
    transcript: List[str]
    tools_called: List[str]
    next_action: Optional[str]  # "call_tool:<name>" | "answer" | "give_up"
    final_answer: Optional[str]
    model_used: Optional[str]
    status: str  # "ok" | "not_configured" | "error" | "max_iterations_exceeded"
    iteration: int


def _build_prompt(state: CopilotGraphState) -> str:
    transcript_text = "\n".join(state.get("transcript") or []) or "(no tool calls made yet)"
    return (
        "You are the ADOS Executive Copilot, helping a plant executive check "
        "system status.\n\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        f"Tool results so far:\n{transcript_text}\n\n"
        f"Question: {state['query']}\n\n"
        "Decide your next step. Respond in EXACTLY this format, nothing else:\n"
        "TOOL: <tool name from the list above, exactly as written>\n"
        "or, once you have enough information from the tool results above to "
        "answer:\n"
        "ANSWER: <your answer, citing only numbers/facts that appeared in the "
        "tool results above — never invent a figure>"
    )


def _make_reason_node(tools_dict: Dict[str, Callable[[], Any]]):
    async def reason_node(state: CopilotGraphState) -> CopilotGraphState:
        if not local_llm_client.is_configured():
            return {**state, "status": "not_configured", "next_action": "give_up", "final_answer": None}

        prompt = _build_prompt(state)
        result = await asyncio.to_thread(local_llm_client._generate_text, prompt, 500, 0.2)
        if result["status"] != "live_llm_generated":
            return {
                **state,
                "status": "error",
                "next_action": "give_up",
                "final_answer": None,
                "model_used": result.get("model_used"),
            }

        text = result["text"]
        tool_match = _TOOL_PATTERN.match(text)
        answer_match = _ANSWER_PATTERN.match(text)

        if answer_match:
            return {
                **state,
                "next_action": "answer",
                "final_answer": answer_match.group(1).strip(),
                "model_used": result["model_used"],
                "status": "ok",
            }
        if tool_match and tool_match.group(1) in tools_dict:
            return {**state, "next_action": f"call_tool:{tool_match.group(1)}", "model_used": result["model_used"]}

        # Unparseable or names a tool that doesn't exist — never silently
        # guess which tool was meant, matching
        # local_llm_client._pick_and_justify's rule for its own
        # PICK:/REASON: protocol.
        return {
            **state,
            "status": "error",
            "next_action": "give_up",
            "final_answer": None,
            "model_used": result["model_used"],
        }

    return reason_node


def _make_act_node(tools_dict: Dict[str, Callable[[], Any]]):
    async def act_node(state: CopilotGraphState) -> CopilotGraphState:
        tool_name = state["next_action"].split(":", 1)[1]
        tool_fn = tools_dict[tool_name]
        try:
            output = await asyncio.to_thread(tool_fn)
            entry = f"TOOL {tool_name} RESULT: {output}"
        except Exception as exc:
            entry = f"TOOL {tool_name} FAILED: {exc}"

        transcript = list(state.get("transcript") or [])
        transcript.append(entry)
        tools_called = list(state.get("tools_called") or [])
        tools_called.append(tool_name)
        return {
            **state,
            "transcript": transcript,
            "tools_called": tools_called,
            "iteration": state.get("iteration", 0) + 1,
        }

    return act_node


def route_after_reason(state: CopilotGraphState) -> str:
    if state.get("iteration", 0) >= MAX_ITERATIONS and state.get("next_action", "").startswith("call_tool:"):
        return "max_iterations"
    if state.get("next_action") == "answer":
        return "end"
    if state.get("next_action", "").startswith("call_tool:"):
        return "act"
    return "end"  # give_up — not_configured or error, already terminal


def build_graph(tools: Optional[Dict[str, Callable[[], Any]]] = None):
    """`tools` defaults to the HTTP-based TOOLS in .tools (standalone use,
    e.g. calling this agent from outside the ADOS backend process). The
    real backend route passes in_process_tools(orchestrator) instead — see
    backend/app/routers/langgraph_agents.py — since the HTTP tools'
    self-referential call back into this same process is both wasteful
    and, per tools.py's in_process_tools() docstring, currently broken
    against real RBAC auth."""
    tools_dict = tools if tools is not None else TOOLS
    builder = StateGraph(CopilotGraphState)
    builder.add_node("reason", _make_reason_node(tools_dict))
    builder.add_node("act", _make_act_node(tools_dict))

    builder.add_edge(START, "reason")
    builder.add_conditional_edges(
        "reason",
        route_after_reason,
        {"act": "act", "end": END, "max_iterations": END},
    )
    builder.add_edge("act", "reason")

    return builder.compile()


async def ask_copilot(query: str, tools: Optional[Dict[str, Callable[[], Any]]] = None) -> CopilotGraphState:
    """Entry point mirroring executive/copilot.py's NLExecutiveCopilot.ask()
    call shape, but LLM-driven and tool-calling rather than keyword-routed —
    the two are separate, parallel copilot surfaces (see this module's
    docstring), not a replacement of one by the other."""
    graph = build_graph(tools)
    initial: CopilotGraphState = {"query": query, "transcript": [], "tools_called": [], "iteration": 0}
    result = await graph.ainvoke(initial)
    if result.get("iteration", 0) >= MAX_ITERATIONS and result.get("status") != "ok":
        result = {**result, "status": "max_iterations_exceeded", "final_answer": None}
    return result
