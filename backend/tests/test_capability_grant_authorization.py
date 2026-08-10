"""
The grant is the server's, not the agent's — regression tests for the boundary
that makes "ADOS decides what is allowed" true rather than aspirational.

WHAT WAS MISSING
----------------
`test_runtime_approval_round_trip.py` proves the grant is re-checked when a
*parked* request is decided. Nothing covered the ordinary path: a live session
asking, right now, for something its mission never granted. That is the case
the boundary exists for, and it ran unexercised — including the part that
matters most, which is not the returned string but the absence of a connector
call behind it.

WHAT THESE TESTS PIN
--------------------
* a capability outside the mission's grant is denied, and the attempt is
  recorded rather than silently dropped
* no connector is invoked and no external system is touched on that path
* a capability name the agent invented is refused, and an unrecognized name
  inside a corrupted grant still fails safe
* the tier is computed server-side from the capability's risk class; nothing
  the agent puts in `arguments` can lower it
* the grant is re-read from the mission row on every call, not cached from
  when the session started
* `AgentSessionSpec.allowed_capabilities` is advisory — the negative control at
  the bottom shows what trusting it would have allowed

WHY "THE CONNECTOR WAS NEVER INVOKED" IS THE ASSERTION
------------------------------------------------------
A denial that returns `{"status": "denied"}` after posting the ticket is
indistinguishable, from the agent's side, from one that refused first. The
external effect is the thing being prevented, so the tests assert on a
recording connector and a recording hub, not on the reply.

No external writes: ServiceNow is an `httpx.MockTransport` throughout.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from contracts import Capability, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import IntegrationHub, default_hub
from orchestrate.governance import CAPABILITY_RISK_CLASS

GRANTED = Capability.NOTIFY_IT_HELPDESK          # risk class: low  -> autonomous
WITHHELD = Capability.CREATE_CHANGE_REQUEST      # risk class: high -> tier 2


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
def _watched_hub(monkeypatch):
    """Records both layers: every `hub.invoke` ADOS attempts, and every request
    that reached a transport. Either one firing on a denied path is the defect.
    """
    invoked = []
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content or b"{}"))
        return httpx.Response(201, json={"result": {"sys_id": "s1", "number": "INC0099999"}})

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(handler))],
    )

    original = IntegrationHub.invoke

    async def spy(self, call):
        invoked.append(call)
        return await original(self, call)

    monkeypatch.setattr(IntegrationHub, "invoke", spy)
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)
    return invoked, posted


@pytest.fixture
def _as_runtime(monkeypatch):
    def present(token):
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )
    return present


async def _session(*grants: str):
    """A mission granting exactly `grants`, and a live token for its session.
    Takes raw strings so a corrupted grant can be expressed too."""
    async with async_session_factory() as db:
        mission = MissionRow(
            title="grant", objective="o", domain="it",
            allowed_capabilities=list(grants), status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        db.add(RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        ))
        await db.commit()
        return mission.mission_id, token


async def _rows(mission_id):
    async with async_session_factory() as db:
        return (await db.execute(
            select(CapabilityRequestRow).where(CapabilityRequestRow.mission_id == mission_id)
        )).scalars().all()


# --- the positive control ----------------------------------------------------

async def test_a_granted_capability_executes_through_the_connector(_as_runtime, _watched_hub):
    """So the denials below mean 'this one was refused', not 'nothing works'."""
    invoked, posted = _watched_hub
    _, token = await _session(GRANTED.value)
    _as_runtime(token)

    answer = await request_capability.fn(GRANTED.value, {"summary": "pool exhaustion"})

    assert answer["status"] == "executed", answer
    assert len(invoked) == 1
    assert len(posted) == 1


# --- outside the grant -------------------------------------------------------

async def test_a_capability_outside_the_grant_is_denied(_as_runtime, _watched_hub):
    invoked, posted = _watched_hub
    _, token = await _session(GRANTED.value)
    _as_runtime(token)

    answer = await request_capability.fn(WITHHELD.value, {"short_description": "let me in"})

    assert answer["status"] == "denied"
    assert f"'{WITHHELD.value}' is not in this mission's capability grant" == answer["reason"]
    assert invoked == [], "the hub was asked to execute a capability outside the grant"
    assert posted == [], "a denied capability reached the external system"


async def test_the_denied_attempt_is_recorded_rather_than_dropped(_as_runtime, _watched_hub):
    """A refusal nobody can see afterwards is not governance. The row is what
    tells an auditor the agent asked for something it was not granted — and it
    carries the arguments it wanted to use."""
    mission_id, token = await _session(GRANTED.value)
    _as_runtime(token)

    answer = await request_capability.fn(WITHHELD.value, {"short_description": "let me in"})

    rows = await _rows(mission_id)
    assert len(rows) == 1
    row = rows[0]
    assert str(row.request_id) == answer["request_id"]
    assert row.capability == WITHHELD.value
    assert row.status == "denied"
    assert row.result is None, "a denial has no outcome"
    assert row.arguments == {"short_description": "let me in"}


async def test_a_mission_that_granted_nothing_can_do_nothing(_as_runtime, _watched_hub):
    invoked, posted = _watched_hub
    _, token = await _session()  # allowed_capabilities = []
    _as_runtime(token)

    answer = await request_capability.fn(GRANTED.value, {"summary": "s"})

    assert answer["status"] == "denied"
    assert (invoked, posted) == ([], [])


# --- names the agent supplies ------------------------------------------------

async def test_a_capability_name_the_agent_invented_is_refused(_as_runtime, _watched_hub):
    """The agent writes the capability string. It is matched against the grant
    before anything else looks at it, so an invented name is refused by the
    same check as a real-but-withheld one."""
    invoked, posted = _watched_hub
    _, token = await _session(GRANTED.value)
    _as_runtime(token)

    answer = await request_capability.fn("DropAllTables", {"confirm": True})

    assert answer["status"] == "denied"
    assert "not in this mission's capability grant" in answer["reason"]
    assert (invoked, posted) == ([], [])


async def test_an_unrecognized_name_inside_the_grant_still_fails_safe(
    _as_runtime, _watched_hub
):
    """A mission row is data, and data can be wrong — a typo, a stale migration,
    an operator granting a capability that was later renamed. Passing the grant
    check must not imply the name resolves to something ADOS can execute."""
    invoked, posted = _watched_hub
    _, token = await _session("ExfiltrateEverything")
    _as_runtime(token)

    answer = await request_capability.fn("ExfiltrateEverything", {})

    assert answer["status"] == "denied"
    assert answer["reason"] == "'ExfiltrateEverything' is not a known ADOS capability"
    assert (invoked, posted) == ([], [])


# --- the tier is the server's ------------------------------------------------

async def test_the_tier_comes_from_the_risk_class_not_from_the_agents_confidence(
    _as_runtime, _watched_hub
):
    """`assign_policy_tier` reads `_confidence` and `_estimated_cost_usd` out of
    the agent's own arguments. For a high-risk capability neither is consulted
    — the risk class decides first — so an agent cannot talk its way past a
    human by claiming certainty."""
    invoked, posted = _watched_hub
    mission_id, token = await _session(WITHHELD.value)
    _as_runtime(token)

    assert CAPABILITY_RISK_CLASS[WITHHELD] == "high"
    answer = await request_capability.fn(WITHHELD.value, {
        "short_description": "routine, honestly",
        "_confidence": 1.0,
        "_estimated_cost_usd": 0.0,
    })

    assert answer["status"] == "pending_approval"
    assert answer["policy_tier"] == int(PolicyTier.EXECUTIVE_APPROVAL)
    assert (invoked, posted) == ([], []), "a tier 2 request executed without a human"

    rows = await _rows(mission_id)
    assert rows[0].policy_tier == int(PolicyTier.EXECUTIVE_APPROVAL)
    assert rows[0].risk_class == "high"


async def test_governance_fields_in_the_arguments_are_ignored(_as_runtime, _watched_hub):
    """The agent controls the `arguments` dict entirely. If any of these keys
    were read back out of it, the audit row would record the agent's claims
    about its own governance as if ADOS had decided them."""
    mission_id, token = await _session(WITHHELD.value)
    _as_runtime(token)

    answer = await request_capability.fn(WITHHELD.value, {
        "short_description": "s",
        "policy_tier": 0,
        "risk_class": "low",
        "status": "executed",
        "decided_by": "user:cfo",
        "approved_by": "user:cfo",
        "mission_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
    })

    assert answer["status"] == "pending_approval"
    rows = await _rows(mission_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.policy_tier == int(PolicyTier.EXECUTIVE_APPROVAL)
    assert row.risk_class == "high"
    assert row.status == "pending_approval"
    assert row.decided_by is None
    assert row.mission_id == mission_id
    # The id the agent tried to supply is not the one it got back.
    assert str(row.request_id) == answer["request_id"]


async def test_a_cost_claim_can_add_approval_but_never_remove_it(_as_runtime, _watched_hub):
    """The hints are honoured in the direction that adds friction: a low-risk
    capability the agent says is expensive gets parked. The other direction is
    unreachable — the defaults (`_confidence` 0.95, `_estimated_cost_usd` 0.0)
    are already the most permissive inputs the function accepts, so there is no
    value the agent can send that buys it more autonomy than saying nothing.
    """
    invoked, posted = _watched_hub
    _, token = await _session(GRANTED.value)
    _as_runtime(token)

    parked = await request_capability.fn(GRANTED.value, {
        "summary": "s", "_estimated_cost_usd": 300_000.0,
    })
    assert parked["status"] == "pending_approval"
    assert (invoked, posted) == ([], [])

    quiet = await request_capability.fn(GRANTED.value, {"summary": "s", "_confidence": 0.0})
    assert quiet["status"] == "pending_approval", (
        "a low confidence claim must not be ignored either"
    )


async def test_underscore_arguments_never_reach_the_connector(_as_runtime, _watched_hub):
    """The governance hints are ADOS's inputs, not the external system's. A
    ServiceNow ticket carrying `_confidence: 0.95` would be leaking the
    agent's internal reasoning into someone else's system of record."""
    invoked, posted = _watched_hub
    _, token = await _session(GRANTED.value)
    _as_runtime(token)

    await request_capability.fn(GRANTED.value, {
        "summary": "pool exhaustion", "_confidence": 0.99, "_estimated_cost_usd": 12.0,
    })

    assert len(posted) == 1
    body = json.dumps(posted[0])
    assert "_confidence" not in body
    assert "_estimated_cost_usd" not in body
    assert invoked[0].input == {"summary": "pool exhaustion"}


# --- the grant is live -------------------------------------------------------

async def test_the_grant_is_re_read_on_every_call(_as_runtime, _watched_hub):
    """Not cached at session start. A grant narrowed mid-session — an operator
    revoking a permission while the agent is still running — must take effect
    on the very next call, not at the next session."""
    invoked, posted = _watched_hub
    mission_id, token = await _session(GRANTED.value)
    _as_runtime(token)

    assert (await request_capability.fn(GRANTED.value, {"summary": "first"}))["status"] == "executed"

    async with async_session_factory() as db:
        mission = await db.get(MissionRow, mission_id)
        mission.allowed_capabilities = []
        await db.commit()

    second = await request_capability.fn(GRANTED.value, {"summary": "second"})

    assert second["status"] == "denied"
    assert len(invoked) == 1, "the revoked capability executed again"
    assert len(posted) == 1


# --- the negative control ----------------------------------------------------

async def test_trusting_the_spec_the_agent_was_handed_would_have_allowed_this(
    _as_runtime, _watched_hub
):
    """`AgentSessionSpec.allowed_capabilities` is handed to the runtime so it
    knows what to ask for, and the container can read and edit it freely — it
    is in the workspace. This restores the rule "check the request against the
    capability list the session was started with" and shows it permitting
    exactly what the server-side grant refuses.

    Without this, the tests above prove only that the gateway agrees with
    itself; this pins that the two lists are different things and that only one
    of them is authoritative.
    """
    from orchestrate.runtime.base import AgentSessionSpec

    invoked, posted = _watched_hub
    mission_id, token = await _session(GRANTED.value)

    # What the container holds — and, being in the container, what it could
    # have written itself.
    spec = AgentSessionSpec(
        mission_id=str(mission_id), session_id="s", objective="o",
        allowed_capabilities=[GRANTED.value, WITHHELD.value],
    )

    def old_rule(capability, spec):  # the tempting shortcut
        return capability in spec.allowed_capabilities

    assert old_rule(WITHHELD.value, spec) is True, (
        "the spec really does list a capability the mission never granted"
    )

    _as_runtime(token)
    answer = await request_capability.fn(WITHHELD.value, {"short_description": "s"})

    assert answer["status"] == "denied"
    assert (invoked, posted) == ([], [])

    # And the server-side list, which is the one that decided.
    async with async_session_factory() as db:
        mission = await db.get(MissionRow, mission_id)
    assert mission.allowed_capabilities == [GRANTED.value]
