"""
P19-lite — the one genuine Model-C engineering blocker identified by the
Model-C Decision Gate (docs/prime-agent-integration/31-model-c-decision-gate.md,
Phase 2): a permanently dead host's Docker/workspace resources had no safe
escalation path, because `orphan_sweep.py`'s `owner_host`/`node_id` filter
(P16) — correctly — never lets one host conclude another host's resource is
"absent" just because it is invisible from here.

WHAT THIS TABLE IS
-------------------
One row per live ADOS process host, upserted on every periodic-loop tick
(backend/app/main.py) with its own `node_id` (orchestrate/runtime/
orphan_sweep.py::effective_node_id) and the current time. Nothing else reads
or writes it except orchestrate/runtime/node_heartbeat.py's own two
functions. Deliberately NOT tenant data — a host's liveness has no tenant,
so this table is never wrapped in `db.tenancy.all_tenants_session` and is
never subject to tenant scoping at all.

WHY A ROW PER HOST IS ENOUGH TO ANSWER "IS THIS HOST GONE"
-------------------------------------------------------------
A host stops updating its row the moment its process is gone (killed,
crashed, the machine itself disappeared) — there is no separate shutdown
signal to fail to send, matching the same "detect staleness, do not wait for
a goodbye message" posture `admission_lease_reclaim.py` and
`session_reconcile.py` already use for their own resources. `last_seen_at`
older than a conservative, operator-tunable threshold
(`Settings.node_heartbeat_dead_after_seconds`) is the entire declared-dead
signal `orphan_sweep.claim_batch`'s widened cross-host claim depends on. See
that module's own docstring for how the claim itself stays safe once a host
is declared dead.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NodeHeartbeatRow(Base):
    __tablename__ = "node_heartbeats"

    # The same identity orphan_sweep.py already stamps onto
    # RuntimeSessionRow.owner_host — one row per distinct node_id, upserted
    # in place (never inserted twice), so "how many hosts have ever existed"
    # is not a question this table tries to answer; only "is this host
    # currently alive" is.
    node_id: Mapped[str] = mapped_column(primary_key=True)

    last_seen_at: Mapped[datetime] = mapped_column(default=_utcnow)
