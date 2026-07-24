"""
Decision Memory query & search contract schemas for Phase 4.
Decouples backend persistence (Phase 4A) from AI reasoning & memory retrieval (Phase 4B).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from .incident_record import IncidentRecord


class DecisionMemoryQuery(BaseModel):
    """Query schema for searching past incident audit records."""
    model_config = ConfigDict(populate_by_name=True)

    plant_id: Optional[str] = Field(default=None, alias="plantId")
    line_id: Optional[str] = Field(default=None, alias="lineId")
    defect_type: Optional[str] = Field(default=None, alias="defectType")
    condition_id: Optional[str] = Field(default=None, alias="conditionId")
    supplier_id: Optional[str] = Field(default=None, alias="supplierId")
    min_confidence: Optional[float] = Field(default=0.0, alias="minConfidence")
    limit: int = Field(default=10)


class DecisionMemorySearchResult(BaseModel):
    """Result payload returned by Decision Memory search capability."""
    model_config = ConfigDict(populate_by_name=True)

    total_matches: int = Field(..., alias="totalMatches")
    records: List[IncidentRecord] = Field(default_factory=list)
    relevance_scores: List[float] = Field(default_factory=list, alias="relevanceScores")
