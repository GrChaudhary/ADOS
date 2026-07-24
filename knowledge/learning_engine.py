"""
Learning Engine implementation (knowledge/learning_engine.py).
Replays historical IncidentRecord audit trails to recalibrate CausalGraph edge weights.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
from contracts import IncidentRecord
from .causal_graph import CausalGraph
from .causal_models import CausalEdge
from executive.seed_data import INCIDENT_RECORDS_SEED


class LearningReplaySummary(BaseModel):
    """Summary of batch learning replay execution."""
    model_config = ConfigDict(populate_by_name=True)

    records_processed: int = Field(..., alias="recordsProcessed")
    edges_updated: int = Field(..., alias="edgesUpdated")
    weight_adjustments: List[Dict[str, Any]] = Field(default_factory=list, alias="weightAdjustments")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LearningEngine:
    """
    Self-learning engine that analyzes historical incident outcomes to continuously
    recalibrate Causal Graph edge weights.
    """

    def __init__(self, causal_graph: Optional[CausalGraph] = None):
        self.causal_graph: CausalGraph = causal_graph or CausalGraph(seed=True)

    def replay_audit_trail(
        self,
        records: Optional[List[IncidentRecord]] = None,
        learning_rate: float = 0.08
    ) -> LearningReplaySummary:
        """
        Replays a collection of IncidentRecords to recalibrate CausalGraph weights.
        """
        dataset = records if records is not None else list(INCIDENT_RECORDS_SEED)
        adjustments: List[Dict[str, Any]] = []

        for rec in dataset:
            if not rec.causal_chain:
                continue

            primary_cause = rec.causal_chain[0]
            condition_id = primary_cause.condition_id
            outcome_id = "OUT-DIMENSIONAL-FAULT"  # Map or extract target outcome

            # Determine outcome verification
            # Resolved + (Tier 0 OR accepted recommendation) -> Verified True
            is_verified = (rec.final_state == "Resolved") and (rec.recommendation_accepted is not False)

            old_edge = self.causal_graph.get_edge(condition_id, outcome_id)
            old_weight = old_edge.weight if old_edge else primary_cause.weight

            updated_edge = self.causal_graph.recalibrate_weight(
                condition_id=condition_id,
                outcome_id=outcome_id,
                verified=is_verified,
                learning_rate=learning_rate
            )

            if updated_edge:
                adjustments.append({
                    "incident_id": rec.incident_id,
                    "condition_id": condition_id,
                    "outcome_id": outcome_id,
                    "verified": is_verified,
                    "previous_weight": old_weight,
                    "new_weight": updated_edge.weight,
                    "delta": round(updated_edge.weight - old_weight, 4),
                    "evidence_count": updated_edge.evidence_count
                })

        return LearningReplaySummary(
            recordsProcessed=len(dataset),
            edgesUpdated=len(adjustments),
            weightAdjustments=adjustments
        )
