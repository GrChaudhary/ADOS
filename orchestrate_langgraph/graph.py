"""
LangGraph implementation of the representative slice:

    vision_spec -> causal_isolation -> governance_gate -> execute_capability -> END

MVP fidelity notes (see ../orchestrate_langgraph/COMPARISON.md's Scope &
Methodology section for the full reasoning): CandidateGeneration/Reserving
(Substitution/Parameter-Adjustment/Impact-Simulation), feedback_calibration,
and preemption are out of scope for this slice — scenario_defaults.py
supplies the capability + cost figure those stages would otherwise have
produced. execute_capability is a deterministic mock (ConsoleConnector
only), never a real ServiceNow/SAP call.

Checkpointer is InMemorySaver — matches the custom engine's own
ApprovalQueue, which is equally in-memory-only and non-durable across a
process restart today (see COMPARISON.md's observability section for the
one place this does create a real, documented asymmetry).
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from contracts import CallStatus, IncidentRecord, PolicyTier

from .nodes import (
    causal_isolation_node,
    execute_capability_node,
    governance_gate_node,
    route_after_governance,
    severity_triage_node,
    vision_spec_node,
)
from .scenario_defaults import SLICE_CAPABILITY, SLICE_ESTIMATED_COST_USD
from .state import IncidentGraphState


def build_graph():
    builder = StateGraph(IncidentGraphState)
    builder.add_node("vision_spec", vision_spec_node)
    builder.add_node("severity_triage", severity_triage_node)
    builder.add_node("causal_isolation", causal_isolation_node)
    builder.add_node("governance_gate", governance_gate_node)
    builder.add_node("execute_capability", execute_capability_node)

    builder.add_edge(START, "vision_spec")
    builder.add_edge("vision_spec", "severity_triage")
    builder.add_edge("severity_triage", "causal_isolation")
    builder.add_edge("causal_isolation", "governance_gate")
    builder.add_conditional_edges(
        "governance_gate", route_after_governance, {"execute_capability": "execute_capability", END: END}
    )
    builder.add_edge("execute_capability", END)

    return builder.compile(checkpointer=InMemorySaver())


def _to_incident_record(result: Dict[str, Any], plant_id: str, line_id: str) -> IncidentRecord:
    approval_decision = result.get("approval_decision")
    capability_status = result.get("capability_status")
    final_state = "Resolved" if capability_status == CallStatus.SUCCEEDED.value else "Failed"

    now = datetime.now(timezone.utc).isoformat()
    return IncidentRecord(
        incident_id=result["incident_id"],
        plant_id=plant_id,
        line_id=line_id,
        detected_at=now,
        resolved_at=now,
        final_state=final_state,
        causal_chain=result.get("causal_chain", []),
        confidence=result.get("causal_confidence", 0.0),
        alternatives=result.get("alternatives", []),
        policy_tier=PolicyTier(result["policy_tier"]),
        approved_by=result.get("approved_by"),
        recommendation_accepted=(
            True if approval_decision == "approved" else False if approval_decision == "rejected" else None
        ),
        capability_invoked=SLICE_CAPABILITY if capability_status is not None else None,
        capability_status=CallStatus(capability_status) if capability_status is not None else None,
        estimated_cost_usd=SLICE_ESTIMATED_COST_USD,
    )


async def run_incident_langgraph(
    plant_id: str,
    line_id: str,
    part_number: str,
    vision_data: dict,
    priority: Optional[Any] = None,
    incident_id: Optional[str] = None,
):
    """
    Mirrors DecisionOrchestrator.run_incident()'s signature shape for a
    symmetric call site in tests/demos. `priority` is accepted but unused
    — this slice has no preemption/priority queueing (see COMPARISON.md's
    "Preemption — design note" section) — kept only so a parity test's two
    call sites read the same way.

    Returns (IncidentRecord, graph, config): callers that hit a Tier 1/2
    approval gate need `graph`/`config` to resume via
    resume_incident_langgraph() below; a fresh graph is built per call
    (compile() is cheap — the checkpointer, not the graph object, holds
    state) so each incident gets an independent InMemorySaver-backed thread.
    """
    incident_id = incident_id or str(uuid.uuid4())
    graph = build_graph()
    config = {"configurable": {"thread_id": incident_id}}
    initial: IncidentGraphState = {
        "incident_id": incident_id,
        "plant_id": plant_id,
        "line_id": line_id,
        "part_number": part_number,
        "vision_data": vision_data,
    }
    result = await graph.ainvoke(initial, config=config)
    if "__interrupt__" in result:
        return None, graph, config  # paused — caller must approve/reject and call resume
    record = _to_incident_record(result, plant_id, line_id)
    return record, graph, config


async def resume_incident_langgraph(graph, config, decision: str, approved_by: Optional[str] = None):
    """decision: "approved" | "rejected". Returns the terminal IncidentRecord."""
    result = await graph.ainvoke(Command(resume={"decision": decision, "approved_by": approved_by}), config=config)
    state_snapshot = await graph.aget_state(config)
    plant_id = state_snapshot.values["plant_id"]
    line_id = state_snapshot.values["line_id"]
    return _to_incident_record(result, plant_id, line_id)
