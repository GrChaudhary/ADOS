"""
Causal Graph data structures per docs/003-causal-graph.md.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ConditionNode(BaseModel):
    """Observable condition node (process parameters, environmental factors, supplier changes)."""
    model_config = ConfigDict(populate_by_name=True)

    condition_id: str = Field(..., alias="conditionId")
    name: str
    condition_type: str = Field(..., alias="conditionType", description="PROCESS_PARAMETER | ENVIRONMENT | SUPPLIER | EQUIPMENT")
    description: Optional[str] = None
    plant_id: Optional[str] = Field(default=None, alias="plantId")


class OutcomeNode(BaseModel):
    """Defect outcome node."""
    model_config = ConfigDict(populate_by_name=True)

    outcome_id: str = Field(..., alias="outcomeId")
    defect_type: str = Field(..., alias="defectType", description="e.g. dimensional fault, surface defect, electrical fault")
    description: Optional[str] = None


class CausalEdge(BaseModel):
    """Directed, weighted causal edge from condition to outcome."""
    model_config = ConfigDict(populate_by_name=True)

    condition_id: str = Field(..., alias="conditionId")
    outcome_id: str = Field(..., alias="outcomeId")
    weight: float = Field(..., description="Causal probability/confidence weight [0.0 - 1.0]")
    evidence_count: int = Field(default=1, alias="evidenceCount")
    evidence_paths: List[str] = Field(default_factory=list, alias="evidencePaths")
    last_updated: Optional[str] = Field(default=None, alias="lastUpdated")


class CausalRankResult(BaseModel):
    """Result item returned by rankCandidateCauses()."""
    model_config = ConfigDict(populate_by_name=True)

    condition: ConditionNode
    weight: float
    evidence_path: List[str] = Field(..., alias="evidencePath")
    rank: int
