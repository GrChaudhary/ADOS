"""
Graph node functions for the LangGraph representative slice.

vision_spec_node / causal_isolation_node wrap the REAL agent classes
(agents/vision_spec_agent.py, agents/causal_isolation_agent.py) unmodified
— business logic must be identical to the custom engine's so the
comparison isolates the orchestration framework, not reimplemented logic.
Agent instances are built once at module import (mirroring
orchestrate/agent_runner.py's AgentRunner, which also builds its agents
dict once in __init__) so repeated graph runs/benchmark iterations don't
pay redundant KnowledgeGraph()/CausalGraph() seed-loading cost the custom
engine wouldn't pay either.
"""

from typing import Optional

# NOTE on import order: orchestrate/__init__.py and agents/__init__.py are
# mutually reachable (agents -> agents.sdk -> knowledge -> executive ->
# orchestrate.governance; orchestrate/__init__.py -> agent_runner.py ->
# agents). Whichever one a fresh process touches FIRST wins cleanly;
# touching bare `agents` first mid-cycle leaves it only partially
# initialized and raises ImportError (reproduced while writing this
# module). orchestrate/orchestrator.py's own module always resolves this
# safely because it's conventionally imported before `agents` — mirror
# that here by importing orchestrate.governance before `agents`, so this
# module works whether it's the first thing a process imports (as
# tests/test_orchestrate_langgraph.py run in isolation will do) or not.
from orchestrate.governance import assign_policy_tier

from agents import CausalIsolationAgent, SeverityTriageAgent, VisionSpecAgent
from agents.sdk import IncidentContext, StageInput
from contracts import CapabilityCall, CausalChainEntry, GovernanceInfo, PolicyTier
from integrations import IntegrationHub
from integrations.connectors.console import ConsoleConnector
from langgraph.graph import END
from langgraph.types import interrupt

from .scenario_defaults import SLICE_CAPABILITY, SLICE_ESTIMATED_COST_USD
from .state import IncidentGraphState

_vision_agent = VisionSpecAgent()
_causal_agent = CausalIsolationAgent()
_severity_agent = SeverityTriageAgent()


def _incident_context(state: IncidentGraphState) -> IncidentContext:
    return IncidentContext(
        incident_id=state["incident_id"],
        plant_id=state["plant_id"],
        line_id=state["line_id"],
        part_number=state["part_number"],
    )


def vision_spec_node(state: IncidentGraphState) -> dict:
    output, _envelope = _vision_agent.run(
        _incident_context(state),
        StageInput(
            stage_name="Perception",
            payload={"vision_data": state["vision_data"], "part_number": state["part_number"]},
        ),
    )
    return {"vision_result": output.result}


def severity_triage_node(state: IncidentGraphState) -> dict:
    """Extensibility experiment only — see agents/severity_triage_agent.py
    and orchestrate_langgraph/extensibility_experiment/."""
    output, _envelope = _severity_agent.run(
        _incident_context(state),
        StageInput(stage_name="Perception", payload={"deviation_mm": state["vision_result"]["deviation_mm"]}),
    )
    return {"severity_result": output.result}


def causal_isolation_node(state: IncidentGraphState) -> dict:
    output, _envelope = _causal_agent.run(
        _incident_context(state),
        StageInput(
            stage_name="Reasoning",
            payload={"defect_type": state["vision_result"]["defect_type"]},
        ),
    )
    causal_chain = [
        CausalChainEntry(
            condition_id=rc["condition_id"],
            description=rc["name"],
            weight=rc["weight"],
            evidence_path=rc["evidence_path"],
        ).model_dump(by_alias=True)
        for rc in output.result["ranked_causes"]
    ]
    return {
        "causal_result": output.result,
        "causal_confidence": output.confidence,
        "causal_chain": causal_chain,
        "alternatives": [a.model_dump(by_alias=True) for a in output.alternatives],
    }


def governance_gate_node(state: IncidentGraphState) -> dict:
    tier = assign_policy_tier(SLICE_CAPABILITY, state["causal_confidence"], SLICE_ESTIMATED_COST_USD)
    if tier == PolicyTier.AUTONOMOUS:
        return {"policy_tier": tier.value, "approval_decision": "approved", "approved_by": None}

    # interrupt() re-executes this WHOLE node from the top when the graph
    # resumes (confirmed against the installed langgraph==1.2.10 API) —
    # assign_policy_tier is pure so re-running it above is harmless, but
    # nothing with side effects may ever be added below this line in this
    # node.
    decision = interrupt(
        {
            "policy_tier": tier.name,
            "confidence": state["causal_confidence"],
            "estimated_cost_usd": SLICE_ESTIMATED_COST_USD,
            "capability": SLICE_CAPABILITY.value,
        }
    )
    return {
        "policy_tier": tier.value,
        "approval_decision": decision["decision"],
        "approved_by": decision.get("approved_by"),
    }


def route_after_governance(state: IncidentGraphState):
    return "execute_capability" if state["approval_decision"] == "approved" else END


async def execute_capability_node(state: IncidentGraphState) -> dict:
    # Deliberately NOT integrations.default_hub() — its "preferred
    # configured connector" rule means behavior depends on whatever real
    # credentials happen to be in .env. A step labeled "mocked" must be
    # deterministic regardless of environment, so this hub only ever
    # registers ConsoleConnector.
    hub = IntegrationHub()
    hub.registry.register(ConsoleConnector())

    call = CapabilityCall(
        capability=SLICE_CAPABILITY,
        incident_id=state["incident_id"],
        requested_by="orchestrate_langgraph/graph",
        input={
            "execution_steps": [f"Dispatch {SLICE_CAPABILITY.value}"],
            "target_line_id": state["line_id"],
        },
        governance=GovernanceInfo(
            policy_tier=PolicyTier(state["policy_tier"]),
            approved_by=state.get("approved_by"),
        ),
    )
    response = await hub.invoke(call)
    return {"capability_status": response.status.value, "capability_output": response.output}
