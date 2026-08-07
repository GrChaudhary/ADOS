"""
Tests for MOA IT, Finance, and Cross-Domain multi-pod execution.
"""

import pytest
from contracts import PolicyTier, Capability
from orchestrate.governance import assign_policy_tier
from orchestrate.moa.it_domain import IT_ACTIONS, execute_it_action
from orchestrate.moa.finance_domain import FINANCE_ACTIONS, execute_finance_action
from orchestrate.moa import graph as moa_graph


def test_it_domain_actions_and_governance():
    """Verify IT domain actions are registered with correct governance policy tiers."""
    assert "notify_it_helpdesk" in IT_ACTIONS
    assert "grant_jira_access" in IT_ACTIONS
    assert "revoke_aws_role" in IT_ACTIONS
    assert "deprovision_cloud_account" in IT_ACTIONS

    # Tier 0 (Autonomous)
    t0 = assign_policy_tier(Capability.NOTIFY_IT_HELPDESK, confidence=1.0, estimated_cost_usd=0.0)
    assert t0 == PolicyTier.AUTONOMOUS

    # Tier 1 (Manager Approval)
    t1_jira = assign_policy_tier(Capability.GRANT_JIRA_ACCESS, confidence=1.0, estimated_cost_usd=40000.0)
    assert t1_jira == PolicyTier.APPROVAL_REQUIRED

    t1_aws = assign_policy_tier(Capability.REVOKE_AWS_ROLE, confidence=1.0, estimated_cost_usd=40000.0)
    assert t1_aws == PolicyTier.APPROVAL_REQUIRED

    # Tier 2 (Executive Approval)
    t2 = assign_policy_tier(Capability.DEPROVISION_CLOUD_ACCOUNT, confidence=1.0, estimated_cost_usd=100000.0)
    assert t2 == PolicyTier.EXECUTIVE_APPROVAL


def test_finance_domain_actions_and_governance():
    """Verify Finance domain actions are registered with correct governance policy tiers."""
    assert "flag_invoice_discrepancy" in FINANCE_ACTIONS
    assert "approve_expense_reimbursement" in FINANCE_ACTIONS
    assert "issue_vendor_payment_hold" in FINANCE_ACTIONS
    assert "process_wire_transfer" in FINANCE_ACTIONS

    # Tier 0 (Autonomous)
    t0 = assign_policy_tier(Capability.FLAG_INVOICE_DISCREPANCY, confidence=1.0, estimated_cost_usd=0.0)
    assert t0 == PolicyTier.AUTONOMOUS

    # Tier 1 (Manager Approval)
    t1_expense = assign_policy_tier(Capability.APPROVE_EXPENSE_REIMBURSEMENT, confidence=1.0, estimated_cost_usd=40000.0)
    assert t1_expense == PolicyTier.APPROVAL_REQUIRED

    t1_hold = assign_policy_tier(Capability.ISSUE_VENDOR_PAYMENT_HOLD, confidence=1.0, estimated_cost_usd=45000.0)
    assert t1_hold == PolicyTier.APPROVAL_REQUIRED

    # Tier 2 (Executive Approval)
    t2 = assign_policy_tier(Capability.PROCESS_WIRE_TRANSFER, confidence=1.0, estimated_cost_usd=250000.0)
    assert t2 == PolicyTier.EXECUTIVE_APPROVAL


def test_it_and_finance_execution_helpers():
    """Verify execution helpers for IT and Finance domains."""
    res_it = execute_it_action("grant_jira_access", "DevOps Engineer")
    assert res_it["status"] == "success"
    assert res_it["capability"] == "GrantJiraAccess"

    res_fin = execute_finance_action("process_wire_transfer", "Acme Logistics")
    assert res_fin["status"] == "success"
    assert res_fin["capability"] == "ProcessWireTransfer"


@pytest.mark.asyncio
async def test_run_moa_task_it_domain(monkeypatch):
    """Test MOA execution with domain='it'."""
    def mock_generate_text(prompt, max_tokens=400, temperature=0.2):
        if "(nothing done yet)" in prompt:
            return {"status": "live_llm_generated", "text": "ACTION: grant_jira_access", "model_used": "mock-nemotron"}
        return {"status": "live_llm_generated", "text": "ANSWER: IT task completed", "model_used": "mock-nemotron"}

    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client.is_configured", lambda: True)
    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client._generate_text", mock_generate_text)

    result, graph, config = await moa_graph.run_moa_task("Alice Engineer", "Grant Jira access", domain="it")
    # Requires Tier 1 approval for grant_jira_access
    assert result is None, "Should interrupt for Tier 1 human approval"


@pytest.mark.asyncio
async def test_run_moa_task_cross_domain(monkeypatch):
    """Test MOA execution with domain='cross-domain' spanning multiple pods."""
    def mock_generate_text(prompt, max_tokens=400, temperature=0.2):
        return {"status": "live_llm_generated", "text": "ANSWER: Cross-domain analysis completed", "model_used": "mock-nemotron"}

    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client.is_configured", lambda: True)
    monkeypatch.setattr("orchestrate.moa.graph.local_llm_client._generate_text", mock_generate_text)

    result, graph, config = await moa_graph.run_moa_task("Marcus Vance", "Cross domain audit", domain="cross-domain")
    assert result["status"] == "ok"
    assert result["final_answer"] == "Cross-domain analysis completed"
