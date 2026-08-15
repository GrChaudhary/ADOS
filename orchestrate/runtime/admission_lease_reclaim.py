"""
P12 -- reclaims `admission_leases` rows a crashed process never released,
and prunes old `rate_limit_events` rows for table hygiene (see
db/models/admission_lease.py and db/models/rate_limit_event.py for the
full rationale of each table).

WHY A SEPARATE MODULE, NOT PART OF admission_control.py
-----------------------------------------------------------
admission_control.py's job is the hot-path acquire/release check --
correctness under real concurrency, called on every capability execution.
This module's job is a periodic, low-frequency cleanup pass, called from the
same centralized scheduler orphan_sweep/session_reconcile already share
(backend/app/main.py) -- a different lifecycle, kept in a different file for
the same reason orphan_sweep.py and session_reconcile.py are already two
files rather than one.

WHY A BOUNDED MAX AGE IS SAFE
---------------------------------
A lease is only ever held for the duration of one `hub.invoke()` call --
normally milliseconds to, for a Prime Agent mission, at most
`max_wall_clock_seconds`. `admission_lease_max_age_seconds` (Settings) must
be set generously above the longest call this deployment actually allows;
anything older than that age was, by construction, never released by the
`finally` block that would have (see integrations/hub.py), i.e. the process
that acquired it is gone. Reclaiming it is not a guess about whether the
call is "probably done" -- it is the same bounded-staleness argument
session_reconcile.py already makes for abandoned sessions, applied to a
narrower, purely-numeric resource instead of a whole session row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete

from db.models.admission_lease import AdmissionLeaseRow
from db.models.rate_limit_event import RateLimitEventRow

DEFAULT_LEASE_MAX_AGE_SECONDS = 1800.0
DEFAULT_RATE_LIMIT_EVENT_RETENTION_SECONDS = 3600.0


@dataclass(frozen=True)
class ReclaimReport:
    leases_reclaimed: int
    rate_limit_events_pruned: int


async def reclaim_stale_admission_state(
    session_factory,
    *,
    lease_max_age_seconds: float = DEFAULT_LEASE_MAX_AGE_SECONDS,
    rate_limit_event_retention_seconds: float = DEFAULT_RATE_LIMIT_EVENT_RETENTION_SECONDS,
    now: Optional[datetime] = None,
) -> ReclaimReport:
    now = now or datetime.now(timezone.utc)
    lease_cutoff = now - timedelta(seconds=lease_max_age_seconds)
    event_cutoff = now - timedelta(seconds=rate_limit_event_retention_seconds)

    async with session_factory() as db:
        lease_result = await db.execute(
            delete(AdmissionLeaseRow).where(AdmissionLeaseRow.acquired_at < lease_cutoff)
        )
        event_result = await db.execute(
            delete(RateLimitEventRow).where(RateLimitEventRow.occurred_at < event_cutoff)
        )
        await db.commit()

    return ReclaimReport(
        leases_reclaimed=lease_result.rowcount or 0,
        rate_limit_events_pruned=event_result.rowcount or 0,
    )
