"""
Unit tests for Prime Agent RLM integration.
"""

import pytest
from contracts import Capability, PolicyTier
from knowledge.prime_agent_client import PrimeAgentClient, prime_agent_client
from orchestrate.governance import CAPABILITY_RISK_CLASS, assign_policy_tier
from backend.app.routers.agents_registry import BUILTIN_AGENTS, BUILTIN_IDS


def test_prime_agent_client_configured_property(monkeypatch):
    client = PrimeAgentClient()
    monkeypatch.delenv("PRIME_AGENT_API_KEY", raising=False)
    assert not client.is_configured()

    monkeypatch.setenv("PRIME_AGENT_API_KEY", "test-key-123")
    assert client.is_configured()


@pytest.mark.asyncio
async def test_prime_agent_client_simulation():
    res = await prime_agent_client.execute_rlm_task(
        prompt="Analyze spindle vibration drift",
        domain="mfg",
        max_iterations=3,
    )
    assert res["status"] == "success"
    assert res["agent"] == "prime-rlm-agent"
    assert "kernelTrace" in res or "trace" in res
    assert len(res.get("kernelTrace", res.get("trace", []))) > 0


def test_prime_agent_capability_contracts():
    assert Capability.RUN_PRIME_RLM_AGENT == "RunPrimeRLMAgent"
    assert CAPABILITY_RISK_CLASS[Capability.RUN_PRIME_RLM_AGENT] == "medium"

    # Governance evaluation: Medium risk class capability with cost < 25000 and confidence > 0.90 -> AUTONOMOUS
    tier = assign_policy_tier(Capability.RUN_PRIME_RLM_AGENT, confidence=0.95, estimated_cost_usd=1200.0)
    assert tier == PolicyTier.AUTONOMOUS

    # Medium risk class with cost > 25000 -> APPROVAL_REQUIRED
    tier_req = assign_policy_tier(Capability.RUN_PRIME_RLM_AGENT, confidence=0.85, estimated_cost_usd=30000.0)
    assert tier_req == PolicyTier.APPROVAL_REQUIRED


def test_prime_agent_registry_entry():
    assert "prime-rlm-agent" in BUILTIN_IDS
    entry = next(a for a in BUILTIN_AGENTS if a.id == "prime-rlm-agent")
    assert entry.label == "Prime RLM Agent"
    assert entry.icon == "🧬"
    assert entry.stage == "Reasoning"
    assert entry.memoryRAG is True
