"""
P11 — proof, against a REAL Docker daemon, that the mission-concurrency
admission gate (integrations/hub.py::IntegrationHub.invoke(), gate=
"mission_concurrency") refuses a second concurrent RunPrimeRLMAgent mission
BEFORE `docker run` is ever issued for it — not merely that a fake/mocked
connector's `execute()` is uncalled (see test_integration_hub_admission.py
for that, Docker-free proof), but that the real `PrimeAgentRuntime.start()`
genuinely never runs a second container.

Only `PrimeAgentRuntime.run_objective` is monkeypatched (to block on an
asyncio.Event instead of talking to a real LLM/kernel) — `start()` and
`teardown()` are the real thing: a real `docker run`, a real per-session
egress boundary, a real `docker rm -f`. This is the one place this phase
touches Docker for admission control specifically; the broader recovery
exercise (scripts/p11_orphan_recovery_exercise.py) is the other.

MARKED `docker`: deselected by default (`-m 'not external and not docker'`),
requires the `ados-prime-runtime`/`ados-egress-relay` images already built
(same precondition test_two_session_isolation.py checks).
"""

import asyncio
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from integrations.admission_control import AdmissionControl
from integrations.connectors.prime_runtime import PrimeRuntimeConnector
from integrations.hub import IntegrationHub
from orchestrate.runtime.base import SessionOutcome, SessionState
from orchestrate.runtime.prime import PrimeAgentRuntime

pytestmark = pytest.mark.docker

RUNTIME_IMAGE = "ados-prime-runtime:0.7.1"
RELAY_IMAGE = "ados-egress-relay:1"


def _images_present() -> bool:
    if not shutil.which("docker"):
        return False
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    ).stdout
    return RUNTIME_IMAGE in out and RELAY_IMAGE in out


def _running_ados_prime_containers() -> list:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=ados-prime-", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    return [n for n in out.splitlines() if n.strip()]


@pytest.fixture(autouse=True)
async def _clean():
    if not _images_present():
        pytest.skip(f"requires {RUNTIME_IMAGE} and {RELAY_IMAGE} built locally")
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


def _call() -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input={"prompt": "say hello", "domain": "it", "max_wall_clock_seconds": 120},
        requested_by="test:admission-docker",
        incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def test_mission_gate_refuses_a_second_container_before_docker_run(monkeypatch):
    """One real container starts and is held open (run_objective blocks on
    an Event); a second, concurrent mission attempt must be refused by the
    mission_concurrency gate BEFORE PrimeAgentRuntime.start() ever runs for
    it — proven by an independent `docker ps` count, not by trusting the
    connector's own return value."""
    hold = asyncio.Event()

    async def blocking_run_objective(self, spec):
        await hold.wait()
        return SessionOutcome(state=SessionState.COMPLETED, final_answer="hi", tool_execution_count=1, tool_success_count=1)

    monkeypatch.setattr(PrimeAgentRuntime, "run_objective", blocking_run_objective)

    hub = IntegrationHub(admission_control=AdmissionControl(max_concurrent_capability_executions=10, max_concurrent_missions=1))
    hub.registry.register(PrimeRuntimeConnector())

    first_task = asyncio.create_task(hub.invoke(_call()))
    # Wait for the REAL container to actually exist before attempting the
    # second call — real docker run takes real wall-clock time, unlike the
    # in-memory fakes in test_integration_hub_admission.py.
    for _ in range(200):  # up to ~20s
        if _running_ados_prime_containers():
            break
        await asyncio.sleep(0.1)
    containers_after_first = _running_ados_prime_containers()
    assert len(containers_after_first) == 1, f"expected exactly one real container, found {containers_after_first}"

    second_response = await hub.invoke(_call())
    assert second_response.status == CallStatus.FAILED
    assert "Prime Agent missions" in (second_response.error or "")

    # The independent check that actually matters: no SECOND container was
    # ever created for the refused attempt.
    containers_after_second_attempt = _running_ados_prime_containers()
    assert containers_after_second_attempt == containers_after_first, (
        "a mission refused by admission control must never reach PrimeAgentRuntime.start() "
        f"— container set changed from {containers_after_first} to {containers_after_second_attempt}"
    )

    hold.set()
    first_response = await first_task
    assert first_response.status == CallStatus.SUCCEEDED

    # Independent verification the one real container is gone after
    # teardown — cleanup, not just the admission-control claim.
    for _ in range(100):
        if not _running_ados_prime_containers():
            break
        await asyncio.sleep(0.1)
    assert _running_ados_prime_containers() == [], "the one real container must be torn down by the end of the test"
