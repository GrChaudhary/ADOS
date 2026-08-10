"""
The human-approval round trip: pending -> durable request -> decision ->
resumed execution -> final governed result.

WHAT WAS MISSING
----------------
The gateway parked Tier 1/2 requests correctly and the `ados` skill polled for
them correctly, but nothing in ADOS could ever move a row out of
`pending_approval` — `mcp_gateway.py` was the only writer of that table. Every
Tier 1/2 request parked forever and the agent raised `CapabilityTimeout`. Half a
round trip is not an approval workflow.

WHAT THESE TESTS PIN
--------------------
* a parked request executes only after a human decides, and then really executes
* a rejected request produces NO side effect and NO success-shaped result
* the runtime cannot decide its own request
* deciding twice cannot execute twice
* a dead session's parked request does not fire into the void
* the grant is re-checked at decision time, not trusted from when it parked
* the approver's identity reaches the connector and the audit row
* one request id throughout, still resolvable

No external writes: ServiceNow is an `httpx.MockTransport` throughout.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.rbac import Role, User, create_access_token
from contracts import Capability, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub

# NotifyITHelpdesk is tier 0 by default. A high claimed cost drives
# assign_policy_tier to a tier that requires a human, which is the only way to
# park a request without inventing a fake capability.
EXPENSIVE = {"summary": "Root cause: pool exhaustion", "_estimated_cost_usd": 300_000.0}


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


def _headers(role=Role.EXECUTIVE, limit=1_000_000.0, username="approver-1"):
    user = User(
        user_id=f"u-{username}", username=username, display_name=username,
        role=role, approval_limit_usd=limit,
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _mission_and_session(capability=Capability.NOTIFY_IT_HELPDESK):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="approval round trip", objective="o", domain="it",
            allowed_capabilities=[capability.value], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


@pytest.fixture
def _as_runtime(monkeypatch):
    def present(token):
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )
    return present


@pytest.fixture
def _servicenow(monkeypatch):
    """Install a recording ServiceNow and report what reached it."""
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content or b"{}"))
        return httpx.Response(201, json={"result": {
            "sys_id": "abc123", "number": "INC0099999",
        }})

    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(handler))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)
    return posted


async def _park_a_request(_as_runtime, token) -> str:
    """Drive the real gateway until it parks a request on a human."""
    _as_runtime(token)
    parked = await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))
    assert parked["status"] == "pending_approval", parked
    return parked["request_id"]


# --- the round trip ----------------------------------------------------------

async def test_a_tier_1_request_parks_and_nothing_executes_until_a_human_decides(
    client, _as_runtime, _servicenow
):
    _, session_id, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    # Nothing has happened out there.
    assert _servicenow == [], "a parked request must not touch the external system"

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        sess = await db.get(RuntimeSessionRow, session_id)
    assert row.status == "pending_approval"
    assert row.result is None
    assert row.policy_tier >= PolicyTier.APPROVAL_REQUIRED
    assert sess.state == "waiting_approval"

    # It is visible to a human, which is the only way it ever gets decided.
    queue = client.get("/runtime/capability-requests", headers=_headers()).json()
    assert queue["count"] == 1
    assert queue["requests"][0]["requestId"] == request_id


async def test_approval_executes_through_the_governed_path_and_the_agent_sees_the_result(
    client, _as_runtime, _servicenow
):
    """The whole round trip, ending where the agent is actually looking."""
    _, session_id, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    decided = client.post(
        f"/runtime/capability-requests/{request_id}/approve", headers=_headers()
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["status"] == "executed"
    assert body["decidedBy"] == "user:approver-1"

    # It really executed — one real POST, through the connector.
    assert len(_servicenow) == 1
    assert _servicenow[0]["short_description"].startswith("Root cause")

    # The audit row is the executor's, not the approver's assertion.
    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
        sess = await db.get(RuntimeSessionRow, session_id)
    assert row.status == "executed"
    assert row.result["outcome"]["connector"] == "servicenow"
    assert row.result["outcome"]["output"]["number"] == "INC0099999"
    assert sess.state == "running", "the session should be unblocked once nothing is parked"

    # And the agent's own poll — the thing it is sitting in — now returns it.
    _as_runtime(token)
    polled = await mcp_gateway.get_capability_request.fn(request_id)
    assert polled["status"] == "executed"
    assert polled["result"]["outcome"]["output"]["number"] == "INC0099999"


async def test_rejection_produces_no_side_effect_and_no_success_shaped_result(
    client, _as_runtime, _servicenow
):
    _, session_id, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    body = client.post(
        f"/runtime/capability-requests/{request_id}/reject",
        headers=_headers(), json={"reason": "not during the change freeze"},
    ).json()

    assert body["status"] == "denied"
    assert "not during the change freeze" in body["reason"]
    assert body["result"] is None, "a refusal has no outcome to report"
    assert _servicenow == [], "a rejected request must never reach the external system"

    async with async_session_factory() as db:
        sess = await db.get(RuntimeSessionRow, session_id)
    assert sess.state == "running"

    # The agent learns it was refused, with the reason — the skill raises
    # CapabilityDenied on exactly this shape.
    _as_runtime(token)
    polled = await mcp_gateway.get_capability_request.fn(request_id)
    assert polled["status"] == "denied"
    assert "not during the change freeze" in polled["reason"]


# --- the things that must not be possible ------------------------------------

async def test_the_runtime_cannot_approve_its_own_request(client, _as_runtime, _servicenow):
    """The session token names a session and carries no claims. If it could
    release a Tier 1/2 request, parking it would be theatre."""
    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    # The runtime's own credential, presented the only way it can be.
    refused = client.post(
        f"/runtime/capability-requests/{request_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code in (401, 403), refused.text
    assert _servicenow == []

    # And no approve tool exists on the MCP surface at all.
    tool_names = {t.lower() for t in (await mcp_gateway.mcp.get_tools()).keys()}
    assert not any("approve" in n or "decide" in n or "reject" in n for n in tool_names), (
        f"the runtime must not be able to decide its own requests: {tool_names}"
    )


async def test_deciding_twice_cannot_execute_twice(client, _as_runtime, _servicenow):
    """A double approval of NotifyITHelpdesk would raise two real tickets."""
    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    first = client.post(f"/runtime/capability-requests/{request_id}/approve", headers=_headers())
    second = client.post(f"/runtime/capability-requests/{request_id}/approve", headers=_headers())

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already" in second.json()["detail"]
    assert len(_servicenow) == 1, "the capability executed more than once"


async def test_a_rejected_request_cannot_then_be_approved(client, _as_runtime, _servicenow):
    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    client.post(f"/runtime/capability-requests/{request_id}/reject", headers=_headers())
    revived = client.post(f"/runtime/capability-requests/{request_id}/approve", headers=_headers())

    assert revived.status_code == 409
    assert _servicenow == []


async def test_an_auditor_cannot_decide(client, _as_runtime, _servicenow):
    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    refused = client.post(
        f"/runtime/capability-requests/{request_id}/approve",
        headers=_headers(role=Role.AUDITOR),
    )
    assert refused.status_code == 403
    assert "read-only" in refused.json()["detail"]
    assert _servicenow == []


async def test_an_approver_below_the_cost_limit_cannot_release_it(
    client, _as_runtime, _servicenow
):
    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    refused = client.post(
        f"/runtime/capability-requests/{request_id}/approve",
        headers=_headers(role=Role.EXECUTIVE, limit=1_000.0),
    )
    assert refused.status_code == 403
    assert "Approval limit" in refused.json()["detail"]
    assert _servicenow == []


async def test_a_dead_session_s_parked_request_does_not_fire_into_the_void(
    client, _as_runtime, _servicenow
):
    """The container is gone and the workspace deleted. Executing now would
    create a real ticket for a mission that already ended, with nobody
    watching for it."""
    _, session_id, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    async with async_session_factory() as db:
        sess = await db.get(RuntimeSessionRow, session_id)
        sess.state = "completed"
        await db.commit()

    refused = client.post(f"/runtime/capability-requests/{request_id}/approve", headers=_headers())
    assert refused.status_code == 409
    assert "nobody waiting" in refused.json()["detail"]
    assert _servicenow == []


async def test_the_grant_is_rechecked_at_decision_time(client, _as_runtime, _servicenow):
    """A mission's grant can be narrowed while a request waits on a human.
    The narrower answer must win — approving from a stale grant would let a
    revoked permission be exercised after it was revoked."""
    mission_id, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    async with async_session_factory() as db:
        mission = await db.get(MissionRow, mission_id)
        mission.allowed_capabilities = []
        await db.commit()

    refused = client.post(f"/runtime/capability-requests/{request_id}/approve", headers=_headers())
    assert refused.status_code == 409
    assert "no longer in this mission's capability grant" in refused.json()["detail"]
    assert _servicenow == []

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
    assert row.status == "denied"


async def test_two_approvers_deciding_at_the_same_moment_execute_once(
    _as_runtime, _servicenow
):
    """The sequential double-approval test above passes even with a
    check-then-act race in it. This one does not: both callers read the row
    concurrently, and without `SELECT ... FOR UPDATE` both see
    `pending_approval` and both execute — two real tickets.

    Calls the endpoint coroutines directly with two independent sessions,
    because TestClient is synchronous and cannot produce the overlap.
    """
    import asyncio

    from backend.app.routers.runtime_approvals import approve_capability_request

    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)

    user = User(
        user_id="u-race", username="racer", display_name="racer",
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0,
    )

    class _FakeRequest:
        class app:
            class state:
                pass

    async def decide():
        async with async_session_factory() as db:
            try:
                return await approve_capability_request(
                    request_id, _FakeRequest(), current_user=user, session=db
                )
            except Exception as exc:  # HTTPException(409) for the loser
                return exc

    outcomes = await asyncio.gather(decide(), decide())

    executed = [o for o in outcomes if isinstance(o, dict)]
    assert len(executed) == 1, f"both approvals went through: {outcomes}"
    assert len(_servicenow) == 1, (
        f"the capability executed {len(_servicenow)} times — a concurrent double "
        "approval raised more than one real ticket"
    )


# --- provenance --------------------------------------------------------------

async def test_the_approvers_identity_reaches_the_connector_and_the_row(
    client, _as_runtime, _servicenow, monkeypatch
):
    """Who released this is part of the governed result, not a UI detail."""
    seen = {}
    original = ServiceNowConnector.execute

    async def spy(self, call):
        seen["approved_by"] = call.governance.approved_by
        seen["tier"] = int(call.governance.policy_tier)
        seen["request_id"] = call.request_id
        return await original(self, call)

    monkeypatch.setattr(ServiceNowConnector, "execute", spy)

    _, _, token = await _mission_and_session()
    request_id = await _park_a_request(_as_runtime, token)
    client.post(
        f"/runtime/capability-requests/{request_id}/approve",
        headers=_headers(username="dana-exec"),
    )

    assert seen["approved_by"] == "dana-exec"
    assert seen["tier"] >= int(PolicyTier.APPROVAL_REQUIRED)
    # Still one id, all the way through — the P2 provenance fix must survive.
    assert seen["request_id"] == request_id

    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
    assert row.decided_by == "user:dana-exec"
    assert str(row.request_id) == request_id


async def test_the_autonomous_path_still_records_no_approver(client, _as_runtime, _servicenow, monkeypatch):
    """Negative control for the field: Tier 0 must stay `approved_by: None`.
    A default that quietly stamps somebody in would make every autonomous
    action look human-approved in the audit trail."""
    seen = {}
    original = ServiceNowConnector.execute

    async def spy(self, call):
        seen["approved_by"] = call.governance.approved_by
        return await original(self, call)

    monkeypatch.setattr(ServiceNowConnector, "execute", spy)

    _, _, token = await _mission_and_session()
    _as_runtime(token)
    done = await request_capability.fn("NotifyITHelpdesk", {"summary": "cheap and routine"})

    assert done["status"] == "executed"
    assert seen["approved_by"] is None
