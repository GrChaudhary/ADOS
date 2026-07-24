"""
Memory-Augmented RAG module for ADOS reasoning agents (agents/sdk/memory_rag.py).
Queries DecisionMemoryIndex to attach past incident precedent evidence and boost confidence.
"""

from typing import List, Tuple, Optional
from contracts import DecisionMemoryQuery, DecisionMemorySearchResult, IncidentRecord
from knowledge.decision_memory_index import DecisionMemoryIndex
from .models import EvidenceItem, AlternativeOption


class DecisionMemoryRAG:
    """
    RAG utility for reasoning agents to query past incident precedents.
    """

    def __init__(self, memory_index: Optional[DecisionMemoryIndex] = None):
        self.memory_index: DecisionMemoryIndex = memory_index or DecisionMemoryIndex()

    def retrieve_precedents(
        self,
        defect_type: Optional[str] = None,
        condition_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        part_number: Optional[str] = None,
        limit: int = 3
    ) -> Tuple[List[EvidenceItem], List[AlternativeOption], float]:
        """
        Retrieves matching past incident precedents.
        Returns:
          - evidence: list of EvidenceItems with source_type="PRECEDENT"
          - alternatives: list of AlternativeOptions evaluated in past incidents
          - confidence_boost: float [0.0 - 0.15] based on precedent volume & success
        """
        query = DecisionMemoryQuery(
            plantId=plant_id,
            defectType=defect_type,
            conditionId=condition_id,
            limit=limit
        )

        res: DecisionMemorySearchResult = self.memory_index.search(query)

        evidence_items: List[EvidenceItem] = []
        rejected_alts: List[AlternativeOption] = []
        successful_precedents_count = 0

        for idx, rec in enumerate(res.records):
            score = res.relevance_scores[idx] if idx < len(res.relevance_scores) else 0.5
            if rec.final_state == "Resolved":
                successful_precedents_count += 1

            evidence_items.append(
                EvidenceItem(
                    source_type="PRECEDENT",
                    reference_id=rec.incident_id,
                    description=f"Past Incident {rec.incident_id} ({rec.plant_id}): State={rec.final_state}, MTTR={rec.actual_downtime_min}min, Tier={rec.policy_tier}",
                    data={
                        "incident_id": rec.incident_id,
                        "relevance_score": score,
                        "causal_chain": [c.model_dump(by_alias=True) for c in rec.causal_chain],
                        "actual_cost_usd": rec.actual_cost_usd,
                        "approved_by": rec.approved_by
                    }
                )
            )

            # Extract rejected alternatives from past record
            for alt in rec.alternatives:
                if isinstance(alt, dict) and alt.get("option"):
                    rejected_alts.append(
                        AlternativeOption(
                            option_id=f"PRECEDENT-ALT-{rec.incident_id}",
                            description=alt.get("option", "Historical Alternative"),
                            status="REJECTED",
                            reason=alt.get("reason", "Rejected in historical incident precedent")
                        )
                    )

        # Calculate confidence boost
        confidence_boost = min(0.12, round(successful_precedents_count * 0.04, 3))

        return evidence_items, rejected_alts, confidence_boost
