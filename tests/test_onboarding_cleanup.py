"""
orchestrate/onboarding/cleanup.py — the "eventual cleanup policy" the
vault TODO flagged as missing for onboarding sessions' cloned-repo
workdirs. Uses real Postgres for the DB-backed cleanup_if_no_longer_needed/
sweep_stale_workdirs tests, matching test_onboarding_runtime_registry.py's
own precondition; the pure-decision and filesystem-guard tests need
neither Docker nor Postgres.
"""

import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow
from orchestrate.onboarding import cleanup


@pytest.fixture(autouse=True)
async def _clean_table():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE onboarding_sessions CASCADE"))
        await session.commit()
    yield


def _make_row(*, track, status, local_path, workdir_cleaned_up=False, updated_at=None) -> OnboardingSessionRow:
    now = datetime.now(timezone.utc)
    return OnboardingSessionRow(
        id=str(uuid.uuid4()),
        track=track,
        status=status,
        source_url="https://example.com/some/repo",
        domain="hr" if track else None,
        capability_id="some.capability" if track else None,
        selected_tool_name=None,
        inspection_report={"local_path": local_path} if local_path else None,
        audit_log=[],
        created_by="admin-1",
        created_at=now,
        updated_at=updated_at or now,
        workdir_cleaned_up=workdir_cleaned_up,
    )


async def _insert(row: OnboardingSessionRow) -> None:
    async with async_session_factory() as session:
        session.add(row)
        await session.commit()


# ---------------------------------------------------------------------
# workdir_no_longer_needed — pure decision, no I/O.
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "track,status,expected",
    [
        # OPENAPI: needed through Turn 1/2 (local_path holds the spec
        # file), done from SYNTHESIZED onward regardless of outcome.
        ("openapi", "submitted", False),
        ("openapi", "inspected", False),
        ("openapi", "synthesized", True),
        ("openapi", "risk_reviewed", True),
        ("openapi", "sandbox_tested", True),
        ("openapi", "failed", True),
        ("openapi", "aborted", True),
        # MCP_NATIVE/RAW_CODE: local_path is needed forever once live —
        # only terminal-without-activating states are safe.
        ("mcp_native", "sandbox_tested", False),
        ("mcp_native", "failed", True),
        ("mcp_native", "aborted", True),
        ("raw_code", "failed", True),
        ("raw_code", "sandbox_tested", False),
        # Track classification itself failed (track is None) — treated
        # like MCP_NATIVE/RAW_CODE's stricter rule, only terminal is safe.
        (None, "failed", True),
    ],
)
def test_workdir_no_longer_needed_pure_decision(track, status, expected):
    assert cleanup.workdir_no_longer_needed(track, status) is expected


@pytest.mark.parametrize("track", ["mcp_native", "raw_code", "openapi", None])
def test_workdir_no_longer_needed_never_true_once_activated(track):
    """Unconditional on track — an OPENAPI row reaching ACTIVATED already
    had its workdir cleaned back at synthesize() time in practice, but the
    'never touch an ACTIVATED row' rule stays absolute regardless."""
    assert cleanup.workdir_no_longer_needed(track, "activated") is False


# ---------------------------------------------------------------------
# Filesystem guard — must only ever touch a real
# tempfile.mkdtemp(prefix="ados-onboarding-") directory.
# ---------------------------------------------------------------------

def test_is_within_onboarding_tempdir_accepts_a_real_onboarding_workdir():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        assert cleanup._is_within_onboarding_tempdir(workdir) is True
    finally:
        workdir.rmdir()


def test_is_within_onboarding_tempdir_rejects_wrong_prefix_under_tempdir():
    workdir = Path(tempfile.mkdtemp(prefix="something-else-"))
    try:
        assert cleanup._is_within_onboarding_tempdir(workdir) is False
    finally:
        workdir.rmdir()


def test_is_within_onboarding_tempdir_rejects_a_real_fixture_directory():
    """The exact case that matters: this codebase's own onboarding tests
    pass tests/fixtures/mcp_native_sample directly as source_url (a local
    path, never cloned) — that must never be a deletion candidate."""
    fixture = Path(__file__).parent / "fixtures" / "mcp_native_sample"
    assert fixture.is_dir()
    assert cleanup._is_within_onboarding_tempdir(fixture) is False


# ---------------------------------------------------------------------
# cleanup_workdir_for_row — the actual deletion, guarded.
# ---------------------------------------------------------------------

def test_cleanup_workdir_for_row_removes_a_real_onboarding_workdir():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    (workdir / "repo").mkdir()
    (workdir / "repo" / "marker.txt").write_text("hello")
    row = _make_row(track="openapi", status="synthesized", local_path=str(workdir))

    assert cleanup.cleanup_workdir_for_row(row) is True
    assert not workdir.exists()


def test_cleanup_workdir_for_row_refuses_a_path_outside_the_tempdir_guard():
    fixture = Path(__file__).parent / "fixtures" / "mcp_native_sample"
    row = _make_row(track="mcp_native", status="failed", local_path=str(fixture))

    assert cleanup.cleanup_workdir_for_row(row) is False
    assert fixture.is_dir()  # never touched


def test_cleanup_workdir_for_row_is_a_safe_noop_with_no_local_path():
    row = _make_row(track=None, status="failed", local_path=None)
    assert cleanup.cleanup_workdir_for_row(row) is False


def test_cleanup_workdir_for_row_is_a_safe_noop_when_already_gone():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    workdir.rmdir()  # created then removed -- simulates a double-cleanup race
    row = _make_row(track="openapi", status="failed", local_path=str(workdir))
    assert cleanup.cleanup_workdir_for_row(row) is False


# ---------------------------------------------------------------------
# cleanup_if_no_longer_needed — the DB-backed, event-triggered path.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_if_no_longer_needed_cleans_a_failed_session():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    row = _make_row(track="mcp_native", status="failed", local_path=str(workdir))
    await _insert(row)

    cleaned = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)

    assert cleaned is True
    assert not workdir.exists()
    async with async_session_factory() as session:
        refreshed = await session.get(OnboardingSessionRow, row.id)
        assert refreshed.workdir_cleaned_up is True


@pytest.mark.asyncio
async def test_cleanup_if_no_longer_needed_is_a_noop_for_a_still_in_progress_mcp_native_session():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        row = _make_row(track="mcp_native", status="synthesized", local_path=str(workdir))
        await _insert(row)

        cleaned = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)

        assert cleaned is False
        assert workdir.exists()  # still needed -- sandbox test / activation come later
        async with async_session_factory() as session:
            refreshed = await session.get(OnboardingSessionRow, row.id)
            assert refreshed.workdir_cleaned_up is False
    finally:
        workdir.rmdir()


@pytest.mark.asyncio
async def test_cleanup_if_no_longer_needed_cleans_an_openapi_session_right_after_synthesize():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    row = _make_row(track="openapi", status="synthesized", local_path=str(workdir))
    await _insert(row)

    cleaned = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)

    assert cleaned is True
    assert not workdir.exists()


@pytest.mark.asyncio
async def test_cleanup_if_no_longer_needed_never_touches_an_activated_session():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        row = _make_row(track="mcp_native", status="activated", local_path=str(workdir))
        await _insert(row)

        cleaned = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)

        assert cleaned is False
        assert workdir.exists()
    finally:
        workdir.rmdir()


@pytest.mark.asyncio
async def test_cleanup_if_no_longer_needed_is_idempotent():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    row = _make_row(track="mcp_native", status="failed", local_path=str(workdir))
    await _insert(row)

    first = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)
    second = await cleanup.cleanup_if_no_longer_needed(async_session_factory, row.id)

    assert first is True
    assert second is False  # already marked workdir_cleaned_up -- no double-rmtree attempt


# ---------------------------------------------------------------------
# sweep_stale_workdirs — the age-based catch for abandoned sessions.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sweep_cleans_a_stale_abandoned_session_regardless_of_track():
    """The case cleanup_if_no_longer_needed deliberately doesn't cover: a
    session stuck at SANDBOX_TESTED (retriable, so no event fired) that
    nobody ever came back to."""
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    stale_updated_at = datetime.now(timezone.utc) - timedelta(hours=48)
    row = _make_row(track="mcp_native", status="sandbox_tested", local_path=str(workdir), updated_at=stale_updated_at)
    await _insert(row)

    cleaned_ids = await cleanup.sweep_stale_workdirs(async_session_factory, stale_after_hours=24)

    assert row.id in cleaned_ids
    assert not workdir.exists()
    async with async_session_factory() as session:
        refreshed = await session.get(OnboardingSessionRow, row.id)
        assert refreshed.workdir_cleaned_up is True


@pytest.mark.asyncio
async def test_sweep_leaves_a_recently_updated_session_alone():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        row = _make_row(track="mcp_native", status="sandbox_tested", local_path=str(workdir))  # updated_at=now
        await _insert(row)

        cleaned_ids = await cleanup.sweep_stale_workdirs(async_session_factory, stale_after_hours=24)

        assert row.id not in cleaned_ids
        assert workdir.exists()
    finally:
        workdir.rmdir()


@pytest.mark.asyncio
async def test_sweep_never_cleans_an_activated_session_no_matter_how_stale():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        stale_updated_at = datetime.now(timezone.utc) - timedelta(days=365)
        row = _make_row(track="mcp_native", status="activated", local_path=str(workdir), updated_at=stale_updated_at)
        await _insert(row)

        cleaned_ids = await cleanup.sweep_stale_workdirs(async_session_factory, stale_after_hours=24)

        assert row.id not in cleaned_ids
        assert workdir.exists()
    finally:
        workdir.rmdir()


@pytest.mark.asyncio
async def test_sweep_skips_a_row_already_marked_cleaned_up():
    """Guards against a redundant rmtree attempt on a path that may have
    since been reused/recreated by something unrelated."""
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    try:
        stale_updated_at = datetime.now(timezone.utc) - timedelta(hours=48)
        row = _make_row(
            track="mcp_native", status="failed", local_path=str(workdir),
            workdir_cleaned_up=True, updated_at=stale_updated_at,
        )
        await _insert(row)

        cleaned_ids = await cleanup.sweep_stale_workdirs(async_session_factory, stale_after_hours=24)

        assert row.id not in cleaned_ids
        assert workdir.exists()  # never touched -- already marked done
    finally:
        workdir.rmdir()
