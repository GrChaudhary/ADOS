"""
orchestrate_langgraph/ evaluation tests — mirrors tests/test_orchestrate.py's
two most relevant scenarios (Tier 1 resolve, Tier 1 reject) against the
LangGraph slice, plus a cross-engine equivalence test asserting the
LangGraph graph and the hand-rolled baseline_slice.py produce identical
decisions for the same input. See orchestrate_langgraph/COMPARISON.md for
the full evaluation this feeds.

conftest.py's autouse fixture already forces
local_llm_client.is_configured() == False for every test in this repo, so
CausalIsolationAgent's rule-based fallback path runs deterministically here
too — no new gating code needed.
"""

import asyncio

import pytest

from contracts import Capability, PolicyTier
from orchestrate.governance import ApprovalQueue
from orchestrate_langgraph.baseline_slice import run_incident_baseline
from orchestrate_langgraph.graph import resume_incident_langgraph, run_incident_langgraph
from orchestrate_langgraph.scenario_defaults import SCENARIO


@pytest.mark.asyncio
async def test_langgraph_resolves_with_tier1_approval():
    record, graph, config = await run_incident_langgraph(**SCENARIO, incident_id="lg-tier1-resolve-1")

    # Structural difference from the custom engine, worth noting in
    # COMPARISON.md: run_incident_langgraph() returns immediately once
    # interrupted (no live coroutine is blocked waiting), so there is no
    # concurrent "auto-approve" background task to spawn here, unlike
    # tests/test_orchestrate.py's equivalent test against the real
    # orchestrator.
    assert record is None
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("governance_gate",)
    assert snapshot.tasks[0].interrupts[0].value["policy_tier"] == "APPROVAL_REQUIRED"

    final = await resume_incident_langgraph(graph, config, decision="approved", approved_by="ops-lead-1")

    assert final.final_state == "Resolved"
    assert final.policy_tier == PolicyTier.APPROVAL_REQUIRED
    assert final.approved_by == "ops-lead-1"
    assert final.recommendation_accepted is True
    assert final.capability_invoked == Capability.SCHEDULE_MAINTENANCE
    assert final.capability_status is not None
    assert len(final.causal_chain) > 0
    assert len(final.alternatives) >= 1


@pytest.mark.asyncio
async def test_langgraph_fails_on_rejected_approval():
    record, graph, config = await run_incident_langgraph(**SCENARIO, incident_id="lg-tier1-reject-1")
    assert record is None

    final = await resume_incident_langgraph(graph, config, decision="rejected", approved_by="ops-lead-2")

    assert final.final_state == "Failed"
    assert final.recommendation_accepted is False
    assert final.capability_invoked is None  # execute_capability_node never ran


@pytest.mark.asyncio
async def test_cross_engine_equivalence():
    """The falsifiable core of the correctness comparison: given the same
    input, both engines must reach an identical decision. Any divergence
    here is a wiring bug in one of the two implementations, not a
    legitimate framework difference — both wrap the exact same
    VisionSpecAgent/CausalIsolationAgent classes, which are confirmed
    deterministic (no random, no wall-clock branches)."""
    baseline_queue = ApprovalQueue()

    async def approve_baseline():
        for _ in range(200):
            pending = baseline_queue.list_pending()
            if pending:
                baseline_queue.approve(pending[0].incident_id, approved_by="ops-lead-equivalence")
                return
            await asyncio.sleep(0.01)

    baseline_record, _ = await asyncio.gather(
        run_incident_baseline(**SCENARIO, incident_id="equiv-baseline-1", approval_queue=baseline_queue),
        approve_baseline(),
    )

    _, graph, config = await run_incident_langgraph(**SCENARIO, incident_id="equiv-langgraph-1")
    langgraph_record = await resume_incident_langgraph(
        graph, config, decision="approved", approved_by="ops-lead-equivalence"
    )

    assert baseline_record.causal_chain == langgraph_record.causal_chain
    assert baseline_record.confidence == langgraph_record.confidence
    assert baseline_record.alternatives == langgraph_record.alternatives
    assert baseline_record.policy_tier == langgraph_record.policy_tier
    assert baseline_record.capability_invoked == langgraph_record.capability_invoked
    assert baseline_record.capability_status == langgraph_record.capability_status
    assert baseline_record.final_state == langgraph_record.final_state
