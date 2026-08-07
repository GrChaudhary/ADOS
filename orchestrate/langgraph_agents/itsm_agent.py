"""
LangGraph replacement for orchestrate/ados_itsm_agent.agent.yaml — the
watsonx-hosted agent that created/looked-up ServiceNow incidents. See
orchestrate/langgraph_agents/__init__.py for why this exists.

Ticket creation is a write with real consequences, unlike the executive
copilot's read-only tools, so it's held to a higher bar:

  - It never auto-executes. Every CREATE_INCIDENT request pauses via
    LangGraph's interrupt()/Command(resume=...) — the same primitive
    already proven in orchestrate_langgraph/nodes.py's governance_gate_node
    — and only proceeds after an explicit "approved" decision. This
    deliberately does not reuse orchestrate/governance.py's
    assign_policy_tier() confidence/cost formula: that formula is
    calibrated for the manufacturing incident pipeline's probabilistic
    agents and doesn't map cleanly onto a deterministic, user-instructed
    chat action. It's also a genuinely new, unvalidated path —
    integrations/connectors/servicenow.py's own docstring says it has
    never been tested against a live ServiceNow instance — so "always ask
    a human first" is the honest default here, not a computed autonomy
    tier.
  - The actual creation goes through IntegrationHub.invoke() with
    Capability.CREATE_INCIDENT, so it inherits real governance for free:
    the hot-disable circuit breaker (capability_manifest.py), the
    require_governance policy rule, and whichever real connector (or
    console fallback) is registered — instead of orchestrate/
    servicenow_itsm_tools.py's separate, ungoverned, IBM-ADK-specific
    ServiceNow client.
  - get_incident is a pure read (no governance-relevant side effects) and
    is not routed through the Hub — see servicenow_lookup.py.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from integrations import IntegrationHub, default_hub
from knowledge.local_llm_client import local_llm_client

from .servicenow_lookup import get_incident

MAX_ITERATIONS = 4

_TOOL_PATTERN = re.compile(r"^\s*TOOL:\s*get_incident\s+(\S+)", re.IGNORECASE)
_CREATE_PATTERN = re.compile(r"^\s*CREATE_INCIDENT:\s*([^|]+)\|(.*)", re.IGNORECASE | re.DOTALL)
_ANSWER_PATTERN = re.compile(r"^\s*ANSWER:\s*(.+)", re.IGNORECASE | re.DOTALL)

_ACTIONS_DESCRIPTION = (
    "- get_incident: look up an existing ServiceNow incident by number\n"
    "- create_incident: open a new ServiceNow incident (requires human approval before it actually runs)"
)


class ItsmGraphState(TypedDict, total=False):
    request_id: str
    query: str
    transcript: List[str]
    tools_called: List[str]
    next_action: Optional[str]  # "lookup:<number>" | "propose" | "answer" | "give_up"
    proposed_incident: Optional[Dict[str, str]]
    approval_decision: Optional[str]
    approved_by: Optional[str]
    final_answer: Optional[str]
    model_used: Optional[str]
    status: str
    iteration: int


def _build_prompt(state: ItsmGraphState) -> str:
    transcript_text = "\n".join(state.get("transcript") or []) or "(nothing done yet)"
    return (
        "You are the ADOS ITSM Agent. You create and look up ServiceNow "
        "incident records on behalf of ADOS.\n\n"
        f"Available actions:\n{_ACTIONS_DESCRIPTION}\n\n"
        f"So far:\n{transcript_text}\n\n"
        f"Request: {state['query']}\n\n"
        "Decide your next step. Respond in EXACTLY ONE of these formats, nothing else:\n"
        "TOOL: get_incident <ticket number>\n"
        "CREATE_INCIDENT: <one-line short description>|<full description>\n"
        "ANSWER: <your reply to the user>\n"
        "Never invent a ticket number — only report one that actually came back from "
        "a tool result above."
    )


async def reason_node(state: ItsmGraphState) -> ItsmGraphState:
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
    create_match = _CREATE_PATTERN.match(text)
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
    if create_match:
        return {
            **state,
            "next_action": "propose",
            "proposed_incident": {
                "short_description": create_match.group(1).strip(),
                "description": create_match.group(2).strip(),
            },
            "model_used": result["model_used"],
        }
    if tool_match:
        return {**state, "next_action": f"lookup:{tool_match.group(1)}", "model_used": result["model_used"]}

    # Unparseable — never silently guess which action was meant.
    return {
        **state,
        "status": "error",
        "next_action": "give_up",
        "final_answer": None,
        "model_used": result["model_used"],
    }


async def lookup_node(state: ItsmGraphState) -> ItsmGraphState:
    number = state["next_action"].split(":", 1)[1]
    try:
        output = await asyncio.to_thread(get_incident, number)
        entry = f"TOOL get_incident({number}) RESULT: {output}"
    except Exception as exc:
        entry = f"TOOL get_incident({number}) FAILED: {exc}"

    transcript = list(state.get("transcript") or [])
    transcript.append(entry)
    tools_called = list(state.get("tools_called") or [])
    tools_called.append("get_incident")
    return {**state, "transcript": transcript, "tools_called": tools_called, "iteration": state.get("iteration", 0) + 1}


def _make_propose_node(hub: IntegrationHub):
    async def propose_and_create_node(state: ItsmGraphState) -> ItsmGraphState:
        # interrupt() re-executes this WHOLE node from the top when the
        # graph resumes (same LangGraph invariant documented in
        # orchestrate_langgraph/nodes.py's governance_gate_node, confirmed
        # against langgraph==1.2.10) — nothing above this line may have
        # side effects.
        decision = interrupt(
            {
                "proposed_incident": state["proposed_incident"],
                "message": "New ServiceNow incident proposed — approve to actually create it.",
            }
        )

        transcript = list(state.get("transcript") or [])
        tools_called = list(state.get("tools_called") or [])
        iteration = state.get("iteration", 0) + 1

        if decision.get("decision") != "approved":
            transcript.append(f"CREATE_INCIDENT REJECTED: {state['proposed_incident']}")
            return {
                **state,
                "transcript": transcript,
                "approval_decision": decision.get("decision"),
                "approved_by": decision.get("approved_by"),
                "iteration": iteration,
            }

        call = CapabilityCall(
            capability=Capability.CREATE_INCIDENT,
            incident_id=state["request_id"],
            requested_by="langgraph-itsm-agent",
            input=dict(state["proposed_incident"]),
            governance=GovernanceInfo(
                policy_tier=PolicyTier.APPROVAL_REQUIRED, approved_by=decision.get("approved_by")
            ),
        )
        response = await hub.invoke(call)
        tools_called.append("create_incident")
        if response.status == CallStatus.SUCCEEDED:
            transcript.append(f"CREATE_INCIDENT SUCCEEDED via {response.connector}: {response.output}")
        else:
            transcript.append(f"CREATE_INCIDENT FAILED via {response.connector}: {response.error}")

        return {
            **state,
            "transcript": transcript,
            "tools_called": tools_called,
            "approval_decision": decision.get("decision"),
            "approved_by": decision.get("approved_by"),
            "iteration": iteration,
        }

    return propose_and_create_node


def route_after_reason(state: ItsmGraphState) -> str:
    next_action = state.get("next_action", "")
    if state.get("iteration", 0) >= MAX_ITERATIONS and (next_action.startswith("lookup:") or next_action == "propose"):
        return "max_iterations"
    if next_action == "answer":
        return "end"
    if next_action.startswith("lookup:"):
        return "lookup"
    if next_action == "propose":
        return "propose"
    return "end"  # give_up — not_configured or error, already terminal


def build_graph(hub: Optional[IntegrationHub] = None):
    hub = hub if hub is not None else default_hub()
    builder = StateGraph(ItsmGraphState)
    builder.add_node("reason", reason_node)
    builder.add_node("lookup", lookup_node)
    builder.add_node("propose", _make_propose_node(hub))

    builder.add_edge(START, "reason")
    builder.add_conditional_edges(
        "reason",
        route_after_reason,
        {"lookup": "lookup", "propose": "propose", "end": END, "max_iterations": END},
    )
    builder.add_edge("lookup", "reason")
    builder.add_edge("propose", "reason")

    return builder.compile(checkpointer=InMemorySaver())


async def ask_itsm_agent(query: str, hub: Optional[IntegrationHub] = None, request_id: Optional[str] = None):
    """Returns (result, graph, config). result is None when the graph
    paused on a create-incident proposal — call resume_itsm_agent() with
    the human's decision to continue. Mirrors orchestrate_langgraph/
    graph.py's run_incident_langgraph() return shape and the same
    "fresh graph + independent InMemorySaver thread per call" reasoning."""
    request_id = request_id or str(uuid.uuid4())
    graph = build_graph(hub)
    config = {"configurable": {"thread_id": request_id}}
    initial: ItsmGraphState = {
        "request_id": request_id,
        "query": query,
        "transcript": [],
        "tools_called": [],
        "iteration": 0,
    }
    result = await graph.ainvoke(initial, config=config)
    if "__interrupt__" in result:
        return None, graph, config
    if result.get("iteration", 0) >= MAX_ITERATIONS and result.get("status") != "ok":
        result = {**result, "status": "max_iterations_exceeded", "final_answer": None}
    return result, graph, config


async def resume_itsm_agent(graph, config, decision: str, approved_by: Optional[str] = None):
    """decision: "approved" | "rejected"."""
    result = await graph.ainvoke(Command(resume={"decision": decision, "approved_by": approved_by}), config=config)
    if "__interrupt__" in result:
        return None, graph, config
    if result.get("iteration", 0) >= MAX_ITERATIONS and result.get("status") != "ok":
        result = {**result, "status": "max_iterations_exceeded", "final_answer": None}
    return result, graph, config
