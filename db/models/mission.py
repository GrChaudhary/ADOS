"""
Mission, runtime session, and capability request — ADOS's side of the Prime
Agent runtime boundary, and the reason ADOS stays the system of record.

The split matters. Prime Agent owns its own session storage (a JSONL tree it
writes inside the disposable workspace) and ADOS deliberately does not try to
mirror it. What ADOS owns is everything an auditor would need after the
container is gone:

    missions             what was asked, what was granted, what came back
    runtime_sessions     which runtime ran it, under what identity, and how it ended
    capability_requests  every action the runtime asked for, and what ADOS decided

A runtime that dies, hangs, or lies cannot damage any of the above, because
none of it is written by the runtime. Capability rows in particular are written
by the gateway that executed the call — the agent's self-report is never the
source of truth.

See docs/prime-agent-integration/12-runtime-design-note.md.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .tenant import DEFAULT_TENANT_ID


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MissionRow(Base):
    """A unit of organizational work. Outlives any runtime that serves it."""

    __tablename__ = "missions"

    mission_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # P17 — the real security boundary db/tenancy.py enforces on every ORM
    # READ/UPDATE/DELETE against this table (never on INSERT — see
    # db/tenancy.py's own do_orm_execute filter). Defaults to the
    # well-known default tenant rather than refusing an unset value:
    # SQLAlchemy sends an explicit NULL for an unset non-Optional Mapped
    # column (verified against this exact model, not assumed), so "no
    # Python default" would mean every one of this codebase's existing
    # direct-construction test helpers breaks on a column those tests have
    # no interest in — the wrong cost for the wrong protection, since the
    # actual security boundary is the READ-side filter, not the INSERT
    # default. Every real production creation path (integrations/
    # connectors/prime_runtime.py, backend/app/mcp_gateway.py) sets this
    # explicitly regardless. See
    # docs/prime-agent-integration/28-multi-tenancy-and-tenant-isolation.md.
    tenant_id: Mapped[uuid.UUID] = mapped_column(default=DEFAULT_TENANT_ID)

    title: Mapped[str]
    objective: Mapped[str]
    domain: Mapped[str] = mapped_column(default="it")

    # The capability grant. This is the authoritative allow-list the MCP
    # gateway resolves on every request — the runtime never supplies it and
    # cannot widen it. Stored as capability *names* (Capability enum values).
    allowed_capabilities: Mapped[List[str]] = mapped_column(JSON, default=list)

    # pending | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(default="pending")

    # The case file: what ADOS knows about this mission that the runtime does
    # not. Reachable ONLY through the FetchIncidentEvidence capability, never
    # placed in the workspace — that distinction is the whole point. A runtime
    # handed its evidence up front can write a plausible report with a broken
    # kernel; a runtime that must fetch it cannot, and the missing capability
    # row is what tells ADOS the difference.
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=None)

    # The agent's final answer, captured from the runtime event stream before
    # the container is torn down (the workspace is disposable by design).
    # NARRATIVE, NOT EVIDENCE. Stored so a human can read what the agent
    # claimed; never consulted when deciding whether the mission succeeded.
    result: Mapped[Optional[str]] = mapped_column(default=None)
    failure_reason: Mapped[Optional[str]] = mapped_column(default=None)

    created_by: Mapped[str] = mapped_column(default="system")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class RuntimeSessionRow(Base):
    """One execution attempt of a mission on a runtime. A mission may have
    several over its life (retry, resume, a different runtime)."""

    __tablename__ = "runtime_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID]

    # P17 — denormalized from the owning mission at creation time (never
    # re-derived by a join), same reasoning as owner_host below: a query
    # against this table must be tenant-filterable on its own column, not
    # dependent on every caller remembering to join missions first. Default
    # rationale: see MissionRow.tenant_id above.
    tenant_id: Mapped[uuid.UUID] = mapped_column(default=DEFAULT_TENANT_ID)

    runtime: Mapped[str] = mapped_column(default="prime-agent")

    # created | starting | running | waiting_approval | completed | failed
    # | cancelled | torn_down   (see the state machine in the design note)
    state: Mapped[str] = mapped_column(default="created")

    # SHA-256 of the bearer token, never the token itself. The token is opaque
    # and identity-only: it names this row and carries no claims, so nothing
    # the container holds can be decoded or forged into a wider grant. Storing
    # only the hash means a database leak does not hand out live sessions.
    token_hash: Mapped[Optional[str]] = mapped_column(default=None)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    # Prime Agent's own session id, from its `session` event. Opaque to ADOS
    # and allowed to dangle — its storage lives in the disposable workspace.
    runtime_session_id: Mapped[Optional[str]] = mapped_column(default=None)
    container_name: Mapped[Optional[str]] = mapped_column(default=None)
    workspace_path: Mapped[Optional[str]] = mapped_column(default=None)

    # P16 — which ADOS process host created this session's real Docker/
    # workspace resources (Settings.node_id, normally the machine hostname).
    # NULL for every row written before this column existed, and treated by
    # orphan_sweep.py as "claimable by any sweeper" — the same posture a
    # single-host deployment already has, since there both would be the same
    # host anyway. Its only consumer is orphan_sweep.claim_batch's node_id
    # filter: a container/network/workspace can only ever be verified against
    # the local Docker daemon and local filesystem a sweeper actually has, so
    # a sweeper on a host that did not create this session must never
    # conclude its resources are "absent" just because they are invisible
    # from here. See docs/prime-agent-integration/27-multi-tenancy-and-multi-host-safety.md.
    owner_host: Mapped[Optional[str]] = mapped_column(default=None)

    # Normalized runtime events (runtime.tool.started, runtime.turn.completed,
    # …) kept as the mission's evidence trail.
    events: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Effects actually observed. `agent_end` alone does NOT mean success — a
    # model was seen returning agent_end with empty content, zero tool calls
    # and exit 0, having done nothing. Completion is asserted against these.
    tool_execution_count: Mapped[int] = mapped_column(default=0)
    capability_request_count: Mapped[int] = mapped_column(default=0)

    failure_reason: Mapped[Optional[str]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class CapabilityRequestRow(Base):
    """One capability the runtime asked ADOS for, and what ADOS decided.

    Written by the gateway, never by the runtime. This is the audit spine of
    the whole boundary: if a row says `executed`, ADOS executed it."""

    __tablename__ = "capability_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID]
    mission_id: Mapped[uuid.UUID]

    # P17 — denormalized from the owning session/mission at parking time.
    # This is the exact column the P16-demonstrated defect needed and did
    # not have: db/tenancy.py's global ORM filter uses this to make
    # list_capability_requests/get/approve/reject tenant-scoped without
    # requiring any of those call sites to remember a WHERE clause. Default
    # rationale: see MissionRow.tenant_id above.
    tenant_id: Mapped[uuid.UUID] = mapped_column(default=DEFAULT_TENANT_ID)

    capability: Mapped[str]
    arguments: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # pending_approval | executed | denied | failed
    status: Mapped[str] = mapped_column(default="pending_approval")

    policy_tier: Mapped[Optional[int]] = mapped_column(default=None)
    risk_class: Mapped[Optional[str]] = mapped_column(default=None)
    # Why a denial happened, in words the agent can act on.
    reason: Mapped[Optional[str]] = mapped_column(default=None)

    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=None)

    # Supplied by the runtime so a retried call returns the original result
    # instead of executing a second time. Scoped per session, not global.
    idempotency_key: Mapped[Optional[str]] = mapped_column(default=None)

    decided_by: Mapped[Optional[str]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
