"""
IT domain pod action registry for the Main Orchestrating Agent (MOA).

Exposes IT-specific capability tools, risk classifications, and action specifications.
Integrates with L5 Governance (orchestrate/governance.py) and IntegrationHub (integrations/hub.py).
"""

from dataclasses import dataclass
from typing import Dict, Any

from contracts import Capability


@dataclass(frozen=True)
class ITAction:
    key: str
    description: str
    capability: Capability
    estimated_cost_usd: float


IT_ACTIONS: Dict[str, ITAction] = {
    "notify_it_helpdesk": ITAction(
        key="notify_it_helpdesk",
        description="Send notification ticket to IT Helpdesk regarding user access changes",
        capability=Capability.NOTIFY_IT_HELPDESK,
        estimated_cost_usd=0.0,
    ),
    "grant_jira_access": ITAction(
        key="grant_jira_access",
        description="Grant user workspace license to Atlassian Jira and Confluence",
        capability=Capability.GRANT_JIRA_ACCESS,
        estimated_cost_usd=40000.0,
    ),
    "revoke_aws_role": ITAction(
        key="revoke_aws_role",
        description="Revoke AWS IAM administrator role and invalidate active access sessions",
        capability=Capability.REVOKE_AWS_ROLE,
        estimated_cost_usd=40000.0,
    ),
    "deprovision_cloud_account": ITAction(
        key="deprovision_cloud_account",
        description="Fully deprovision cloud infrastructure account and purge access credentials",
        capability=Capability.DEPROVISION_CLOUD_ACCOUNT,
        estimated_cost_usd=100000.0,
    ),
}


def execute_it_action(action_key: str, employee_name: str) -> Dict[str, Any]:
    """Execution helper for IT domain capabilities."""
    action = IT_ACTIONS.get(action_key)
    if not action:
        return {"status": "error", "error": f"Unknown IT action: {action_key}"}

    return {
        "status": "success",
        "action": action_key,
        "capability": action.capability.value,
        "message": f"IT action '{action_key}' executed for {employee_name}.",
    }
