"""
A runtime session must always end, and its credential must always stop working.

THE DEFECT (two halves, found by P6-C, fixed here)
--------------------------------------------------
`mcp_gateway._resolve_session` accepts a token when the session row is in
`starting`, `running` or `waiting_approval` and the expiry has not passed. Both
of those guards were, in practice, unreachable:

* `token_expires_at` was checked on every capability call and **set by nothing**
  — the column defaulted to NULL in every code path, so the expiry branch was
  dead and state was the only revocation.
* the terminal state was written *after* `run_objective` returned, with only
  the teardown in the `finally`. If the objective raised, the container died,
  or ADOS was killed mid-mission, the container was destroyed and the row
  stayed at `running`.

Together those made a crashed mission leave a permanently valid credential for
a session that no longer exists. Either fix alone is incomplete: state revokes
promptly but only while ADOS is alive to write it, expiry revokes
unconditionally but only eventually. A dead ADOS process defeats the first and
not the second, which is why both are here.

WHAT THESE TESTS PIN
--------------------
* a session reaches a terminal state on every path: clean completion, an
  objective that raises, a container that will not start, a cancellation, and
  a teardown that fails or raises
* the real failure still propagates — the guard must not swallow what went
  wrong to report tidy bookkeeping
* what teardown could not remove is recorded on the row as an orphan rather
  than logged and forgotten
* teardown attempts every resource even after an earlier one times out
* an abandoned session — the row nobody ever closed — stops being able to act
  once its token expires

No Docker and no external writes: the runtime is a stand-in throughout, so
these run in the default suite rather than behind a marker.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import _LIVE_STATES, hash_token, request_capability
from contracts import Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from integrations.connectors.prime_runtime import PrimeRuntimeConnector
from orchestrate.runtime.base import SessionOutcome, SessionState
from orchestrate.runtime.prime import TOKEN_GRACE_SECONDS, token_expiry


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


def _call(**overrides):
    payload = {"prompt": "explain the outage", "domain": "it"}
    payload.update(overrides)
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input=payload,
        requested_by="user:sophia",
        incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.APPROVAL_REQUIRED),
    )


def _outcome(state=SessionState.COMPLETED, **kw):
    base = dict(
        state=state, final_answer="The root cause was pool exhaustion.",
        tool_execution_count=3, tool_success_count=3,
    )
    base.update(kw)
    return SessionOutcome(**base)


class _StandInRuntime:
    """A PrimeAgentRuntime that never touches Docker.

    Deliberately mirrors the real object's contract rather than a mock's: it
    exposes `container_name` and `workspace` after `start`, and `teardown`
    returns a list of leftovers, so a change to that contract breaks these
    tests instead of silently passing.
    """

    instances = []

    def __init__(self, **_kw):
        self.container_name = None
        self.workspace = None
        self.start_error = None
        self.objective_error = None
        self.teardown_error = None
        self.outcome = _outcome()
        self.leftovers = []
        self.torn_down = False
        _StandInRuntime.instances.append(self)

    async def start(self, spec, token):
        if self.start_error:
            raise self.start_error
        self.container_name = f"ados-prime-{spec.session_id[:12]}"
        self.workspace = f"/tmp/ados-mission-{spec.mission_id[:8]}"

    async def run_objective(self, spec):
        if self.objective_error:
            raise self.objective_error
        return self.outcome

    async def teardown(self):
        self.torn_down = True
        if self.teardown_error:
            raise self.teardown_error
        return list(self.leftovers)


@pytest.fixture
def runtime(monkeypatch):
    """Install the stand-in and hand back the instance the connector built."""
    _StandInRuntime.instances.clear()
    monkeypatch.setattr("orchestrate.runtime.prime.PrimeAgentRuntime", _StandInRuntime)

    def configure(**attrs):
        holder = {}

        def factory(**kw):
            made = _StandInRuntime(**kw)
            for key, value in attrs.items():
                setattr(made, key, value)
            holder["runtime"] = made
            return made

        monkeypatch.setattr("orchestrate.runtime.prime.PrimeAgentRuntime", factory)
        return holder

    return configure


async def _only_session():
    async with async_session_factory() as db:
        rows = (await db.execute(text("SELECT * FROM runtime_sessions"))).mappings().all()
        missions = (await db.execute(text("SELECT * FROM missions"))).mappings().all()
    assert len(rows) == 1, f"expected one session row, got {len(rows)}"
    return rows[0], missions[0]


# --- every path ends terminal ------------------------------------------------

async def test_a_clean_run_closes_the_session_and_records_the_outcome(runtime):
    runtime()
    outcome, session_id = await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    assert outcome.state is SessionState.COMPLETED
    row, mission = await _only_session()
    assert row["state"] == "completed"
    assert row["tool_execution_count"] == 3
    assert mission["status"] == "completed"
    assert mission["result"].startswith("The root cause")


async def test_an_objective_that_raises_still_closes_the_session(runtime):
    """The row used to stay at `running` here — with the container already
    destroyed by the teardown in the same `finally`."""
    held = runtime(objective_error=RuntimeError("the kernel never came up"))

    with pytest.raises(RuntimeError, match="the kernel never came up"):
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, mission = await _only_session()
    assert row["state"] == "failed"
    assert "the kernel never came up" in row["failure_reason"]
    assert mission["status"] == "failed"
    assert held["runtime"].torn_down is True


async def test_a_container_that_never_starts_does_not_leave_the_row_at_starting(runtime):
    """`start()` raises before the row is moved to `running`, so the row is at
    `starting` — which the gateway also treats as live."""
    runtime(start_error=RuntimeError("container failed to start: no such image"))

    with pytest.raises(RuntimeError, match="no such image"):
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert row["state"] == "failed"
    assert row["state"] not in _LIVE_STATES


async def test_a_cancelled_mission_closes_the_session(runtime):
    """`CancelledError` derives from BaseException, not Exception. An
    `except Exception` here would let the likeliest interruption — a shutdown,
    a timeout, an operator cancelling — leave the row live."""
    runtime(objective_error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert row["state"] == "failed"
    assert "CancelledError" in row["failure_reason"]


@pytest.mark.parametrize("failure", [
    RuntimeError("boom"),
    asyncio.CancelledError(),
    KeyboardInterrupt(),
    MemoryError(),
])
async def test_the_row_is_never_left_live_however_the_run_ends(runtime, failure):
    """The invariant itself, stated once over the shapes that reach it."""
    runtime(objective_error=failure)

    with pytest.raises(type(failure)):
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert row["state"] not in _LIVE_STATES, (
        f"a {type(failure).__name__} left the session at {row['state']!r}, and its token with it"
    )


# --- the real failure survives -----------------------------------------------

async def test_the_original_exception_is_what_reaches_the_caller(runtime):
    """Bookkeeping in a `finally` is exactly where a real failure goes missing.
    The caller must still see the kernel error, not a teardown or database
    error raised while tidying up after it."""
    original = RuntimeError("provider returned 429 after 5 retries")
    runtime(objective_error=original, leftovers=["container ados-prime-abc: timed out"])

    with pytest.raises(RuntimeError) as raised:
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    assert raised.value is original


async def test_a_teardown_that_raises_does_not_mask_the_run_and_does_not_skip_the_row(runtime):
    """`teardown()` promises not to raise. This asserts the caller does not
    depend on that promise: if it ever breaks, the row must still be closed."""
    original = RuntimeError("the objective failed first")
    runtime(objective_error=original, teardown_error=OSError("docker socket gone"))

    with pytest.raises(RuntimeError) as raised:
        await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    assert raised.value is original, "the teardown error replaced the real failure"
    row, _ = await _only_session()
    assert row["state"] == "failed"
    assert "teardown raised OSError" in row["failure_reason"]


async def test_a_teardown_that_raises_on_a_successful_run_still_returns_the_outcome(runtime):
    runtime(teardown_error=OSError("docker socket gone"))

    outcome, _ = await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    assert outcome.state is SessionState.COMPLETED
    row, _ = await _only_session()
    assert row["state"] == "completed"
    assert "teardown raised OSError" in row["failure_reason"]


# --- orphans are recorded ----------------------------------------------------

async def test_what_teardown_could_not_remove_is_recorded_on_the_row(runtime):
    """Nothing else in ADOS knows these names once the runtime object is gone.
    A leftover that is only logged is a leftover nobody will ever sweep."""
    runtime(leftovers=[
        "container ados-prime-abc123: TimeoutError: timed out",
        "network ados-rt-abc123",
    ])

    await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert "orphaned container ados-prime-abc123" in row["failure_reason"]
    assert "orphaned network ados-rt-abc123" in row["failure_reason"]
    # The container and workspace names are on the row too, so a sweeper has
    # everything it needs without parsing prose.
    assert row["container_name"].startswith("ados-prime-")
    assert row["workspace_path"].startswith("/tmp/ados-mission-")


async def test_a_clean_teardown_records_no_orphans(runtime):
    """The negative half: a run that cleaned up must not look like one that
    did not, or the field is noise."""
    runtime()
    await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert row["failure_reason"] is None


# --- teardown finishes what it starts ----------------------------------------
#
# These drive the REAL PrimeAgentRuntime.teardown with docker stubbed out, not
# the stand-in above. The stand-in proves the caller records leftovers; these
# prove there are leftovers to record instead of an exception.


def _runtime_with_resources(tmp_path):
    from orchestrate.runtime.egress import Destination, EgressBoundary
    from orchestrate.runtime.prime import PrimeAgentRuntime

    session = uuid.uuid4().hex[:12]
    runtime = PrimeAgentRuntime(mcp_url="http://ados-gateway:8077/mcp/")
    runtime.container_name = f"ados-prime-{session}"
    runtime.egress = EgressBoundary(session, [Destination("ados-gateway", 8077)])
    workspace = tmp_path / f"ados-mission-{session}"
    workspace.mkdir()
    (workspace / "brief.md").write_text("the mission brief")
    runtime.workspace = workspace
    return runtime, workspace


async def test_teardown_attempts_every_resource_even_after_the_first_times_out(
    monkeypatch, tmp_path
):
    """The reliability defect this replaced.

    `_run` raises `TimeoutError` when a docker command does not return — which
    is exactly what a wedged daemon does, and the daemon wedging is not
    hypothetical: it happened mid-run during P6-B. Teardown was three bare
    awaits, so a hung `docker rm` on the agent container propagated out through
    the caller's `finally`, leaving the relay, both per-session networks and the
    workspace behind, and replacing the real failure with a timeout.
    """
    runtime, workspace = _runtime_with_resources(tmp_path)
    attempted = []

    async def fake_run(*args, timeout=60.0):
        attempted.append(args)
        if args[:3] == ("docker", "rm", "-f") and args[3] == runtime.container_name:
            raise TimeoutError(f"timed out: {' '.join(args)}")
        return 0, ""

    monkeypatch.setattr("orchestrate.runtime.egress._run", fake_run)

    leftovers = await runtime.teardown()

    commands = {" ".join(a) for a in attempted}
    assert any(runtime.container_name in c for c in commands), "the container was not attempted"
    assert any(runtime.egress.relay_container in c for c in commands), (
        "the relay was never attempted — teardown stopped at the container"
    )
    assert any(runtime.egress.internal_network in c for c in commands)
    assert any(runtime.egress.egress_network in c for c in commands)
    assert not workspace.exists(), "the workspace was left on disk"

    assert len(leftovers) == 1
    assert runtime.container_name in leftovers[0]
    assert "TimeoutError" in leftovers[0]


async def test_a_clean_teardown_reports_nothing_left_behind(monkeypatch, tmp_path):
    runtime, workspace = _runtime_with_resources(tmp_path)

    async def fake_run(*args, timeout=60.0):
        return 0, ""

    monkeypatch.setattr("orchestrate.runtime.egress._run", fake_run)

    assert await runtime.teardown() == []
    assert not workspace.exists()


async def test_a_resource_that_was_never_there_is_not_reported_as_an_orphan(
    monkeypatch, tmp_path
):
    """`docker rm` on something already gone exits non-zero. The goal is
    absence, so "No such container" is success — reporting it would fill the
    orphan field with noise on every run that tore down twice."""
    runtime, _ = _runtime_with_resources(tmp_path)

    async def fake_run(*args, timeout=60.0):
        return 1, "Error response from daemon: No such container: whatever"

    monkeypatch.setattr("orchestrate.runtime.egress._run", fake_run)

    assert await runtime.teardown() == []


async def test_a_workspace_that_will_not_delete_is_reported(monkeypatch, tmp_path):
    """`shutil.rmtree(ignore_errors=True)` never raises and never says it
    failed, so the directory is re-checked rather than assumed gone."""
    runtime, workspace = _runtime_with_resources(tmp_path)

    async def fake_run(*args, timeout=60.0):
        return 0, ""

    monkeypatch.setattr("orchestrate.runtime.egress._run", fake_run)
    monkeypatch.setattr("shutil.rmtree", lambda *a, **k: None)  # silently does nothing

    leftovers = await runtime.teardown()

    assert leftovers == [f"workspace {workspace}"]
    assert workspace.exists()


async def test_repeated_start_and_teardown_cycles_leave_nothing(monkeypatch, tmp_path):
    """Sessions are created and destroyed continuously; a leak that only shows
    up on the third cycle is the kind nobody notices until disk or the network
    pool runs out."""
    async def fake_run(*args, timeout=60.0):
        return 0, ""

    monkeypatch.setattr("orchestrate.runtime.egress._run", fake_run)

    workspaces = []
    names = set()
    for _ in range(5):
        runtime, workspace = _runtime_with_resources(tmp_path)
        workspaces.append(workspace)
        names.add(runtime.egress.internal_network)
        assert await runtime.teardown() == []

    assert len(names) == 5, "per-session networks collided across cycles"
    assert not any(w.exists() for w in workspaces)


# --- the token's own lifetime ------------------------------------------------

async def test_the_session_row_is_given_an_expiry_when_it_is_created(runtime):
    """The defect in one assertion: this column was NULL on every row ADOS
    ever wrote, which made the gateway's expiry check dead code."""
    runtime()
    before = datetime.now(timezone.utc)
    await PrimeRuntimeConnector()._run(_call(), "explain the outage")

    row, _ = await _only_session()
    assert row["token_expires_at"] is not None, "the token never expires"
    assert row["token_expires_at"] > before


def test_the_expiry_outlasts_the_whole_wall_clock_budget():
    """A token that dies before its own session does would abort a legitimate
    long mission — including one parked on a human, which the skill waits up to
    900s for. The grace is for container start and teardown, not a second
    budget."""
    now = datetime.now(timezone.utc)
    expiry = token_expiry(1800.0, now=now)

    assert expiry > now + timedelta(seconds=1800.0)
    assert expiry == now + timedelta(seconds=1800.0 + TOKEN_GRACE_SECONDS)


def test_a_shorter_mission_gets_a_shorter_lived_token():
    """The lifetime tracks the session's own deadline rather than being a flat
    constant, so a two-minute job does not mint a half-hour credential."""
    now = datetime.now(timezone.utc)
    assert token_expiry(120.0, now=now) < token_expiry(1800.0, now=now)


async def test_an_abandoned_session_stops_being_able_to_act_once_its_token_expires(monkeypatch):
    """The case neither guard covers alone: ADOS died mid-mission, so nothing
    ever wrote a terminal state. The row still says `running` — and the token
    must nonetheless stop working."""
    token = "tok-" + uuid.uuid4().hex
    async with async_session_factory() as db:
        mission = MissionRow(
            title="abandoned", objective="o", domain="it",
            allowed_capabilities=[Capability.NOTIFY_IT_HELPDESK.value], status="running",
        )
        db.add(mission)
        await db.flush()
        db.add(RuntimeSessionRow(
            mission_id=mission.mission_id,
            state="running",  # nobody ever closed it
            token_hash=hash_token(token),
            token_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        await db.commit()

    monkeypatch.setattr(
        mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
    )
    answer = await request_capability.fn(
        Capability.NOTIFY_IT_HELPDESK.value, {"summary": "still here"}
    )

    assert answer["status"] == "denied"
    assert answer["reason"] == "session token expired"
    # And the state guard genuinely was not what refused it — the row is still
    # one the gateway considers live.
    async with async_session_factory() as db:
        rows = (await db.execute(text("SELECT state FROM runtime_sessions"))).scalars().all()
    assert rows == ["running"]
