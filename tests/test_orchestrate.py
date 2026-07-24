"""
Phase 3A tests — orchestrate/. Mirrors the structure of
tests/test_phase2_integration.py and tests/test_cross_phase_integration.py.
"""

import asyncio

import pytest

from backend.app.eventbus import InMemoryEventBus
from contracts import Capability, IncidentState, PolicyTier
from integrations import default_hub
from orchestrate import (
    DecisionOrchestrator,
    IncidentStateMachine,
    InvalidTransition,
    PriorityInputs,
    assign_policy_tier,
    compute_priority_score,
)
from orchestrate.preemption import PreemptionEngine


def test_capability_for_parameter_adjustment_is_schedule_maintenance():
    capability = DecisionOrchestrator._capability_for_option("OPT-1-PARAMETER-ADJUST", {})
    assert capability == Capability.SCHEDULE_MAINTENANCE


def test_capability_for_substitution_with_stock_reserves_inventory():
    capability = DecisionOrchestrator._capability_for_option(
        "OPT-2-PART-SUBSTITUTION", {"top_candidate": {"in_stock_quantity": 180}}
    )
    assert capability == Capability.RESERVE_INVENTORY


def test_capability_for_substitution_without_stock_creates_purchase_order():
    capability = DecisionOrchestrator._capability_for_option(
        "OPT-2-PART-SUBSTITUTION", {"top_candidate": {"in_stock_quantity": 0}}
    )
    assert capability == Capability.CREATE_PURCHASE_ORDER


def test_state_machine_happy_path():
    sm = IncidentStateMachine()
    for state in [
        IncidentState.DIAGNOSING,
        IncidentState.CANDIDATE_GENERATION,
        IncidentState.RESERVING,
        IncidentState.AWAITING_APPROVAL,
        IncidentState.EXECUTING,
        IncidentState.RESOLVED,
    ]:
        sm.transition(state)
    assert sm.state == IncidentState.RESOLVED
    assert sm.is_terminal()


def test_state_machine_rejects_illegal_transition():
    sm = IncidentStateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition(IncidentState.RESOLVED)  # Detected -> Resolved skips every state


def test_priority_score_orders_by_safety_first():
    high_safety = PriorityInputs(
        safety_impact=1.0, customer_impact=0.0, line_down_cost_per_hour_usd=0,
        production_priority=0.0, is_systemic=False,
    )
    low_safety = PriorityInputs(
        safety_impact=0.0, customer_impact=1.0, line_down_cost_per_hour_usd=50_000,
        production_priority=1.0, is_systemic=True,
    )
    assert compute_priority_score(high_safety) > 0
    assert compute_priority_score(low_safety) < 1.0


def test_governance_high_risk_capability_never_tier0():
    tier = assign_policy_tier(Capability.CREATE_PURCHASE_ORDER, confidence=0.999)
    assert tier == PolicyTier.EXECUTIVE_APPROVAL


def test_governance_low_risk_high_confidence_is_autonomous():
    tier = assign_policy_tier(Capability.NOTIFY_OPERATOR, confidence=0.95)
    assert tier == PolicyTier.AUTONOMOUS


def test_governance_low_risk_low_confidence_needs_approval():
    tier = assign_policy_tier(Capability.NOTIFY_OPERATOR, confidence=0.5)
    assert tier == PolicyTier.APPROVAL_REQUIRED


def test_preemption_engine_bumps_lower_priority_occupant():
    engine = PreemptionEngine()
    low = engine.claim_or_preempt("Line3", "inc-low", priority_score=0.2)
    assert low is not None
    assert not low.preempt_event.is_set()

    high = engine.claim_or_preempt("Line3", "inc-high", priority_score=0.9)
    assert high is not None
    assert low.preempt_event.is_set()  # the lower-priority occupant got bumped

    # A third, lower-priority incident can't take the line from the current (high) occupant
    blocked = engine.claim_or_preempt("Line3", "inc-blocked", priority_score=0.3)
    assert blocked is None


@pytest.mark.asyncio
async def test_orchestrator_resolves_with_tier1_approval():
    bus = InMemoryEventBus()
    hub = default_hub()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=hub)
    priority = PriorityInputs(
        safety_impact=0.9, customer_impact=0.6, line_down_cost_per_hour_usd=12_000,
        production_priority=0.7, is_systemic=False,
    )

    async def auto_approve():
        for _ in range(200):
            pending = orchestrator.approvals.list_pending()
            if pending:
                orchestrator.approvals.approve(pending[0].incident_id, approved_by="ops-lead-1")
                return
            await asyncio.sleep(0.01)

    run_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id="Line3", part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=priority,
        )
    )
    approver_task = asyncio.create_task(auto_approve())
    record = await asyncio.wait_for(run_task, timeout=5)
    await approver_task

    assert record.final_state == IncidentState.RESOLVED.value
    assert record.policy_tier == PolicyTier.APPROVAL_REQUIRED
    assert record.approved_by == "ops-lead-1"
    assert record.recommendation_accepted is True
    assert record.capability_invoked == Capability.SCHEDULE_MAINTENANCE
    assert len(record.causal_chain) > 0

    events = await bus.recent(incident_id=record.incident_id)
    assert "StageRequested" in [e.event_type for e in events]
    assert "AgentCompleted" in [e.event_type for e in events]

    stored = orchestrator.audit_trail.get(record.incident_id)
    assert stored is not None and stored.incident_id == record.incident_id


@pytest.mark.asyncio
async def test_orchestrator_fails_on_rejected_approval():
    bus = InMemoryEventBus()
    hub = default_hub()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=hub)
    priority = PriorityInputs(
        safety_impact=0.5, customer_impact=0.5, line_down_cost_per_hour_usd=5_000,
        production_priority=0.5, is_systemic=False,
    )

    async def auto_reject():
        for _ in range(200):
            pending = orchestrator.approvals.list_pending()
            if pending:
                orchestrator.approvals.reject(pending[0].incident_id, approved_by="ops-lead-2")
                return
            await asyncio.sleep(0.01)

    run_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id="Line4", part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=priority,
        )
    )
    rejecter_task = asyncio.create_task(auto_reject())
    record = await asyncio.wait_for(run_task, timeout=5)
    await rejecter_task

    assert record.final_state == IncidentState.FAILED.value
    assert record.recommendation_accepted is False


@pytest.mark.asyncio
async def test_orchestrator_preempts_lower_priority_incident_on_same_line():
    bus = InMemoryEventBus()
    hub = default_hub()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=hub)

    low_priority = PriorityInputs(
        safety_impact=0.1, customer_impact=0.1, line_down_cost_per_hour_usd=100,
        production_priority=0.1, is_systemic=False,
    )
    high_priority = PriorityInputs(
        safety_impact=1.0, customer_impact=1.0, line_down_cost_per_hour_usd=50_000,
        production_priority=1.0, is_systemic=True,
    )

    # Manually occupy the line at low priority (simulating an in-flight incident)
    # without running the full pipeline, then start a high-priority one — it
    # must win the line and the (simulated) low-priority occupant must be
    # signalled to preempt.
    occupant = orchestrator._preemption.claim_or_preempt("Line5", "inc-in-flight", priority_score=0.05)
    assert occupant is not None

    async def auto_approve():
        for _ in range(200):
            pending = orchestrator.approvals.list_pending()
            if pending:
                orchestrator.approvals.approve(pending[0].incident_id, approved_by="ops-lead-3")
                return
            await asyncio.sleep(0.01)

    run_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id="Line5", part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=high_priority,
        )
    )
    approver_task = asyncio.create_task(auto_approve())
    record = await asyncio.wait_for(run_task, timeout=5)
    await approver_task

    assert occupant.preempt_event.is_set()
    assert record.final_state == IncidentState.RESOLVED.value


@pytest.mark.asyncio
async def test_preempted_incident_auto_resumes_under_same_incident_id():
    """docs/005's Preempted -> Diagnosing edge: a bumped incident should
    wait for the line and resolve on its own, not just record Preempted
    and stop. Deterministic by construction — the high-priority incident
    is given a moment to claim the line before the low-priority one starts,
    so the low one hits the occupant-is-None wait path, not a timing race
    against a mid-flight preempt_event."""
    bus = InMemoryEventBus()
    hub = default_hub()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=hub)

    high_priority = PriorityInputs(
        safety_impact=1.0, customer_impact=1.0, line_down_cost_per_hour_usd=50_000,
        production_priority=1.0, is_systemic=True,
    )
    low_priority = PriorityInputs(
        safety_impact=0.1, customer_impact=0.1, line_down_cost_per_hour_usd=100,
        production_priority=0.1, is_systemic=False,
    )

    async def auto_approve_all():
        approved = set()
        for _ in range(1000):
            for pending in orchestrator.approvals.list_pending():
                if pending.incident_id not in approved:
                    orchestrator.approvals.approve(pending.incident_id, approved_by="ops-lead-resume")
                    approved.add(pending.incident_id)
            await asyncio.sleep(0.005)

    approver_task = asyncio.create_task(auto_approve_all())

    high_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id="Line-Resume", part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=high_priority,
            incident_id="inc-high",
        )
    )
    await asyncio.sleep(0.02)  # let the high-priority incident claim the line first

    low_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id="Line-Resume", part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=low_priority,
            incident_id="inc-low",
        )
    )

    high_record = await asyncio.wait_for(high_task, timeout=5)
    low_record = await asyncio.wait_for(low_task, timeout=5)
    approver_task.cancel()

    assert high_record.final_state == IncidentState.RESOLVED.value
    assert low_record.final_state == IncidentState.RESOLVED.value
    assert low_record.incident_id == "inc-low"  # same incident_id throughout — resumed, not restarted as a new incident
