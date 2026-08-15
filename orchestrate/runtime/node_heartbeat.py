"""
Dead-host reclamation — the one genuine Model-C engineering blocker named by
the Model-C Decision Gate (docs/prime-agent-integration/
31-model-c-decision-gate.md, Phase 2). Two small functions on top of
`node_heartbeats` (db/models/node_heartbeat.py):

  - `record_heartbeat` — called once per periodic-loop tick
    (backend/app/main.py) by every live process, upserting its own row.
  - `declared_dead_node_ids` — called on the same tick to find every OTHER
    node whose heartbeat has gone stale past a conservative threshold.

WHY THIS IS SAFE TO FEED INTO orphan_sweep.claim_batch
----------------------------------------------------------
`claim_batch`'s existing node_id filter (P16) already refuses to let host A
claim host B's resources, for a documented reason: host A's local Docker
daemon can never distinguish "host B's container was already removed" from
"host B's container is alive and simply not visible from here" — both look
like `_docker_label` returning None. Widening the claim to include a
declared-dead host's rows does NOT change that fact; it only changes what a
sweeper is allowed to conclude once it claims one. `orphan_sweep.py`'s
`_process_one` never runs a real Docker/filesystem check against a
cross-host candidate (see `ClaimedItem.via_dead_host_reclaim`) — it records
an honest `unverifiable` outcome instead. That is the entire safety
property: reclamation here means "close the bookkeeping on a host we have
conservatively concluded is never coming back," never "we proved the
resource is gone," and never "re-run anything." Sessions eligible for the
sweep are already terminal (`TERMINAL_STATES`) — there is nothing to
re-execute.

A host that is merely partitioned (network to Postgres severed, but the
host and its real Docker resources are still very much alive) can be
wrongly declared dead by this mechanism. The consequence is bounded to a
Docker/workspace resource leak on that host until it recovers and its own
sweeper (once reconnected) processes its own sessions again — never a
duplicate mission execution, never a lost safety guarantee. The existing
token-expiry fencing (session_reconcile.py, mcp_gateway.py's
`_resolve_session`) is completely unchanged by this module and continues to
be what actually prevents a revived host from taking any unsafe *action* —
this module only ever touches cleanup bookkeeping, never approval or
execution state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.models.node_heartbeat import NodeHeartbeatRow

#: Conservative on purpose: comfortably above a few missed
#: `orphan_reconcile_interval_seconds` ticks (default 300s) so a host that is
#: merely slow, briefly GC-paused, or transiently partitioned from Postgres
#: is never declared dead — only one that has been silent for a long,
#: sustained period is. Operator-tunable (Settings.node_heartbeat_dead_after_seconds)
#: for deployments with a different real tick interval.
DEFAULT_DEAD_AFTER_SECONDS = 900.0


async def record_heartbeat(session_factory, node_id: str, *, now: Optional[datetime] = None) -> None:
    """Upsert this host's own row. Called every periodic-loop tick — never
    conditionally, never skipped — so a host's absence from this table is
    always a true statement about how long ago it last ran a tick, not an
    artifact of when it happened to start."""
    now = now or datetime.now(timezone.utc)
    stmt = insert(NodeHeartbeatRow).values(node_id=node_id, last_seen_at=now)
    stmt = stmt.on_conflict_do_update(index_elements=["node_id"], set_={"last_seen_at": now})
    async with session_factory() as db:
        await db.execute(stmt)
        await db.commit()


async def declared_dead_node_ids(
    session_factory,
    *,
    dead_after_seconds: float = DEFAULT_DEAD_AFTER_SECONDS,
    exclude_node_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[str]:
    """Every node_id whose last heartbeat is older than `dead_after_seconds`
    — the entire declared-dead signal. `exclude_node_id` is a defense-in-depth
    guard (this host can never be its own dead-host trigger, independent of
    whether it happens to have written its own row yet this tick) — the
    caller in backend/app/main.py always passes its own node_id."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=dead_after_seconds)
    query = select(NodeHeartbeatRow.node_id).where(NodeHeartbeatRow.last_seen_at < cutoff)
    if exclude_node_id is not None:
        query = query.where(NodeHeartbeatRow.node_id != exclude_node_id)
    async with session_factory() as db:
        rows = (await db.execute(query)).scalars().all()
    return list(rows)
