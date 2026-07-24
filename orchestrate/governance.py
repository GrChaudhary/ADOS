"""
L5 Governance enforcement — docs/007-governance.md. This is what closes
the gap left in Phase 1: `/capabilities/invoke` accepted whatever
`governance` the caller supplied. Here, tier is computed server-side from
the capability's risk class and the decision's confidence, never trusted
from a caller, and Tier 1/2 decisions block on ApprovalQueue until a human
acts.

Risk-class-first, confidence-second — a high-confidence high-risk action
still doesn't earn Tier 0 (docs/007's stated reason: impact class matters
independent of confidence). Tuning these thresholds per plant/capability
is the open question docs/007-governance.md already flags; this is the
MVP starting policy, not a final one.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from contracts import Capability, PolicyTier

CAPABILITY_RISK_CLASS: Dict[Capability, str] = {
    Capability.NOTIFY_OPERATOR: "low",
    Capability.CREATE_INCIDENT: "low",
    Capability.QUERY_EXTERNAL_STOCK: "low",
    Capability.GET_FREIGHT_QUOTE: "low",
    Capability.UPDATE_MES: "medium",
    Capability.SCHEDULE_MAINTENANCE: "medium",
    Capability.RESERVE_INVENTORY: "medium",
    Capability.CREATE_CHANGE_REQUEST: "high",
    Capability.CREATE_PURCHASE_ORDER: "high",
    Capability.CREATE_EXTERNAL_PO: "high",
}

# Confidence required to earn Tier 0 within a risk class. "high" has no
# entry: it can never be Tier 0 regardless of confidence.
_TIER0_CONFIDENCE_THRESHOLD = {"low": 0.85, "medium": 0.97}


def promote_policy_tier(capability: Capability, target_risk_class: str) -> None:
    """Promotes a capability's risk class dynamically (e.g. high -> medium or low) upon Tier 0 qualification."""
    CAPABILITY_RISK_CLASS[capability] = target_risk_class


def assign_policy_tier(capability: Capability, confidence: float) -> PolicyTier:
    risk_class = CAPABILITY_RISK_CLASS.get(capability, "high")  # unknown capability: fail safe
    if risk_class == "high":
        return PolicyTier.EXECUTIVE_APPROVAL
    threshold = _TIER0_CONFIDENCE_THRESHOLD.get(risk_class, 0.97)
    if confidence >= threshold:
        return PolicyTier.AUTONOMOUS
    return PolicyTier.APPROVAL_REQUIRED


@dataclass
class PendingApproval:
    incident_id: str
    capability: Capability
    policy_tier: PolicyTier
    confidence: float
    summary: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    decision: Optional[str] = None  # "approved" | "rejected" | "escalated"
    approved_by: Optional[str] = None
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> str:
        await self._event.wait()
        return self.decision

    def resolve(self, decision: str, approved_by: Optional[str] = None) -> None:
        self.decision = decision
        self.approved_by = approved_by
        self._event.set()


class ApprovalQueue:
    """In-memory Tier 1/2 approval queue — the human approval workflow's
    backing store for the MVP. A real deployment would persist this and
    route by role/capability (docs/007-governance.md's Policy Engine),
    both left as follow-ups."""

    def __init__(self):
        self._pending: Dict[str, PendingApproval] = {}

    def enqueue(self, approval: PendingApproval) -> PendingApproval:
        self._pending[approval.incident_id] = approval
        return approval

    def get(self, incident_id: str) -> Optional[PendingApproval]:
        return self._pending.get(incident_id)

    def list_pending(self):
        return [a for a in self._pending.values() if a.decision is None]

    def approve(self, incident_id: str, approved_by: str) -> PendingApproval:
        approval = self._require(incident_id)
        approval.resolve("approved", approved_by)
        return approval

    def reject(self, incident_id: str, approved_by: str) -> PendingApproval:
        approval = self._require(incident_id)
        approval.resolve("rejected", approved_by)
        return approval

    def escalate(self, incident_id: str, approved_by: str) -> PendingApproval:
        approval = self._require(incident_id)
        approval.resolve("escalated", approved_by)
        return approval

    def _require(self, incident_id: str) -> PendingApproval:
        approval = self._pending.get(incident_id)
        if approval is None:
            raise KeyError(f"no pending approval for incident {incident_id}")
        return approval
