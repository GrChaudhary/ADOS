"""
P7-D — controlled exercises of the lifecycle failures P6-D/P7-C's own unit
tests could not reach, plus the recovery path connecting P6-D and P7-C:

  * ADOS failure during a mission — the process itself dying, not an
    exception inside it, so nothing survives to run `_finalize_session`'s
    `finally`. Modelled and proven recoverable in
    test_session_reconcile.py (a directly-inserted row, exactly the shape
    the three real Aug 9 sessions had) — not duplicated here.
  * Runtime failure during approval — the container is gone while a human
    is still deciding. Already covered by
    test_runtime_approval_round_trip.py::
    test_a_dead_session_s_parked_request_does_not_fire_into_the_void
    (409, "nobody waiting", no connector call) — not duplicated here.
  * Docker failure during teardown, and recovery/sweep afterward — THIS
    file, against a real Docker daemon: one real resource's removal is
    made to genuinely fail while the others are removed for real, the
    survivor is independently confirmed still present, and
    orchestrate/runtime/orphan_sweep.py — completely unmodified — is
    proven to find and remove it afterward.
"""

import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime import egress as egress_module
from orchestrate.runtime import orphan_sweep as sweep
from orchestrate.runtime.egress import Destination, EgressBoundary

pytestmark = pytest.mark.docker


def _docker_available() -> bool:
    return bool(shutil.which("docker"))


def _sh(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _network_exists(name: str) -> bool:
    return _sh("docker", "network", "inspect", name).returncode == 0


def _container_exists(name: str) -> bool:
    return _sh("docker", "inspect", name).returncode == 0


@pytest.fixture(autouse=True)
async def _clean_db():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


@pytest.fixture
async def real_boundary():
    """A real, fully-up EgressBoundary — real relay container, real
    internal + egress networks — pointed at a real stand-in upstream on a
    scratch network, the same pattern test_runtime_egress_boundary.py's own
    `boundary` fixture uses. Cleaned up unconditionally in `finally`.

    Session identity is a REAL uuid.UUID, generated here and used both to
    build the boundary (as PrimeAgentRuntime.start() does: `str(session_id)`)
    and later as the exact RuntimeSessionRow.session_id primary key — the
    two must be the same value, or orphan_sweep.candidates_for_session()'s
    deterministic recomputation of the relay/network names would not match
    what this fixture actually created.
    """
    if not _docker_available():
        pytest.skip("needs a local Docker daemon")

    session_id = uuid.uuid4()
    tag = session_id.hex[:12]
    listener = f"ados-lifecycle-listener-{tag}"
    scratch_net = f"ados-lifecycle-up-{tag}"
    boundary = None
    try:
        _sh("docker", "network", "create", scratch_net)
        r = _sh(
            "docker", "run", "-d", "--name", listener, "--network", scratch_net,
            "python:3.12-alpine", "python3", "-m", "http.server", "8077",
        )
        assert r.returncode == 0, r.stderr

        boundary = EgressBoundary(str(session_id), [Destination(listener, 8077)])
        await boundary.start()
        _sh("docker", "network", "connect", scratch_net, boundary.relay_container)

        yield boundary, session_id
    finally:
        _sh("docker", "rm", "-f", listener)
        if boundary is not None:
            await boundary.teardown()
        _sh("docker", "network", "rm", scratch_net)


@pytest.mark.skipif(not _docker_available(), reason="needs a local Docker daemon")
async def test_a_docker_failure_during_teardown_leaves_exactly_the_stuck_resource_and_sweep_recovers_it(
    real_boundary, monkeypatch,
):
    boundary, session_id = real_boundary
    relay_name = boundary.relay_container
    internal_net, egress_net = boundary.internal_network, boundary.egress_network

    assert _container_exists(relay_name)
    assert _network_exists(internal_net)
    assert _network_exists(egress_net)

    # Inject a REAL teardown failure for exactly the internal network's
    # removal command — everything else goes through the real, unmodified
    # _run. NOT the relay: Docker genuinely refuses to remove a network
    # with a container still attached, so failing the relay would cascade
    # into failing BOTH networks for a real (if different) reason, which
    # would not isolate "one resource fails, unrelated others still
    # succeed" the way this test needs to.
    real_run = egress_module._run

    async def flaky_run(*args, timeout=60.0):
        if args[:4] == ("docker", "network", "rm", internal_net):
            return 1, "Error response from daemon: simulated Docker failure (P7-D controlled test)"
        return await real_run(*args, timeout=timeout)

    monkeypatch.setattr(egress_module, "_run", flaky_run)

    leftovers = await boundary.teardown()

    # The injected failure: real, independently confirmed.
    assert any(internal_net in item for item in leftovers)
    assert _network_exists(internal_net), "the network must genuinely still exist — this is not a mocked failure"
    # The resilience P6-D fixed: the OTHER resources still got removed for
    # real despite this one's failure, in the same teardown call.
    assert not _container_exists(relay_name)
    assert not _network_exists(egress_net)

    monkeypatch.undo()  # restore the real _run before any further Docker calls

    # Record it on a session row exactly as _finalize_session does today —
    # this test does not change that contract, only exercises it.
    async with async_session_factory() as db:
        mission = MissionRow(
            title="P7-D lifecycle test", objective="test", domain="it",
            allowed_capabilities=[], status="failed", created_by="test",
        )
        db.add(mission)
        await db.flush()
        row = RuntimeSessionRow(
            session_id=session_id,  # the SAME uuid the real boundary was built from
            mission_id=mission.mission_id, state="failed",
            failure_reason="; ".join(f"orphaned {item}" for item in leftovers),
        )
        db.add(row)
        await db.commit()

    # Recovery: orphan_sweep.py, completely unmodified, discovers this
    # session (via the same failure_reason signal _finalize_session already
    # writes) and recomputes the internal network's name deterministically
    # from session_id — not from the leftover string.
    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id and o.item.kind == "network_internal"]
    assert len(mine) == 1
    assert mine[0].status == "cleaned"

    # Independent confirmation — not the sweeper's own report.
    assert not _network_exists(internal_net)
