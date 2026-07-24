"""
Proves executive/ (Phase 3B) works over IncidentRecords the real
DecisionOrchestrator (Phase 3A) produces, not just executive/seed_data.py's
fixtures. Same role as test_cross_phase_integration.py played for
Phase 1/2: two independently-built halves, checked against each other
rather than each side's own tests in isolation.
"""

import asyncio

import pytest

from backend.app.eventbus import InMemoryEventBus
from executive import KPIEngine, RecommendationEngine
from integrations import default_hub
from orchestrate import DecisionOrchestrator, PriorityInputs


async def _run_one_incident(orchestrator: DecisionOrchestrator, line_id: str):
    priority = PriorityInputs(
        safety_impact=0.9, customer_impact=0.6, line_down_cost_per_hour_usd=12_000,
        production_priority=0.7, is_systemic=False,
    )

    async def auto_approve():
        for _ in range(200):
            pending = orchestrator.approvals.list_pending()
            if pending:
                orchestrator.approvals.approve(pending[0].incident_id, approved_by="ops-lead-test")
                return
            await asyncio.sleep(0.01)

    run_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P1", line_id=line_id, part_number="P-1002",
            vision_data={"measured_bore_diameter_mm": 45.085}, priority=priority,
        )
    )
    approver_task = asyncio.create_task(auto_approve())
    record = await asyncio.wait_for(run_task, timeout=5)
    await approver_task
    return record


@pytest.mark.asyncio
async def test_kpi_engine_computes_over_real_orchestrator_output():
    orchestrator = DecisionOrchestrator(event_bus=InMemoryEventBus(), integration_hub=default_hub())
    await _run_one_incident(orchestrator, "Line-X1")
    await _run_one_incident(orchestrator, "Line-X2")

    real_records = orchestrator.audit_trail.all()
    assert len(real_records) == 2

    # Explicitly pass real records — KPIEngine(records=None) would silently
    # fall back to executive/seed_data.py's fixtures, which is exactly the
    # gap this test exists to close.
    kpis = KPIEngine(records=real_records).compute_kpis()

    assert kpis.total_incidents == 2
    assert kpis.resolved_incidents == 2
    assert kpis.mttr_avg_minutes >= 0
    # Both incidents in this scenario are Tier 1 (see orchestrate/governance.py's
    # confidence thresholds for Capability.SCHEDULE_MAINTENANCE at ~0.89 confidence)
    assert kpis.tier_distribution["Tier 1 (Approval)"] == 2


@pytest.mark.asyncio
async def test_recommendation_engine_reasons_over_real_orchestrator_output():
    orchestrator = DecisionOrchestrator(event_bus=InMemoryEventBus(), integration_hub=default_hub())
    await _run_one_incident(orchestrator, "Line-X3")

    real_records = orchestrator.audit_trail.all()
    engine = RecommendationEngine(
        records=real_records,
        knowledge_graph=orchestrator.knowledge_graph,
        causal_graph=orchestrator.causal_graph,
    )
    # Doesn't assert specific recommendations fire (one incident is a thin
    # signal) — asserts it runs cleanly over live data with no schema
    # mismatch between what orchestrate/ produces and what executive/ expects.
    recommendations = engine.generate_strategic_recommendations()
    assert isinstance(recommendations, list)
