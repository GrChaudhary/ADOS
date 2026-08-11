"""
P10 — extends the P7-D build-identity drift guard onto the capability-
execution choke point, not just mission start.

P8's own re-derivation (docs/prime-agent-integration/18-production-readiness-
review.md §5.2) found `verify_no_drift_since_process_start()` was called
exactly once, in `PrimeRuntimeConnector._run()`, before any container
exists — never again for the rest of that mission's life. A commit landing
while a mission was already in flight was never checked again for that
mission's remaining `request_capability` calls, including ones that reach a
real external system (ServiceNow). `_execute_capability` (backend/app/
mcp_gateway.py) is the single choke point both the autonomous path and the
human-approval path call through, so one added call there closes the gap for
both without touching either caller.

Same monkeypatch fixture shape as test_build_identity.py's own P7-D section
and test_prime_agent.py's `test_a_stale_process_refuses_the_mission_before_
creating_any_row` — only `CURRENT_BUILD_REVISION` is faked; the real
repository on disk is never touched, so these tests pass or fail on their
own logic, not on this checkout's actual git state.
"""
import uuid

import pytest

from contracts import Capability, PolicyTier
from orchestrate.runtime import build_identity
from orchestrate.runtime.capability_execution import STATUS_FAILED

from backend.app import mcp_gateway


def _fake(commit: str) -> build_identity.BuildRevision:
    return build_identity.BuildRevision(commit=commit, dirty=False, source="test")


@pytest.fixture
def stale_gateway(monkeypatch):
    """Simulates a commit having landed after this process's own frozen
    identity was computed — the exact P8 scenario, without needing a second
    real git checkout (test_build_identity.py already proves the underlying
    git-reading mechanism works against real checkouts; this file is about
    proving the NEW call site, not re-proving that)."""
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", _fake("a" * 40))
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: _fake("b" * 40),
    )


@pytest.fixture
def matching_gateway(monkeypatch):
    same = _fake("c" * 40)
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", same)
    monkeypatch.setattr(build_identity, "compute_build_revision", lambda repo_root, source=None: same)


def _must_not_be_invoked(monkeypatch):
    """A stub hub whose invoke() fails the test if it is ever reached —
    the strongest available proof that the connector, and therefore any
    external side effect, was never approached."""

    class _StubHub:
        async def invoke(self, call):
            raise AssertionError("connector reached despite a stale build — no external effect should be attempted")

    monkeypatch.setattr("integrations.hub.default_hub", lambda *a, **kw: _StubHub())


async def test_a_stale_gateway_refuses_the_capability_before_any_connector_is_reached(
    stale_gateway, monkeypatch,
):
    _must_not_be_invoked(monkeypatch)

    result = await mcp_gateway._execute_capability(
        Capability.NOTIFY_IT_HELPDESK.value,
        {"summary": "should never reach ServiceNow"},
        mission_id=uuid.uuid4(),
        tier=PolicyTier.AUTONOMOUS,
        request_id=uuid.uuid4(),
    )

    assert result["outcome_status"] == STATUS_FAILED
    assert "StaleGatewayError" in result["error"]


async def test_a_matching_gateway_proceeds_to_the_connector(matching_gateway, monkeypatch):
    calls = []

    class _StubHub:
        async def invoke(self, call):
            calls.append(call)

            class _Resp:
                def model_dump(self, mode="json"):
                    return {"status": "succeeded", "output": {}}

            return _Resp()

    monkeypatch.setattr("integrations.hub.default_hub", lambda *a, **kw: _StubHub())

    result = await mcp_gateway._execute_capability(
        Capability.NOTIFY_IT_HELPDESK.value,
        {"summary": "fine, no drift"},
        mission_id=uuid.uuid4(),
        tier=PolicyTier.AUTONOMOUS,
        request_id=uuid.uuid4(),
    )

    assert len(calls) == 1, "a matching build must still reach the connector exactly once"
    assert result["outcome_status"] != STATUS_FAILED or "StaleGatewayError" not in (result.get("error") or "")


async def test_the_real_repository_right_now_does_not_refuse_capability_execution():
    """No mocking: this process's own CURRENT_BUILD_REVISION, checked
    against the real repository state at the moment this test runs — mirrors
    test_build_identity.py's own equivalent real-repo sanity check. Fails
    only if something has actually been committed since this test process
    started, which is exactly the condition the guard exists to catch."""
    calls = []

    class _StubHub:
        async def invoke(self, call):
            calls.append(call)

            class _Resp:
                def model_dump(self, mode="json"):
                    return {"status": "succeeded", "output": {}}

            return _Resp()

    import integrations.hub as hub_module
    original = hub_module.default_hub
    hub_module.default_hub = lambda *a, **kw: _StubHub()
    try:
        result = await mcp_gateway._execute_capability(
            Capability.NOTIFY_IT_HELPDESK.value,
            {"summary": "real repo, no drift expected"},
            mission_id=uuid.uuid4(),
            tier=PolicyTier.AUTONOMOUS,
            request_id=uuid.uuid4(),
        )
    finally:
        hub_module.default_hub = original

    assert len(calls) == 1
    assert "StaleGatewayError" not in (result.get("error") or "")
