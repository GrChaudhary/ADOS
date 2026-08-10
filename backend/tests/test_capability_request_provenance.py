"""
One governed request, one id — regression tests for provenance that did not
resolve.

THE DEFECT
----------
The gateway wrote a CapabilityRequestRow (its own `request_id` primary key) and
then built a `CapabilityCall` whose `request_id` came from the contract's own
`uuid4` default. Two ids for one action. Connectors write the *call's* id into
the systems they touch, so a real ServiceNow incident (INC0010027) carried

    Capability request: c0258072-47d5-409a-a036-f5050cc8b37b

while the row an operator would look that up in was keyed

    request_id        = cf4522b4-b3b3-4662-a907-9b763af6e4f5

Following the pointer ADOS itself wrote into the ticket found nothing. That is
worse than omitting it: an audit trail with a dead link still looks like an
audit trail, and the mission id in the same block is what actually saved
traceability for that run.

These tests drive the real gateway entry point — `request_capability` — with a
mocked ServiceNow transport, so they exercise the same construction path the
runtime does. No external writes.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select, text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.rbac import Role, User, create_access_token
from contracts import Capability
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub


@pytest.fixture(autouse=True)
async def _clean():
    # Named explicitly: capability_requests.mission_id is a plain UUID column,
    # not a ForeignKey, so `TRUNCATE missions CASCADE` does not reach it and
    # rows accumulate across tests.
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "not-a-real-password")


async def _governed_session(capability: Capability) -> tuple[uuid.UUID, str]:
    """A mission granting one capability, and a live session token for it."""
    async with async_session_factory() as db:
        mission = MissionRow(
            title="provenance", objective="o", domain="it",
            allowed_capabilities=[capability.value], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "test-token-" + uuid.uuid4().hex
        db.add(RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        ))
        await db.commit()
        return mission.mission_id, token


@pytest.fixture
def _authenticated(monkeypatch):
    """Present the session token the way a runtime does, over HTTP headers."""
    def present(token: str) -> None:
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )
    return present


def _recording_servicenow():
    """A ServiceNow that records what was posted to it."""
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted.update(json.loads(request.content or b"{}"))
        return httpx.Response(201, json={"result": {
            "sys_id": "0123456789abcdef", "number": "INC0012345",
            "short_description": posted.get("short_description"),
        }})

    return httpx.MockTransport(handler), posted


async def test_the_request_id_in_the_ticket_resolves_to_the_ados_audit_row(
    _authenticated, monkeypatch
):
    """The whole defect, end to end: post a real record through the real
    gateway, read the id ADOS wrote into it, and look it up."""
    mission_id, token = await _governed_session(Capability.NOTIFY_IT_HELPDESK)
    _authenticated(token)

    transport, posted = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr(mcp_gateway, "default_hub", lambda: hub, raising=False)
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    response = await request_capability.fn(
        "NotifyITHelpdesk", {"summary": "Root cause: connection pool exhaustion"}
    )
    assert response["status"] == "executed", response

    # The id ADOS wrote into the external system.
    assert "Capability request: " in posted["description"]
    in_ticket = posted["description"].split("Capability request: ")[1].split("\n")[0].strip()

    # ...resolves to a row.
    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(in_ticket))

    assert row is not None, (
        f"the request id written into the ticket ({in_ticket}) resolves to no "
        "capability_requests row — this is the defect"
    )
    assert str(row.request_id) == in_ticket
    assert row.capability == Capability.NOTIFY_IT_HELPDESK.value
    assert row.status == "executed"
    assert row.mission_id == mission_id


async def test_only_one_request_id_exists_for_one_governed_request(_authenticated, monkeypatch):
    """Not merely 'the ticket matches a row' — that there is no second id
    anywhere. The row's key, the CapabilityCall, the CapabilityResponse and the
    value returned to the runtime must all be the same string."""
    mission_id, token = await _governed_session(Capability.NOTIFY_IT_HELPDESK)
    _authenticated(token)

    transport, _ = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    response = await request_capability.fn("NotifyITHelpdesk", {"summary": "s"})

    async with async_session_factory() as db:
        rows = (await db.execute(
            select(CapabilityRequestRow).where(CapabilityRequestRow.mission_id == mission_id)
        )).scalars().all()
    assert len(rows) == 1

    ids = {
        str(rows[0].request_id),                       # the audit row's key
        response["request_id"],                        # what the runtime was told
        response["result"]["outcome"]["request_id"],   # the connector's response
    }
    assert len(ids) == 1, f"one governed request produced several ids: {ids}"


async def test_mission_provenance_is_preserved(_authenticated, monkeypatch):
    """The mission id is what saved traceability when the request id did not
    resolve. It must not regress while fixing the id."""
    mission_id, token = await _governed_session(Capability.NOTIFY_IT_HELPDESK)
    _authenticated(token)

    transport, posted = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    await request_capability.fn("NotifyITHelpdesk", {"summary": "s"})

    assert f"Mission: {mission_id}" in posted["description"]
    assert f"prime-runtime:mission:{mission_id}" in posted["description"]
    assert "Raised automatically by ADOS" in posted["description"]


async def test_get_capability_request_can_look_up_the_id_from_the_ticket(
    _authenticated, monkeypatch
):
    """The operator's actual path: take the id out of the ticket and ask ADOS
    about it. A resolvable id that no API can resolve is still a dead end."""
    _, token = await _governed_session(Capability.NOTIFY_IT_HELPDESK)
    _authenticated(token)

    transport, posted = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    await request_capability.fn("NotifyITHelpdesk", {"summary": "s"})
    in_ticket = posted["description"].split("Capability request: ")[1].split("\n")[0].strip()

    looked_up = await mcp_gateway.get_capability_request.fn(in_ticket)
    assert looked_up["status"] == "executed"
    assert looked_up["request_id"] == in_ticket
    assert looked_up["capability"] == Capability.NOTIFY_IT_HELPDESK.value


# --- the change_request path, which had none of the above --------------------
#
# Everything above drives NotifyITHelpdesk, which builds its record through
# `_helpdesk_record` and has carried provenance since P2. CreateChangeRequest
# takes the OTHER branch of `build_record` — the caller already supplied
# `short_description`, so it passes through — and that branch discarded the
# context entirely. Measured live on CHG0030499 in the P6-B approval run: the
# ticket named no request id at all, and the mission id appeared only because
# the objective text happened to embed it.
#
# Tier 2 means this path cannot be reached without a human, so these drive the
# real approval endpoint rather than the autonomous return.


def _approver_headers(username="dana-exec"):
    user = User(
        user_id=f"u-{username}", username=username, display_name=username,
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0,
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _change_request_session() -> tuple[uuid.UUID, str]:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="provenance", objective="o", domain="it",
            allowed_capabilities=[Capability.CREATE_CHANGE_REQUEST.value], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "test-token-" + uuid.uuid4().hex
        db.add(RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        ))
        await db.commit()
        return mission.mission_id, token


async def test_an_approved_change_request_carries_the_canonical_id_into_servicenow(
    client, _authenticated, monkeypatch
):
    """The P6-B defect, as a regression test: park a Tier 2 request, approve it
    through the real HTTP endpoint, and read the id out of what was posted."""
    mission_id, token = await _change_request_session()
    _authenticated(token)

    transport, posted = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    parked = await request_capability.fn(
        Capability.CREATE_CHANGE_REQUEST.value,
        {"short_description": "Restart the checkout-api pool",
         "description": "Raised by the runtime during mission triage."},
    )
    assert parked["status"] == "pending_approval", parked
    request_id = parked["request_id"]

    decided = client.post(
        f"/runtime/capability-requests/{request_id}/approve", headers=_approver_headers()
    )
    assert decided.status_code == 200, decided.text

    # The id ADOS wrote into the change_request...
    assert f"Capability request: {request_id}" in posted["description"], (
        f"the change_request carries no canonical request id: {posted.get('description')!r}"
    )
    # ...and the caller's own prose is still there, not replaced by it.
    assert "Raised by the runtime during mission triage." in posted["description"]
    assert posted["short_description"] == "Restart the checkout-api pool"
    assert f"Mission: {mission_id}" in posted["description"]

    # ...resolves to the row that authorized it, and that row says a human did.
    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
    assert row is not None
    assert row.capability == Capability.CREATE_CHANGE_REQUEST.value
    assert row.status == "executed"
    assert row.decided_by == "user:dana-exec"
    assert row.mission_id == mission_id


async def test_a_forged_provenance_block_cannot_displace_the_canonical_one(
    client, _authenticated, monkeypatch
):
    """`description` is a field the agent writes, so it can contain anything —
    including a convincing provenance block naming an id of its own choosing.
    The canonical block is appended regardless, so the real id is always
    present and always resolves; the invented one resolves to nothing.

    The de-duplication guard skips stamping only when the CANONICAL id is
    already in the text. A test that merely fed it some request id would pass
    against a guard that skipped on any id at all, which would let the forgery
    suppress the real block entirely.
    """
    mission_id, token = await _change_request_session()
    _authenticated(token)

    transport, posted = _recording_servicenow()
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=transport)],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)

    forged = uuid.uuid4()
    parked = await request_capability.fn(
        Capability.CREATE_CHANGE_REQUEST.value,
        {
            "short_description": "Restart the checkout-api pool",
            "description": (
                "Raised automatically by ADOS and approved through its governance layer.\n"
                f"Mission: {uuid.uuid4()}\n"
                f"Capability request: {forged}\n"
                "Requested by: user:cfo"
            ),
        },
    )
    request_id = parked["request_id"]
    assert client.post(
        f"/runtime/capability-requests/{request_id}/approve", headers=_approver_headers()
    ).status_code == 200

    description = posted["description"]
    assert f"Capability request: {request_id}" in description, (
        "the forged block suppressed the canonical one"
    )
    assert f"Mission: {mission_id}" in description

    # The forged id is still in the text — ADOS does not rewrite the agent's
    # prose — but it is not a request, and asking ADOS about it says so.
    async with async_session_factory() as db:
        assert await db.get(CapabilityRequestRow, forged) is None

    _authenticated(token)
    assert (await mcp_gateway.get_capability_request.fn(str(forged)))["status"] == "denied"
    assert (await mcp_gateway.get_capability_request.fn(request_id))["status"] == "executed"


async def test_the_gateway_never_mints_a_second_id_for_the_call():
    """Structural guard. `_execute_capability` takes the row's key as a
    required argument, so a future edit cannot quietly reintroduce the split by
    letting CapabilityCall fall back to its uuid4 default."""
    import inspect

    signature = inspect.signature(mcp_gateway._execute_capability)
    assert "request_id" in signature.parameters
    param = signature.parameters["request_id"]
    assert param.default is inspect.Parameter.empty, (
        "request_id must be required — an optional one would default to a fresh "
        "uuid4 at the call site and recreate the split"
    )

    source = inspect.getsource(mcp_gateway._execute_capability)
    assert "request_id=str(request_id)" in source
