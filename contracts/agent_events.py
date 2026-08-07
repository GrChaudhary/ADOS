"""
Agent and Stage event payload schemas per docs/010-api-contracts.md & docs/004-agent-framework.md.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class AgentCompletedPayload(BaseModel):
    """Payload for AgentCompleted events."""
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    stage_name: str = Field(..., alias="stageName")
    execution_time_ms: float = Field(..., alias="executionTimeMs")
    confidence: float = Field(..., description="Agent output confidence [0.0 - 1.0]")
    result: Dict[str, Any] = Field(..., description="Primary output result object")
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Concrete evidence references")
    alternatives: List[Dict[str, Any]] = Field(default_factory=list, description="Rejected options considered")


class IncidentDetectedPayload(BaseModel):
    """Payload for IncidentDetected initial perception events."""
    model_config = ConfigDict(populate_by_name=True)

    plant_id: str = Field(..., alias="plantId")
    line_id: str = Field(..., alias="lineId")
    defect_type: str = Field(..., alias="defectType")
    severity: str = Field(default="HIGH", alias="severity")
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    vision_data: Optional[Dict[str, Any]] = Field(default=None, alias="visionData")


class PendingApprovalPayload(BaseModel):
    """Payload for PendingApproval events published to governance.pending_approval topic."""
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(..., alias="taskId")
    domain: str = Field(default="hr")
    action_key: str = Field(..., alias="actionKey")
    capability: str
    policy_tier: int = Field(..., alias="policyTier")
    estimated_cost_usd: float = Field(..., alias="estimatedCostUsd")
    summary: str
    timestamp: str


class ApprovalDecisionPayload(BaseModel):
    """Payload for ApprovalDecision events when a human signs off or rejects."""
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(..., alias="taskId")
    decision: str = Field(..., description="'approved' | 'rejected'")
    approved_by: Optional[str] = Field(default=None, alias="approvedBy")
    role: Optional[str] = Field(default=None)
    timestamp: str

