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
