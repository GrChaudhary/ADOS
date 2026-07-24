"""
Capability call envelope per docs/010-api-contracts.md and
docs/006-integration-hub.md. This is the Integration Hub side of the
contract — the orchestrator/agents call a capability, the Connector
Policy Engine resolves and executes it, governance is mandatory on every
call. Mirrors the field/alias conventions established in event_envelope.py
(snake_case fields, camelCase aliases) so both halves of contracts/ read
the same way.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .capabilities import Capability, CallStatus, PolicyTier


class GovernanceInfo(BaseModel):
    """Mandatory governance context attached to every capability call —
    the Integration Hub rejects a call missing this rather than assuming
    Tier 0. See docs/007-governance.md."""

    model_config = ConfigDict(populate_by_name=True)

    policy_tier: PolicyTier = Field(..., alias="policyTier")
    approved_by: Optional[str] = Field(
        default=None,
        alias="approvedBy",
        description="Approver identity for Tier 1/2 calls; null for Tier 0",
    )


class CapabilityCall(BaseModel):
    """Request envelope for invoking a Capability Registry capability."""

    model_config = ConfigDict(populate_by_name=True)

    capability: Capability
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), alias="requestId"
    )
    incident_id: str = Field(..., alias="incidentId")
    requested_by: str = Field(
        ...,
        alias="requestedBy",
        description="orchestrator | agent id that issued this call",
    )
    schema_version: str = Field(default="1.0.0", alias="schemaVersion")
    input: Dict[str, Any] = Field(
        default_factory=dict, description="Capability-specific input payload"
    )
    governance: GovernanceInfo

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)


class CapabilityResponse(BaseModel):
    """Response envelope returned once a capability call executes."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(..., alias="requestId")
    status: CallStatus
    connector: Optional[str] = Field(
        default=None, description="Connector that fulfilled the call"
    )
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    compensating_action_ran: bool = Field(
        default=False,
        alias="compensatingActionRan",
        description="Whether a rollback/compensating action already ran on failure",
    )
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        alias="occurredAt",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)
