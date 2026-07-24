"""
Audit trail — docs/007-governance.md's append-only decision record store.
Backs both governance/compliance review and Phase 3B's `executive/` KPI
and recommendation reasoning, which reads `contracts.IncidentRecord`
collections (see docs/handoff-phase3b-antigravity.md).
"""

from typing import List, Optional

from contracts import IncidentRecord


class AuditTrail:
    def __init__(self):
        self._records: List[IncidentRecord] = []

    def append(self, record: IncidentRecord) -> IncidentRecord:
        self._records.append(record)
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
