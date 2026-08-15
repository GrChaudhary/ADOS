"""
The human half of the Prime Agent approval round trip.

A Tier 1/2 capability request from a runtime is parked by the MCP gateway as a
durable `capability_requests` row with `status='pending_approval'`, and the
gateway deliberately does NOT hold the agent's HTTP call open against a human's
attention span — the agent polls `get_capability_request`. Until these
endpoints existed, nothing ever moved such a row: `mcp_gateway.py` was the only
writer of that table and had no path out of `pending_approval`. Every Tier 1/2
request parked forever and the agent eventually raised `CapabilityTimeout`.

    runtime asks  ->  gateway parks the row  ->  HUMAN DECIDES HERE
                                                      |
                             approve -> executed via the gateway's own
                                        _execute_capability, audited, and the
                                        agent's next poll returns the result
                             reject  -> denied, with a reason, and no side effect

WHAT THIS FILE DELIBERATELY DOES NOT DO
---------------------------------------
**It does not execute anything itself.** Approval calls
`mcp_gateway._execute_capability` — the same choke point the autonomous path
uses, and the same one that writes the audit row. A second execution path here
would be a second place for a capability to become a real side effect, which is
exactly the shape of every false-success defect this integration has hit.

**It is not reachable by the runtime.** These are ADOS user endpoints behind
`get_current_user`, requiring a real JWT with a role. The runtime holds only an
opaque, identity-only session token that names a session and carries no claims,
and the MCP surface exposes no approve tool. An agent cannot release its own
Tier 1/2 request by any route, which is the entire point of parking it.

**It does not re-derive the tier.** The tier on the row was assigned by
`orchestrate/governance.py` when the request arrived. Recomputing it here would
let a later code change silently downgrade an already-parked request.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from db.session import get_db_session
from orchestrate.async_approvals import publish_approval_decision_event
from orchestrate.runtime.capability_execution import (
    STATUS_EXECUTED,
    STATUS_EXECUTING,
    STATUS_FAILED,
    STATUS_OUTCOME_UNKNOWN,
)

from ..auth import get_current_user
from ..mcp_gateway import _LIVE_STATES, _execute_capability
from ..rbac import User, authorize_governance_decision
from ..tenancy import get_tenant_context

logger = logging.getLogger("ados.runtime_approvals")

router = APIRouter(
    prefix="/runtime/capability-requests",
    tags=["runtime-approvals"],
    # P17 — get_tenant_context resolves the caller's active tenant and
    # scopes every ORM query below (db/tenancy.py's do_orm_execute filter)
    # to it automatically. This is the exact fix for the defect P16 proved
    # live: before this, every route here queried CapabilityRequestRow with
    # no ownership filter at all. No route body below changes as a result
    # -- a cross-tenant GET now 404s and a cross-tenant approve/reject now
    # 404s before ever reaching a decision, because the row is invisible to
    # the query, not because of a new explicit check.
    dependencies=[Depends(get_current_user), Depends(get_tenant_context)],
)


def _estimated_cost(row: CapabilityRequestRow) -> float:
    """What the runtime claimed this would cost, used for the approver's limit
    check. It is the same value `assign_policy_tier` used to decide the tier in
    the first place, so approver limits and tier assignment cannot disagree
    about what action they are talking about.

    Note this is the *agent's* number. It is not evidence of anything and is
    not treated as such — it only ever makes approval harder, never easier,
    because a larger claimed cost narrows the set of people who may approve.
    """
    try:
        return float((row.arguments or {}).get("_estimated_cost_usd", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _view(row: CapabilityRequestRow) -> Dict[str, Any]:
    return {
        "requestId": str(row.request_id),
        "missionId": str(row.mission_id),
        "sessionId": str(row.session_id),
        "capability": row.capability,
        "arguments": row.arguments,
        "status": row.status,
        "policyTier": row.policy_tier,
        "riskClass": row.risk_class,
        "estimatedCostUsd": _estimated_cost(row),
        "decidedBy": row.decided_by,
        "reason": row.reason,
        "result": row.result,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_capability_requests(
    status_filter: str = "pending_approval",
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """The approver's queue. Defaults to what is actually waiting on a human."""
    rows = (
        await session.execute(
            select(CapabilityRequestRow)
            .where(CapabilityRequestRow.status == status_filter)
            .order_by(CapabilityRequestRow.created_at)
        )
    ).scalars().all()
    return {"status": status_filter, "count": len(rows), "requests": [_view(r) for r in rows]}


@router.get("/{request_id}")
async def get_capability_request_detail(
    request_id: str, session: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    return _view(await _load_pending_or_404(session, request_id, require_pending=False))


async def _load_pending_or_404(
    session: AsyncSession, request_id: str, *, require_pending: bool = True
) -> CapabilityRequestRow:
    """Loads the row, taking a row lock when a decision is about to be made.

    `SELECT ... FOR UPDATE` rather than a plain read, because the
    already-decided check below is otherwise check-then-act: two approvers
    clicking at the same moment would both read `pending_approval` and both
    execute, and for `NotifyITHelpdesk` that is two real tickets.

    P9 UPDATE — the lock is no longer held across the external call. It used
    to be: this function's `FOR UPDATE` was taken and kept open for the
    entire duration of `approve_capability_request`, including the real HTTP
    request to the connector, so a concurrent second approval blocked (and
    then correctly 409'd) but an ADOS crash during that same window rolled
    the whole decision back — silently returning an already-decided-looking
    request to `pending_approval` even if the external effect had already
    happened. `approve_capability_request` now durably commits `executing`
    (releasing this lock) BEFORE making that call, and this function's own
    check — `require_pending and row.status != "pending_approval"` — is what
    makes `pending_approval` and "decided" (whether `executing`, `executed`,
    `failed`, or `outcome_unknown`) mutually exclusive from that commit
    onward, independent of whether the process survives what happens next.
    The `ados` skill's poll loop was updated alongside this to treat
    `executing` the same as `pending_approval` (keep polling), so an
    intermediate, non-final status was exactly the objection this design
    used to have and no longer does — see
    infrastructure/prime-runtime/ados_skill/src/ados/__init__.py.
    """
    try:
        request_uuid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed request_id")

    query = select(CapabilityRequestRow).where(CapabilityRequestRow.request_id == request_uuid)
    if require_pending:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no such capability request")
    if require_pending and row.status != "pending_approval":
        # 409, not 200. Deciding an already-decided request must not execute it
        # a second time — a double approval of `NotifyITHelpdesk` would raise
        # two real tickets, and of a payment capability, worse.
        #
        # P15 — the FOR UPDATE lock above (query.with_for_update()) is what
        # makes this branch reachable at all under real concurrency: without
        # it, two racing decisions could both read 'pending_approval' and
        # both pass this check (proven live, as a negative control, in
        # scripts/p15_multiprocess_concurrency_proof.py's Case 1). The
        # metric below is this branch's own observability — previously a
        # 409 with no Prometheus signal, a genuine gap this phase's Phase 10
        # review found (its own required signal list names "duplicate
        # approval refusal" explicitly).
        from ..metrics import authorization_denials_total
        authorization_denials_total.labels(reason="already_decided").inc()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"request is already '{row.status}' and cannot be decided again",
        )
    return row


async def _live_session_or_409(
    session: AsyncSession, row: CapabilityRequestRow
) -> RuntimeSessionRow:
    """A dead session's parked request must not execute.

    The agent that asked is gone: the container is torn down, its workspace
    deleted, and nothing will consume the result. Executing anyway would create
    a real external side effect on behalf of a mission that already ended, and
    no one would be watching for it. Refusing is the honest outcome, and it is
    visible rather than silent.
    """
    runtime_session = await session.get(RuntimeSessionRow, row.session_id)
    if runtime_session is None:
        raise HTTPException(status_code=404, detail="the runtime session no longer exists")
    if runtime_session.state not in _LIVE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"runtime session is '{runtime_session.state}' — the agent that requested this "
                "is gone, so approving would act with nobody waiting for the result"
            ),
        )
    return runtime_session


def _confirm_token_expiry_recorded_or_409(runtime_session: RuntimeSessionRow) -> None:
    """P10: `state` alone is not proof of liveness for a session whose token
    was never given an expiry. Every session created by the real path
    (integrations/connectors/prime_runtime.py) has set token_expires_at
    unconditionally since P6-D — a NULL here means this row did not come
    from a currently-live mission at all (a pre-P6-D fossil, or a
    debugging tool that bypassed the real creation path; see
    docs/prime-agent-integration/18-production-readiness-review.md §16).
    Re-derivation during P10 found such a row's own `state` was still
    `running` long after its process died, with parked requests sitting
    genuinely approvable through this endpoint — a session `_live_session_
    or_409` alone would have called "live". This does not reinterpret the
    session row's own lifecycle meaning (state and token_expires_at are
    both left exactly as they are); it only refuses to let APPROVAL — the
    one action here with a real external side effect — treat "state says
    running" as sufficient proof when the one thing that could ever have
    made that state expire never existed.

    Deliberately NOT folded into `_live_session_or_409` and NOT applied to
    reject: rejecting has no side effect and must remain available as the
    way to close exactly this kind of stale request — the same fossil rows
    this check is about were closed, during P10, by rejecting them.
    """
    if runtime_session.token_expires_at is None:
        from ..metrics import token_expiry_refusals_total
        token_expiry_refusals_total.inc()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "runtime session has no recorded token expiry and cannot be confirmed live — "
                "refusing to approve a request that cannot be proven to have an active caller"
            ),
        )


async def _release_session_if_nothing_else_pending(
    session: AsyncSession, runtime_session: RuntimeSessionRow
) -> None:
    """Back to 'running' only when this session has nothing else parked.

    A session may have more than one request awaiting a human, and flipping the
    state on the first decision would misreport the others as unblocked.
    """
    remaining = (
        await session.execute(
            select(CapabilityRequestRow).where(
                CapabilityRequestRow.session_id == runtime_session.session_id,
                CapabilityRequestRow.status == "pending_approval",
            )
        )
    ).scalars().all()
    if not remaining and runtime_session.state == "waiting_approval":
        runtime_session.state = "running"


@router.post("/{request_id}/approve")
async def approve_capability_request(
    request_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Release a parked request, and execute it through the governed path.

    P9: THREE COMMITS, NOT ONE
    ----------------------------
    This used to be a single transaction spanning the entire external call —
    the `SELECT ... FOR UPDATE` lock, the decision, AND the connector's real
    HTTP request all inside one still-open transaction, nothing durable
    written until the very end. If ADOS died anywhere in that window, the
    transaction rolled back to `pending_approval` in full — even if the
    external system had already acted. A second approval, or the agent's own
    retry, would then execute it again: a real duplicate side effect. See
    docs/prime-agent-integration/18-production-readiness-review.md §9.

    Phase 1 (below) durably commits `executing` — with the decider's identity
    already on the row — BEFORE the external call. That commit is what makes
    "already decided" true regardless of what happens next: a concurrent or
    later approval attempt sees anything other than `pending_approval` and is
    refused (`_load_pending_or_404`'s existing check, unchanged). Phase 2 is
    the external call itself, with no transaction open. Phase 3 durably
    records the real, tri-state outcome. A crash between phase 1 and phase 3
    leaves the row at `executing`, never silently re-approvable; a later pass
    over stalled `executing` rows (orchestrate/runtime/capability_reconcile.py)
    is the only thing that ever moves it further, and only ever to
    `outcome_unknown` — never back to something executable.
    """
    row = await _load_pending_or_404(session, request_id)
    runtime_session = await _live_session_or_409(session, row)
    _confirm_token_expiry_recorded_or_409(runtime_session)

    authorize_governance_decision(
        current_user,
        policy_tier=row.policy_tier or 0,
        estimated_cost_usd=_estimated_cost(row),
        subject="runtime capability request",
    )

    mission = await session.get(MissionRow, row.mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="the mission no longer exists")
    # The grant is re-checked at decision time, not trusted from when the
    # request was parked. A mission's grant can be narrowed while a request
    # waits, and the narrower answer must win.
    if row.capability not in set(mission.allowed_capabilities or []):
        row.status = "denied"
        row.decided_by = f"user:{current_user.username}"
        row.reason = (
            f"'{row.capability}' is no longer in this mission's capability grant; "
            "approval refused"
        )
        await _release_session_if_nothing_else_pending(session, runtime_session)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=row.reason)

    from contracts import PolicyTier  # local: keeps the module import graph flat

    # --- Phase 1: durable decision, before any external effect -------------
    row.status = STATUS_EXECUTING
    row.decided_by = f"user:{current_user.username}"
    await _release_session_if_nothing_else_pending(session, runtime_session)
    await session.commit()

    # --- Phase 2: the external call, no transaction/lock held --------------
    result = await _execute_capability(
        row.capability,
        row.arguments or {},
        mission_id=row.mission_id,
        tier=PolicyTier(row.policy_tier or 0),
        request_id=row.request_id,
        approved_by=current_user.username,
    )
    outcome_status = result.get("outcome_status", STATUS_FAILED)

    # --- Phase 3: durable result --------------------------------------------
    await session.refresh(row)
    if row.status != STATUS_EXECUTING:
        # Something else already resolved this row while the call above was
        # in flight — a reconciliation pass concluding it was stalled, most
        # plausibly. Overwriting that with a now-late result here would be
        # exactly the "silently return to an executable-looking state"
        # mistake this phase exists to prevent. The real outcome is not
        # lost — it is logged — but the row's own durable state, decided by
        # an independent process, wins.
        logger.warning(
            "Capability execution completed after its request row was "
            "independently resolved elsewhere; the row's own state is kept",
            extra={"request_id": str(row.request_id), "row_status": row.status, "late_outcome": outcome_status},
        )
        return _view(row)

    # Written from the executor's own answer, exactly as the autonomous path
    # does. "The approver said yes" is not "the action succeeded".
    row.status = outcome_status
    row.result = result
    row.reason = None if outcome_status == STATUS_EXECUTED else result.get("error")
    await session.commit()
    await session.refresh(row)

    if outcome_status == STATUS_OUTCOME_UNKNOWN:
        # P10: same signal as the autonomous path's own — see
        # mcp_gateway.py's identical log line for why this needs to be
        # visible outside the database, not just in row.status.
        logger.warning(
            "Capability execution outcome unknown — requires reconciliation",
            extra={"request_id": str(row.request_id), "capability": row.capability},
        )

    await publish_approval_decision_event(
        task_id=str(row.request_id),
        decision="approved",
        approved_by=current_user.username,
        role=current_user.role.value,
        bus=getattr(request.app.state, "event_bus", None),
    )
    return _view(row)


@router.post("/{request_id}/reject")
async def reject_capability_request(
    request_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> Dict[str, Any]:
    """Refuse a parked request. Nothing executes, and the agent is told why."""
    row = await _load_pending_or_404(session, request_id)
    runtime_session = await _live_session_or_409(session, row)

    authorize_governance_decision(
        current_user,
        policy_tier=row.policy_tier or 0,
        estimated_cost_usd=_estimated_cost(row),
        subject="runtime capability request",
    )

    given = (body or {}).get("reason") or "no reason given"
    row.status = "denied"
    row.decided_by = f"user:{current_user.username}"
    row.reason = f"rejected by {current_user.username}: {given}"
    # `result` stays None. There is no outcome to report because nothing ran,
    # and writing a success-shaped payload here is the exact false-success the
    # rest of this system is built to prevent.
    await _release_session_if_nothing_else_pending(session, runtime_session)
    await session.commit()
    await session.refresh(row)

    await publish_approval_decision_event(
        task_id=str(row.request_id),
        decision="rejected",
        approved_by=current_user.username,
        role=current_user.role.value,
        bus=getattr(request.app.state, "event_bus", None),
    )
    return _view(row)
