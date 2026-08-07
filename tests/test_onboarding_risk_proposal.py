"""orchestrate/onboarding/risk_proposal.py — Turn 3. Confirms the
deliberate v1 floor (every onboarded action fails safe to Executive
Approval, since Capability.DYNAMIC_CAPABILITY has no
CAPABILITY_RISK_CLASS entry) holds regardless of cost/confidence, and that
propose_risk_profile() enforces the same "at least one action" rule
CapabilityManifestRegistry.propose() itself requires."""

import pytest

from contracts import PolicyTier
from orchestrate.onboarding.models import OnboardingTrack, SynthesizedAction
from orchestrate.onboarding.risk_proposal import propose_risk, propose_risk_profile


@pytest.mark.parametrize("estimated_cost_usd", [0.0, 100.0, 50_000.0, 1_000_000.0])
def test_every_onboarded_action_fails_safe_to_executive_approval_regardless_of_cost(estimated_cost_usd):
    entry = propose_risk("read_ticket", "Fetch a support ticket", estimated_cost_usd)
    assert entry.tier is PolicyTier.EXECUTIVE_APPROVAL
    assert entry.action == "read_ticket"
    assert "no track record" in entry.reasoning
    assert "fails safe" in entry.reasoning


def test_reasoning_mentions_the_real_estimated_cost():
    entry = propose_risk("create_ticket", "Create a ticket", 12_345.67)
    assert "$12,345.67" in entry.reasoning


def test_propose_risk_profile_maps_every_action():
    actions = [
        SynthesizedAction(
            key="read_ticket", description="Fetch a ticket", capability_id="zendesk.read_ticket",
            domain="support", version="1.0.0", estimated_cost_usd=0.0, track=OnboardingTrack.MCP_NATIVE, runtime={},
        ),
        SynthesizedAction(
            key="create_ticket", description="Create a ticket", capability_id="zendesk.create_ticket",
            domain="support", version="1.0.0", estimated_cost_usd=0.0, track=OnboardingTrack.MCP_NATIVE, runtime={},
        ),
    ]
    profile = propose_risk_profile(actions)
    assert [e.action for e in profile] == ["read_ticket", "create_ticket"]
    assert all(e.tier is PolicyTier.EXECUTIVE_APPROVAL for e in profile)


def test_propose_risk_profile_rejects_empty_actions():
    with pytest.raises(ValueError, match="at least one action"):
        propose_risk_profile([])
