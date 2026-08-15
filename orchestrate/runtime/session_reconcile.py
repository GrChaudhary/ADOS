"""
Reconciliation for sessions abandoned by an ADOS process failure.

THE GAP
-------
P6-D made terminal-state writes failure-safe against an EXCEPTION raised
inside the process serving a mission (`_finalize_session` runs from a
`finally`). It cannot help against the *process itself* dying — SIGKILL, an
OOM kill, `docker compose down` mid-mission — because nothing survives to
run that `finally` block. Three real sessions from Aug 9 are exactly this:
`state` stuck at `running` forever, their runtime long gone. P7-C reconciled
their leaked workspace bytes by hand, once, and explicitly left their DB rows
alone as a lifecycle decision out of scope for a resource-cleanup phase. This
module is that decision, made deliberately rather than by omission.

THE SAFE CRITERION
-------------------
A session is reconciled — and ONLY reconciled — when its own credential is
ALREADY, PROVABLY unusable: `token_expires_at IS NOT NULL AND < now()`.
`token_expiry()` (prime.py) ties a session's token lifetime to
`max_wall_clock_seconds + TOKEN_GRACE_SECONDS`, so a genuinely still-running
mission cannot yet have an expired token — it would have reached a terminal
state, one way or another, well inside its own budget. A row that is BOTH
non-terminal AND past its own token expiry is therefore not a guess: nothing
holding that token can act through the gateway any more (`mcp_gateway.
_resolve_session` already refuses it), whether or not this reconciliation
pass ever runs. Reconciling it changes bookkeeping to match a fact that is
already true, not the other way around — the "do not blindly change running
rows" rule this module was asked to honour.

Rows with `token_expires_at IS NULL` — the pre-P6-D fossils — are
DELIBERATELY left alone here. There is no deterministic signal their
credential is dead (none was ever given an expiry), so calling one abandoned
would be a judgment call, not a proof, and this module does not make those.
P6-D guarantees no row created from here on can ever be NULL again, so this
category can only shrink; it does not need general automated handling.

WHAT RECONCILIATION ACTUALLY DOES
-----------------------------------
Only two things: sets `state = "failed"` (an existing, well-understood
terminal value already excluded from `mcp_gateway._LIVE_STATES` and from
`TERMINAL_STATES`), and stamps the same `orphaned …` marker
`_finalize_session` already writes into `failure_reason`. Nothing else. In
particular this module never touches Docker or the filesystem itself — once
a row carries that marker and a terminal state, `orphan_sweep.py`'s existing,
unmodified claim query picks it up on its own next pass. Reconciliation's
entire job is making an abandoned row visible to the sweeper that already
exists; it does not duplicate what that sweeper does.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from db.models.mission import RuntimeSessionRow
from db.tenancy import all_tenants_session

from .base import TERMINAL_STATES

_TERMINAL_VALUES = {s.value for s in TERMINAL_STATES}

#: Same literal substring orphan_sweep.py's ORPHAN_MARKER looks for — reusing
#: the existing signal rather than inventing a second one.
_RECONCILE_NOTE_PREFIX = "orphaned session: process abandoned before writing a terminal state"

DEFAULT_RECONCILE_LIMIT = 50


@dataclass(frozen=True)
class ReconciledSession:
    session_id: uuid.UUID
    mission_id: uuid.UUID
    token_expired_at: datetime


async def reconcile_abandoned_sessions(
    session_factory,
    *,
    limit: int = DEFAULT_RECONCILE_LIMIT,
    now: Optional[datetime] = None,
) -> List[ReconciledSession]:
    """Finds sessions stuck non-terminal with an already-expired token,
    marks them `failed` with the orphan marker, and returns what it touched.

    `SELECT ... FOR UPDATE SKIP LOCKED`, the same idiom `orphan_sweep.py` and
    `runtime_approvals.py` both use: two concurrent reconciliation passes (or
    one racing the periodic task) partition the work instead of double
    -writing the same row.
    """
    now = now or datetime.now(timezone.utc)
    reconciled: List[ReconciledSession] = []

    # P17 — background reconciliation, not a user request: scans every
    # tenant's abandoned sessions by design. See
    # db/tenancy.py::use_all_tenants's own docstring.
    async with all_tenants_session(session_factory) as db:
        rows = (
            await db.execute(
                select(RuntimeSessionRow)
                .where(RuntimeSessionRow.state.not_in(_TERMINAL_VALUES))
                .where(RuntimeSessionRow.token_expires_at.is_not(None))
                .where(RuntimeSessionRow.token_expires_at < now)
                .order_by(RuntimeSessionRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for row in rows:
            note = f"{_RECONCILE_NOTE_PREFIX} (token expired {row.token_expires_at.isoformat()})"
            row.failure_reason = "; ".join(p for p in (row.failure_reason, note) if p)
            row.state = "failed"
            reconciled.append(
                ReconciledSession(
                    session_id=row.session_id, mission_id=row.mission_id, token_expired_at=row.token_expires_at,
                )
            )

        if reconciled:
            await db.commit()
        else:
            await db.rollback()

    return reconciled
