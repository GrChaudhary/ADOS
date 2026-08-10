"""
The session credential: what it proves, and what it must never leak.

WHAT WAS MISSING
----------------
Every authorization decision in the gateway starts at `_resolve_session` —
token -> session row -> mission -> grant — and nothing else in ADOS establishes
who a runtime is. Yet nothing exercised the *refusal* side of that function.
The existing runtime tests all present a valid token and go on to test what
happens afterwards, so a `_resolve_session` that accepted any string at all
would have passed every one of them, and the first sign of it would have been a
container acting under a mission that never granted it anything.

WHAT THESE TESTS PIN
--------------------
* an unrecognized, malformed, absent, expired, or dead-session token is refused
* a valid token for that session still works (so the refusals are not vacuous)
* a refusal reaches no connector and writes no capability request
* a token resolves to ITS OWN mission's grant and no other session's requests
* the raw token appears in no database column, no log record, and no file in
  the bind-mounted workspace

WHY THE TOKEN IS SHAPED THIS WAY
--------------------------------
It is deliberately weak in what it carries and strong in what it guards: 32
bytes of `secrets.token_urlsafe`, stored only as a SHA-256, naming one session
row and asserting nothing. It cannot be decoded into a role, a capability list,
or a wider grant. A container that leaks its token leaks the ability to act as
one mission — not the ability to describe itself as another.

No external writes: ServiceNow is an `httpx.MockTransport` throughout.
"""

import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from contracts import Capability
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub

ROUTINE = {"summary": "Root cause: connection pool exhaustion"}


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "not-a-real-password")


@pytest.fixture
def _servicenow(monkeypatch):
    """A recording ServiceNow. If a refused call ever reaches a connector it
    shows up here, rather than in a real instance."""
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content or b"{}"))
        return httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC0099999"}})

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(handler))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)
    return posted


@pytest.fixture
def _present(monkeypatch):
    """Present an arbitrary Authorization header the way a runtime does — over
    HTTP headers, which is the only channel the gateway reads identity from."""
    def present(headers):
        monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: headers or {})
    return present


@pytest.fixture
def _as_runtime(_present):
    def present(token):
        _present({"authorization": f"Bearer {token}"})
    return present


async def _session(
    *,
    state="running",
    expires_at=None,
    capability=Capability.NOTIFY_IT_HELPDESK,
    title="session auth",
):
    """A mission granting one capability, and a live token naming its session."""
    async with async_session_factory() as db:
        mission = MissionRow(
            title=title, objective="o", domain="it",
            allowed_capabilities=[capability.value], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state=state,
            token_hash=hash_token(token), token_expires_at=expires_at,
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


async def _capability_rows():
    async with async_session_factory() as db:
        return (await db.execute(select(CapabilityRequestRow))).scalars().all()


# --- the positive control ----------------------------------------------------
#
# First, because every refusal below is only meaningful against a call that is
# otherwise known to work. Without this, a broken fixture would make the whole
# file pass while proving nothing.

async def test_the_valid_token_for_this_session_is_accepted_and_executes(
    _as_runtime, _servicenow
):
    _, _, token = await _session()
    _as_runtime(token)

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert answer["status"] == "executed", answer
    assert len(_servicenow) == 1


# --- the refusals ------------------------------------------------------------

async def test_a_token_that_names_no_session_is_refused(_as_runtime, _servicenow):
    """The unauthenticated case: a well-formed string that is simply not ours."""
    await _session()
    _as_runtime("tok-" + uuid.uuid4().hex)  # never stored anywhere

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert answer["status"] == "denied"
    assert answer["reason"] == "unrecognized session token"
    assert _servicenow == []


@pytest.mark.parametrize("headers", [
    None,                                             # no headers at all
    {},                                               # headers, no authorization
    {"authorization": ""},                            # empty
    {"authorization": "tok-whatever"},                # no scheme
    {"authorization": "Basic dXNlcjpwYXNz"},          # the wrong scheme
    {"authorization": "Bearer"},                      # scheme, no value
    {"authorization": "Bearer "},                     # scheme, empty value
])
async def test_a_request_without_a_usable_bearer_token_is_refused(
    headers, _present, _servicenow
):
    """Malformed credentials are refused before any lookup happens. The empty
    and whitespace forms matter most: `Bearer ` hashes to a perfectly valid
    SHA-256 of the empty string, so the refusal must not depend on the hash
    failing to match something."""
    await _session()
    _present(headers)

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert answer["status"] == "denied"
    assert answer["reason"] in {"missing bearer token", "unrecognized session token"}
    assert _servicenow == []


async def test_an_expired_token_is_refused(_as_runtime, _servicenow):
    """`token_expires_at` is stored as `timestamp with time zone` and compared
    against an aware `now`. If that column ever becomes naive, this comparison
    raises TypeError instead of denying — an expiry check that crashes is not
    an expiry check, and the exception would escape as a transport error rather
    than a structured refusal the agent can report."""
    _, _, token = await _session(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    _as_runtime(token)

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert answer["status"] == "denied"
    assert answer["reason"] == "session token expired"
    assert _servicenow == []


async def test_a_token_still_inside_its_expiry_is_accepted(_as_runtime, _servicenow):
    """The other half of the comparison — a check that denies everything is
    also 'never lets an expired token through'."""
    _, _, token = await _session(
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    _as_runtime(token)

    assert (await request_capability.fn(
        Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE)
    ))["status"] == "executed"


@pytest.mark.parametrize("state", ["created", "completed", "failed", "cancelled", "torn_down"])
async def test_a_token_whose_session_is_no_longer_live_is_dead(
    state, _as_runtime, _servicenow
):
    """Session state, not wall clock, is what actually revokes a credential
    here — see the open finding that nothing in production sets an expiry. A
    torn-down session's container is gone and its workspace deleted; acting on
    its behalf would produce a real side effect with nobody waiting for it."""
    _, _, token = await _session(state=state)
    _as_runtime(token)

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert answer["status"] == "denied"
    assert f"session is {state}" in answer["reason"]
    assert _servicenow == []


async def test_a_refused_call_leaves_no_capability_request_behind(_as_runtime, _servicenow):
    """An unauthenticated caller must not be able to write rows into ADOS's
    audit table. A denial inside the grant IS recorded (that attempt came from
    a known session and is worth seeing); an unrecognized token is not a
    session at all, so there is no session to record it against."""
    await _session()
    _as_runtime("tok-" + uuid.uuid4().hex)

    await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert await _capability_rows() == []
    assert _servicenow == []


# --- one token, one mission --------------------------------------------------

async def test_a_token_resolves_only_to_its_own_missions_grant(_as_runtime, _servicenow):
    """Two live sessions. The grant comes from the mission the *token's* row
    points at, so holding a valid token cannot borrow another mission's
    permissions — the capability below is granted, just not to this caller."""
    _, _, quiet_token = await _session(
        capability=Capability.NOTIFY_IT_HELPDESK, title="may only notify"
    )
    await _session(capability=Capability.CREATE_CHANGE_REQUEST, title="may raise changes")

    _as_runtime(quiet_token)
    answer = await request_capability.fn(Capability.CREATE_CHANGE_REQUEST.value, {})

    assert answer["status"] == "denied"
    assert "not in this mission's capability grant" in answer["reason"]
    assert _servicenow == []


async def test_the_discovery_tool_refuses_an_unknown_token_and_reveals_nothing(_as_runtime):
    """`list_capabilities` is how the agent learns its grant. An unauthenticated
    caller must not get the catalogue — a denial that helpfully listed what it
    could have asked for would make the refusal pointless."""
    await _session()
    _as_runtime("tok-" + uuid.uuid4().hex)

    answer = await mcp_gateway.list_capabilities.fn()

    assert answer["status"] == "denied"
    assert answer["capabilities"] == []
    assert "mission_id" not in answer


async def test_the_discovery_tool_reports_this_missions_grant_and_only_that(_as_runtime):
    mission_id, _, token = await _session(capability=Capability.NOTIFY_IT_HELPDESK)
    _as_runtime(token)

    answer = await mcp_gateway.list_capabilities.fn()

    assert answer["status"] == "ok"
    assert answer["mission_id"] == str(mission_id)
    assert [c["capability"] for c in answer["capabilities"]] == [
        Capability.NOTIFY_IT_HELPDESK.value
    ]


async def test_one_session_cannot_poll_another_sessions_request(_as_runtime, _servicenow):
    """The request id is a UUID an agent could hold from anywhere. Reads are
    scoped to the presenting session, so knowing an id is not authority to see
    its result — which may contain the output of a system this mission was
    never granted."""
    _, _, mine = await _session(title="mission a")
    _as_runtime(mine)
    executed = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))
    request_id = executed["request_id"]

    _, _, theirs = await _session(title="mission b")
    _as_runtime(theirs)
    answer = await mcp_gateway.get_capability_request.fn(request_id)

    assert answer["status"] == "denied"
    assert answer["reason"] == "no such request for this session"
    assert "result" not in answer


# --- the token itself must not leak ------------------------------------------

async def test_the_raw_token_is_never_stored_in_any_column():
    """Column-by-column rather than `assert row.token_hash != token`, so a
    future column that helpfully caches the token — for a debug view, a retry,
    an admin screen — fails here instead of shipping."""
    _, session_id, token = await _session()

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, session_id)
        stored = {c.name: getattr(row, c.name) for c in RuntimeSessionRow.__table__.columns}

    assert stored["token_hash"] == hash_token(token)
    for name, value in stored.items():
        assert token not in str(value), f"the raw session token is stored in {name}"

    # And the whole row as the database itself renders it, which also covers
    # the JSON `events` column and anything added beside it.
    async with async_session_factory() as db:
        dumped = (await db.execute(
            text("SELECT row_to_json(t) FROM runtime_sessions t WHERE session_id = :s"),
            {"s": str(session_id)},
        )).scalar_one()
    assert token not in json.dumps(dumped)


async def test_the_raw_token_never_reaches_the_logs(_as_runtime, _servicenow, caplog):
    """Both paths, because they log differently: a denial logs a warning naming
    the capability, and an execution logs through the connector layer. A token
    in a log line is a credential in a file that outlives the container and is
    read by people who are not the agent."""
    caplog.set_level(logging.DEBUG)

    _, _, token = await _session()
    _as_runtime(token)
    await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))
    await request_capability.fn(Capability.CREATE_CHANGE_REQUEST.value, {})  # denied

    logged = "\n".join(
        [r.getMessage() for r in caplog.records]
        + [str(getattr(r, "__dict__", {})) for r in caplog.records]
    )
    assert logged, "nothing was logged at all — this test would pass vacuously"
    assert token not in logged


async def test_the_denial_reason_does_not_echo_the_token_back(_as_runtime):
    """A refusal is returned to the agent and ends up in mission evidence. An
    error message quoting the credential it rejected would copy it there."""
    await _session()
    bogus = "tok-" + uuid.uuid4().hex
    _as_runtime(bogus)

    answer = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, dict(ROUTINE))

    assert bogus not in json.dumps(answer)


def test_the_workspace_on_disk_never_holds_the_token(tmp_path):
    """The workspace is bind-mounted into the container at /work, so anything
    written there is readable by model-generated code and survives on the host
    until teardown. The MCP config names an ENV VAR (`bearerTokenEnvVar`)
    rather than embedding the credential — this walks every file the runtime
    seeds to prove nothing wrote it out anyway."""
    from orchestrate.runtime.base import AgentSessionSpec
    from orchestrate.runtime.prime import PrimeAgentRuntime

    token = "tok-" + uuid.uuid4().hex
    runtime = PrimeAgentRuntime(mcp_url="http://ados-gateway:8000/mcp/")
    spec = AgentSessionSpec(
        mission_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()),
        objective="o", success_criteria="c",
        workspace_files={"brief.md": "the mission brief"},
    )

    workspace = runtime._prepare_workspace(spec, token)
    try:
        seeded = [p for p in workspace.rglob("*") if p.is_file()]
        assert seeded, "no files were seeded — this test would pass vacuously"
        for path in seeded:
            assert token not in path.read_text(errors="replace"), (
                f"the session token was written to {path.relative_to(workspace)}"
            )

        settings = json.loads((workspace / ".agent" / "settings.json").read_text())
        ados = settings["mcpServers"]["ados"]
        assert ados["bearerTokenEnvVar"] == "ADOS_MCP_TOKEN"
        assert "bearerToken" not in ados, "the literal credential is back in the config"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_runtime_session_token_is_not_a_user_credential():
    """Why self-approval fails at authentication (401) rather than at
    authorization (403): the two credential systems do not overlap. The session
    token is an opaque random string with no signature and no claims, so it
    cannot be decoded into a User at all — there is no identity for RBAC to
    then find insufficient.

    This is the structural reason the runtime cannot decide its own requests;
    `test_the_runtime_cannot_approve_its_own_request` covers the HTTP surface.
    """
    from fastapi import HTTPException

    from backend.app.rbac import decode_access_token
    from orchestrate.runtime.prime import mint_session_token

    token = mint_session_token()
    with pytest.raises(HTTPException) as refused:
        decode_access_token(token)
    assert refused.value.status_code == 401
