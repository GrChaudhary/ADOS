"""
Feedback & Calibration Agent implementation (Learning Stage).
Recalibrates Causal Graph weights based on verified incident recovery outcomes.
"""

from typing import Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import CausalGraph


class FeedbackCalibrationAgent(BaseAgent):
    """Updates causal edge weights when post-execution outcomes confirm or refute predicted root causes."""

    def __init__(self, causal_graph: Optional[CausalGraph] = None):
        super().__init__(agent_id="feedback-calibration-agent", stage_name="Learning")
        self.causal_graph = causal_graph or CausalGraph()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        condition_id = stage_input.payload.get("condition_id", "COND-TOL-DRIFT")
        outcome_id = stage_input.payload.get("outcome_id", "OUT-DIMENSIONAL-FAULT")
        verified = stage_input.payload.get("outcome_verified", True)

        old_edge = self.causal_graph.get_edge(condition_id, outcome_id)
        old_weight = old_edge.weight if old_edge else 0.72

        updated_edge = self.causal_graph.recalibrate_weight(
            condition_id=condition_id,
            outcome_id=outcome_id,
            verified=verified,
            learning_rate=0.05
        )

        new_weight = updated_edge.weight if updated_edge else old_weight

        result = {
            "incident_id": context.incident_id,
            "condition_id": condition_id,
            "outcome_id": outcome_id,
            "outcome_verified": verified,
            "previous_weight": old_weight,
            "recalibrated_weight": new_weight,
            "delta": round(new_weight - old_weight, 4),
            "evidence_count": updated_edge.evidence_count if updated_edge else 1
        }

        evidence = [
            EvidenceItem(
                source_type="CAUSAL_GRAPH",
                reference_id=f"EDGE-{condition_id}-{outcome_id}",
                description=f"Recalibrated causal weight for {condition_id}: {old_weight} -> {new_weight} (verified={verified})",
                data=result
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-NO-CALIBRATION",
                description="Skip weight adjustment",
                status="REJECTED",
                reason="Single verified incident outcome must update causal priors to prevent diagnostic drift"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.97,
            evidence=evidence,
            alternatives=alternatives
        )
