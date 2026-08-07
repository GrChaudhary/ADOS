"""
Cleanup for orchestrate/onboarding/'s cloned-repo workdirs — the "no
eventual cleanup policy yet" gap flagged in the vault TODO. inspector.py's
own inspect() docstring explains why cloning is deliberately NOT
auto-cleaned inline: this is a conversational, multi-turn pipeline, and
synthesize()/sandbox_runner() need the same clone still on disk in a later
turn, potentially a separate process/request entirely. This module is the
piece that was missing: deciding *when* a clone's job is actually done, and
doing the deletion safely.

The two onboarding tracks that clone anything have genuinely different
workdir lifetimes, not one uniform TTL:

  - OPENAPI: local_path is only ever read during Turn 1 (classify) and
    Turn 2 (synthesize, which re-parses the spec file at
    report["openapi_spec_path"], a path inside local_path). Nothing
    downstream — not the sandbox test, not a live call — ever touches it
    again: wrapper_generator.synthesize_openapi_action's runtime dict has
    no local_path key at all, only method/path_template/base_url. Safe to
    delete the moment Turn 2 succeeds.
  - MCP_NATIVE / RAW_CODE: local_path is a PERMANENT runtime dependency
    once a capability reaches ACTIVATED — every live call re-hashes it
    (sandbox_runner._image_tag_for) to resolve the content-cached Docker
    image tag, and a cache-evicted image needs the same source again to
    rebuild. An activated session's workdir must NEVER be auto-deleted;
    there is no capability-teardown concept in this codebase yet (hot-
    disable/deprecate both keep the manifest, they don't delete it) that
    would make that safe.

Deliberately narrow in a second way too: this module only ever deletes a
workdir and marks the row `workdir_cleaned_up`. It never mutates `status`
or touches capability_manifests. A session stuck mid-flow past its TTL
might represent a genuinely abandoned attempt, but deciding to also
fail/hot-disable it is a separate, bigger product decision this cleanup
pass doesn't make on its own.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models.onboarding_session import OnboardingSessionRow

from .models import OnboardingSessionStatus, OnboardingTrack

_WORKDIR_PREFIX = "ados-onboarding-"
_DEFAULT_STALE_HOURS = 24
_ACTIVATED = OnboardingSessionStatus.ACTIVATED.value


def _stale_after_hours() -> int:
    # Read fresh on every call, not bound as a def-time default — same
    # reasoning as sandbox_runner._enforce_image_cache_limit's `limit`
    # param: a plain default argument is evaluated once at import, so a
    # test (or ops) patching the env var afterward would silently have no
    # effect on calls relying on the default.
    return int(os.environ.get("ADOS_ONBOARDING_WORKDIR_STALE_HOURS", str(_DEFAULT_STALE_HOURS)))


def _is_within_onboarding_tempdir(path: Path) -> bool:
    """Refuses to ever touch a path that isn't recognizably one of this
    pipeline's own tempfile.mkdtemp(prefix="ados-onboarding-") directories.
    In particular, an admin-supplied LOCAL directory path (inspector.
    _clone_or_fetch returns that path unchanged for a non-remote source —
    never a clone) must never be a deletion candidate; neither should
    tests/fixtures/* used directly as a source, which is exactly how this
    codebase's own onboarding tests exercise the MCP-native/raw_code
    tracks. A false "not safe" here just costs one permanently-orphaned
    directory; a false "safe" would delete a real, possibly load-bearing
    directory outside this pipeline's control — the same asymmetric-risk
    reasoning sandbox_runner._compute_build_context_hash already applies
    to its own cache-miss-vs-cache-hit choice (a false miss just costs a
    rebuild; a false hit serves stale code)."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.parent == Path(tempfile.gettempdir()).resolve() and resolved.name.startswith(_WORKDIR_PREFIX)


def workdir_no_longer_needed(track: Optional[str], status: str) -> bool:
    """Pure decision, no I/O — used for the immediate, event-triggered
    cleanup fired right at the turn where a workdir's need just ended (see
    capability_onboarding.py's Turn 1 classification-failure and Turn 2
    synthesize call sites). Deliberately stricter than
    sweep_stale_workdirs' own eligibility check below — this only ever
    says yes once a track's real, understood lifetime rule says the clone
    can never be needed again, not just "looks idle for a while"."""
    if status == _ACTIVATED:
        # MCP_NATIVE/RAW_CODE: never — permanent runtime dependency, see
        # module docstring. OPENAPI reaching ACTIVATED already had its
        # workdir cleaned back at synthesize() time, well before
        # activation, so this branch never actually fires for it in
        # practice — but the "never touch an ACTIVATED row" rule stays
        # unconditional on track, for safety.
        return False
    if track == OnboardingTrack.OPENAPI.value:
        return status not in (OnboardingSessionStatus.SUBMITTED.value, OnboardingSessionStatus.INSPECTED.value)
    # MCP_NATIVE / RAW_CODE / unclassified (track detection itself
    # failed): only safe once genuinely terminal without ever activating.
    return status in (OnboardingSessionStatus.FAILED.value, OnboardingSessionStatus.ABORTED.value)


def _local_path_for(row: OnboardingSessionRow) -> Optional[str]:
    report = row.inspection_report or {}
    return report.get("local_path")


def cleanup_workdir_for_row(row: OnboardingSessionRow) -> bool:
    """Best-effort, synchronous (plain shutil.rmtree, no subprocess) —
    returns True only if a directory was actually found and removed.
    Never raises: a permission error or a directory that's already gone
    both just mean "nothing more to do here," not a reason to fail
    whatever caller triggered this."""
    local_path = _local_path_for(row)
    if not local_path:
        return False
    path = Path(local_path)
    if not _is_within_onboarding_tempdir(path):
        return False
    try:
        if not path.is_dir():
            return False
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    except OSError:
        return False


async def cleanup_if_no_longer_needed(session_factory: async_sessionmaker, session_id: str) -> bool:
    """Called inline at the exact turn a session's workdir need just
    ended. Re-reads the row fresh rather than trusting a caller-passed
    one, since this always runs after the caller's own state-changing
    update already committed. A no-op (returns False) for any session
    whose track/status combination still might need the clone — safe to
    call unconditionally after every synthesize(), for every track,
    rather than branching in the router."""
    async with session_factory() as session:
        row = (
            await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id))
        ).scalar_one_or_none()
        if row is None or row.workdir_cleaned_up:
            return False
        if not workdir_no_longer_needed(row.track, row.status):
            return False
        cleaned = cleanup_workdir_for_row(row)
        if cleaned:
            row.workdir_cleaned_up = True
            session.add(row)
            await session.commit()
        return cleaned


async def sweep_stale_workdirs(session_factory: async_sessionmaker, *, stale_after_hours: Optional[int] = None) -> List[str]:
    """The 'eventual cleanup policy' the vault TODO flagged as missing —
    catches sessions abandoned mid-flow (e.g. INSPECTED/SYNTHESIZED/
    RISK_REVIEWED/SANDBOX_TESTED with no further activity), which is
    deliberately outside workdir_no_longer_needed's stricter, always-safe
    rule above: an abandoned session that never reached ACTIVATED has
    nothing depending on its clone regardless of which turn it stalled at,
    once enough time has passed that "still in progress" stops being a
    credible explanation. Age is measured off updated_at (bumped on every
    real turn), not created_at, so a session someone is actively working
    through slowly is never penalized. Never sweeps an ACTIVATED row,
    unconditionally, regardless of age — see module docstring. Returns the
    session ids actually cleaned, for a caller (e.g. an admin-triggered
    REST endpoint) to report back."""
    threshold_hours = _stale_after_hours() if stale_after_hours is None else stale_after_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)
    cleaned_ids: List[str] = []
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(OnboardingSessionRow).where(
                    OnboardingSessionRow.workdir_cleaned_up.is_(False),
                    OnboardingSessionRow.updated_at < cutoff,
                )
            )
        ).scalars().all()
        for row in rows:
            if row.status == _ACTIVATED:
                continue
            if cleanup_workdir_for_row(row):
                row.workdir_cleaned_up = True
                session.add(row)
                cleaned_ids.append(row.id)
        if cleaned_ids:
            await session.commit()
    return cleaned_ids
