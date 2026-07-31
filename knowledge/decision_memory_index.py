"""
Decision Memory Index implementation (knowledge/decision_memory_index.py).
Provides structured & similarity search over historical IncidentRecords for Phase 4B.
"""

from typing import List, Optional
from contracts import IncidentRecord, DecisionMemoryQuery, DecisionMemorySearchResult

# Deliberately not a module-level import: knowledge/__init__.py imports this
# module directly, and cloudant_client.py transitively imports back into
# knowledge/agents/orchestrate — a module-level import here reintroduces
# that circular import. Deferred the same way __init__ already defers
# executive.seed_data below.


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
        Searches real plant history in Cloudant first (the same store
        backend/app/routers/memory.py's /memory/search uses for the
        Knowledge tab, and that every resolved incident is automatically
        saved to — orchestrate/orchestrator.py's _finalize), falling back
        to the static seed set only when Cloudant isn't configured or has
        no matches yet. This is also what agents/sdk/memory_rag.py's
        DecisionMemoryRAG calls for Causal Isolation's precedent search, so
        that reasoning now draws on the plant's actual incident history
        instead of being permanently frozen on the seed data.
        """
        from knowledge.cloudant_client import cloudant_db

        if cloudant_db.is_configured():
            cloudant_result = self._search_cloudant(query)
            if cloudant_result is not None:
                return cloudant_result

        return self._search_local(query)

    def _search_cloudant(self, query: DecisionMemoryQuery) -> Optional[DecisionMemorySearchResult]:
        """Mirrors memory.py's prior inline Cloudant search exactly (same
        selector fields, same flat 0.95 relevance score) so pulling it in
        here doesn't change what the Knowledge tab already returns —
        it just gives Causal Isolation's RAG the same real data path.
        Returns None (not an empty result) on zero matches so the caller
        falls through to the seed data instead of treating "nothing in
        Cloudant yet" as "no precedents exist"."""
        from knowledge.cloudant_client import cloudant_db

        search_text = query.defect_type or query.condition_id or query.line_id or query.plant_id or ""
        docs = cloudant_db.search_incidents(search_text, limit=query.limit or 50)

        records: List[IncidentRecord] = []
        for d in docs:
            try:
                clean_d = {k: v for k, v in d.items() if not k.startswith("_")}
                records.append(IncidentRecord.model_validate(clean_d))
            except Exception:
                pass

        if not records:
            return None

        return DecisionMemorySearchResult(
            total_matches=len(records),
            records=records,
            relevance_scores=[0.95] * len(records),
        )

    def _search_local(self, query: DecisionMemoryQuery) -> DecisionMemorySearchResult:
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
