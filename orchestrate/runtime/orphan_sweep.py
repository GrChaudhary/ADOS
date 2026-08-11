"""
Orphan sweep — safely discovers and removes Docker/workspace resources a
terminated runtime session's teardown could not remove.

THE CURRENT CLEANUP CONTRACT THIS BUILDS ON (surveyed, not modified)
----------------------------------------------------------------------
`PrimeAgentRuntime.teardown()` / `EgressBoundary.teardown()` (prime.py,
egress.py) already attempt every resource independently and return a
`List[str]` of what survived — human-readable strings like
`"container ados-prime-abc123: <docker error>"` or
`"workspace /var/.../ados-mission-xxxx"`. `integrations/connectors/
prime_runtime.py`'s `_finalize_session` folds that list into
`RuntimeSessionRow.failure_reason` as `"orphaned <item>; orphaned <item>"`
prose. That is the entire existing "orphan recording": one free-text column,
nothing structured, nothing consuming it. The producer side is deliberately
untouched here — existing P6-D tests assert the `List[str]` shape directly,
and this module does not need it to change to do its job.

WHAT THIS MODULE ADDS
----------------------
A consumer that:

  1. finds terminal sessions (`state` in `TERMINAL_STATES` —
     orchestrate/runtime/base.py) whose `failure_reason` records an orphan;
  2. recomputes that session's full candidate resource set DETERMINISTICALLY
     from data ADOS itself already persisted — `container_name` and
     `workspace_path`, plus the same suffix/naming functions `egress.py` uses
     to name the relay and the two per-session networks — rather than parsing
     the diagnostic prose. A caller of this module can never supply a
     resource name or path; every candidate traces back to one session row;
  3. verifies each candidate against the real Docker daemon / filesystem
     before ever deleting anything: a Docker resource must carry the
     `ados.session_id` label (egress.py) matching this exact session, and a
     workspace path must resolve under the system temp root with the
     `ados-mission-` prefix — a name or path that merely looks right is
     refused, not swept;
  4. records what happened as new entries on the session's own `events`
     column (already a JSON audit trail — no schema migration needed), so a
     second sweep is a safe no-op and a failed attempt stays retryable.

WHY EVENTS, NOT A NEW COLUMN
------------------------------
`RuntimeSessionRow.events` already exists and already is exactly this: an
append-only, structured, per-session record nothing erases. Adding a new
column here would mean a migration landing on top of unrelated, uncommitted
migration work this phase was explicitly told not to touch. Reusing `events`
keeps this module's entire footprint additive.

CONCURRENCY
-----------
Two phases, deliberately not one. `claim_batch` runs inside a short
transaction using `SELECT ... FOR UPDATE SKIP LOCKED` on the session row — the
same idiom `runtime_approvals.py` uses to guard the approval decision — so two
sweepers racing on the same row never both claim it; whichever loses just
skips to the next row rather than blocking. It appends `orphan_sweep.claimed`
events and commits immediately: the slow part (real Docker/filesystem calls)
happens in `process_claimed`, entirely OUTSIDE any transaction. `finalize_batch`
then reopens a short transaction per session to write final outcomes. A claim
that is never finalized (its sweeper crashed mid-Docker-call) is not stuck
forever: `CLAIM_LEASE_SECONDS` bounds how long a `claimed` event blocks a
retry before a later sweep is allowed to reclaim it. No literal grace period
beyond that lease exists or is needed — a session's orphan is only ever
recorded once teardown has already been attempted and failed, so there is
nothing to wait out.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select

from db.models.mission import RuntimeSessionRow

from .base import TERMINAL_STATES
from .egress import LABEL_SESSION, _SAFE_SUFFIX

_TERMINAL_VALUES = {s.value for s in TERMINAL_STATES}

#: The existing, unmodified producer-side signal (see module docstring).
ORPHAN_MARKER = "orphaned"

#: How long a `claimed` event blocks a resource from being reclaimed by a
#: different sweep before it is treated as abandoned. Long enough to cover a
#: real `docker rm`/`docker network rm` (each individually timeboxed to well
#: under a minute elsewhere in this codebase); bounded rather than open-ended
#: so a sweeper that dies mid-operation does not orphan the orphan record.
CLAIM_LEASE_SECONDS_DEFAULT = 300.0

#: One sweep pass claims at most this many sessions. "Bounded" is a stated
#: requirement, not an incidental default — an unbounded sweep is a different,
#: unreviewed feature (a background job) that this phase was explicitly told
#: not to build.
DEFAULT_CLAIM_LIMIT = 50


@dataclass(frozen=True)
class Candidate:
    """One resource a session *might* still have lying around. Always
    constructed from a session row's own persisted fields — never from a
    caller."""

    kind: str  # "container" | "relay" | "network_internal" | "network_egress" | "workspace"
    name: str  # a docker resource name, or an absolute workspace path


@dataclass(frozen=True)
class ClaimedItem:
    session_id: uuid.UUID
    kind: str
    name: str
    sweep_id: str


@dataclass(frozen=True)
class Outcome:
    item: ClaimedItem
    status: str  # "cleaned" | "absent" | "failed" | "refused"
    detail: str


@dataclass(frozen=True)
class SweepReport:
    sweep_id: str
    claimed: int
    outcomes: List[Outcome]

    @property
    def cleaned(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "cleaned")

    @property
    def absent(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "absent")

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "failed")

    @property
    def refused(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "refused")


_DOCKER_KINDS = {"container", "relay", "network_internal", "network_egress"}


def candidates_for_session(row: RuntimeSessionRow) -> List[Candidate]:
    """The full deterministic candidate set for one session — recomputed from
    columns ADOS itself wrote, using the exact naming functions `egress.py`
    used to create them. This is why the sweeper never has to parse
    `failure_reason`: it already knows every name a session's teardown could
    have left behind, whether or not that specific one actually leaked."""
    suffix = _SAFE_SUFFIX.sub("", str(row.session_id))[:24]
    out: List[Candidate] = []
    if row.container_name:
        out.append(Candidate("container", row.container_name))
    out.append(Candidate("relay", f"ados-relay-{suffix}"))
    out.append(Candidate("network_internal", f"ados-rt-{suffix}"))
    out.append(Candidate("network_egress", f"ados-rt-out-{suffix}"))
    if row.workspace_path:
        out.append(Candidate("workspace", row.workspace_path))
    return out


def _latest_sweep_status(events: Sequence[Dict[str, Any]], kind: str, name: str) -> Optional[Dict[str, Any]]:
    """The most recent `orphan_sweep.*` event for this exact (kind, name),
    or None if this candidate has never been touched by a sweep. Events are
    always appended in order (see finalize_batch/claim_batch), so the last
    match in list order is the current status."""
    latest = None
    for event in events or []:
        etype = event.get("type", "")
        if not etype.startswith("orphan_sweep."):
            continue
        detail = event.get("detail") or {}
        if detail.get("kind") == kind and detail.get("name") == name:
            latest = event
    return latest


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _eligible_for_claim(
    events: Sequence[Dict[str, Any]], kind: str, name: str, *, now: datetime, lease_seconds: float
) -> bool:
    """`cleaned` and `absent` are both terminal — never reclaimed. A resource
    that was already gone the moment it was checked has just as surely
    finished sweeping as one this process actually removed; treating only
    `cleaned` as terminal would make every already-clean candidate (the
    common case: most of a session's candidate set never really leaked)
    reclaimed forever, on every single sweep, indefinitely.

    Anything else (never attempted, failed, refused, or a claim whose lease
    has expired) is eligible again. A live, unexpired claim is not — that is
    the one thing this function exists to refuse, since it is what keeps two
    sweepers from double-processing the same resource."""
    status = _latest_sweep_status(events, kind, name)
    if status is None:
        return True
    if status["type"] in ("orphan_sweep.cleaned", "orphan_sweep.absent"):
        return False
    if status["type"] == "orphan_sweep.claimed":
        claimed_at = _parse_iso(status["at"])
        return (now - claimed_at).total_seconds() >= lease_seconds
    # failed / refused: safe and cheap to re-check next sweep.
    return True


async def claim_batch(
    session_factory,
    *,
    limit: int = DEFAULT_CLAIM_LIMIT,
    lease_seconds: float = CLAIM_LEASE_SECONDS_DEFAULT,
    sweep_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[ClaimedItem]:
    """Phase 1 — the only phase that touches the database transactionally.

    `with_for_update(skip_locked=True)` claims whichever matching session rows
    are not currently locked by a concurrent sweep; a row already held by
    another sweeper is skipped, not waited on, so two sweepers running at once
    partition the work instead of serializing behind each other.
    """
    sweep_id = sweep_id or str(uuid.uuid4())
    now = now or datetime.now(timezone.utc)
    claimed: List[ClaimedItem] = []

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(RuntimeSessionRow)
                .where(RuntimeSessionRow.state.in_(_TERMINAL_VALUES))
                .where(RuntimeSessionRow.failure_reason.ilike(f"%{ORPHAN_MARKER}%"))
                .order_by(RuntimeSessionRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        any_claimed = False
        for row in rows:
            events = list(row.events or [])
            row_claimed_any = False
            for candidate in candidates_for_session(row):
                if not _eligible_for_claim(events, candidate.kind, candidate.name, now=now, lease_seconds=lease_seconds):
                    continue
                events.append(
                    {
                        "type": "orphan_sweep.claimed",
                        "at": now.isoformat(),
                        "detail": {"kind": candidate.kind, "name": candidate.name, "sweep_id": sweep_id},
                    }
                )
                claimed.append(ClaimedItem(session_id=row.session_id, kind=candidate.kind, name=candidate.name, sweep_id=sweep_id))
                row_claimed_any = True
            if row_claimed_any:
                row.events = events  # reassign (not in-place mutate) so SQLAlchemy tracks the change
                any_claimed = True

        if any_claimed:
            await db.commit()
        else:
            await db.rollback()

    return claimed


# --- Docker inspection / removal --------------------------------------------


async def _run(*args: str, timeout: float = 60.0):
    import asyncio
    import subprocess as _subprocess

    proc = await asyncio.create_subprocess_exec(*args, stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, f"timed out: {' '.join(args)}"
    return proc.returncode, out.decode(errors="replace")


def _inspect_format(kind: str) -> List[str]:
    if kind == "network_internal" or kind == "network_egress":
        return ["docker", "network", "inspect", "-f", '{{index .Labels "' + LABEL_SESSION + '"}}']
    return ["docker", "inspect", "-f", '{{index .Config.Labels "' + LABEL_SESSION + '"}}']


async def _docker_label(kind: str, name: str) -> Optional[str]:
    """None means the resource does not exist. Otherwise the value of its
    `ados.session_id` label (which may be the empty string if the resource
    exists but was never labelled by ADOS at all — treated as a mismatch by
    the caller, never as a match)."""
    code, out = await _run(*_inspect_format(kind), name, timeout=20.0)
    if code != 0:
        return None
    return out.strip()


async def _docker_remove(kind: str, name: str) -> tuple[bool, str]:
    if kind == "network_internal" or kind == "network_egress":
        code, out = await _run("docker", "network", "rm", name, timeout=30.0)
    else:
        code, out = await _run("docker", "rm", "-f", name, timeout=60.0)
    if code != 0 and "no such" not in out.lower() and "not found" not in out.lower():
        return False, out.strip()[:300]
    return True, ""


async def _process_docker(item: ClaimedItem) -> Outcome:
    label = await _docker_label(item.kind, item.name)
    if label is None:
        return Outcome(item, "absent", "already gone")
    if label != str(item.session_id):
        return Outcome(
            item, "refused",
            f"ownership label mismatch: expected session {item.session_id}, found {label!r}",
        )
    ok, err = await _docker_remove(item.kind, item.name)
    if not ok:
        return Outcome(item, "failed", err)
    still_there = await _docker_label(item.kind, item.name)
    if still_there is not None:
        return Outcome(item, "failed", "still present after removal attempt")
    return Outcome(item, "cleaned", "removed")


# --- Workspace directories ---------------------------------------------------

_WORKSPACE_PREFIX = "ados-mission-"


def _workspace_path_ok(path: Path) -> bool:
    """Mirrors orchestrate/onboarding/cleanup.py's `_is_within_onboarding_tempdir`:
    refuses anything that is not recognizably one of THIS project's own
    `tempfile.mkdtemp(prefix="ados-mission-...")` directories directly under
    the system temp root. A candidate here was already built from a session's
    own `workspace_path` column, never from caller input — this is a second,
    independent check on top of that, not the only one."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.parent == Path(tempfile.gettempdir()).resolve() and resolved.name.startswith(_WORKSPACE_PREFIX)


async def _process_workspace(item: ClaimedItem) -> Outcome:
    path = Path(item.name)
    if not _workspace_path_ok(path):
        return Outcome(item, "refused", f"path fails workspace-root/naming validation: {path}")
    if not path.exists():
        return Outcome(item, "absent", "already gone")
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        return Outcome(item, "failed", "rmtree left the directory behind")
    return Outcome(item, "cleaned", "removed")


async def _process_one(item: ClaimedItem) -> Outcome:
    try:
        if item.kind == "workspace":
            return await _process_workspace(item)
        if item.kind in _DOCKER_KINDS:
            return await _process_docker(item)
        return Outcome(item, "refused", f"unrecognized kind {item.kind!r}")
    except Exception as exc:  # noqa: BLE001 — one failure must never abort the batch
        return Outcome(item, "failed", f"{type(exc).__name__}: {exc}")


async def process_claimed(items: Sequence[ClaimedItem]) -> List[Outcome]:
    """Phase 2 — no database transaction is open here. Every item is
    attempted independently: a timeout or error on one resource must not
    prevent the rest from being attempted, the exact failure mode P6-D fixed
    in the original teardown path (see prime.py's teardown() docstring)."""
    return [await _process_one(item) for item in items]


async def finalize_batch(session_factory, outcomes: Sequence[Outcome]) -> None:
    """Phase 3 — one short transaction per affected session, writing the
    final outcome for each item this pass processed. Never removes a prior
    event: `cleaned` becomes the new latest status for that (kind, name) and
    is therefore terminal, but the `claimed` event (and any earlier `failed`/
    `refused` ones) stay in the list as history."""
    by_session: Dict[uuid.UUID, List[Outcome]] = {}
    for outcome in outcomes:
        by_session.setdefault(outcome.item.session_id, []).append(outcome)

    if not by_session:
        return

    async with session_factory() as db:
        for session_id, items in by_session.items():
            row = (
                await db.execute(
                    select(RuntimeSessionRow).where(RuntimeSessionRow.session_id == session_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                continue
            events = list(row.events or [])
            now_iso = datetime.now(timezone.utc).isoformat()
            for outcome in items:
                events.append(
                    {
                        "type": f"orphan_sweep.{outcome.status}",
                        "at": now_iso,
                        "detail": {
                            "kind": outcome.item.kind,
                            "name": outcome.item.name,
                            "note": outcome.detail,
                            "sweep_id": outcome.item.sweep_id,
                        },
                    }
                )
            row.events = events
        await db.commit()


async def sweep_once(
    session_factory,
    *,
    limit: int = DEFAULT_CLAIM_LIMIT,
    lease_seconds: float = CLAIM_LEASE_SECONDS_DEFAULT,
    sweep_id: Optional[str] = None,
) -> SweepReport:
    """The one public entry point. Claim, process, finalize — bounded to
    `limit` sessions, safe to call repeatedly (idempotent), safe to call
    concurrently with another in-flight sweep (see module docstring)."""
    sweep_id = sweep_id or str(uuid.uuid4())
    claimed = await claim_batch(session_factory, limit=limit, lease_seconds=lease_seconds, sweep_id=sweep_id)
    outcomes = await process_claimed(claimed)
    await finalize_batch(session_factory, outcomes)
    return SweepReport(sweep_id=sweep_id, claimed=len(claimed), outcomes=outcomes)
