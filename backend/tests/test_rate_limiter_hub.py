"""
P12 — the mission-start rate limiter wired into IntegrationHub.invoke()
(integrations/rate_limiter.py, integrations/hub.py). See
test_integration_hub_admission.py for the sibling concurrency-gate tests
this file's structure mirrors.

Real Postgres throughout (RateLimiter(session_factory=async_session_factory))
— no mocking of the rate-limit table itself. The connector is a spy, never
real Docker/LLM, matching every other unmarked (non-docker) test in this
suite's own convention.
"""

import uuid

import pytest
from sqlalchemy import text

from backend.app import metrics
from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from integrations.admission_control import AdmissionControl
from integrations.connectors.base import Connector
from integrations.hub import IntegrationHub
from integrations.rate_limiter import RateLimiter


class _SpyConnector(Connector):
    def __init__(self, capability: Capability):
        self.name = "spy-connector"
        self.capabilities = {capability}
        self.execute_calls = 0

    async def execute(self, call: CapabilityCall) -> "CapabilityResponse":  # noqa: F821
        from contracts import CapabilityResponse

        self.execute_calls += 1
        return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)


def _call() -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input={},
        requested_by="test:rate-limit",
        incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE rate_limit_events CASCADE"))
        await db.commit()
    yield


def _counter_value(counter, **labels) -> float:
    child = counter.labels(**labels) if labels else counter
    return child._value.get()


async def test_admitted_up_to_the_limit_then_refused_before_the_connector():
    spy = _SpyConnector(Capability.RUN_PRIME_RLM_AGENT)
    hub = IntegrationHub(
        admission_control=AdmissionControl(max_concurrent_capability_executions=10, max_concurrent_missions=10),
        rate_limiter=RateLimiter(session_factory=async_session_factory),
        mission_start_rate_limit_max=2,
        mission_start_rate_limit_window_seconds=60,
    )
    hub.registry.register(spy)

    before = _counter_value(metrics.admission_rejections_total, gate="mission_start_rate")

    r1 = await hub.invoke(_call())
    r2 = await hub.invoke(_call())
    assert r1.status == CallStatus.SUCCEEDED
    assert r2.status == CallStatus.SUCCEEDED
    assert spy.execute_calls == 2

    r3 = await hub.invoke(_call())
    assert r3.status == CallStatus.FAILED
    assert "rate limit" in (r3.error or "")
    assert spy.execute_calls == 2, "the rate-limited third call must never reach the connector"

    after = _counter_value(metrics.admission_rejections_total, gate="mission_start_rate")
    assert after - before == 1, "exactly one mission_start_rate rejection must be recorded"

    # The mission/capability concurrency slots the rejected call took before
    # being refused by the rate limiter must still be released, not leaked.
    assert hub.admission_control.current_missions == 0
    assert hub.admission_control.current_capability_executions == 0


async def test_disabled_when_max_is_non_positive():
    spy = _SpyConnector(Capability.RUN_PRIME_RLM_AGENT)
    hub = IntegrationHub(
        admission_control=AdmissionControl(max_concurrent_capability_executions=10, max_concurrent_missions=10),
        rate_limiter=RateLimiter(session_factory=async_session_factory),
        mission_start_rate_limit_max=0,
        mission_start_rate_limit_window_seconds=60,
    )
    hub.registry.register(spy)
    for _ in range(5):
        response = await hub.invoke(_call())
        assert response.status == CallStatus.SUCCEEDED
    assert spy.execute_calls == 5


async def test_only_applies_to_run_prime_rlm_agent():
    """The rate limiter is scoped to mission starts specifically — an
    ordinary capability call must never be rate-limited by it, even with a
    limit of 1 already exhausted by a mission start."""
    from contracts import CapabilityResponse

    class _OtherSpy(Connector):
        name = "other-spy"
        capabilities = {Capability.NOTIFY_OPERATOR}

        async def execute(self, call: CapabilityCall) -> CapabilityResponse:
            return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)

    mission_spy = _SpyConnector(Capability.RUN_PRIME_RLM_AGENT)
    other_spy = _OtherSpy()
    hub = IntegrationHub(
        admission_control=AdmissionControl(max_concurrent_capability_executions=10, max_concurrent_missions=10),
        rate_limiter=RateLimiter(session_factory=async_session_factory),
        mission_start_rate_limit_max=1,
        mission_start_rate_limit_window_seconds=60,
    )
    hub.registry.register(mission_spy)
    hub.registry.register(other_spy)

    assert (await hub.invoke(_call())).status == CallStatus.SUCCEEDED  # exhausts the mission-start limit

    other_call = CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR, input={}, requested_by="test:rate-limit",
        incident_id=str(uuid.uuid4()), governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )
    response = await hub.invoke(other_call)
    assert response.status == CallStatus.SUCCEEDED, "a non-mission-start capability must be unaffected by the mission-start rate limit"
