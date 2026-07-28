"""
Audit trail — docs/007-governance.md's append-only decision record store.
Backs both governance/compliance review and Phase 3B's `executive/` KPI
and recommendation reasoning, which reads `contracts.IncidentRecord`
collections (see docs/handoff-phase3b-antigravity.md).

Write-through to IBM Cloudant when configured (knowledge/cloudant_client.py)
so incidents survive a process restart and `/memory/search` - which already
prefers Cloudant when configured - sees live records instead of only the
static seed. In-memory is always the ground truth for reads within this
process; Cloudant is best-effort (a write failure never fails the incident).
"""

import asyncio
from typing import List, Optional

from contracts import IncidentRecord

from knowledge.cloudant_client import cloudant_db


class AuditTrail:
    def __init__(self, seed_records: Optional[List[IncidentRecord]] = None):
        # Mirrors knowledge/decision_memory_index.py's DecisionMemoryIndex
        # seed_records pattern. Deliberately does NOT touch Cloudant here -
        # AuditTrail()/DecisionOrchestrator() are constructed bare at ~9
        # call sites across the test suite and scripts/run_orchestrator_demo.py;
        # hydrating implicitly would silently add live network calls to all
        # of them. See hydrate_from_cloudant() for the explicit opt-in.
        self._records: List[IncidentRecord] = list(seed_records) if seed_records is not None else []

    async def append(self, record: IncidentRecord) -> IncidentRecord:
        self._records.append(record)
        if cloudant_db.is_configured():
            try:
                await asyncio.to_thread(cloudant_db.save_incident, record.model_dump(by_alias=True))
            except Exception as e:
                print(f"[AuditTrail] Cloudant write-through failed for {record.incident_id}: {e}")
        return record

    def get(self, incident_id: str) -> Optional[IncidentRecord]:
        for record in reversed(self._records):
            if record.incident_id == incident_id:
                return record
        return None

    def all(self) -> List[IncidentRecord]:
        return list(self._records)

    def recent(self, limit: int = 100) -> List[IncidentRecord]:
        return self._records[-limit:]

    async def hydrate_from_cloudant(self) -> int:
        """Loads existing Cloudant documents into memory at startup. Called
        explicitly from backend/app/main.py's lifespan, only when Cloudant
        is configured - never implicitly from __init__ (see comment above)."""
        docs = await asyncio.to_thread(cloudant_db.list_incidents, 500)
        loaded = 0
        for doc in docs:
            try:
                clean = {k: v for k, v in doc.items() if not k.startswith("_")}
                self._records.append(IncidentRecord.model_validate(clean))
                loaded += 1
            except Exception as e:
                print(f"[AuditTrail] Skipping malformed Cloudant doc {doc.get('_id')}: {e}")
        return loaded
