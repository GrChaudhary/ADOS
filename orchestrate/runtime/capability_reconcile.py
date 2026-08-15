"""
P9 — reconciliation for `capability_requests` rows a crash or an ambiguous
external response left without a known outcome.

TWO SEPARATE JOBS, DELIBERATELY KEPT SEPARATE
-----------------------------------------------
1. `mark_stalled_executions_unknown` — a row can be found durably `executing`
   (orchestrate/runtime/capability_execution.py) with nothing ever completing
   it, because the ADOS process that would have written the final result died
   first. This function is the only thing that ever moves such a row forward,
   and it moves it to exactly one place: `outcome_unknown`. It never guesses
   at success or failure — there is no signal available to this function that
   would justify either.

2. `reconcile_outcome_unknown` — for a row already at `outcome_unknown` (via
   the function above, OR written there directly and synchronously by
   `_execute_capability` when a connector itself returns `CallStatus.UNKNOWN`
   — see mcp_gateway.py), asks the external system whether the action it
   describes actually happened, using ONLY the row's own canonical
   `request_id` — never a provenance block or marker text the agent's own
   capability arguments could have influenced. A positive match resolves the
   row to `executed`, recording exactly which external record it is, and
   creates nothing new. No match, or a query that could not be answered at
   all, leaves the row at `outcome_unknown` — reconciliation only ever adds
   certainty, never subtracts it by guessing.

`outcome_unknown` is otherwise a dead end on purpose: nothing in this
codebase transitions it to something an agent's retry or a human's approval
click can act on without going through this exact, evidence-gated path. See
docs/prime-agent-integration/18-production-readiness-review.md §9 for the
crash window this closes, and §11 for why automatic re-execution on a
NEGATIVE (not-found) reconciliation result is deliberately not built here —
a human decides that, by raising a fresh, distinct capability request, not by
reviving an ambiguous one.

SCHEDULING
----------
P9 deliberately left both functions manual-only (`scripts/reconcile_
capability_requests.py`, mirroring `scripts/sweep_orphans.py`'s own
precedent): the correctness fix (a row can no longer be silently
re-executed) never depended on either function running automatically — the
guard holds the moment a row reaches `executing`/`outcome_unknown`,
independent of whether anything ever resolves the ambiguity afterward.

P12 found that safety and Model B readiness are different bars: a
long-running service's audit trail should not depend on an operator
remembering to run a script. Both functions are now ALSO called
automatically, from the same centralized periodic loop
`backend/app/main.py::_reconcile_and_sweep_orphans_periodically` already
runs session/orphan cleanup from (one scheduler, not a second independent
loop). Nothing about the safety argument above changed to make this safe —
it was already true; P12 only added a second caller. `scripts/reconcile_
capability_requests.py` remains available for an operator who wants to run
either on demand, e.g. right after a known incident, without waiting for the
next tick.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from contracts import Capability
from db.models.mission import CapabilityRequestRow
from db.tenancy import all_tenants_session
from integrations.connectors.servicenow import ServiceNowConnector, _CAPABILITY_TABLE

from .capability_execution import (
    EXECUTION_STALL_SECONDS_DEFAULT,
    STATUS_EXECUTED,
    STATUS_EXECUTING,
    STATUS_OUTCOME_UNKNOWN,
)

logger = logging.getLogger("ados.capability_reconcile")

DEFAULT_RECONCILE_LIMIT = 50


@dataclass(frozen=True)
class StalledExecution:
    request_id: uuid.UUID
    session_id: uuid.UUID
    mission_id: uuid.UUID
    executing_since: datetime


@dataclass(frozen=True)
class ReconciliationOutcome:
    request_id: uuid.UUID
    resolved: bool  # True only when positive proof was found and the row now reads `executed`
    detail: str


async def mark_stalled_executions_unknown(
    session_factory,
    *,
    stall_seconds: float = EXECUTION_STALL_SECONDS_DEFAULT,
    limit: int = DEFAULT_RECONCILE_LIMIT,
    now: Optional[datetime] = None,
) -> List[StalledExecution]:
    """Finds rows stuck at `executing` whose own `updated_at` — stamped the
    instant that status was written, before any external call was ever
    attempted — is older than `stall_seconds`, and moves them to
    `outcome_unknown`.

    `SELECT ... FOR UPDATE SKIP LOCKED`, the same idiom every other
    concurrency-sensitive pass in this codebase uses (orphan_sweep.py,
    session_reconcile.py, runtime_approvals.py's decision lock): a row a live
    request is still legitimately holding mid-execution is SKIPPED, not
    stolen, so this can safely run concurrently with real traffic.

    P11: wrapped for `ados_reconciliation_runs_total{result}` — success means
    this pass RAN, not that it found or resolved anything (an empty pass is
    still a successful pass); failure means it raised, most plausibly a
    Postgres error, before it could reach its own commit/rollback.
    """
    from backend.app.metrics import reconciliation_runs_total

    try:
        stalled = await _mark_stalled_executions_unknown_impl(
            session_factory, stall_seconds=stall_seconds, limit=limit, now=now,
        )
    except Exception:
        reconciliation_runs_total.labels(result="failure").inc()
        raise
    reconciliation_runs_total.labels(result="success").inc()
    return stalled


async def _mark_stalled_executions_unknown_impl(
    session_factory,
    *,
    stall_seconds: float,
    limit: int,
    now: Optional[datetime],
) -> List[StalledExecution]:
    now = now or datetime.now(timezone.utc)
    stalled: List[StalledExecution] = []

    # P17 — this is a background reconciliation pass, not a user request; it
    # must scan every tenant's stalled/unknown rows by design. See
    # db/tenancy.py::use_all_tenants's own docstring for why that's safe:
    # this only ever transitions a status column or resolves against
    # externally-verified evidence, never returns tenant data to a caller.
    async with all_tenants_session(session_factory) as db:
        rows = (
            await db.execute(
                select(CapabilityRequestRow)
                .where(CapabilityRequestRow.status == STATUS_EXECUTING)
                .order_by(CapabilityRequestRow.updated_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for row in rows:
            since = row.updated_at
            if since is not None and since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            if since is None or (now - since).total_seconds() < stall_seconds:
                continue
            row.status = STATUS_OUTCOME_UNKNOWN
            note = (
                f"execution outcome unknown: no result was recorded within "
                f"{stall_seconds:.0f}s of the decision to execute (stalled since "
                f"{since.isoformat() if since else 'unknown'}) — the owning ADOS "
                f"process may have died before it could record what happened. "
                f"This request will not execute automatically again; it requires "
                f"reconciliation against the external system."
            )
            row.reason = "; ".join(p for p in (row.reason, note) if p)
            stalled.append(
                StalledExecution(
                    request_id=row.request_id, session_id=row.session_id,
                    mission_id=row.mission_id, executing_since=since,
                )
            )

        if stalled:
            await db.commit()
        else:
            await db.rollback()

    if stalled:
        logger.warning(
            "Capability executions stalled — moved to outcome_unknown",
            extra={"count": len(stalled), "request_ids": [str(s.request_id) for s in stalled]},
        )
        from backend.app.metrics import outcome_unknown_total
        outcome_unknown_total.inc(len(stalled))

    return stalled


def _record_matches_this_row(record: Dict[str, Any], request_id: uuid.UUID) -> bool:
    """A second, in-process check on top of the server-side `descriptionLIKE`
    query: ServiceNow's `LIKE` is a substring match, so this re-confirms the
    exact canonical id — not a prefix or an unrelated request that happens to
    share digits — actually appears in the field, using the same string the
    query searched for. Belt and suspenders around the one check this whole
    mechanism exists to get right.
    """
    haystack = f"{record.get('description', '')} {record.get('short_description', '')}"
    return str(request_id) in haystack


async def reconcile_outcome_unknown(
    session_factory,
    *,
    limit: int = DEFAULT_RECONCILE_LIMIT,
    connector: Optional[ServiceNowConnector] = None,
) -> List[ReconciliationOutcome]:
    """For each `outcome_unknown` row, searches the capability's mapped
    ServiceNow table for a record carrying this row's own `request_id` in its
    provenance. A match resolves the row to `executed` and records the
    match's own `sys_id`/`number` — reconciliation creates nothing; it only
    ever recognises what is already there.

    Capabilities with no ServiceNow table mapping (`_CAPABILITY_TABLE`) have
    no automated reconciliation path today and are left untouched — an honest
    "cannot reconcile this automatically" rather than a false "resolved".

    P11: wrapped for `ados_reconciliation_runs_total{result}` — same success/
    failure meaning as mark_stalled_executions_unknown above.
    """
    from backend.app.metrics import reconciliation_runs_total

    try:
        outcomes = await _reconcile_outcome_unknown_impl(session_factory, limit=limit, connector=connector)
    except Exception:
        reconciliation_runs_total.labels(result="failure").inc()
        raise
    reconciliation_runs_total.labels(result="success").inc()
    return outcomes


async def _reconcile_outcome_unknown_impl(
    session_factory,
    *,
    limit: int,
    connector: Optional[ServiceNowConnector],
) -> List[ReconciliationOutcome]:
    connector = connector or ServiceNowConnector()
    outcomes: List[ReconciliationOutcome] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    def _log_attempt(row: CapabilityRequestRow, found: bool, detail: str) -> None:
        """Every reconciliation pass over a row is durably recorded — found or
        not — so 'has anyone checked, and what did they see' is observable
        state (`row.result`), not something only a log line remembers. This
        is the "third case must be observable in durable ADOS state"
        requirement applied to the reconciliation process itself, not just to
        the row's own status.
        """
        attempts = list((row.result or {}).get("reconciliation_attempts") or [])
        attempts.append({"at": now_iso, "found": found, "detail": detail})
        row.result = {**(row.result or {}), "reconciliation_attempts": attempts}

    # P17 — this is a background reconciliation pass, not a user request; it
    # must scan every tenant's stalled/unknown rows by design. See
    # db/tenancy.py::use_all_tenants's own docstring for why that's safe:
    # this only ever transitions a status column or resolves against
    # externally-verified evidence, never returns tenant data to a caller.
    async with all_tenants_session(session_factory) as db:
        rows = (
            await db.execute(
                select(CapabilityRequestRow)
                .where(CapabilityRequestRow.status == STATUS_OUTCOME_UNKNOWN)
                .order_by(CapabilityRequestRow.updated_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for row in rows:
            try:
                capability = Capability(row.capability)
            except ValueError:
                _log_attempt(row, False, "unrecognized capability")
                outcomes.append(ReconciliationOutcome(row.request_id, False, "unrecognized capability"))
                continue

            table = _CAPABILITY_TABLE.get(capability)
            if table is None:
                detail = f"no automated reconciliation path for {capability.value}"
                _log_attempt(row, False, detail)
                outcomes.append(ReconciliationOutcome(row.request_id, False, detail))
                continue

            ok, records = await connector.find_by_request_id(table, str(row.request_id))
            if not ok:
                detail = "reconciliation query could not be answered"
                _log_attempt(row, False, detail)
                outcomes.append(ReconciliationOutcome(row.request_id, False, detail))
                continue

            matches = [r for r in records if _record_matches_this_row(r, row.request_id)]
            if not matches:
                detail = "no matching external record found"
                _log_attempt(row, False, detail)
                outcomes.append(ReconciliationOutcome(row.request_id, False, detail))
                continue

            match = matches[0]
            detail = f"resolved via existing record {match.get('number')} ({table}/{match.get('sys_id')})"
            _log_attempt(row, True, detail)
            row.status = STATUS_EXECUTED
            row.result = {
                **(row.result or {}),
                "reconciled": True,
                "reconciled_match": {
                    "table": table, "sys_id": match.get("sys_id"), "number": match.get("number"),
                },
            }
            row.reason = None
            outcomes.append(ReconciliationOutcome(row.request_id, True, detail))

        if rows:
            await db.commit()
        else:
            await db.rollback()

    if outcomes:
        resolved_count = sum(1 for o in outcomes if o.resolved)
        logger.info(
            "Reconciliation pass complete",
            extra={
                "checked": len(outcomes), "resolved": resolved_count,
                "still_unknown": len(outcomes) - resolved_count,
            },
        )

    return outcomes
