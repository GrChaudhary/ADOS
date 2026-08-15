"""
P11 — admission control for `IntegrationHub.invoke()`, the one place every
capability call in this system reaches a connector (see hub.py's own
docstring). Nothing bounded concurrency before this: `orchestrate/
agent_runner.py`'s single `asyncio.Lock` is a correctness lock for two
agents' shared mutable state, not a resource ceiling, and `db/engine.py`
uses `NullPool` deliberately — no pool ceiling either. Doc 18
(docs/prime-agent-integration/18-production-readiness-review.md) names this
exact gap.

WHY PER-INSTANCE, NOT A MODULE-LEVEL SINGLETON
-------------------------------------------------
~800 tests construct their own `IntegrationHub()`/`default_hub()` instances
constantly. A module-level admission-control singleton would leak
concurrency state across unrelated tests — a test that fails to release a
slot (or is still holding one when the next test starts) would silently
throttle every test after it. `IntegrationHub.__init__` builds its own
`AdmissionControl`, mirroring how it already builds its own
`ConnectorPolicyEngine`.

WHY THIS IS SAFE UNDER REAL CONCURRENCY WITHOUT A LOCK
---------------------------------------------------------
`try_acquire_*` is synchronous and contains no `await`. Under Python's
cooperative single-threaded event loop, a function with no await point
cannot be interleaved with another coroutine mid-execution — the
check-then-increment here is therefore atomic with respect to every other
task on the same loop, the same property every other in-process counter in
this codebase (e.g. RuntimeSessionRow.capability_request_count's read-then-
write inside one open transaction) relies on. This does NOT extend across
processes — confirmed true, and closed below.

P12 — GLOBAL ENFORCEMENT, ADDITIVELY
-------------------------------------
The paragraph above was an accurate scope statement, not a defect, for
Model A's single-process envelope — but P12 found it is a real gap for a
long-running (Model B) service: two ADOS processes against the same
Postgres database would each independently enforce the configured ceiling,
together admitting up to Nx the intended global limit.

Fixed additively, not by replacing the fast local check: when
`session_factory` is supplied, `try_acquire_capability_slot_global`/
`try_acquire_mission_slot_global` (async — this is the one place in this
class that awaits) claim a row in `admission_leases`
(db/models/admission_lease.py) under `pg_advisory_xact_lock`, the same
"let Postgres serialize the count-then-act" idiom `backend/app/
mcp_gateway.py`'s approval-queue gate already uses — genuinely global,
enforced by the database, not by whichever process's memory answers first.
`release_*_global` deletes the lease row.

The in-process counters above are kept, unconditionally, as the fast local
pre-check every caller still pays first (hub.py) — cheap, no DB round trip,
and still exactly correct for the common single-process case. The global
check only matters (and only ever rejects something the local check
admitted) when a second process exists, which is precisely the case the
local check cannot see. `session_factory=None` (every one of the ~800
existing tests that construct `AdmissionControl()`/`IntegrationHub()`
directly) preserves the exact P11 behavior, unchanged — the global methods
are simply never called by hub.py in that case.

A lease abandoned by a process that dies mid-execution (never reaches its
`finally`) is reclaimed by the same centralized periodic loop that already
reclaims abandoned Docker resources and sessions — see
orchestrate/runtime/admission_lease_reclaim.py.
"""

from __future__ import annotations

import os
import socket
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text

from db.models.admission_lease import AdmissionLeaseRow

DEFAULT_MAX_CONCURRENT_CAPABILITY_EXECUTIONS = 10
DEFAULT_MAX_CONCURRENT_MISSIONS = 3

GATE_CAPABILITY_CONCURRENCY = "capability_concurrency"
GATE_MISSION_CONCURRENCY = "mission_concurrency"

_HOLDER = f"{socket.gethostname()}:{os.getpid()}"


class AdmissionControl:
    def __init__(
        self,
        *,
        max_concurrent_capability_executions: int = DEFAULT_MAX_CONCURRENT_CAPABILITY_EXECUTIONS,
        max_concurrent_missions: int = DEFAULT_MAX_CONCURRENT_MISSIONS,
        session_factory: Optional[object] = None,
    ):
        self._max_capability = max_concurrent_capability_executions
        self._max_missions = max_concurrent_missions
        self._current_capability = 0
        self._current_missions = 0
        # Optional[async_sessionmaker] -- typed loosely (not imported at
        # module scope) to avoid a hard dependency on db.engine for the
        # ~800 tests that never set this.
        self._session_factory = session_factory

    def try_acquire_capability_slot(self) -> bool:
        if self._current_capability >= self._max_capability:
            return False
        self._current_capability += 1
        return True

    def release_capability_slot(self) -> None:
        self._current_capability = max(0, self._current_capability - 1)

    def try_acquire_mission_slot(self) -> bool:
        if self._current_missions >= self._max_missions:
            return False
        self._current_missions += 1
        return True

    def release_mission_slot(self) -> None:
        self._current_missions = max(0, self._current_missions - 1)

    @property
    def current_capability_executions(self) -> int:
        """Diagnostics/tests only — never consulted by the gate logic above,
        which always reads `self._current_capability` directly."""
        return self._current_capability

    @property
    def current_missions(self) -> int:
        return self._current_missions

    @property
    def globally_coordinated(self) -> bool:
        return self._session_factory is not None

    async def _try_acquire_global(self, gate: str, limit: int) -> Optional[UUID]:
        """None means rejected. Otherwise the lease id `_release_global`
        needs. The advisory lock is transaction-scoped (auto-released at
        commit/rollback below) and keyed per-gate, so the two gates never
        serialize against each other, only against themselves."""
        if self._session_factory is None:
            return None
        async with self._session_factory() as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"ados_admission_{gate}"})
            count = (
                await db.execute(
                    select(func.count()).select_from(AdmissionLeaseRow).where(AdmissionLeaseRow.gate == gate)
                )
            ).scalar_one()
            if count >= limit:
                await db.rollback()
                return None
            lease_id = uuid4()
            db.add(AdmissionLeaseRow(id=lease_id, gate=gate, holder=_HOLDER))
            await db.commit()
            return lease_id

    async def _release_global(self, lease_id: Optional[UUID]) -> None:
        if self._session_factory is None or lease_id is None:
            return
        async with self._session_factory() as db:
            await db.execute(delete(AdmissionLeaseRow).where(AdmissionLeaseRow.id == lease_id))
            await db.commit()

    async def try_acquire_capability_slot_global(self) -> Optional[UUID]:
        return await self._try_acquire_global(GATE_CAPABILITY_CONCURRENCY, self._max_capability)

    async def release_capability_slot_global(self, lease_id: Optional[UUID]) -> None:
        await self._release_global(lease_id)

    async def try_acquire_mission_slot_global(self) -> Optional[UUID]:
        return await self._try_acquire_global(GATE_MISSION_CONCURRENCY, self._max_missions)

    async def release_mission_slot_global(self, lease_id: Optional[UUID]) -> None:
        await self._release_global(lease_id)
