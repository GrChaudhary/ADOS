"""
IncidentRecord — the audit-trail / Decision Memory entry shape, per
docs/007-governance.md's "required decision evidence" and the KPI
derivations table in docs/008-executive-intelligence.md.

This is the Phase 3 decoupling contract, same role contracts/event_envelope.py
played for Phase 1/2: orchestrate/ (Phase 3A) produces one IncidentRecord
per resolved/failed incident; executive/ (Phase 3B) reasons over a
collection of them for KPIs, recommendations, and predictive risk — without
either side waiting on the other's implementation, only agreement on this
shape.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .capabilities import Capability, CallStatus, PolicyTier


class CausalChainEntry(BaseModel):
    """One ranked candidate cause attached to the decision — mirrors
    rankCandidateCauses() in docs/003-causal-graph.md."""

    model_config = ConfigDict(populate_by_name=True)

    condition_id: str = Field(..., alias="conditionId")
    description: str
    weight: float
    evidence_path: List[str] = Field(default_factory=list, alias="evidencePath")


class IncidentRecord(BaseModel):
    """One row of Decision Memory / the audit trail — docs/007-governance.md
    requires every decision to carry evidence, confidence, causal chain,
    and alternatives; this is where that's stored once an incident closes."""

    model_config = ConfigDict(populate_by_name=True)

    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="incidentId")
    plant_id: str = Field(..., alias="plantId")
    line_id: str = Field(..., alias="lineId")

    detected_at: str = Field(..., alias="detectedAt")
    resolved_at: Optional[str] = Field(default=None, alias="resolvedAt")
    final_state: str = Field(
        ..., alias="finalState", description="Resolved | Failed — docs/005-decision-orchestrator.md"
    )

    causal_chain: List[CausalChainEntry] = Field(default_factory=list, alias="causalChain")
    confidence: float = Field(..., description="Overall decision confidence")
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)

    policy_tier: PolicyTier = Field(..., alias="policyTier")
    approved_by: Optional[str] = Field(default=None, alias="approvedBy")
    recommendation_accepted: Optional[bool] = Field(
        default=None,
        alias="recommendationAccepted",
        description="Tier 1/2 only: did the approver accept the recommendation as-is? "
        "Null for Tier 0 (no human decision made). Drives the Recommendation "
        "Acceptance KPI in docs/008-executive-intelligence.md.",
    )

    capability_invoked: Optional[Capability] = Field(default=None, alias="capabilityInvoked")
    capability_status: Optional[CallStatus] = Field(default=None, alias="capabilityStatus")
    supplier_id: Optional[str] = Field(default=None, alias="supplierId")

    estimated_cost_usd: Optional[float] = Field(default=None, alias="estimatedCostUsd")
    actual_cost_usd: Optional[float] = Field(default=None, alias="actualCostUsd")
    estimated_downtime_min: Optional[float] = Field(default=None, alias="estimatedDowntimeMin")
    actual_downtime_min: Optional[float] = Field(default=None, alias="actualDowntimeMin")

    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(), alias="createdAt"
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)
