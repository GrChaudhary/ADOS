"""
P12 — IntegrationHub.invoke() actually wiring the global (Postgres-backed)
admission layer, not just AdmissionControl's own methods in isolation
(test_admission_control_global.py covers those). This is the layer that
matters in practice: hub.invoke() is what every real capability call goes
through, and it is the one place the local-pass/global-reject release
sequencing (admission_control.py's own docstring) actually has to be
correct under real concurrency.

Real Postgres throughout; the connector is a spy, never real Docker/LLM.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from contracts import CallStatus, Capability, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.admission_lease import AdmissionLeaseRow
from integrations.admission_control import GATE_CAPABILITY_CONCURRENCY, AdmissionControl
from integrations.connectors.base import Connector
from integrations.hub import IntegrationHub


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE admission_leases CASCADE"))
        await db.commit()
    yield


class _SpyConnector(Connector):
    def __init__(self, capability: Capability):
        self.name = "spy-connector"
        self.capabilities = {capability}
        self.execute_calls = 0

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        self.execute_calls += 1
        return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)


def _call() -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR, input={}, requested_by="test:hub-global-admission",
        incident_id=str(uuid.uuid4()), governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def test_hub_invoke_rejects_globally_even_when_this_processs_own_local_counter_is_fresh():
    """THE scenario that actually distinguishes hub.py's global check from
    its local one, and the reason a same-process concurrent-race test
    cannot: within one process, the local in-process counter always sees
    every call this process makes, so it alone already enforces the limit
    for calls that all originate here — the global check can only ever
    matter when *another* process has already consumed capacity this
    process's own local counter has no way to know about.

    Simulated deterministically, without real multiprocessing, by directly
    seeding `admission_leases` with rows a "phantom" other process would
    have written — this process's own AdmissionControl starts with a
    perfectly fresh local counter (0) and would happily admit through the
    local check alone. Only the global (Postgres) check can catch this."""
    limit = 3
    async with async_session_factory() as db:
        for _ in range(limit):  # global capacity already fully consumed by "other processes"
            db.add(AdmissionLeaseRow(gate=GATE_CAPABILITY_CONCURRENCY, holder="phantom-other-process"))
        await db.commit()

    spy = _SpyConnector(Capability.NOTIFY_OPERATOR)
    hub = IntegrationHub(
        admission_control=AdmissionControl(
            max_concurrent_capability_executions=limit, max_concurrent_missions=limit,
            session_factory=async_session_factory,
        ),
    )
    hub.registry.register(spy)

    response = await hub.invoke(_call())

    assert response.status == CallStatus.FAILED, (
        "the local counter is fresh (0 < limit) and would have admitted this call on its own -- "
        "only the global Postgres check can correctly refuse it here"
    )
    assert spy.execute_calls == 0, "a globally-rejected call must never reach the connector"
    assert hub.admission_control.current_capability_executions == 0, (
        "the local slot taken before the global rejection must have been released, not leaked"
    )

    async with async_session_factory() as db:
        rows = (await db.execute(text("SELECT count(*) FROM admission_leases WHERE holder != 'phantom-other-process'"))).scalar_one()
    assert rows == 0, "the rejected call must never have created its own lease row"
