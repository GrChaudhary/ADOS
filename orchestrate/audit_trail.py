"""
Audit trail — docs/007-governance.md's append-only decision record store.
Backs both governance/compliance review and Phase 3B's `executive/` KPI
and recommendation reasoning, which reads `contracts.IncidentRecord`
collections (see docs/handoff-phase3b-antigravity.md).

Persistence (db/ — real Postgres, replacing the old Cloudant write-through):
same optional `session_factory` pattern as integrations/capability_manifest.py's
CapabilityManifestRegistry. When none is given (every bare construction in
tests/scripts), this is pure in-memory, exactly as before. When given (how
backend/app/main.py wires it via DecisionOrchestrator), writes upsert into
Postgres by incident_id (INSERT ... ON CONFLICT DO UPDATE — no row lock
needed the way capability manifests needed one: writes to a given
incident_id are always sequential within one run_incident() coroutine, so
there's no concurrent-writer race to serialize against). In-memory is
always the ground truth for reads within this process; hydrate_from_db()
populates it at startup from whatever survived the last restart. A
Postgres write failure is caught and logged, never raised — same
best-effort convention the old Cloudant write-through used, since failing
an otherwise-successful incident over an audit-log write is the wrong
tradeoff.

persist_snapshot() is the write path used while an incident still sits at
AwaitingApproval (orchestrator.py's `_snapshot_pending`) — it upserts to
Postgres WITHOUT adding to the in-memory list, deliberately: the in-memory
list should hold one entry per incident once it reaches a terminal state
(what append() is for), not a stale intermediate snapshot that a later
append() would sit alongside within the same running process. A restart,
however, hydrates from Postgres — which only ever has the latest upserted
row per incident_id, since the ON CONFLICT update replaces it in place —
so this in-memory/Postgres distinction only matters within one process's
lifetime, not across a restart.
"""

from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from contracts import Capability, CallStatus, CausalChainEntry, IncidentRecord, PolicyTier

from db.models.incident import IncidentRow


def _record_to_row_values(record: IncidentRecord) -> dict:
    return dict(
        incident_id=record.incident_id,
        plant_id=record.plant_id,
        line_id=record.line_id,
        detected_at=record.detected_at,
        resolved_at=record.resolved_at,
        final_state=record.final_state,
        causal_chain=[c.model_dump(by_alias=True) for c in record.causal_chain],
        confidence=record.confidence,
        alternatives=record.alternatives,
        policy_tier=record.policy_tier.value,
        approved_by=record.approved_by,
        recommendation_accepted=record.recommendation_accepted,
        capability_invoked=record.capability_invoked.value if record.capability_invoked else None,
        capability_status=record.capability_status.value if record.capability_status else None,
        supplier_id=record.supplier_id,
        execution_steps=record.execution_steps,
        target_line_id=record.target_line_id,
        estimated_cost_usd=record.estimated_cost_usd,
        actual_cost_usd=record.actual_cost_usd,
        estimated_downtime_min=record.estimated_downtime_min,
        actual_downtime_min=record.actual_downtime_min,
        created_at=record.created_at,
    )


def row_to_incident_record(row: IncidentRow) -> IncidentRecord:
    return IncidentRecord(
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


class AuditTrail:
    def __init__(
        self,
        seed_records: Optional[List[IncidentRecord]] = None,
        session_factory: Optional[async_sessionmaker] = None,
    ):
        # Mirrors knowledge/decision_memory_index.py's DecisionMemoryIndex
        # seed_records pattern. Deliberately does NOT touch Postgres here -
        # AuditTrail()/DecisionOrchestrator() are constructed bare at ~9
        # call sites across the test suite and scripts/run_orchestrator_demo.py;
        # hydrating implicitly would silently add a live DB dependency to
        # all of them. See hydrate_from_db() for the explicit opt-in.
        self._records: List[IncidentRecord] = list(seed_records) if seed_records is not None else []
        self._session_factory = session_factory

    async def _upsert(self, record: IncidentRecord) -> None:
        if self._session_factory is None:
            return
        values = _record_to_row_values(record)
        update_values = {k: v for k, v in values.items() if k != "incident_id"}
        stmt = insert(IncidentRow).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["incident_id"], set_=update_values)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(stmt)
        except Exception as e:
            print(f"[AuditTrail] Postgres write-through failed for {record.incident_id}: {e}")

    async def append(self, record: IncidentRecord) -> IncidentRecord:
        self._records.append(record)
        await self._upsert(record)
        return record

    async def persist_snapshot(self, record: IncidentRecord) -> None:
        """Postgres-only write, no in-memory append — see module docstring."""
        await self._upsert(record)

    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        for record in reversed(self._records):
            if record.incident_id == incident_id:
                return record
        return None

    async def get_from_db(self, incident_id: str) -> Optional[IncidentRecord]:
        """P13 — a live Postgres read, bypassing the in-memory list.

        `get()` above only ever sees what THIS process's `hydrate_from_db()`
        loaded at ITS OWN startup, or appended itself. A worker process that
        never ran a given incident's `run_incident()` coroutine and started
        before `persist_snapshot()` wrote it has no way to see it via `get()`
        — this is the read half of the cross-worker visibility gap P13
        closes (see DecisionOrchestrator.resolve_pending_approval, the only
        caller). Not merged into `get()` itself: every other caller of
        `get()` (list_incidents, executive/ KPI reads) is a hot, frequent
        path this module's own docstring already documents as
        in-memory-is-ground-truth-for-reads; making every one of those pay
        for a Postgres round trip would be a much larger behavior change
        than the one specific gap this method exists to close."""
        if self._session_factory is None:
            return None
        async with self._session_factory() as session:
            row = (
                await session.execute(select(IncidentRow).where(IncidentRow.incident_id == incident_id))
            ).scalar_one_or_none()
        return row_to_incident_record(row) if row is not None else None

    async def claim_awaiting_approval(self, incident_id: str) -> bool:
        """P13 — atomically transitions `incident_id` from `AwaitingApproval`
        to `Executing` (an existing, already-meaningful IncidentState —
        contracts/incident_state.py — not a new invented value), and returns
        whether THIS caller is the one that made that transition.

        Reconstructing a PendingApproval on a process that never ran the
        incident (get_from_db, above) makes it newly POSSIBLE for two
        processes to both reconstruct and act on the same decision at
        once — something that could never happen before, since only the
        one originating process ever had the incident visible at all. This
        is the write-side guard that keeps that possibility from becoming a
        real double execution: a single conditional `UPDATE ... WHERE
        final_state = 'AwaitingApproval'` is serialized by Postgres itself,
        so of any number of processes racing to claim the same row, exactly
        one sees `rowcount == 1`. Mirrors P9's "durable checkpoint before
        any external call" discipline (orchestrate/runtime/
        capability_execution.py) for this pipeline's first time needing it.
        """
        if self._session_factory is None:
            return True  # no Postgres wired -- one in-memory instance can't race with itself
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(IncidentRow)
                    .where(IncidentRow.incident_id == incident_id, IncidentRow.final_state == "AwaitingApproval")
                    .values(final_state="Executing")
                )
            return result.rowcount == 1

    def all(self) -> List[IncidentRecord]:
        return list(self._records)

    def recent(self, limit: int = 100) -> List[IncidentRecord]:
        return self._records[-limit:]

    async def hydrate_from_db(self) -> int:
        """Loads every persisted incident into memory at startup. Called
        explicitly from backend/app/main.py's lifespan, only when a
        session_factory is configured — never implicitly from __init__
        (see comment there)."""
        if self._session_factory is None:
            return 0

        async with self._session_factory() as session:
            rows = (await session.execute(select(IncidentRow))).scalars().all()

        loaded = 0
        for row in rows:
            try:
                self._records.append(row_to_incident_record(row))
                loaded += 1
            except Exception as e:
                print(f"[AuditTrail] Skipping malformed incident row {row.incident_id}: {e}")
        return loaded
