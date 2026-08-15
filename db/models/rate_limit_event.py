"""
P12 — a fixed-window, Postgres-backed rate limiter, distinct from admission
control's concurrency ceilings (db/models/admission_lease.py).

WHY THIS IS A DIFFERENT MECHANISM, NOT MORE ADMISSION CONTROL
----------------------------------------------------------------
Admission control bounds how many calls are IN FLIGHT at once. It does not
bound how often a caller can START one — a caller that starts a Prime Agent
mission, has it fail or get refused immediately, and starts another, could
stay under any concurrency ceiling indefinitely while still hammering a paid
LLM provider once per loop iteration. Doc 18 (docs/prime-agent-integration/
18-production-readiness-review.md, "Rate limiting: None, on any endpoint,
including ones that call a paid LLM per request... a hard TPM ceiling was
already hit in testing") names exactly this gap. Confirmed by grep (see the
P12 research report): no token-bucket, sliding-window, or requests-per-
window mechanism exists anywhere in this codebase before this table.

Scoped to `RunPrimeRLMAgent` starts specifically -- the one capability that
triggers a real LLM provider call and a real Docker container, i.e. the
capability doc 18 actually names. Not a generic per-endpoint limiter; adding
one for every route without a concrete, named cost would be inventing limits
without justification, which P12's own instructions warn against.

MECHANISM
---------
Fixed-window: a row is inserted per admitted mission start; a check counts
rows newer than `window_seconds` under a `pg_advisory_xact_lock` (the same
count-then-admit idiom `backend/app/mcp_gateway.py`'s approval-queue gate
already uses). No release step -- unlike an admission lease, a rate-limit
event is not "held" for a duration, so there is nothing to leak on a crash.
Rows age out of every future window on their own; the same centralized
periodic reconciliation loop prunes rows older than the window purely for
table hygiene, not correctness (see orchestrate/runtime/admission_lease_
reclaim.py).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RateLimitEventRow(Base):
    __tablename__ = "rate_limit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # "mission_start" today -- a fixed, closed enum, kept as a column (not
    # baked into the table name) so a second limiter can reuse this table
    # later without another migration.
    limiter: Mapped[str]

    occurred_at: Mapped[datetime] = mapped_column(default=_utcnow)
