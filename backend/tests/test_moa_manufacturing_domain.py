"""
Tests for MOA Manufacturing & Supply Chain Domain Pod.
"""

import pytest
from contracts import PolicyTier, Capability
from orchestrate.governance import assign_policy_tier
from orchestrate.moa.manufacturing_domain import MANUFACTURING_ACTIONS, execute_manufacturing_action
from orchestrate.moa import graph as moa_graph


def test_manufacturing_domain_actions_and_governance():
    """Verify Manufacturing domain actions are registered with correct governance policy tiers."""
    assert "query_external_stock" in MANUFACTURING_ACTIONS
    assert "reserve_inventory" in MANUFACTURING_ACTIONS
    assert "update_mes" in MANUFACTURING_ACTIONS
    assert "schedule_maintenance" in MANUFACTURING_ACTIONS
    assert "create_purchase_order" in MANUFACTURING_ACTIONS

    # Tier 0 (Autonomous)
    t0_query = assign_policy_tier(Capability.QUERY_EXTERNAL_STOCK, confidence=1.0, estimated_cost_usd=0.0)
    assert t0_query == PolicyTier.AUTONOMOUS

    t0_reserve = assign_policy_tier(Capability.RESERVE_INVENTORY, confidence=1.0, estimated_cost_usd=5000.0)
    assert t0_reserve == PolicyTier.AUTONOMOUS

    # Tier 1 (Manager Approval)
    t1_mes = assign_policy_tier(Capability.UPDATE_MES, confidence=1.0, estimated_cost_usd=40000.0)
    assert t1_mes == PolicyTier.APPROVAL_REQUIRED

    t1_maint = assign_policy_tier(Capability.SCHEDULE_MAINTENANCE, confidence=1.0, estimated_cost_usd=40000.0)
    assert t1_maint == PolicyTier.APPROVAL_REQUIRED

    # Tier 2 (Executive Approval)
    t2 = assign_policy_tier(Capability.CREATE_PURCHASE_ORDER, confidence=1.0, estimated_cost_usd=250000.0)
    assert t2 == PolicyTier.EXECUTIVE_APPROVAL


def test_manufacturing_execution_helper():
    """Verify execution helper for Manufacturing domain."""
    res = execute_manufacturing_action("update_mes", "Production Line 4")
    assert res["status"] == "success"
    assert res["capability"] == "UpdateMES"


@pytest.mark.asyncio
async def test_run_moa_task_manufacturing_domain(monkeypatch):
    """Test MOA execution with domain='manufacturing'."""
    def mock_generate_text(prompt, max_tokens=400, temperature=0.2):
        if "(nothing done yet)" in prompt:
            return {"status": "live_llm_generated", "text": "ACTION: update_mes", "model_used": "mock-nemotron"}
        return {"status": "live_llm_generated", "text": "ANSWER: Manufacturing MES parameters updated", "model_used": "mock-nemotron"}

    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client.is_configured", lambda: True)
    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client._generate_text", mock_generate_text)

    result, graph, config = await moa_graph.run_moa_task("Production Line 4", "Update MES parameters", domain="manufacturing")
    # Requires Tier 1 approval for update_mes
    assert result is None, "Should interrupt for Tier 1 human approval"
