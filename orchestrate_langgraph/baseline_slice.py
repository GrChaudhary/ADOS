"""
Hand-rolled baseline: the SAME 4-stage slice (vision_spec -> causal_isolation
-> governance gate -> mocked capability execution) sequenced using the
existing engine's own primitives directly — NOT going through
DecisionOrchestrator.run_incident(), which always runs all 8 stages with no
partial-pipeline entrypoint. This exists so the comparison in
COMPARISON.md is "4-stage custom vs. 4-stage LangGraph," not silently
"8-stage custom vs. 4-stage LangGraph" — see that file's Scope &
Methodology section. It composes orchestrator.py's own public primitives
the same way orchestrator.py itself does; it does not modify orchestrate/.

Approval blocking uses the real PendingApproval/ApprovalQueue mechanism
(an asyncio.Event under the hood) — a caller that hits a Tier 1/2 gate
must concurrently call approval_queue.approve()/reject() on the returned
queue for this coroutine to ever complete, exactly like
tests/test_orchestrate.py's own tests do against the real orchestrator.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# See nodes.py's NOTE on import order — orchestrate.governance must be
# touched before a bare `from agents import ...` for this module to be
# safely importable standalone (e.g. tests/test_orchestrate_langgraph.py
# run in isolation).
from orchestrate.governance import ApprovalQueue, PendingApproval, assign_policy_tier

from agents import CausalIsolationAgent, VisionSpecAgent
from agents.sdk import IncidentContext, StageInput
from contracts import CapabilityCall, CausalChainEntry, GovernanceInfo, IncidentRecord, PolicyTier
from integrations import IntegrationHub
from integrations.connectors.console import ConsoleConnector

from .scenario_defaults import SLICE_CAPABILITY, SLICE_ESTIMATED_COST_USD

_vision_agent = VisionSpecAgent()
_causal_agent = CausalIsolationAgent()


async def run_incident_baseline(
    plant_id: str,
    line_id: str,
    part_number: str,
    vision_data: dict,
    priority: Optional[Any] = None,
    incident_id: Optional[str] = None,
    approval_queue: Optional[ApprovalQueue] = None,
) -> IncidentRecord:
    """Mirrors run_incident_langgraph()'s signature for a symmetric call
    site in tests. `priority` accepted-but-unused, same reason as the
    LangGraph side (no preemption/priority queueing in this slice).
    `approval_queue`: pass a shared ApprovalQueue if a concurrent task
    needs to see/resolve the pending approval (as tests/test_orchestrate.py's
    own tests do against the real orchestrator); one is created if omitted,
    which only makes sense for a Tier 0 (AUTONOMOUS) scenario since nothing
    else can resolve it otherwise.
    """
    incident_id = incident_id or str(uuid.uuid4())
    detected_at = datetime.now(timezone.utc).isoformat()
    approval_queue = approval_queue if approval_queue is not None else ApprovalQueue()

    ctx = IncidentContext(incident_id=incident_id, plant_id=plant_id, line_id=line_id, part_number=part_number)

    vision_out, _ = _vision_agent.run(
        ctx, StageInput(stage_name="Perception", payload={"vision_data": vision_data, "part_number": part_number})
    )
    causal_out, _ = _causal_agent.run(
        ctx, StageInput(stage_name="Reasoning", payload={"defect_type": vision_out.result["defect_type"]})
    )
    causal_chain = [
        CausalChainEntry(
            condition_id=rc["condition_id"],
            description=rc["name"],
            weight=rc["weight"],
            evidence_path=rc["evidence_path"],
        )
        for rc in causal_out.result["ranked_causes"]
    ]
    alternatives = [a.model_dump(by_alias=True) for a in causal_out.alternatives]

    tier = assign_policy_tier(SLICE_CAPABILITY, causal_out.confidence, SLICE_ESTIMATED_COST_USD)
    if tier == PolicyTier.AUTONOMOUS:
        decision, approved_by = "approved", None
    else:
        pending = PendingApproval(
            incident_id=incident_id,
            capability=SLICE_CAPABILITY,
            policy_tier=tier,
            confidence=causal_out.confidence,
            summary=f"{SLICE_CAPABILITY.value} for {part_number}",
            estimated_cost_usd=SLICE_ESTIMATED_COST_USD,
        )
        approval_queue.enqueue(pending)
        decision = await pending.wait()
        approved_by = pending.approved_by

    if decision != "approved":
        return IncidentRecord(
            incident_id=incident_id,
            plant_id=plant_id,
            line_id=line_id,
            detected_at=detected_at,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            final_state="Failed",
            causal_chain=causal_chain,
            confidence=causal_out.confidence,
            alternatives=alternatives,
            policy_tier=tier,
            approved_by=approved_by,
            recommendation_accepted=False,
            estimated_cost_usd=SLICE_ESTIMATED_COST_USD,
        )

    # Deliberately NOT integrations.default_hub() — see nodes.py's
    # execute_capability_node docstring for why a mocked step must be
    # deterministic regardless of ambient .env credentials.
    hub = IntegrationHub()
    hub.registry.register(ConsoleConnector())
    call = CapabilityCall(
        capability=SLICE_CAPABILITY,
        incident_id=incident_id,
        requested_by="orchestrate_langgraph/baseline_slice",
        input={
            "execution_steps": [f"Dispatch {SLICE_CAPABILITY.value}"],
            "target_line_id": line_id,
        },
        governance=GovernanceInfo(policy_tier=tier, approved_by=approved_by),
    )
    response = await hub.invoke(call)

    return IncidentRecord(
        incident_id=incident_id,
        plant_id=plant_id,
        line_id=line_id,
        detected_at=detected_at,
        resolved_at=datetime.now(timezone.utc).isoformat(),
        final_state="Resolved" if response.status.value == "succeeded" else "Failed",
        causal_chain=causal_chain,
        confidence=causal_out.confidence,
        alternatives=alternatives,
        policy_tier=tier,
        approved_by=approved_by,
        recommendation_accepted=True,
        capability_invoked=SLICE_CAPABILITY,
        capability_status=response.status,
        estimated_cost_usd=SLICE_ESTIMATED_COST_USD,
    )
