"""
Finance domain pod action registry for the Main Orchestrating Agent (MOA).

Exposes Finance-specific capability tools, risk classifications, and action specifications.
Integrates with L5 Governance (orchestrate/governance.py) and IntegrationHub (integrations/hub.py).
"""

from dataclasses import dataclass
from typing import Dict, Any

from contracts import Capability


@dataclass(frozen=True)
class FinanceAction:
    key: str
    description: str
    capability: Capability
    estimated_cost_usd: float


FINANCE_ACTIONS: Dict[str, FinanceAction] = {
    "flag_invoice_discrepancy": FinanceAction(
        key="flag_invoice_discrepancy",
        description="Flag invoice discrepancy in Accounts Payable for audit review",
        capability=Capability.FLAG_INVOICE_DISCREPANCY,
        estimated_cost_usd=0.0,
    ),
    "approve_expense_reimbursement": FinanceAction(
        key="approve_expense_reimbursement",
        description="Approve employee expense reimbursement submission",
        capability=Capability.APPROVE_EXPENSE_REIMBURSEMENT,
        estimated_cost_usd=40000.0,
    ),
    "issue_vendor_payment_hold": FinanceAction(
        key="issue_vendor_payment_hold",
        description="Place temporary administrative hold on vendor payout",
        capability=Capability.ISSUE_VENDOR_PAYMENT_HOLD,
        estimated_cost_usd=45000.0,
    ),
    "process_wire_transfer": FinanceAction(
        key="process_wire_transfer",
        description="Execute high-value corporate international wire transfer",
        capability=Capability.PROCESS_WIRE_TRANSFER,
        estimated_cost_usd=250000.0,
    ),
}


def execute_finance_action(action_key: str, target_name: str) -> Dict[str, Any]:
    """Execution helper for Finance domain capabilities."""
    action = FINANCE_ACTIONS.get(action_key)
    if not action:
        return {"status": "error", "error": f"Unknown Finance action: {action_key}"}

    return {
        "status": "success",
        "action": action_key,
        "capability": action.capability.value,
        "message": f"Finance action '{action_key}' executed for {target_name}.",
    }
