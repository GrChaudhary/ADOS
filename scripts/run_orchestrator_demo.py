"""
Phase 3A demo: the same defect-to-recovery scenario as
scripts/run_demo_pipeline.py, but driven through the real
DecisionOrchestrator — event-driven agent sequencing, governance tier
assignment, a simulated human approval, and a real Integration Hub
capability call — instead of a hand-scripted sequence of agent.run() calls.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.eventbus import InMemoryEventBus
from integrations import default_hub
from orchestrate import DecisionOrchestrator, PriorityInputs


async def simulate_approver(orchestrator: DecisionOrchestrator, incident_id_holder: dict):
    """Polls for a pending approval and approves it — standing in for a
    human clicking "Approve" in the UI (docs/011-ui-ux.md)."""
    for _ in range(500):
        pending = orchestrator.approvals.list_pending()
        if pending:
            approval = pending[0]
            print(f"\n[APPROVER] Reviewing: {approval.summary}")
            print(f"[APPROVER] Policy tier: {approval.policy_tier.name} | Confidence: {approval.confidence}")
            orchestrator.approvals.approve(approval.incident_id, approved_by="ops-lead-demo")
            print("[APPROVER] Approved.\n")
            return
        await asyncio.sleep(0.01)


async def run_demo():
    print("=" * 80)
    print("      ADOS Phase 3A: Decision Orchestrator — Full Incident Lifecycle")
    print("=" * 80)

    bus = InMemoryEventBus()
    hub = default_hub()
    orchestrator = DecisionOrchestrator(event_bus=bus, integration_hub=hub)

    priority = PriorityInputs(
        safety_impact=0.9,
        customer_impact=0.6,
        line_down_cost_per_hour_usd=12_000,
        production_priority=0.7,
        is_systemic=False,
    )

    print("\n[INCIDENT] Starting run against Line 2 (FAC-P04-L2)...")
    run_task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id="FAC-P04-L2",
            line_id="Line 2",
            part_number="MH-8820",
            vision_data={"measured_bore_diameter_mm": 45.085},
            priority=priority,
        )
    )
    approver_task = asyncio.create_task(simulate_approver(orchestrator, {}))

    record = await run_task
    await approver_task

    print(f"[INCIDENT] ID: {record.incident_id}")
    print(f"[INCIDENT] Final state: {record.final_state}")
    print(f"[INCIDENT] Policy tier: {record.policy_tier.name} | Approved by: {record.approved_by}")
    print(f"[INCIDENT] Causal chain ({len(record.causal_chain)} candidates):")
    for entry in record.causal_chain:
        print(f"   - {entry.description} (weight={entry.weight})")
    print(f"[INCIDENT] Capability invoked: {record.capability_invoked} -> {record.capability_status}")
    print(f"[INCIDENT] Cost: ${record.actual_cost_usd} | Downtime: {record.actual_downtime_min} min")

    events = await bus.recent(incident_id=record.incident_id)

    completed = next((e for e in events if e.event_type == "CapabilityInvocationCompleted"), None)
    if completed:
        print(f"\n[EXECUTION CHECKLIST] {completed.payload['capability']} — {completed.payload['status'].upper()}")
        for step in completed.payload["executionSteps"]:
            mark = "[x]" if completed.payload["status"] == "succeeded" else "[ ]"
            print(f"   {mark} {step}")

    print(f"\n[EVENT BUS] {len(events)} events published for this incident:")
    for e in events:
        print(f"   {e.event_type:<16} produced_by={e.produced_by}")

    print("\n" + "=" * 80)
    print("      SUCCESS: Phase 3A orchestrated decision loop completed cleanly!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_demo())
