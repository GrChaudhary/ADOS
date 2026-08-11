"""
The orphan sweeper (orchestrate/runtime/orphan_sweep.py) — no Docker daemon
needed for these: Docker/filesystem calls are monkeypatched at the module's
own seams (`_docker_label`, `_docker_remove`) so what is under test here is
the DECISION logic — claim eligibility, ownership refusal, active-session
protection, idempotency, partial-failure handling, concurrency — using a
real Postgres database throughout, the same way the rest of this suite does.

The real Docker daemon is exercised separately in
test_orphan_sweep_docker.py (`@pytest.mark.docker`), which proves the
`_docker_label`/`_docker_remove` seams themselves are correct against real
containers and networks, including a genuinely unrelated same-shaped name.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime import orphan_sweep as sweep


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


async def _make_session(
    *,
    state: str = "completed",
    container_name: str = None,
    workspace_path: str = None,
    orphaned: bool = True,
    events: list = None,
) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="test", objective="test", domain="it",
            allowed_capabilities=[], status="completed", created_by="test",
        )
        db.add(mission)
        await db.flush()
        suffix = uuid.uuid4().hex[:12]
        row = RuntimeSessionRow(
            mission_id=mission.mission_id,
            state=state,
            container_name=container_name or f"ados-prime-{suffix}",
            workspace_path=workspace_path,
            failure_reason=(f"orphaned container {container_name}: timed out" if orphaned else "clean exit"),
            events=events or [],
        )
        db.add(row)
        await db.commit()
        return row.session_id


async def _fetch(session_id: uuid.UUID) -> RuntimeSessionRow:
    async with async_session_factory() as db:
        return await db.get(RuntimeSessionRow, session_id)


# --- candidate derivation (pure) ---------------------------------------------


def test_candidates_are_derived_from_the_row_not_supplied_by_a_caller():
    row = RuntimeSessionRow(
        session_id=uuid.uuid4(), mission_id=uuid.uuid4(), state="completed",
        container_name="ados-prime-abc123def456", workspace_path="/tmp/ados-mission-deadbeef-xyz",
    )
    candidates = sweep.candidates_for_session(row)
    kinds = {c.kind for c in candidates}
    assert kinds == {"container", "relay", "network_internal", "network_egress", "workspace"}
    by_kind = {c.kind: c.name for c in candidates}
    assert by_kind["container"] == "ados-prime-abc123def456"
    assert by_kind["relay"] == f"ados-relay-{sweep._SAFE_SUFFIX.sub('', str(row.session_id))[:24]}"
    assert by_kind["network_internal"] == f"ados-rt-{sweep._SAFE_SUFFIX.sub('', str(row.session_id))[:24]}"
    assert by_kind["network_egress"] == f"ados-rt-out-{sweep._SAFE_SUFFIX.sub('', str(row.session_id))[:24]}"
    assert by_kind["workspace"] == "/tmp/ados-mission-deadbeef-xyz"


def test_no_container_name_or_workspace_means_no_such_candidate():
    row = RuntimeSessionRow(session_id=uuid.uuid4(), mission_id=uuid.uuid4(), state="completed")
    kinds = {c.kind for c in sweep.candidates_for_session(row)}
    assert "container" not in kinds
    assert "workspace" not in kinds
    assert kinds == {"relay", "network_internal", "network_egress"}


# --- active-session protection -----------------------------------------------


@pytest.mark.asyncio
async def test_an_active_session_is_never_claimed():
    session_id = await _make_session(state="running", orphaned=True)
    claimed = await sweep.claim_batch(async_session_factory)
    assert all(c.session_id != session_id for c in claimed)


@pytest.mark.asyncio
async def test_a_waiting_for_approval_session_is_never_claimed():
    session_id = await _make_session(state="waiting_for_approval", orphaned=True)
    claimed = await sweep.claim_batch(async_session_factory)
    assert all(c.session_id != session_id for c in claimed)


@pytest.mark.asyncio
async def test_a_recently_completed_session_with_a_recorded_orphan_is_sweepable():
    session_id = await _make_session(state="completed", orphaned=True)
    claimed = await sweep.claim_batch(async_session_factory)
    assert any(c.session_id == session_id for c in claimed)


@pytest.mark.asyncio
async def test_a_clean_session_with_no_orphan_marker_is_never_claimed():
    session_id = await _make_session(state="completed", orphaned=False)
    claimed = await sweep.claim_batch(async_session_factory)
    assert all(c.session_id != session_id for c in claimed)


# --- ownership refusal (mocked docker seam) ----------------------------------


@pytest.mark.asyncio
async def test_a_docker_resource_with_mismatched_ownership_label_is_refused(monkeypatch):
    async def fake_label(kind, name):
        return "00000000-0000-0000-0000-000000000000"  # some OTHER session

    async def fake_remove(kind, name):
        raise AssertionError("must never attempt removal without a matching label")

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    monkeypatch.setattr(sweep, "_docker_remove", fake_remove)

    item = sweep.ClaimedItem(session_id=uuid.uuid4(), kind="container", name="ados-prime-lookalike", sweep_id="s1")
    outcome = await sweep._process_docker(item)
    assert outcome.status == "refused"
    assert "mismatch" in outcome.detail


@pytest.mark.asyncio
async def test_a_missing_docker_resource_is_treated_as_absent(monkeypatch):
    async def fake_label(kind, name):
        return None  # does not exist

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    item = sweep.ClaimedItem(session_id=uuid.uuid4(), kind="container", name="ados-prime-gone", sweep_id="s1")
    outcome = await sweep._process_docker(item)
    assert outcome.status == "absent"


@pytest.mark.asyncio
async def test_a_correctly_labelled_docker_resource_is_removed(monkeypatch):
    session_id = uuid.uuid4()
    calls = []

    async def fake_label(kind, name):
        return None if calls else str(session_id)

    async def fake_remove(kind, name):
        calls.append((kind, name))
        return True, ""

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    monkeypatch.setattr(sweep, "_docker_remove", fake_remove)
    item = sweep.ClaimedItem(session_id=session_id, kind="container", name="ados-prime-real", sweep_id="s1")
    outcome = await sweep._process_docker(item)
    assert outcome.status == "cleaned"
    assert calls == [("container", "ados-prime-real")]


# --- workspace path safety (pure + real filesystem) --------------------------


def test_workspace_path_validation_accepts_only_the_ados_temp_pattern(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    good = tmp_path / "ados-mission-deadbeef-xyz"
    good.mkdir()
    bad_prefix = tmp_path / "some-other-dir"
    bad_prefix.mkdir()
    assert sweep._workspace_path_ok(good) is True
    assert sweep._workspace_path_ok(bad_prefix) is False


def test_workspace_path_validation_rejects_paths_outside_the_temp_root(tmp_path):
    outside = tmp_path / "ados-mission-escaped"
    outside.mkdir()
    # tempfile.gettempdir() is real system temp here, not tmp_path, so this
    # correctly-prefixed directory is still refused: it is not UNDER the
    # actual temp root this process would create workspaces in.
    assert sweep._workspace_path_ok(outside) is False


@pytest.mark.asyncio
async def test_process_workspace_refuses_and_does_not_delete_a_path_outside_the_ados_root(tmp_path):
    """Goes through _process_workspace itself, not just the pure validator —
    this is the integration point a validation bypass would actually affect:
    a path that exists but fails the root/prefix check must survive."""
    outside = tmp_path / "ados-mission-escaped"
    outside.mkdir()
    (outside / "marker.txt").write_text("must not be deleted")

    item = sweep.ClaimedItem(session_id=uuid.uuid4(), kind="workspace", name=str(outside), sweep_id="s1")
    outcome = await sweep._process_workspace(item)
    assert outcome.status == "refused"
    assert outside.exists()
    assert (outside / "marker.txt").exists()


@pytest.mark.asyncio
async def test_a_real_workspace_directory_is_removed_and_verified_gone(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    ws = tmp_path / "ados-mission-deadbeef-abc"
    ws.mkdir()
    (ws / "report.md").write_text("leftover")

    item = sweep.ClaimedItem(session_id=uuid.uuid4(), kind="workspace", name=str(ws), sweep_id="s1")
    outcome = await sweep._process_workspace(item)
    assert outcome.status == "cleaned"
    assert not ws.exists()


@pytest.mark.asyncio
async def test_an_already_deleted_workspace_is_absent_not_failed(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    ws = tmp_path / "ados-mission-deadbeef-gone"
    item = sweep.ClaimedItem(session_id=uuid.uuid4(), kind="workspace", name=str(ws), sweep_id="s1")
    outcome = await sweep._process_workspace(item)
    assert outcome.status == "absent"


# --- full pipeline: idempotency, partial failure, DB state -------------------


@pytest.mark.asyncio
async def test_full_sweep_end_to_end_with_all_docker_kinds_mocked_absent(monkeypatch):
    """No real Docker: every candidate reports absent (already gone), which
    is itself a legitimate, common outcome — most orphan candidates were
    never real (e.g. relay/network names computed for a session whose relay
    started fine and whose only real leftover was the container)."""
    async def fake_label(kind, name):
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    session_id = await _make_session(state="completed", orphaned=True, container_name="ados-prime-e2e1")

    report = await sweep.sweep_once(async_session_factory)
    assert report.claimed >= 4  # container + relay + 2 networks (no workspace_path here)
    assert report.absent == report.claimed
    assert report.failed == 0

    row = await _fetch(session_id)
    kinds_recorded = {e["detail"]["kind"] for e in row.events if e["type"] == "orphan_sweep.absent"}
    assert kinds_recorded == {"container", "relay", "network_internal", "network_egress"}


@pytest.mark.asyncio
async def test_sweeping_twice_is_safe_and_the_second_pass_claims_nothing_new(monkeypatch):
    async def fake_label(kind, name):
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    await _make_session(state="completed", orphaned=True, container_name="ados-prime-idem1")

    first = await sweep.sweep_once(async_session_factory)
    assert first.claimed > 0
    assert first.failed == 0

    second = await sweep.sweep_once(async_session_factory)
    assert second.claimed == 0  # everything already terminal (absent)


@pytest.mark.asyncio
async def test_an_exception_on_one_item_does_not_abort_the_rest_of_the_batch(monkeypatch):
    """Distinct from the returned-failure case below: this one RAISES, the
    failure mode _process_one's try/except exists specifically to contain."""
    async def flaky_label(kind, name):
        if kind == "relay":
            raise ConnectionError("simulated docker daemon crash")
        return None  # everything else: already absent

    monkeypatch.setattr(sweep, "_docker_label", flaky_label)
    await _make_session(state="completed", orphaned=True, container_name="ados-prime-exc1")

    report = await sweep.sweep_once(async_session_factory)
    statuses = {o.item.kind: o.status for o in report.outcomes}
    assert statuses["relay"] == "failed"
    assert "ConnectionError" in next(o.detail for o in report.outcomes if o.item.kind == "relay")
    # The exception on "relay" must not have prevented the others.
    assert statuses["container"] == "absent"
    assert statuses["network_internal"] == "absent"
    assert statuses["network_egress"] == "absent"


@pytest.mark.asyncio
async def test_partial_failure_does_not_abandon_the_rest_of_the_batch(monkeypatch):
    """One resource's removal errors; the others must still be attempted and
    correctly recorded — the exact failure mode P6-D fixed in teardown()
    itself, now required of the sweeper too."""
    removed_names = set()

    async def fake_remove(kind, name):
        if kind == "relay":
            return False, "simulated docker daemon timeout"
        removed_names.add(name)
        return True, ""

    session_id = await _make_session(state="completed", orphaned=True, container_name="ados-prime-partial1")

    async def label_matching_unless_removed(kind, name):
        # Simulates a real daemon: present (matching this session) until
        # actually removed, then gone. Without this, the post-removal
        # existence check in _process_docker would see the resource as
        # still there for everything, including what was actually removed.
        if name in removed_names:
            return None
        return str(session_id)

    monkeypatch.setattr(sweep, "_docker_label", label_matching_unless_removed)
    monkeypatch.setattr(sweep, "_docker_remove", fake_remove)

    report = await sweep.sweep_once(async_session_factory)
    statuses = {o.item.kind: o.status for o in report.outcomes}
    assert statuses["relay"] == "failed"
    assert statuses["container"] == "cleaned"
    assert statuses["network_internal"] == "cleaned"
    assert statuses["network_egress"] == "cleaned"

    # Retry: the relay is the only one still eligible; a fixed daemon now
    # succeeds for it.
    async def fake_remove_fixed(kind, name):
        removed_names.add(name)
        return True, ""

    monkeypatch.setattr(sweep, "_docker_remove", fake_remove_fixed)
    retry = await sweep.sweep_once(async_session_factory)
    retry_statuses = {o.item.kind: o.status for o in retry.outcomes}
    assert retry_statuses == {"relay": "cleaned"}  # only the previously-failed one was reclaimed


@pytest.mark.asyncio
async def test_history_is_preserved_not_erased(monkeypatch):
    async def fake_label(kind, name):
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)
    pre_existing_event = {"type": "runtime.tool.started", "at": "2026-08-09T10:00:00+00:00", "detail": {}}
    session_id = await _make_session(
        state="completed", orphaned=True, container_name="ados-prime-hist1", events=[pre_existing_event],
    )

    await sweep.sweep_once(async_session_factory)
    row = await _fetch(session_id)
    assert pre_existing_event in row.events
    assert any(e["type"] == "orphan_sweep.claimed" for e in row.events)
    assert any(e["type"] == "orphan_sweep.absent" for e in row.events)


@pytest.mark.asyncio
async def test_the_claim_limit_bounds_one_sweep_pass():
    for _ in range(3):
        await _make_session(state="completed", orphaned=True)
    claimed = await sweep.claim_batch(async_session_factory, limit=1)
    claimed_sessions = {c.session_id for c in claimed}
    assert len(claimed_sessions) == 1


@pytest.mark.asyncio
async def test_an_expired_claim_lease_becomes_eligible_again():
    session_id = await _make_session(state="completed", orphaned=True, container_name="ados-prime-lease1")

    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    first = await sweep.claim_batch(async_session_factory, sweep_id="sweeper-a", now=long_ago, lease_seconds=60.0)
    assert any(c.session_id == session_id for c in first)

    # Immediately after (well within the lease): a second sweeper must not
    # also claim the same items.
    soon_after = long_ago + timedelta(seconds=5)
    second = await sweep.claim_batch(async_session_factory, sweep_id="sweeper-b", now=soon_after, lease_seconds=60.0)
    assert not any(c.session_id == session_id for c in second)

    # Well past the lease, with the first sweeper never having finalized
    # (simulating a crash mid-Docker-call): now eligible again.
    much_later = long_ago + timedelta(seconds=120)
    third = await sweep.claim_batch(async_session_factory, sweep_id="sweeper-c", now=much_later, lease_seconds=60.0)
    assert any(c.session_id == session_id for c in third)


@pytest.mark.asyncio
async def test_two_concurrent_sweeps_never_claim_the_same_resource(monkeypatch):
    import asyncio

    for _ in range(5):
        await _make_session(state="completed", orphaned=True)

    results = await asyncio.gather(
        sweep.claim_batch(async_session_factory, sweep_id="a"),
        sweep.claim_batch(async_session_factory, sweep_id="b"),
    )
    claimed_a, claimed_b = results
    keys_a = {(c.session_id, c.kind, c.name) for c in claimed_a}
    keys_b = {(c.session_id, c.kind, c.name) for c in claimed_b}
    assert keys_a.isdisjoint(keys_b)
    # Nothing was lost either: every session appears in exactly one side.
    sessions_a = {c.session_id for c in claimed_a}
    sessions_b = {c.session_id for c in claimed_b}
    assert sessions_a.isdisjoint(sessions_b)
