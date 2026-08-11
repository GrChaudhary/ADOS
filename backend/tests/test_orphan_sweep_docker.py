"""
The orphan sweeper against the real Docker engine.

test_orphan_sweep.py proves the DECISION logic (claim eligibility, active-
session protection, idempotency, partial-failure handling, concurrency) with
Docker mocked out at the module's own seams. This file proves those seams
themselves are correct against a real daemon: a real ADOS-labelled orphan is
actually removed and independently confirmed gone, and a real resource that
merely LOOKS like an ADOS orphan — same name shape, no matching label — is
left alone.

    pytest -m docker backend/tests/test_orphan_sweep_docker.py

Deselected by default alongside every other `docker` test in this suite.
"""

import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime import orphan_sweep as sweep
from orchestrate.runtime.egress import LABEL_MANAGED_BY, LABEL_MANAGED_BY_VALUE, LABEL_SESSION

pytestmark = pytest.mark.docker

IMAGE = "alpine:latest"


def _docker_available() -> bool:
    return bool(shutil.which("docker"))


def _sh(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _container_exists(name: str) -> bool:
    return _sh("docker", "inspect", name).returncode == 0


def _network_exists(name: str) -> bool:
    return _sh("docker", "network", "inspect", name).returncode == 0


@pytest.fixture(autouse=True)
async def _clean_db():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


async def _make_session(*, container_name=None, workspace_path=None) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="docker orphan sweep test", objective="test", domain="it",
            allowed_capabilities=[], status="completed", created_by="test",
        )
        db.add(mission)
        await db.flush()
        row = RuntimeSessionRow(
            mission_id=mission.mission_id,
            state="completed",
            container_name=container_name,
            workspace_path=workspace_path,
            failure_reason="orphaned (test-created, real Docker)",
        )
        db.add(row)
        await db.commit()
        return row.session_id


@pytest.fixture
def cleanup_registry():
    """Belt-and-braces: anything created below is also force-removed here,
    independent of whether the sweeper under test worked, so a failing
    assertion never leaks a real container/network past this test."""
    containers, networks = [], []
    yield containers, networks
    for c in containers:
        _sh("docker", "rm", "-f", c)
    for n in networks:
        _sh("docker", "network", "rm", n)


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_a_real_labelled_orphan_container_is_swept_and_confirmed_gone(cleanup_registry):
    containers, _ = cleanup_registry
    session_id = await _make_session(container_name=None)  # set below once we know it
    name = f"ados-prime-{str(session_id).replace('-', '')[:12]}"
    containers.append(name)

    r = _sh(
        "docker", "run", "-d", "--name", name,
        "--label", f"{LABEL_SESSION}={session_id}",
        "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        IMAGE, "sleep", "300",
    )
    assert r.returncode == 0, r.stderr

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        row.container_name = name
        await db.commit()

    assert _container_exists(name), "test setup failed: container was not actually created"

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "container"]
    assert len(mine) == 1
    assert mine[0].status == "cleaned"

    # Independent confirmation — not the sweeper's own report.
    assert not _container_exists(name)

    # Second sweep: safe, no error, nothing left to claim for this container.
    second = await sweep.sweep_once(async_session_factory)
    mine_second = [o for o in second.outcomes if o.item.session_id == session_id and o.item.kind == "container"]
    assert mine_second == []


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_a_real_labelled_orphan_network_is_swept_and_confirmed_gone(cleanup_registry):
    _, networks = cleanup_registry
    session_id = await _make_session()
    suffix = sweep._SAFE_SUFFIX.sub("", str(session_id))[:24]
    net_name = f"ados-rt-{suffix}"
    networks.append(net_name)

    r = _sh(
        "docker", "network", "create",
        "--label", f"{LABEL_SESSION}={session_id}",
        "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        net_name,
    )
    assert r.returncode == 0, r.stderr
    assert _network_exists(net_name)

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "network_internal"]
    assert len(mine) == 1 and mine[0].status == "cleaned"
    assert not _network_exists(net_name)


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_an_unrelated_container_with_the_exact_expected_name_but_no_matching_label_survives(cleanup_registry):
    """The critical safety case: a real container occupying the EXACT name
    the sweeper would compute as this session's candidate, but never created
    by ADOS (no label at all). A name match alone must never be enough."""
    containers, _ = cleanup_registry
    session_id = await _make_session()
    name = f"ados-prime-{str(session_id).replace('-', '')[:12]}"
    containers.append(name)

    # No ados.* labels at all — an operator or an unrelated process could
    # have created this; the sweeper must not assume it knows better.
    r = _sh("docker", "run", "-d", "--name", name, IMAGE, "sleep", "300")
    assert r.returncode == 0, r.stderr

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        row.container_name = name
        await db.commit()

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "container"]
    assert len(mine) == 1
    assert mine[0].status == "refused"

    # Independent confirmation the container is untouched.
    assert _container_exists(name)


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_a_container_labelled_for_a_different_session_survives(cleanup_registry):
    """Same name pattern, a real ados.session_id label — just the WRONG one.
    Distinguishes this from the no-label case above: even a genuine ADOS
    label does not authorize deletion unless it names THIS session."""
    containers, _ = cleanup_registry
    session_id = await _make_session()
    other_session_id = uuid.uuid4()
    name = f"ados-prime-{str(session_id).replace('-', '')[:12]}"
    containers.append(name)

    r = _sh(
        "docker", "run", "-d", "--name", name,
        "--label", f"{LABEL_SESSION}={other_session_id}",
        "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        IMAGE, "sleep", "300",
    )
    assert r.returncode == 0, r.stderr

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        row.container_name = name
        await db.commit()

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "container"]
    assert len(mine) == 1 and mine[0].status == "refused"
    assert _container_exists(name)


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_a_real_workspace_directory_under_the_ados_root_is_swept_and_confirmed_gone():
    # Deliberately NOT tmp_path/tmp_path_factory: those nest under pytest's
    # own base temp dir, not the process's real tempfile.gettempdir(), and
    # _workspace_path_ok requires the direct parent to be the real system
    # temp root — exactly what PrimeAgentRuntime._prepare_workspace uses.
    import tempfile
    from pathlib import Path

    real_ws = Path(tempfile.mkdtemp(prefix=f"ados-mission-{uuid.uuid4().hex[:8]}-"))
    (real_ws / "report.md").write_text("leftover from a test run")

    session_id = await _make_session(workspace_path=str(real_ws))
    assert real_ws.exists()

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "workspace"]
    assert len(mine) == 1 and mine[0].status == "cleaned"
    assert not real_ws.exists()

    second = await sweep.sweep_once(async_session_factory)
    mine_second = [o for o in second.outcomes if o.item.session_id == session_id and o.item.kind == "workspace"]
    assert mine_second == []


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_full_pipeline_cleans_every_labelled_resource_kind_in_one_pass(cleanup_registry):
    """Section 9's A-F sequence in one test: create a real ADOS-labelled
    container AND network for one session, sweep once, independently confirm
    both gone, sweep again, confirm no error and nothing left to claim."""
    containers, networks = cleanup_registry
    session_id = await _make_session()
    suffix = sweep._SAFE_SUFFIX.sub("", str(session_id))[:24]
    container_name = f"ados-prime-{str(session_id).replace('-', '')[:12]}"
    net_name = f"ados-rt-{suffix}"
    containers.append(container_name)
    networks.append(net_name)

    assert _sh(
        "docker", "run", "-d", "--name", container_name,
        "--label", f"{LABEL_SESSION}={session_id}", "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        IMAGE, "sleep", "300",
    ).returncode == 0
    assert _sh(
        "docker", "network", "create",
        "--label", f"{LABEL_SESSION}={session_id}", "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        net_name,
    ).returncode == 0

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        row.container_name = container_name
        await db.commit()

    report = await sweep.sweep_once(async_session_factory)
    assert report.failed == 0

    assert not _container_exists(container_name)
    assert not _network_exists(net_name)

    second = await sweep.sweep_once(async_session_factory)
    assert second.claimed == 0
