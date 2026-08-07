"""
HR domain pod action registry for the Main Orchestrating Agent (MOA) —
orchestration-platform-vision.md §3/§11 step 2. Data-driven so graph.py's
reason-node prompt and act-node governance logic both derive from one
source instead of hardcoded strings in two places.

confidence is fixed at 1.0 for every action here, not computed per-call:
these are deterministic administrative actions (not a probabilistic
diagnosis like the manufacturing agents make), so the real uncertainty is
upstream — whether MOA picked the *right* action — which is a
planning-quality concern this milestone doesn't attempt to score, not a
per-action confidence signal.

estimated_cost_usd is a governance EXPOSURE estimate (same convention the
manufacturing capabilities already use for downtime/scrap cost in
orchestrate/orchestrator.py), not a literal dollar spend. The four values
below are deliberately tuned to land on three different policy tiers via
orchestrate/governance.py's assign_policy_tier(), so a single offboarding
task exercises autonomous, approval-required, and executive-approval
governance in one coherent scenario:

    RevokeBuildingAccess  low,  $0      -> AUTONOMOUS
    DisableITAccess       medium, $40k  -> APPROVAL_REQUIRED (between the
                                            $25k/$250k exposure bands)
    StopPayroll           high, --      -> EXECUTIVE_APPROVAL unconditionally
                                            (risk_class="high" alone forces
                                            this regardless of cost/confidence,
                                            same as CreateChangeRequest etc.)
    NotifyManager          low,  $0      -> AUTONOMOUS
"""

from dataclasses import dataclass
from typing import Dict

from contracts import Capability


@dataclass(frozen=True)
class HRAction:
    key: str  # stable token the LLM must emit verbatim after "ACTION:"
    description: str  # shown in the reason-node prompt
    capability: Capability
    estimated_cost_usd: float


HR_ACTIONS: Dict[str, HRAction] = {
    "revoke_building_access": HRAction(
        key="revoke_building_access",
        description="Revoke the employee's building access badge",
        capability=Capability.REVOKE_BUILDING_ACCESS,
        estimated_cost_usd=0.0,
    ),
    "disable_it_access": HRAction(
        key="disable_it_access",
        description="Disable the employee's IT systems access (email, VPN, internal tools)",
        capability=Capability.DISABLE_IT_ACCESS,
        estimated_cost_usd=40_000.0,
    ),
    "stop_payroll": HRAction(
        key="stop_payroll",
        description="Stop the employee's payroll / final paycheck processing",
        capability=Capability.STOP_PAYROLL,
        # Irrelevant to tier: risk_class="high" always forces EXECUTIVE_APPROVAL
        # regardless of cost — see module docstring.
        estimated_cost_usd=0.0,
    ),
    "notify_manager": HRAction(
        key="notify_manager",
        description="Notify the employee's manager that this task is being processed",
        capability=Capability.NOTIFY_MANAGER,
        estimated_cost_usd=0.0,
    ),
}
