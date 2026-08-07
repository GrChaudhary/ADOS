"""
Turn 3 of the onboarding pipeline (§8.4 step 3) — "propose a risk
profile... using the same weighting factors as the L5 governance model...
the agent proposes; it never self-approves". Reuses
orchestrate/governance.py's assign_policy_tier() as-is rather than
inventing a new weighting model: Capability.DYNAMIC_CAPABILITY has no
entry in CAPABILITY_RISK_CLASS, so every onboarded action fails safe to
the "high" risk class -> PolicyTier.EXECUTIVE_APPROVAL, regardless of
estimated cost or confidence. This is a deliberate v1 floor, matching the
vision doc's own stated philosophy for lower-trust/newly-onboarded sources
(§8.6: a spec-generated agent is "never eligible for full autonomy on
first deployment... autonomy only earned over time via a track record") —
not a gap to fix later. This module's job is producing honest per-action
reasoning for that verdict, not a new tier-weighting model.
"""

from typing import List

from contracts import Capability
from integrations.capability_manifest import RiskProfileEntry
from orchestrate.governance import assign_policy_tier

from .models import SynthesizedAction


def propose_risk(action_key: str, description: str, estimated_cost_usd: float) -> RiskProfileEntry:
    tier = assign_policy_tier(Capability.DYNAMIC_CAPABILITY, confidence=0.0, estimated_cost_usd=estimated_cost_usd)
    reasoning = (
        f"'{action_key}' ({description or action_key}) is a newly onboarded capability with no track "
        "record yet. Capability.DYNAMIC_CAPABILITY has no entry in governance.CAPABILITY_RISK_CLASS, "
        "so assign_policy_tier() fails safe to the 'high' risk class regardless of estimated cost "
        f"(${estimated_cost_usd:,.2f}) — every onboarded action starts at maximum scrutiny until an "
        "admin promotes it via a real usage track record (orchestrate/governance.py's "
        "promote_policy_tier())."
    )
    return RiskProfileEntry(action=action_key, tier=tier, reasoning=reasoning)


def propose_risk_profile(actions: List[SynthesizedAction]) -> List[RiskProfileEntry]:
    if not actions:
        raise ValueError("propose_risk_profile requires at least one action — CapabilityManifestRegistry.propose() rejects an empty risk profile")
    return [propose_risk(a.key, a.description, a.estimated_cost_usd) for a in actions]
