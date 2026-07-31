"""
Agent SDK models conforming to docs/004-agent-framework.md contract.
"""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class IncidentContext(BaseModel):
    """Context information for an active incident."""
    model_config = ConfigDict(populate_by_name=True)

    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="incidentId")
    plant_id: str = Field(..., alias="plantId")
    line_id: str = Field(..., alias="lineId")
    part_number: str = Field(default="", alias="partNumber")
    severity: str = Field(default="HIGH")
    timestamp: Optional[str] = None


class StageInput(BaseModel):
    """Input parameters passed to an agent for a specific execution stage."""
    model_config = ConfigDict(populate_by_name=True)

    stage_name: str = Field(..., alias="stageName")
    payload: Dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    """Evidence reference attached to an agent's decision/finding."""
    model_config = ConfigDict(populate_by_name=True)

    source_type: str = Field(..., alias="sourceType", description="KNOWLEDGE_GRAPH | CAUSAL_GRAPH | EVENT | TELEMETRY")
    reference_id: str = Field(..., alias="referenceId")
    description: str
    data: Dict[str, Any] = Field(default_factory=dict)


class AlternativeOption(BaseModel):
    """An option considered and evaluated by an agent (accepted or rejected)."""
    model_config = ConfigDict(populate_by_name=True)

    option_id: str = Field(..., alias="optionId")
    description: str
    status: str = Field(default="REJECTED", description="SELECTED | REJECTED | FEASIBLE")
    reason: str


class StageOutput(BaseModel):
    """Mandatory output structure produced by every ADOS reasoning agent."""
    model_config = ConfigDict(populate_by_name=True)

    result: Dict[str, Any] = Field(..., description="Primary finding or output payload")
    confidence: float = Field(..., description="Confidence score [0.0 - 1.0], mandatory for L5 governance")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="Mandatory supporting evidence references")
    alternatives: List[AlternativeOption] = Field(default_factory=list, description="Mandatory considered alternatives")
