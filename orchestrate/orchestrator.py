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

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agents.sdk import IncidentContext, StageInput
from contracts import (
    AgentCompletedPayload,
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
from knowledge.cloudant_client import cloudant_db
from knowledge.tts_client import tts_client

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
        seed_records: Optional[List[IncidentRecord]] = None,
    ):
        self._bus = event_bus
        self._hub = integration_hub
        self.knowledge_graph = knowledge_graph or KnowledgeGraph(seed=True)
        self.causal_graph = causal_graph or CausalGraph(seed=True)
        self.digital_twin = digital_twin or DigitalTwinStore()
        self._runner = AgentRunner(
            event_bus, self.knowledge_graph, self.causal_graph, self.digital_twin
        )
        # seed_records is demo/historical data only (executive/seed_data.py,
        # main.py's lifespan) - real Cloudant-backed incidents load
        # separately via hydrate_from_cloudant(), additively (different
        # incident_id namespace), not instead of this.
        self.audit_trail = AuditTrail(seed_records=seed_records)
        self.approvals = ApprovalQueue()
        self._preemption = PreemptionEngine()
        # IBM Watson TTS incident briefings — opt-in (TTS_INCIDENT_BRIEFING_ENABLED,
        # .env.example) and in-memory only, keyed by incident_id. Not
        # persisted to Cloudant: audio bytes in a JSON doc would bloat
        # storage, and briefings are cheap to regenerate on demand.
        self._audio_briefings: Dict[str, bytes] = {}

    def get_audio_briefing(self, incident_id: str) -> Optional[bytes]:
        return self._audio_briefings.get(incident_id)

    async def resume_pending_approvals(self) -> int:
        """Reconstitutes a PendingApproval for every incident left sitting
        at AwaitingApproval when the process last stopped, so
        /incidents/{id}/approve doesn't 404 just because a restart happened
        mid-decision. Call once at startup, after audit_trail has already
        been hydrated from Cloudant (backend/app/main.py's lifespan) — this
        reads from that in-memory collection rather than querying Cloudant
        again itself. Each reconstituted approval carries resume_context
        instead of a live run_incident() coroutine; resume_after_decision()
        is what actually acts on it once a human decides. Returns how many
        were reconstituted."""
        count = 0
        for record in self.audit_trail.all():
            if record.final_state != "AwaitingApproval":
                continue
            if self.approvals.get(record.incident_id) is not None:
                continue
            if not record.capability_invoked or not record.execution_steps or not record.target_line_id:
                # Snapshot predates execution_steps/target_line_id being
                # saved, or never reached a clean AwaitingApproval snapshot.
                # Nothing safe to resume — stays orphaned rather than
                # guessing at what to dispatch.
                continue

            top_option = next(
                (o for o in record.alternatives if o.get("recommendation") == "TOP_PICK"),
                record.alternatives[0] if record.alternatives else {},
            )
            primary_condition_id = record.causal_chain[0].condition_id if record.causal_chain else None

            self.approvals.enqueue(
                PendingApproval(
                    incident_id=record.incident_id,
                    capability=record.capability_invoked,
                    policy_tier=record.policy_tier,
                    confidence=record.confidence,
                    summary=(
                        f"{top_option.get('name', 'Recommended option')} "
                        f"(${record.estimated_cost_usd}, {record.estimated_downtime_min}min) "
                        f"— recovered after a backend restart"
                    ),
                    estimated_cost_usd=record.estimated_cost_usd or 0.0,
                    resume_context={
                        "plant_id": record.plant_id,
                        "line_id": record.line_id,
                        "detected_at": record.detected_at,
                        "causal_chain": record.causal_chain,
                        "confidence": record.confidence,
                        "alternatives": record.alternatives,
                        "chosen_opt": top_option,
                        "execution_steps": record.execution_steps,
                        "target_line_id": record.target_line_id,
                        "primary_condition_id": primary_condition_id,
                    },
                )
            )
            count += 1
        return count

    async def resume_after_decision(self, pending: PendingApproval) -> Optional[IncidentRecord]:
        """Carries out a decision made on a restart-reconstituted
        PendingApproval (pending.resume_context is not None). There's no
        live run_incident() coroutine behind these to react to
        approval.resolve() the way the normal flow does, so
        backend/app/routers/incidents.py's _decide() calls this directly
        instead. Mirrors run_incident's post-approval tail, but builds the
        IncidentRecord straight from the saved snapshot rather than a live
        IncidentStateMachine — that object doesn't survive a restart either.
        Deliberately does not re-run diagnosis/candidate-generation stages:
        dispatches exactly what was already proposed (see IncidentRecord's
        execution_steps/target_line_id docstring)."""
        ctx = pending.resume_context
        if ctx is None or pending.decision is None:
            return None

        if pending.decision == "escalated":
            # Mirrors run_incident's live escalation path (a second,
            # Tier 2 PendingApproval) rather than finalizing anything —
            # nothing to execute yet until *that* one is also decided.
            self.approvals.enqueue(
                PendingApproval(
                    incident_id=pending.incident_id,
                    capability=pending.capability,
                    policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
                    confidence=pending.confidence,
                    summary=pending.summary,
                    estimated_cost_usd=pending.estimated_cost_usd,
                    resume_context=ctx,
                )
            )
            return None

        base_kwargs = dict(
            incident_id=pending.incident_id,
            plant_id=ctx["plant_id"],
            line_id=ctx["line_id"],
            detected_at=ctx["detected_at"],
            causal_chain=ctx["causal_chain"],
            confidence=ctx["confidence"],
            alternatives=ctx["alternatives"],
            policy_tier=pending.policy_tier,
            approved_by=pending.approved_by,
            capability_invoked=pending.capability,
            estimated_cost_usd=pending.estimated_cost_usd,
            estimated_downtime_min=ctx["chosen_opt"].get("downtime_minutes"),
        )

        if pending.decision != "approved":
            record = IncidentRecord(
                resolved_at=datetime.now(timezone.utc).isoformat(),
                final_state="Failed",
                recommendation_accepted=False,
                **base_kwargs,
            )
            return await self.audit_trail.append(record)

        self.digital_twin.set_status(ctx["line_id"], "DEGRADED")

        await self._bus.publish(EventEnvelope(
            event_type="CapabilityInvocationStarted",
            incident_id=pending.incident_id,
            produced_by="orchestrate/decision-orchestrator",
            payload={
                "capability": pending.capability.value,
                "executionSteps": ctx["execution_steps"],
                "targetLineId": ctx["target_line_id"],
            },
        ))

        call = CapabilityCall(
            capability=pending.capability,
            incident_id=pending.incident_id,
            requested_by="orchestrate/decision-orchestrator",
            input={"execution_steps": ctx["execution_steps"], "target_line_id": ctx["target_line_id"]},
            governance=GovernanceInfo(policy_tier=pending.policy_tier, approved_by=pending.approved_by),
        )
        response = await self._hub.invoke(call)

        await self._bus.publish(EventEnvelope(
            event_type="CapabilityInvocationCompleted",
            incident_id=pending.incident_id,
            produced_by="orchestrate/decision-orchestrator",
            payload={
                "capability": pending.capability.value,
                "status": response.status.value,
                "executionSteps": ctx["execution_steps"],
                "targetLineId": ctx["target_line_id"],
                "connector": response.connector,
                "output": response.output,
                "error": response.error,
            },
        ))

        self.digital_twin.set_status(ctx["line_id"], "OPERATIONAL")

        if response.status != CallStatus.SUCCEEDED:
            record = IncidentRecord(
                resolved_at=datetime.now(timezone.utc).isoformat(),
                final_state="Failed",
                recommendation_accepted=True,
                capability_status=response.status,
                **base_kwargs,
            )
            return await self.audit_trail.append(record)

        if ctx.get("primary_condition_id"):
            await self._runner.run_stage(
                "feedback_calibration",
                IncidentContext(
                    incident_id=pending.incident_id,
                    plant_id=ctx["plant_id"],
                    line_id=ctx["line_id"],
                ),
                StageInput(
                    stage_name="Learning",
                    payload={
                        "condition_id": ctx["primary_condition_id"],
                        "outcome_id": "OUT-DIMENSIONAL-FAULT",
                        "outcome_verified": True,
                    },
                ),
            )

        record = IncidentRecord(
            resolved_at=datetime.now(timezone.utc).isoformat(),
            final_state="Resolved",
            recommendation_accepted=True,
            capability_status=response.status,
            actual_cost_usd=pending.estimated_cost_usd,
            actual_downtime_min=ctx["chosen_opt"].get("downtime_minutes"),
            **base_kwargs,
        )
        return await self.audit_trail.append(record)

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
        context_kwargs = {"plant_id": plant_id, "line_id": line_id, "part_number": part_number}
        if incident_id is not None:
            context_kwargs["incident_id"] = incident_id
        context = IncidentContext(**context_kwargs)
        self.digital_twin.set_status(line_id, "DEGRADED")
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
                    StageInput(stage_name="Perception", payload={"vision_data": vision_data, "part_number": part_number}),
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
                    "impact_simulation",
                    context,
                    StageInput(stage_name="Evaluation", payload={"substitution_result": out4a.result}),
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
                    StageInput(
                        stage_name="Execution",
                        payload={
                            "selected_option": top_opt["option_id"],
                            "substitute_part_number": (out4a.result.get("top_candidate") or {}).get("target_part_number"),
                        },
                    ),
                )

                if occupant.preempt_event.is_set():
                    sm.transition(IncidentState.PREEMPTED)
                    await self._preemption.wait_for_line_free(line_id)
                    continue

                sm.transition(IncidentState.AWAITING_APPROVAL)
                capability = self._capability_for_option(top_opt["option_id"], out4a.result)
                tier = assign_policy_tier(capability, out5.confidence, top_opt["estimated_cost_usd"])
                chosen_opt = top_opt
                approved_by: Optional[str] = None
                recommendation_accepted: Optional[bool] = True

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
                            estimated_cost_usd=top_opt["estimated_cost_usd"],
                        )
                    )
                    await self._snapshot_pending(
                        context,
                        sm,
                        confidence=out5.confidence,
                        causal_chain=causal_chain,
                        policy_tier=tier,
                        capability_invoked=capability,
                        estimated_cost_usd=top_opt["estimated_cost_usd"],
                        estimated_downtime_min=top_opt["downtime_minutes"],
                        alternatives=out5.result["ranked_options"],
                        # So a restart that loses this coroutine can still
                        # dispatch exactly what was proposed —
                        # resume_pending_approvals()/resume_after_decision()
                        # below.
                        execution_steps=out6.result["execution_steps"],
                        target_line_id=out6.result["target_line_id"],
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
                                estimated_cost_usd=top_opt["estimated_cost_usd"],
                            )
                        )
                        decision = await approval2.wait()
                        approved_by = approval2.approved_by

                    if decision != "approved":
                        sm.transition(IncidentState.FAILED)
                        return await self._finalize(
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

                    # Dynamic Option Selection resolution
                    selected_id = getattr(approval2 if decision == "escalated" else approval, "selected_option_id", None)
                    if selected_id:
                        for opt in out5.result["ranked_options"]:
                            if opt["option_id"] == selected_id:
                                chosen_opt = opt
                                break

                    recommendation_accepted = (chosen_opt["option_id"] == top_opt["option_id"])
                    capability = self._capability_for_option(chosen_opt["option_id"], out4a.result)

                    # Re-run rerouting for selected option if different from pre-calculated default
                    if chosen_opt["option_id"] != top_opt["option_id"]:
                        out6, _ = await self._runner.run_stage(
                            "rerouting",
                            context,
                            StageInput(
                                stage_name="Execution",
                                payload={
                                    "selected_option": chosen_opt["option_id"],
                                    "substitute_part_number": (out4a.result.get("top_candidate") or {}).get("target_part_number"),
                                },
                            ),
                        )

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
                execution_started_at = time.time()
                response = await self._hub.invoke(call)
                execution_time_ms = round((time.time() - execution_started_at) * 1000, 2)

                await self._bus.publish(EventEnvelope(
                    event_type="CapabilityInvocationCompleted",
                    incident_id=context.incident_id,
                    produced_by="orchestrate/decision-orchestrator",
                    payload={
                        "capability": capability.value,
                        "status": response.status.value,
                        "executionSteps": execution_steps,
                        "targetLineId": target_line_id,
                        "connector": response.connector,
                        "output": response.output,
                        "error": response.error,
                    },
                ))

                # Also represents this connector's work as an AgentCompleted
                # event, same shape agents/sdk/base.py's BaseAgent.run()
                # produces for the 8 Phase 2 reasoning agents - so the
                # watsonx-itsm-agent registry entry (backend/app/routers/
                # agents_registry.py) shows real invocation stats/lineage on
                # frontend-next/src/app/agents/network/page.tsx's Live Swarm
                # tab instead of always reading 0. Scoped to the one connector
                # that has a matching registry entry today; extend this
                # mapping if/when other connectors (SAP, marketplace) get one.
                if response.connector == "watsonx_itsm":
                    await self._bus.publish(EventEnvelope(
                        event_type="AgentCompleted",
                        incident_id=context.incident_id,
                        produced_by="agents/watsonx-itsm-agent",
                        schema_version="1.0.0",
                        payload=AgentCompletedPayload(
                            agent_id="watsonx-itsm-agent",
                            stage_name="Execution",
                            execution_time_ms=execution_time_ms,
                            confidence=out5.confidence,
                            result={"capability": capability.value, **response.output},
                            evidence=[],
                            alternatives=[],
                        ).model_dump(by_alias=True),
                    ))

                if response.status != CallStatus.SUCCEEDED:
                    sm.transition(IncidentState.FAILED)
                    return await self._finalize(
                        context,
                        sm,
                        confidence=out5.confidence,
                        causal_chain=causal_chain,
                        policy_tier=tier,
                        approved_by=approved_by,
                        recommendation_accepted=recommendation_accepted,
                        capability_invoked=capability,
                        capability_status=response.status,
                        estimated_cost_usd=chosen_opt["estimated_cost_usd"],
                        estimated_downtime_min=chosen_opt["downtime_minutes"],
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
                return await self._finalize(
                    context,
                    sm,
                    confidence=out5.confidence,
                    causal_chain=causal_chain,
                    policy_tier=tier,
                    approved_by=approved_by,
                    recommendation_accepted=recommendation_accepted,
                    capability_invoked=capability,
                    capability_status=response.status,
                    estimated_cost_usd=chosen_opt["estimated_cost_usd"],
                    estimated_downtime_min=chosen_opt["downtime_minutes"],
                    actual_cost_usd=chosen_opt["estimated_cost_usd"],
                    actual_downtime_min=chosen_opt["downtime_minutes"],
                    alternatives=out5.result["ranked_options"],
                )
            finally:
                self._preemption.release(line_id, context.incident_id)

        # Bumped max_resume_attempts times in a row — settle as Preempted
        # rather than retrying forever.
        return await self._finalize(
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

    async def _snapshot_pending(self, context: IncidentContext, sm: IncidentStateMachine, **kwargs) -> None:
        """Best-effort Cloudant write while an incident sits at
        AwaitingApproval, so a backend restart doesn't strand it as an
        unrecoverable 404 (previously only _finalize wrote through to
        Cloudant, so anything still mid-pipeline at restart time vanished
        with the in-memory audit_trail/approvals/event_bus state). Purely
        additive: GET /incidents/{id} already falls back to Cloudant when
        the in-memory lookup misses (backend/app/routers/incidents.py), so
        this just gives that fallback something real to find. It's
        read-only after a restart — there's no live PendingApproval to
        resume, so /incidents/{id}/approve still 404s honestly rather than
        pretending to resume mid-flight orchestration."""
        if not cloudant_db.is_configured():
            return
        detected_at = sm.history[0][1]
        record = IncidentRecord(
            incident_id=context.incident_id,
            plant_id=context.plant_id,
            line_id=context.line_id,
            detected_at=detected_at,
            resolved_at=None,
            final_state="AwaitingApproval",
            **kwargs,
        )
        try:
            await asyncio.to_thread(cloudant_db.save_incident, record.model_dump(by_alias=True))
        except Exception as e:
            print(f"[DecisionOrchestrator] Cloudant pending-snapshot write failed for {context.incident_id}: {e}")

    async def _finalize(self, context: IncidentContext, sm: IncidentStateMachine, **kwargs) -> IncidentRecord:
        self.digital_twin.set_status(context.line_id, "OPERATIONAL")
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
        if os.environ.get("TTS_INCIDENT_BRIEFING_ENABLED") == "true" and tts_client.is_configured():
            tts_result = tts_client.synthesize(self._build_briefing_text(record))
            if tts_result.get("status") == "live":
                self._audio_briefings[record.incident_id] = tts_result["audio_bytes"]

        await self.audit_trail.append(record)
        return record

    @staticmethod
    def _build_briefing_text(record: IncidentRecord) -> str:
        """Plain-language spoken summary for the TTS incident briefing —
        deliberately built from IncidentRecord fields only, no invented
        detail, so the audio never says more than the record supports."""
        cause = record.causal_chain[0].description if record.causal_chain else None
        parts = [f"Incident on {record.line_id} at {record.plant_id}: {record.final_state}."]
        if cause:
            parts.append(f"Root cause: {cause}.")
        if record.capability_invoked:
            parts.append(f"Action taken: {record.capability_invoked.value}.")
        parts.append(f"Decision confidence: {round(record.confidence * 100)} percent.")
        return " ".join(parts)
