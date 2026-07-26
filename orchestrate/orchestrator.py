"""
Decision Orchestrator — docs/005-decision-orchestrator.md. Ties the state
machine, priority/preemption, the Phase 2 agent roster (via AgentRunner),
governance tier assignment + human approval, and the Integration Hub into
the full incident lifecycle: Detected -> Diagnosing -> CandidateGeneration
-> Reserving -> AwaitingApproval -> Executing -> Resolved, with Failed/
Escalated/Preempted branches.

Stage-to-state mapping (Phase 2's agents were built with their own
"stage_name" labels — Perception/Reasoning/CandidateGeneration/Evaluation/
Execution/Learning — from docs/004-agent-framework.md's roster table,
which is a finer grain than this module's five working states):
  Diagnosing            -> vision_spec, cad_spec, causal_isolation
  CandidateGeneration   -> substitution, parameter_adjustment, impact_simulation
  Reserving             -> rerouting (soft-reserves via the Digital Twin)
  AwaitingApproval/Executing -> governance decision, then a real
                                Integration Hub capability call
  (Resolved)            -> feedback_calibration (Learning), then finalize

Capability selection is option-aware (`_capability_for_option`): a
parameter-adjustment recommendation schedules maintenance, a substitution
recommendation reserves existing stock if the Substitution Agent found
enough on hand or creates a purchase order otherwise. See
`_capability_for_option`'s docstring for what's still a simplification.

Preemption auto-resumes: a bumped incident waits for its line to free,
then restarts diagnosis (docs/005's Preempted -> Diagnosing edge) under
the same incident_id, up to `max_resume_attempts` times before settling
as Preempted for good. See run_incident's docstring.
"""

from typing import Optional

from agents.sdk import IncidentContext, StageInput
from contracts import (
    CallStatus,
    Capability,
    CapabilityCall,
    CausalChainEntry,
    EventEnvelope,
    GovernanceInfo,
    IncidentRecord,
    IncidentState,
    PolicyTier,
)
from knowledge import CausalGraph, DigitalTwinStore, KnowledgeGraph

from backend.app.eventbus import EventBus
from integrations import IntegrationHub

from .agent_runner import AgentRunner
from .audit_trail import AuditTrail
from .governance import ApprovalQueue, PendingApproval, assign_policy_tier
from .preemption import PreemptionEngine
from .priority import PriorityInputs, compute_priority_score
from .state_machine import IncidentStateMachine


class DecisionOrchestrator:
    def __init__(
        self,
        event_bus: EventBus,
        integration_hub: IntegrationHub,
        knowledge_graph: Optional[KnowledgeGraph] = None,
        causal_graph: Optional[CausalGraph] = None,
        digital_twin: Optional[DigitalTwinStore] = None,
    ):
        self._bus = event_bus
        self._hub = integration_hub
        self.knowledge_graph = knowledge_graph or KnowledgeGraph(seed=True)
        self.causal_graph = causal_graph or CausalGraph(seed=True)
        self.digital_twin = digital_twin or DigitalTwinStore()
        self._runner = AgentRunner(
            event_bus, self.knowledge_graph, self.causal_graph, self.digital_twin
        )
        self.audit_trail = AuditTrail()
        self.approvals = ApprovalQueue()
        self._preemption = PreemptionEngine()

    async def run_incident(
        self,
        plant_id: str,
        line_id: str,
        part_number: str,
        vision_data: dict,
        priority: PriorityInputs,
        incident_id: Optional[str] = None,
        max_resume_attempts: int = 5,
    ) -> IncidentRecord:
        """Runs one incident to a terminal state (Resolved/Failed), or to
        Preempted if it's bumped by a higher-priority incident on the same
        line `max_resume_attempts` times in a row. Preemption auto-resumes
        (docs/005-decision-orchestrator.md's Preempted -> Diagnosing edge):
        the same incident_id waits for the line to free, then restarts
        diagnosis from scratch — it does not pick up mid-stage."""
        context_kwargs = {"plant_id": plant_id, "line_id": line_id}
        if incident_id is not None:
            context_kwargs["incident_id"] = incident_id
        context = IncidentContext(**context_kwargs)
        sm = IncidentStateMachine()
        priority_score = compute_priority_score(priority)
        causal_chain = []

        for _attempt in range(max_resume_attempts):
            occupant = self._preemption.claim_or_preempt(line_id, context.incident_id, priority_score)
            if occupant is None:
                # A higher-or-equal-priority incident already holds this
                # line. Wait for it to free, then retry the claim — this is
                # the "resumed" leg for an incident that never even got to
                # start diagnosing.
                await self._preemption.wait_for_line_free(line_id)
                continue

            try:
                sm.transition(IncidentState.DIAGNOSING)
                if occupant.preempt_event.is_set():
                    sm.transition(IncidentState.PREEMPTED)
                    await self._preemption.wait_for_line_free(line_id)
                    continue

                out1, _ = await self._runner.run_stage(
                    "vision_spec",
                    context,
                    StageInput(stage_name="Perception", payload={"vision_data": vision_data}),
                )
                out2, _ = await self._runner.run_stage(
                    "cad_spec",
                    context,
                    StageInput(
                        stage_name="Reasoning",
                        payload={"part_number": part_number, "measured_value": out1.result["measured_value"]},
                    ),
                )
                out3, _ = await self._runner.run_stage(
                    "causal_isolation",
                    context,
                    StageInput(stage_name="Reasoning", payload={"defect_type": out1.result["defect_type"]}),
                )
                causal_chain = [
                    CausalChainEntry(
                        condition_id=rc["condition_id"],
                        description=rc["name"],
                        weight=rc["weight"],
                        evidence_path=rc["evidence_path"],
                    )
                    for rc in out3.result["ranked_causes"]
                ]

                if occupant.preempt_event.is_set():
                    sm.transition(IncidentState.PREEMPTED)
                    await self._preemption.wait_for_line_free(line_id)
                    continue

                sm.transition(IncidentState.CANDIDATE_GENERATION)
                out4a, _ = await self._runner.run_stage(
                    "substitution",
                    context,
                    StageInput(stage_name="CandidateGeneration", payload={"part_number": part_number}),
                )
                await self._runner.run_stage(
                    "parameter_adjustment",
                    context,
                    StageInput(stage_name="CandidateGeneration", payload={"deviation_mm": out1.result["deviation_mm"]}),
                )
                out5, _ = await self._runner.run_stage(
                    "impact_simulation", context, StageInput(stage_name="Evaluation", payload={})
                )
                top_opt = out5.result["top_recommendation"]

                if occupant.preempt_event.is_set():
                    sm.transition(IncidentState.PREEMPTED)
                    await self._preemption.wait_for_line_free(line_id)
                    continue

                sm.transition(IncidentState.RESERVING)
                out6, _ = await self._runner.run_stage(
                    "rerouting",
                    context,
                    StageInput(stage_name="Execution", payload={"selected_option": top_opt["option_id"]}),
                )

                if occupant.preempt_event.is_set():
                    sm.transition(IncidentState.PREEMPTED)
                    await self._preemption.wait_for_line_free(line_id)
                    continue

                sm.transition(IncidentState.AWAITING_APPROVAL)
                capability = self._capability_for_option(top_opt["option_id"], out4a.result)
                tier = assign_policy_tier(capability, out5.confidence, top_opt["estimated_cost_usd"])
                approved_by: Optional[str] = None
                recommendation_accepted: Optional[bool] = None

                if tier != PolicyTier.AUTONOMOUS:
                    if tier == PolicyTier.EXECUTIVE_APPROVAL:
                        sm.transition(IncidentState.ESCALATED)
                        sm.transition(IncidentState.AWAITING_APPROVAL)

                    summary = f"{top_opt['name']} (${top_opt['estimated_cost_usd']}, {top_opt['downtime_minutes']}min)"
                    approval = self.approvals.enqueue(
                        PendingApproval(
                            incident_id=context.incident_id,
                            capability=capability,
                            policy_tier=tier,
                            confidence=out5.confidence,
                            summary=summary,
                        )
                    )
                    decision = await approval.wait()
                    approved_by = approval.approved_by

                    if decision == "escalated":
                        sm.transition(IncidentState.ESCALATED)
                        sm.transition(IncidentState.AWAITING_APPROVAL)
                        approval2 = self.approvals.enqueue(
                            PendingApproval(
                                incident_id=context.incident_id,
                                capability=capability,
                                policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
                                confidence=out5.confidence,
                                summary=summary,
                            )
                        )
                        decision = await approval2.wait()
                        approved_by = approval2.approved_by

                    if decision != "approved":
                        sm.transition(IncidentState.FAILED)
                        return self._finalize(
                            context,
                            sm,
                            confidence=out5.confidence,
                            causal_chain=causal_chain,
                            policy_tier=tier,
                            approved_by=approved_by,
                            recommendation_accepted=False,
                            capability_invoked=capability,
                            estimated_cost_usd=top_opt["estimated_cost_usd"],
                            estimated_downtime_min=top_opt["downtime_minutes"],
                            alternatives=out5.result["ranked_options"],
                        )
                    recommendation_accepted = True

                sm.transition(IncidentState.EXECUTING)
                execution_steps = out6.result["execution_steps"]
                target_line_id = out6.result["target_line_id"]

                await self._bus.publish(EventEnvelope(
                    event_type="CapabilityInvocationStarted",
                    incident_id=context.incident_id,
                    produced_by="orchestrate/decision-orchestrator",
                    payload={
                        "capability": capability.value,
                        "executionSteps": execution_steps,
                        "targetLineId": target_line_id,
                    },
                ))

                call = CapabilityCall(
                    capability=capability,
                    incident_id=context.incident_id,
                    requested_by="orchestrate/decision-orchestrator",
                    input={
                        "execution_steps": execution_steps,
                        "target_line_id": target_line_id,
                    },
                    governance=GovernanceInfo(policy_tier=tier, approved_by=approved_by),
                )
                response = await self._hub.invoke(call)

                await self._bus.publish(EventEnvelope(
                    event_type="CapabilityInvocationCompleted",
                    incident_id=context.incident_id,
                    produced_by="orchestrate/decision-orchestrator",
                    payload={
                        "capability": capability.value,
                        "status": response.status.value,
                        "executionSteps": execution_steps,
                        "targetLineId": target_line_id,
                    },
                ))

                if response.status != CallStatus.SUCCEEDED:
                    sm.transition(IncidentState.FAILED)
                    return self._finalize(
                        context,
                        sm,
                        confidence=out5.confidence,
                        causal_chain=causal_chain,
                        policy_tier=tier,
                        approved_by=approved_by,
                        recommendation_accepted=recommendation_accepted,
                        capability_invoked=capability,
                        capability_status=response.status,
                        estimated_cost_usd=top_opt["estimated_cost_usd"],
                        estimated_downtime_min=top_opt["downtime_minutes"],
                        alternatives=out5.result["ranked_options"],
                    )

                await self._runner.run_stage(
                    "feedback_calibration",
                    context,
                    StageInput(
                        stage_name="Learning",
                        payload={
                            "condition_id": out3.result["primary_condition_id"],
                            "outcome_id": "OUT-DIMENSIONAL-FAULT",
                            "outcome_verified": True,
                        },
                    ),
                )

                sm.transition(IncidentState.RESOLVED)
                return self._finalize(
                    context,
                    sm,
                    confidence=out5.confidence,
                    causal_chain=causal_chain,
                    policy_tier=tier,
                    approved_by=approved_by,
                    recommendation_accepted=recommendation_accepted,
                    capability_invoked=capability,
                    capability_status=response.status,
                    estimated_cost_usd=top_opt["estimated_cost_usd"],
                    estimated_downtime_min=top_opt["downtime_minutes"],
                    actual_cost_usd=top_opt["estimated_cost_usd"],
                    actual_downtime_min=top_opt["downtime_minutes"],
                    alternatives=out5.result["ranked_options"],
                )
            finally:
                self._preemption.release(line_id, context.incident_id)

        # Bumped max_resume_attempts times in a row — settle as Preempted
        # rather than retrying forever.
        return self._finalize(
            context, sm, confidence=0.0, causal_chain=causal_chain, policy_tier=PolicyTier.AUTONOMOUS
        )

    @staticmethod
    def _capability_for_option(option_id: str, substitution_result: dict) -> Capability:
        """Maps the Impact Simulation Agent's chosen option to the
        capability that actually carries it out, instead of always
        Capability.SCHEDULE_MAINTENANCE. Still simplified: a real system
        would also weigh re-routing (Capability.CREATE_CHANGE_REQUEST for
        a cross-plant move) and would look at requested quantity vs.
        in_stock_quantity rather than a bare "any stock at all" check —
        both are reasonable follow-ups, not guessed at here.
        """
        if option_id == "OPT-2-PART-SUBSTITUTION":
            top_candidate = substitution_result.get("top_candidate") or {}
            if top_candidate.get("in_stock_quantity", 0) > 0:
                return Capability.RESERVE_INVENTORY
            return Capability.CREATE_PURCHASE_ORDER
        return Capability.SCHEDULE_MAINTENANCE  # OPT-1-PARAMETER-ADJUST and unrecognized options

    def _finalize(self, context: IncidentContext, sm: IncidentStateMachine, **kwargs) -> IncidentRecord:
        detected_at = sm.history[0][1]
        resolved_at = sm.history[-1][1] if sm.is_terminal() or sm.state == IncidentState.PREEMPTED else None
        record = IncidentRecord(
            incident_id=context.incident_id,
            plant_id=context.plant_id,
            line_id=context.line_id,
            detected_at=detected_at,
            resolved_at=resolved_at,
            final_state=sm.state.value,
            **kwargs,
        )
        self.audit_trail.append(record)
        return record
