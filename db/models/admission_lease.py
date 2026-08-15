"""
P12 — a durable, Postgres-backed slot for the two admission-control gates
that P11 built as plain in-process counters (integrations/admission_control.py):
capability-execution concurrency and Prime Agent mission concurrency.

WHY THIS TABLE EXISTS
----------------------
P11's own docstring for AdmissionControl states plainly that its counters
"do NOT extend across processes" -- a deliberate, honest scope statement for
Model A's single-process envelope. P12 asked whether that gap is safe for
Model B and found it is not: two independent ADOS processes against the same
Postgres database would each enforce the configured ceiling independently,
admitting up to 2x (Nx) the intended global limit. This table is the fix --
a lease exists in Postgres for exactly as long as a slot is held, so the
limit is enforced by whoever queries this table, not by whichever process's
memory happens to be asked.

Deliberately NOT the same table as `capability_requests` or
`runtime_sessions`: a lease here is pure, ephemeral concurrency-control
state, held by MANY calls that have no governance meaning at all (e.g. a
MOA-triggered capability call that never reaches mcp_gateway.py and so never
gets a `capability_requests` row). Conflating the two would mean either
inventing lease semantics on top of an audit table (wrong -- audit rows must
never be deleted, per `ados_app`'s own DELETE revocation on that table) or
leaving MOA-originated calls unbounded (defeats the point). A lease row is
inserted on acquire and deleted on release -- nothing here is retained for
audit purposes, and nothing here needs to be.

CRASH SAFETY
------------
A process that dies mid-execution (SIGKILL, OOM) never runs the `finally`
block that would release its lease -- the row leaks, permanently shrinking
the effective ceiling. `acquired_at` exists for exactly this: the same
centralized periodic reconciliation loop that already reclaims abandoned
Docker resources and abandoned sessions (backend/app/main.py) also reclaims
any lease older than a bounded max age, on the same interval, using the same
"detect and correct, never guess" posture as everything else in that loop.
See orchestrate/runtime/admission_lease_reclaim.py.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdmissionLeaseRow(Base):
    __tablename__ = "admission_leases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # "capability_concurrency" | "mission_concurrency" -- the same fixed,
    # closed enum already used as `ados_admission_rejections_total`'s `gate`
    # label (backend/app/metrics.py). Never a request/mission/session id.
    gate: Mapped[str]

    acquired_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # hostname:pid -- debugging/observability only (which process is
    # holding this slot), never consulted by any gate logic and never
    # exposed as a Prometheus label (unbounded cardinality across process
    # restarts). A plain DB column read only by a human running SQL by hand.
    holder: Mapped[Optional[str]] = mapped_column(default=None)
