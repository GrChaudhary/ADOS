"""
Autonomous Policy Optimizer implementation (executive/autonomy_optimizer.py).
Evaluates Decision Memory clusters to recommend promoting low-risk decision classes to Tier 0 autonomy.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from contracts import IncidentRecord, PolicyTier
from .seed_data import INCIDENT_RECORDS_SEED


class PolicyPromotionCandidate(BaseModel):
    """Candidate decision class evaluated for Tier 0 autonomous promotion."""
    model_config = ConfigDict(populate_by_name=True)

    candidate_id: str = Field(..., alias="candidateId")
    condition_id: str = Field(..., alias="conditionId")
    decision_class_name: str = Field(..., alias="decisionClassName")
    current_tier: str = Field(default="TIER_1_APPROVAL", alias="currentTier")
    target_tier: str = Field(default="TIER_0_AUTONOMOUS", alias="targetTier")
    sample_volume: int = Field(..., alias="sampleVolume")
    operator_acceptance_rate: float = Field(..., alias="operatorAcceptanceRate")
    avg_confidence: float = Field(..., alias="avgConfidence")
    is_eligible: bool = Field(..., alias="isEligible")
    promotion_rationale: str = Field(..., alias="promotionRationale")
    safety_guardrails: List[str] = Field(default_factory=list, alias="safetyGuardrails")


class AutonomyPolicyOptimizer:
    """
    Analyzes historical decision records to identify and recommend low-risk
    decision categories eligible for promotion to Tier 0 autonomous execution.
    """

    def __init__(self, records: Optional[List[IncidentRecord]] = None):
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)

    def evaluate_promotion_candidates(
        self,
        min_sample_size: int = 2,
        min_acceptance_rate: float = 0.80,
        min_avg_confidence: float = 0.85
    ) -> List[PolicyPromotionCandidate]:
        """
        Evaluates Decision Memory history to find decision categories qualifying for Tier 0 promotion.
        """
        # Group non-autonomous records by condition_id
        condition_groups: Dict[str, List[IncidentRecord]] = {}
        for rec in self.records:
            if rec.causal_chain and rec.policy_tier != PolicyTier.AUTONOMOUS:
                cid = rec.causal_chain[0].condition_id
                condition_groups.setdefault(cid, []).append(rec)

        candidates: List[PolicyPromotionCandidate] = []

        for cid, recs in condition_groups.items():
            sample_size = len(recs)
            accepted_recs = [r for r in recs if r.recommendation_accepted is True]
            acceptance_rate = round(len(accepted_recs) / sample_size, 3) if sample_size > 0 else 0.0
            avg_conf = round(sum(r.confidence for r in recs) / sample_size, 3) if sample_size > 0 else 0.0

            is_eligible = (
                sample_size >= min_sample_size and
                acceptance_rate >= min_acceptance_rate and
                avg_conf >= min_avg_confidence
            )

            cause_desc = recs[0].causal_chain[0].description if recs[0].causal_chain else cid

            candidate = PolicyPromotionCandidate(
                candidate_id=f"PROM-CAND-{cid}",
                condition_id=cid,
                decision_class_name=f"Autonomous Fix for {cause_desc}",
                current_tier="TIER_1_APPROVAL",
                target_tier="TIER_0_AUTONOMOUS",
                sample_volume=sample_size,
                operator_acceptance_rate=acceptance_rate,
                avg_confidence=avg_conf,
                is_eligible=is_eligible,
                promotion_rationale=(
                    f"Qualifies for Tier 0 promotion: Operator acceptance rate is {round(acceptance_rate*100, 1)}% "
                    f"across {sample_size} incidents with average confidence {avg_conf}."
                    if is_eligible else
                    f"Not eligible: Requires minimum {min_sample_size} samples and {min_acceptance_rate*100}% acceptance rate."
                ),
                safety_guardrails=[
                    "Limit parameter adjustments to maximum +/-0.10mm nominal offset",
                    "Require Vision & Spec Agent 3-sigma confidence confirmation prior to trigger",
                    "Automatically halt line if 2 consecutive autonomous adjustments fail to clear defect"
                ]
            )
            candidates.append(candidate)

        return candidates
