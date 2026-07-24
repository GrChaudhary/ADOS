"""
Decision Memory Index implementation (knowledge/decision_memory_index.py).
Provides structured & similarity search over historical IncidentRecords for Phase 4B.
"""

from typing import List, Optional
from contracts import IncidentRecord, DecisionMemoryQuery, DecisionMemorySearchResult


class DecisionMemoryIndex:
    """
    Indexed search engine over historical IncidentRecords.
    Executes contracts.DecisionMemoryQuery to return relevant past incident precedents.
    """

    def __init__(self, seed_records: Optional[List[IncidentRecord]] = None):
        if seed_records is not None:
            self._records = seed_records
        else:
            from executive.seed_data import INCIDENT_RECORDS_SEED
            self._records = list(INCIDENT_RECORDS_SEED)

    def add_record(self, record: IncidentRecord) -> None:
        self._records.append(record)

    def search(self, query: DecisionMemoryQuery) -> DecisionMemorySearchResult:
        """
        Filters and ranks past incident precedents matching the query parameters.
        """
        filtered: List[tuple[IncidentRecord, float]] = []

        for rec in self._records:
            score = 0.5  # Base match score

            # Filter or score by plant_id
            if query.plant_id:
                if rec.plant_id == query.plant_id:
                    score += 0.2
                elif query.plant_id:
                    pass  # Keep cross-plant records with lower score

            # Filter by defect_type
            if query.defect_type:
                # Check causal chain or defect type match
                match_cause = any(
                    query.defect_type.lower() in c.description.lower() or
                    query.defect_type.lower() in c.condition_id.lower()
                    for c in rec.causal_chain
                )
                if match_cause:
                    score += 0.3

            # Filter by condition_id
            if query.condition_id:
                if any(c.condition_id == query.condition_id for c in rec.causal_chain):
                    score += 0.4
                else:
                    continue  # Strict filter if condition_id specified

            # Filter by supplier_id
            if query.supplier_id:
                if rec.supplier_id == query.supplier_id:
                    score += 0.3
                else:
                    continue

            # Confidence threshold
            if rec.confidence < query.min_confidence:
                continue

            filtered.append((rec, round(score, 3)))

        # Sort descending by relevance score
        filtered.sort(key=lambda x: x[1], reverse=True)

        matched_records = [f[0] for f in filtered[:query.limit]]
        relevance_scores = [f[1] for f in filtered[:query.limit]]

        return DecisionMemorySearchResult(
            total_matches=len(filtered),
            records=matched_records,
            relevance_scores=relevance_scores
        )
