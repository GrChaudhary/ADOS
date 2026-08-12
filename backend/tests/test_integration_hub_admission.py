"""
P11 — admission control at IntegrationHub.invoke(), the one place every
capability call in this system reaches a connector (see hub.py's own
docstring, and integrations/admission_control.py's).

WHAT THIS FILE PROVES
----------------------
* below/at/over limit, for both the general capability-execution gate and
  the Prime-Agent-specific mission gate
* a rejected call NEVER reaches connector.execute() — the critical
  invariant P11 was scoped around ("rejected before any external side
  effect")
* a REAL concurrent race (asyncio.gather, not a sequential simulation of
  one) cannot push the peak-in-flight count past the configured limit
* nothing in call.input (agent-supplied) has any effect on the limit —
  admission control is enforced server-side only
* the rejection metric (ados_admission_rejections_total) moves with the
  right label

A docker-marked variant proving a real `docker run` is never issued past
the mission ceiling lives separately in test_admission_control_docker.py —
this file's fake connector never touches Docker, matching the "no Docker
needed for a plain `pytest` run" convention every other unmarked test here
follows.
"""

import asyncio
import uuid

import pytest

from backend.app import metrics
from contracts import CallStatus, Capability, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier
from integrations.admission_control import AdmissionControl
from integrations.connectors.base import Connector
from integrations.hub import IntegrationHub


class _SpyConnector(Connector):
    """Records every real invocation and can optionally block on an
    asyncio.Event before returning — the mechanism the concurrency-race
    tests use to hold a slot open long enough to observe overlap."""

    def __init__(self, capability: Capability, *, hold: asyncio.Event = None, status: CallStatus = CallStatus.SUCCEEDED):
        self.name = "spy-connector"
        self.capabilities = {capability}
        self._hold = hold
        self._status = status
        self.execute_calls = 0
        self.concurrent_in_flight = 0
        self.peak_concurrent = 0

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        self.execute_calls += 1
        self.concurrent_in_flight += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent_in_flight)
        try:
            if self._hold is not None:
                await self._hold.wait()
            return CapabilityResponse(request_id=call.request_id, status=self._status, connector=self.name)
        finally:
            self.concurrent_in_flight -= 1


def _hub(capability: Capability, connector: Connector, admission_control: AdmissionControl) -> IntegrationHub:
    hub = IntegrationHub(admission_control=admission_control)
    hub.registry.register(connector)
    return hub


def _call(capability: Capability, **extra_input) -> CapabilityCall:
    return CapabilityCall(
        capability=capability,
        input=extra_input,
        requested_by="test:admission",
        incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


# --- below / at / over limit --------------------------------------------------

async def test_below_limit_allowed():
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR)
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=2, max_concurrent_missions=2))
    response = await hub.invoke(_call(Capability.NOTIFY_OPERATOR))
    assert response.status == CallStatus.SUCCEEDED
    assert spy.execute_calls == 1


async def test_at_and_over_limit_deterministic():
    """Two calls held open concurrently against limit=2: both must be
    admitted (deterministic — 'at limit' is not a coin flip). A third,
    concurrent with those two, must be refused."""
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR, hold=hold)
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=2, max_concurrent_missions=2))

    t1 = asyncio.create_task(hub.invoke(_call(Capability.NOTIFY_OPERATOR)))
    t2 = asyncio.create_task(hub.invoke(_call(Capability.NOTIFY_OPERATOR)))
    await asyncio.sleep(0.05)  # let both reach connector.execute() and block on `hold`
    assert spy.concurrent_in_flight == 2, "both calls at exactly the limit must have been admitted"

    third = await hub.invoke(_call(Capability.NOTIFY_OPERATOR))
    assert third.status == CallStatus.FAILED
    assert "admission control" in (third.error or "")
    assert spy.execute_calls == 2, "the third, over-limit call must never have reached the connector"

    hold.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1.status == CallStatus.SUCCEEDED and r2.status == CallStatus.SUCCEEDED


# --- rejection never invokes the connector ------------------------------------

async def test_rejection_never_invokes_connector():
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR, hold=hold)
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1))

    held_task = asyncio.create_task(hub.invoke(_call(Capability.NOTIFY_OPERATOR)))
    await asyncio.sleep(0.05)
    assert spy.execute_calls == 1

    rejected = await hub.invoke(_call(Capability.NOTIFY_OPERATOR))
    assert rejected.status == CallStatus.FAILED
    assert spy.execute_calls == 1, "connector.execute() must not have been called for the rejected request"

    hold.set()
    await held_task


async def test_mission_gate_rejection_never_invokes_connector():
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.RUN_PRIME_RLM_AGENT, hold=hold)
    # Generous general ceiling, tight mission ceiling — proves the SPECIFIC
    # mission gate is what triggers, not the general one.
    hub = _hub(
        Capability.RUN_PRIME_RLM_AGENT, spy,
        AdmissionControl(max_concurrent_capability_executions=10, max_concurrent_missions=1),
    )

    held_task = asyncio.create_task(hub.invoke(_call(Capability.RUN_PRIME_RLM_AGENT)))
    await asyncio.sleep(0.05)
    assert spy.execute_calls == 1

    rejected = await hub.invoke(_call(Capability.RUN_PRIME_RLM_AGENT))
    assert rejected.status == CallStatus.FAILED
    assert "Prime Agent missions" in (rejected.error or "")
    assert spy.execute_calls == 1, "connector.execute() must not have been called for the mission-rejected request"
    # The general capability slot consumed by the rejected attempt must have
    # been released, not leaked — a caller who only ever hits the mission
    # gate should not slowly starve the general ceiling too.
    assert hub.admission_control.current_capability_executions == 1  # only the still-held first call

    hold.set()
    await held_task


# --- real concurrent race, not a sequential simulation --------------------------

async def test_concurrent_race_cannot_bypass_the_capability_limit():
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR, hold=hold)
    limit = 3
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=limit, max_concurrent_missions=limit))

    async def attempt():
        return await hub.invoke(_call(Capability.NOTIFY_OPERATOR))

    tasks = [asyncio.create_task(attempt()) for _ in range(10)]
    await asyncio.sleep(0.05)
    assert spy.peak_concurrent <= limit, f"peak concurrent connector executions ({spy.peak_concurrent}) exceeded the configured limit ({limit})"
    assert spy.peak_concurrent == limit, "with 10 concurrent attempts against limit=3, exactly 3 should be in flight"

    hold.set()
    responses = await asyncio.gather(*tasks)
    admitted = [r for r in responses if r.status == CallStatus.SUCCEEDED]
    refused = [r for r in responses if r.status == CallStatus.FAILED]
    assert len(admitted) == limit
    assert len(refused) == 10 - limit
    assert spy.peak_concurrent <= limit


# --- server-side only -----------------------------------------------------------

async def test_agent_supplied_hints_have_no_effect_on_admission():
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR, hold=hold)
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1))

    held_task = asyncio.create_task(hub.invoke(_call(Capability.NOTIFY_OPERATOR)))
    await asyncio.sleep(0.05)

    rejected = await hub.invoke(
        _call(Capability.NOTIFY_OPERATOR, _priority="critical", _max_concurrent=999, _bypass_admission_control=True)
    )
    assert rejected.status == CallStatus.FAILED, "caller-supplied hints in call.input must not influence admission control"

    hold.set()
    await held_task


# --- metric ------------------------------------------------------------------

async def test_admission_rejection_increments_metric():
    hold = asyncio.Event()
    spy = _SpyConnector(Capability.NOTIFY_OPERATOR, hold=hold)
    hub = _hub(Capability.NOTIFY_OPERATOR, spy, AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1))

    held_task = asyncio.create_task(hub.invoke(_call(Capability.NOTIFY_OPERATOR)))
    await asyncio.sleep(0.05)

    before = metrics.admission_rejections_total.labels(gate="capability_concurrency")._value.get()
    await hub.invoke(_call(Capability.NOTIFY_OPERATOR))
    after = metrics.admission_rejections_total.labels(gate="capability_concurrency")._value.get()
    assert after == before + 1

    hold.set()
    await held_task
