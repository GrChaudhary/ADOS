"""
DynamicCapabilityConnector (integrations/connectors/dynamic.py) —
orchestration-platform-vision.md §8's onboarding bridge: every dynamically
onboarded capability shares one sentinel Capability.DYNAMIC_CAPABILITY, and
the connector dispatches internally on the real free-text capability_id
carried in CapabilityCall.input.

Two real gaps this suite exists to pin down, not just the happy path:
  - the connector must independently gate on manifest.status is ACTIVE —
    IntegrationHub.invoke()'s own hot-disable check (integrations/hub.py,
    P14) only blocks HOT_DISABLED, so a capability still sitting in
    PROPOSED/SANDBOX_TESTED (not yet vetted) would otherwise be invocable
    via POST /capabilities/invoke by any authenticated user.
  - that hub-level check resolves dynamic calls by input["capability_id"],
    not call.capability.value (which is always the fixed sentinel string
    for every dynamic call) — the regression test below distinguishes "the
    hub-level check blocked this" from "the connector's own active-check
    happened to also produce FAILED" by asserting on the hub-level check's
    specific hyphenated "hot-disabled" wording, which the connector's own
    message (embedding CapabilityStatus.HOT_DISABLED.value =
    "hot_disabled", underscored) never contains. (Until P14, this
    hub-level check was a synchronous, cache-based PolicyRule named
    hot_disable_policy_rule; it is now an authoritative Postgres read
    inside invoke() itself — see integrations/hub.py's own __init__
    comment for why the synchronous version was removed, not just
    supplemented.)
"""

import pytest

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.capability_manifest import RiskProfileEntry
from integrations.connectors.dynamic import DynamicCapabilityConnector, DynamicDispatchConfig
from integrations.hub import IntegrationHub


def _dynamic_call(capability_id: str | None, **extra_input) -> CapabilityCall:
    payload = {**extra_input}
    if capability_id is not None:
        payload["capability_id"] = capability_id
    return CapabilityCall(
        capability=Capability.DYNAMIC_CAPABILITY,
        incident_id="inc-dynamic-test",
        requested_by="tests/test_dynamic_capability_connector",
        input=payload,
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def _propose_and_advance(hub: IntegrationHub, capability_id: str, *, to_status: str, domain: str = "support"):
    """to_status: 'proposed' | 'sandbox_tested' | 'active' | 'hot_disabled'."""
    await hub.manifests.propose(
        capability_id,
        domain=domain,
        version="1.0.0",
        source="https://github.com/example/onboarded-tool",
        risk_profile=[RiskProfileEntry(action="default", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="newly onboarded")],
        proposed_by="onboarding-agent",
    )
    if to_status == "proposed":
        return
    await hub.manifests.record_sandbox_evidence(capability_id, "ran 2/2 sample tool calls, both succeeded", actor="onboarding-agent")
    if to_status == "sandbox_tested":
        return
    await hub.manifests.activate(capability_id, actor="admin-1", reason="reviewed and approved")
    if to_status == "active":
        return
    await hub.manifests.hot_disable(capability_id, actor="admin-1", reason="misbehaving in production")


@pytest.mark.asyncio
async def test_missing_capability_id_fails_clearly():
    hub = IntegrationHub()
    connector = hub.dynamic_capability_connector
    response = await connector.execute(_dynamic_call(None))
    assert response.status == CallStatus.FAILED
    assert "capability_id" in response.error


@pytest.mark.asyncio
async def test_unknown_capability_id_fails_clearly():
    hub = IntegrationHub()
    connector = hub.dynamic_capability_connector
    response = await connector.execute(_dynamic_call("no-such-capability"))
    assert response.status == CallStatus.FAILED
    assert "no capability manifest registered" in response.error


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["proposed", "sandbox_tested"])
async def test_not_yet_active_capability_is_rejected(status):
    """The connector-level gate this suite exists to prove: nothing short of
    ACTIVE may execute, even though hot_disable_policy_rule wouldn't itself
    object to PROPOSED/SANDBOX_TESTED."""
    hub = IntegrationHub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status=status)

    response = await hub.dynamic_capability_connector.execute(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert "not active" in response.error
    assert status in response.error


@pytest.mark.asyncio
async def test_hot_disabled_dynamic_capability_blocked_by_hub_check_not_just_connector():
    """Regression test for resolving dynamic calls by the real
    capability_id. Distinguishes the hub-level block (message: "is
    hot-disabled") from the connector's own generic active-check (message
    embeds the status value "hot_disabled", underscored) — only the
    hub-level check (integrations/hub.py::invoke(), P14) produces the
    former, since resolving by call.capability.value alone would always
    look up the literal string "DynamicCapability", never this manifest's
    real id."""
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    await _propose_and_advance(hub, "zendesk.delete_ticket", to_status="hot_disabled")

    response = await hub.invoke(_dynamic_call("zendesk.delete_ticket"))
    assert response.status == CallStatus.FAILED
    assert "hot-disabled" in response.error  # hyphenated — the policy rule's exact wording


@pytest.mark.asyncio
async def test_no_dispatch_config_registered_fails_clearly():
    hub = IntegrationHub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    response = await hub.dynamic_capability_connector.execute(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert "no runtime dispatch config" in response.error


@pytest.mark.asyncio
async def test_no_executor_registered_for_track_fails_clearly():
    hub = IntegrationHub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    hub.dynamic_capability_connector.register("zendesk.read_ticket", DynamicDispatchConfig(track="mcp_native"))

    response = await hub.dynamic_capability_connector.execute(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert "no executor registered" in response.error


@pytest.mark.asyncio
async def test_active_capability_with_registered_executor_succeeds_and_records_usage():
    hub = IntegrationHub()
    hub.registry.register(hub.dynamic_capability_connector)
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    hub.dynamic_capability_connector.register("zendesk.read_ticket", DynamicDispatchConfig(track="fake"))

    calls_seen = []

    async def _fake_executor(config: DynamicDispatchConfig, call: CapabilityCall):
        calls_seen.append((config.track, call.input))
        return {"ticket_id": call.input.get("ticket_id"), "subject": "test ticket"}

    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)

    response = await hub.invoke(_dynamic_call("zendesk.read_ticket", ticket_id="T-1"))
    assert response.status == CallStatus.SUCCEEDED
    assert response.connector == "dynamic_capability"
    assert response.output == {"ticket_id": "T-1", "subject": "test ticket"}
    assert calls_seen == [("fake", {"capability_id": "zendesk.read_ticket", "ticket_id": "T-1"})]

    manifest = hub.manifests.manifest_for("zendesk.read_ticket")
    assert manifest.usage_count == 1


@pytest.mark.asyncio
async def test_executor_exception_becomes_failed_response_not_a_raise():
    hub = IntegrationHub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    hub.dynamic_capability_connector.register("zendesk.read_ticket", DynamicDispatchConfig(track="fake"))

    async def _broken_executor(config, call):
        raise RuntimeError("upstream tool crashed")

    hub.dynamic_capability_connector.register_executor("fake", _broken_executor)

    response = await hub.dynamic_capability_connector.execute(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert "upstream tool crashed" in response.error

    # A real executor failure is evidence about THIS capability's own
    # behavior — recorded separately from usage_count (successes only) so
    # CapabilityManifestRegistry.calibrate_tier() can require a genuinely
    # clean track record, not just a high call count.
    manifest = hub.manifests.manifest_for("zendesk.read_ticket")
    assert manifest.usage_count == 0
    assert manifest.failure_count == 1


@pytest.mark.asyncio
async def test_routing_errors_before_the_executor_runs_are_not_counted_as_capability_failures():
    """missing capability_id / not-active / no-dispatch-config / no-
    executor are configuration or routing problems, not evidence the
    onboarded capability itself misbehaved — none of them should move
    failure_count, which calibrate_tier() treats as a hard gate."""
    hub = IntegrationHub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    # Deliberately no dispatch config registered.

    response = await hub.dynamic_capability_connector.execute(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert hub.manifests.manifest_for("zendesk.read_ticket").failure_count == 0


@pytest.mark.asyncio
async def test_default_hub_prefers_dynamic_connector_over_console_for_the_sentinel():
    """ConsoleConnector's capabilities = set(Capability) is re-evaluated
    fresh and therefore includes DYNAMIC_CAPABILITY too — this pins down
    default_hub()'s registration order so Console never silently swallows
    dynamic calls instead of the real connector."""
    from integrations.hub import default_hub

    hub = default_hub()
    await _propose_and_advance(hub, "zendesk.read_ticket", to_status="active")
    # No dispatch config registered on purpose — if Console had won
    # selection this would SUCCEED via the demo fallback instead of failing
    # with the dynamic connector's specific "no runtime dispatch config"
    # message.
    response = await hub.invoke(_dynamic_call("zendesk.read_ticket"))
    assert response.status == CallStatus.FAILED
    assert "no runtime dispatch config" in response.error
