"""
Tests for SmartFactoryConnector — integrations/connectors/smart_factory.py.

Two of these tests could never have passed as originally written: they built
CapabilityCall without its required governance fields, and reached for a
`hub.registry._connectors` attribute that does not exist. Fixing them to match
the real contracts is what surfaced the defects the rest of this file now pins.
"""

import httpx
import pytest

from contracts import (
    CONFIRMED_STATUSES,
    UNRESOLVED_STATUSES,
    CallStatus,
    Capability,
    CapabilityCall,
    CapabilityResponse,
    GovernanceInfo,
    PolicyTier,
)
from integrations.connectors.smart_factory import SmartFactoryConnector
from integrations.hub import default_hub


def _call(capability: Capability, **input_) -> CapabilityCall:
    """CapabilityCall is a validated governance contract: incident_id,
    requested_by and governance are REQUIRED. A capability call that cannot say
    who asked for it, about what, and under which tier is not a thing ADOS is
    willing to represent — which is the point, and why omitting them raises."""
    return CapabilityCall(
        capability=capability,
        input=input_,
        requested_by="test",
        incident_id="INC-TEST-1",
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _gateway(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/twin/gnn-risk" in url:
        return httpx.Response(200, json={"global_risk_score": 0.15, "status": "LOW_RISK"})
    if "/twin/rul" in url:
        return httpx.Response(200, json={"machines": {"ov": {"rul_hours": 450}}})
    if "/stations/vgr/action" in url:
        return httpx.Response(200, json={"status": "success", "action": "reroute", "station_id": "vgr"})
    return httpx.Response(400, json={"error": "unknown endpoint"})


async def test_smart_factory_connector_capabilities():
    connector = SmartFactoryConnector()
    for capability in (
        Capability.REROUTE_STATION,
        Capability.EVALUATE_GNN_RISK,
        Capability.READ_RUL_TELEMETRY,
        Capability.SORT_WORKPIECE,
        Capability.UPDATE_MES,
        Capability.RESERVE_INVENTORY,
    ):
        assert capability in connector.capabilities


async def test_gateway_data_actually_reaches_the_caller():
    """CapabilityResponse has no `result` field. The connector originally
    passed `result=data`, which pydantic silently dropped, so every capability
    returned SUCCEEDED with output == {} — the risk score, the telemetry and
    the station acknowledgement never left the connector and nothing warned."""
    connector = SmartFactoryConnector(transport=_transport(_gateway))

    risk = await connector.execute(_call(Capability.EVALUATE_GNN_RISK))
    assert risk.status is CallStatus.SUCCEEDED
    assert risk.output["global_risk_score"] == 0.15

    rul = await connector.execute(_call(Capability.READ_RUL_TELEMETRY))
    assert rul.status is CallStatus.SUCCEEDED
    assert rul.output["machines"]["ov"]["rul_hours"] == 450

    reroute = await connector.execute(_call(Capability.REROUTE_STATION, target="Line_2_VGR"))
    assert reroute.status is CallStatus.SUCCEEDED
    assert reroute.output["station_id"] == "vgr"


async def test_an_http_error_from_the_gateway_is_not_a_completed_action():
    """SORT_WORKPIECE hits an endpoint the mock rejects with 400. Every branch
    previously returned SUCCEEDED regardless of status code, so the gateway's
    own error body was filed as the result of a successful sort."""
    connector = SmartFactoryConnector(transport=_transport(_gateway))
    response = await connector.execute(_call(Capability.SORT_WORKPIECE))

    assert response.status is CallStatus.FAILED
    assert "HTTP 400" in (response.error or "")


async def test_an_unreachable_gateway_is_a_failure_not_a_simulation():
    """The most consequential of the three. The exception handler returned
    SUCCEEDED with a "simulated" payload whenever the gateway was unreachable,
    which made an unplugged factory and a completed physical action identical
    in the audit trail. ADOS would have recorded the workpiece as re-dispatched
    because nothing threw on our side.

    ConnectError specifically: the request never left, so nothing happened in
    the plant and FAILED is the honest answer."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    connector = SmartFactoryConnector(transport=_transport(refuse))
    response = await connector.execute(_call(Capability.REROUTE_STATION, target="Line_2_VGR"))

    assert response.status is CallStatus.FAILED
    assert "never sent" in (response.error or "")
    assert response.output == {}
    # The old behaviour, pinned so it cannot come back: a "simulated" payload
    # dressed up as a real one.
    assert "simulated" not in str(response.output)


async def test_contact_lost_mid_command_is_UNKNOWN_not_a_guess():
    """The third outcome. A ReadTimeout on a POST means the command was sent
    and the reply never came: the gripper may have moved.

    SUCCEEDED would claim an effect nobody observed. FAILED is worse — it
    invites a retry that could re-dispatch the same workpiece twice. Neither
    binary answer is true, so ADOS records the uncertainty instead."""

    def drop_after_send(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response never arrived", request=request)

    connector = SmartFactoryConnector(transport=_transport(drop_after_send))
    response = await connector.execute(_call(Capability.REROUTE_STATION, target="Line_2_VGR"))

    assert response.status is CallStatus.UNKNOWN
    assert response.status not in CONFIRMED_STATUSES
    assert response.status in UNRESOLVED_STATUSES
    assert "verify before retrying" in (response.error or "")


async def test_a_lost_read_is_plain_failure_not_UNKNOWN():
    """UNKNOWN is reserved for calls that could have changed the world.
    Over-applying it would flood the reconciliation queue with reads that
    changed nothing and can simply be asked again."""

    def drop_after_send(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response never arrived", request=request)

    connector = SmartFactoryConnector(transport=_transport(drop_after_send))
    response = await connector.execute(_call(Capability.READ_RUL_TELEMETRY))

    assert response.status is CallStatus.FAILED


async def test_an_unknown_response_field_cannot_silently_vanish():
    """Defect 1 at the contract level, not the connector level.

    `result=` is not a field on CapabilityResponse. With pydantic's default
    extra="ignore" it was dropped in silence and the response came back
    SUCCEEDED with an empty output — six capabilities' worth of factory data
    lost with nothing raised and no test failing. extra="forbid" turns a
    misspelled field into a construction-time error."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CapabilityResponse(
            request_id="r1",
            status=CallStatus.SUCCEEDED,
            connector="smart_factory",
            result={"global_risk_score": 0.15},   # the original typo
        )


async def test_smart_factory_connector_registered_in_default_hub():
    hub = default_hub()
    for capability in SmartFactoryConnector.capabilities:
        names = [c.name for c in hub.registry.connectors_for(capability)]
        assert "smart_factory" in names, f"{capability.value} -> {names}"


async def test_console_never_wins_a_factory_capability():
    """Registration order is load-bearing: ConsoleConnector declares
    set(Capability) and is_configured() is True, so if it were selected first
    every factory action would return "[console] simulated ..." and succeed.

    Deliberately NOT asserting smart_factory is first overall. ReserveInventory
    resolves to SAP ahead of it, which is correct — inventory reservation is an
    ERP action and was routed there before the factory connector existed. The
    invariant is that the simulator loses, not that the newest connector wins.
    """
    hub = default_hub()
    for capability in SmartFactoryConnector.capabilities:
        names = [c.name for c in hub.registry.connectors_for(capability)]
        assert "console" in names, f"expected console as the fallback for {capability.value}"
        assert names.index("smart_factory") < names.index("console"), (
            f"{capability.value} would fall through to the console simulator: {names}"
        )
