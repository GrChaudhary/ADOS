"""
Decision Memory Index implementation (knowledge/decision_memory_index.py).
Provides structured & similarity search over historical IncidentRecords for Phase 4B.
"""

from typing import List, Optional
from contracts import IncidentRecord, DecisionMemoryQuery, DecisionMemorySearchResult

# executive.seed_data is deliberately not a module-level import here:
# knowledge/__init__.py imports this module directly, and
# executive.seed_data transitively imports back into knowledge/agents/
# orchestrate — a module-level import here would reintroduce that
# circular import. Deferred, same reasoning as hydrate_from_db()'s own
# deferred imports below.


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
        Searches this process's in-memory incident history — seeded from
        executive/seed_data.py's static seed at construction, and (for the
        real backend/app/routers/memory.py singleton) topped up at startup
        with every incident persisted in Postgres via hydrate_from_db()
        (backend/app/main.py's lifespan). This is also what
        agents/sdk/memory_rag.py's DecisionMemoryRAG calls for Causal
        Isolation's precedent search.
        """
        return self._search_local(query)

    async def hydrate_from_db(self, session_factory) -> int:
        """Loads every persisted incident from Postgres directly, not via
        orchestrate/audit_trail.py's AuditTrail — this module can't import
        from orchestrate/ without reintroducing the circular import
        (knowledge/__init__.py -> orchestrate/__init__.py -> agent_runner
        -> knowledge/__init__.py) the top of this file already avoids by
        deferring its Cloudant/executive imports. Called explicitly from
        backend/app/main.py's lifespan, same opt-in convention as
        AuditTrail.hydrate_from_db() — never implicit from __init__."""
        from sqlalchemy import select

        from contracts import Capability, CallStatus, CausalChainEntry, PolicyTier
        from db.models.incident import IncidentRow

        async with session_factory() as session:
            rows = (await session.execute(select(IncidentRow))).scalars().all()

        loaded = 0
        for row in rows:
            try:
                self._records.append(
                    IncidentRecord(
                        incident_id=row.incident_id,
                        plant_id=row.plant_id,
                        line_id=row.line_id,
                        detected_at=row.detected_at,
                        resolved_at=row.resolved_at,
                        final_state=row.final_state,
                        causal_chain=[CausalChainEntry.model_validate(c) for c in row.causal_chain],
                        confidence=row.confidence,
                        alternatives=row.alternatives,
                        policy_tier=PolicyTier(row.policy_tier),
                        approved_by=row.approved_by,
                        recommendation_accepted=row.recommendation_accepted,
                        capability_invoked=Capability(row.capability_invoked) if row.capability_invoked else None,
                        capability_status=CallStatus(row.capability_status) if row.capability_status else None,
                        supplier_id=row.supplier_id,
                        execution_steps=row.execution_steps,
                        target_line_id=row.target_line_id,
                        estimated_cost_usd=row.estimated_cost_usd,
                        actual_cost_usd=row.actual_cost_usd,
                        estimated_downtime_min=row.estimated_downtime_min,
                        actual_downtime_min=row.actual_downtime_min,
                        created_at=row.created_at,
                    )
                )
                loaded += 1
            except Exception as e:
                print(f"[DecisionMemoryIndex] Skipping malformed incident row {row.incident_id}: {e}")
        return loaded

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
