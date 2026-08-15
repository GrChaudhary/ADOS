"""
P14 — proves the authoritative-execution-boundary fix
(integrations/capability_manifest.py::CapabilityManifestRegistry.
refresh_from_db, wired into integrations/hub.py::IntegrationHub.invoke()
and integrations/connectors/dynamic.py::DynamicCapabilityConnector.execute())
actually closes the multi-process safety gap P13 named and deferred:

    a capability this process already cached as ACTIVE must not stay
    ACTIVE here forever once a DIFFERENT worker's registry instance
    hot-disables it.

Every test below constructs at least two independent CapabilityManifest
Registry/DynamicCapabilityConnector instances sharing the same real
Postgres (async_session_factory) — "worker A" and "worker B" — to prove
propagation without a restart. This is a lighter, single-process
complement to scripts/p14_multiprocess_capability_proof.py, which proves
the same invariant across real, separate OS processes (mandatory per the
P14 task spec); both exist because the pytest-level version runs on every
CI pass while the real-process script is the authoritative, heavier proof.
"""

import asyncio
import time

import httpx
import pytest
from sqlalchemy import text

from backend.app import metrics
from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow
from integrations.capability_manifest import CapabilityManifest, CapabilityManifestRegistry, CapabilityStatus, RiskProfileEntry
from integrations.connectors.dynamic import DynamicCapabilityConnector, DynamicDispatchConfig
from integrations.hub import IntegrationHub
from integrations.policy_engine import PolicyViolation
from orchestrate.moa import dynamic_registry
from orchestrate.onboarding import runtime_registry as onboarding_runtime_registry

_ADMIN_AUTH = {
    "Authorization": f"Bearer {create_access_token(User(user_id='p14-admin', username='p14-admin', display_name='P14 Admin', role=Role.ADMIN, approval_limit_usd=1_000_000_000.0))}"
}


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE onboarding_sessions CASCADE"))
        await session.commit()
    dynamic_registry.clear()
    yield
    dynamic_registry.clear()


def _counter_value(counter, **labels) -> float:
    child = counter.labels(**labels) if labels else counter
    return child._value.get()


def _call(capability_id: str, **extra_input) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.DYNAMIC_CAPABILITY,
        incident_id="inc-p14-multiworker",
        requested_by="tests/test_capability_registry_multiworker_safety",
        input={"capability_id": capability_id, **extra_input},
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


def _fresh_worker() -> tuple[CapabilityManifestRegistry, DynamicCapabilityConnector, IntegrationHub]:
    """One independent "worker" — its own registry instance (own
    in-memory cache), own connector, own hub, all sharing the same real
    Postgres. No two calls to this helper share any process-local state."""
    manifests = CapabilityManifestRegistry(session_factory=async_session_factory)
    hub = IntegrationHub(manifests=manifests)
    hub.registry.register(hub.dynamic_capability_connector)
    calls_seen = []

    async def _fake_executor(config, call):
        calls_seen.append(call.input.get("capability_id"))
        return {"ok": True}

    hub.dynamic_capability_connector.register_executor("fake", _fake_executor)
    hub.dynamic_capability_connector._test_calls_seen = calls_seen  # for assertions only
    return manifests, hub.dynamic_capability_connector, hub


async def _propose_sandbox_activate(registry: CapabilityManifestRegistry, capability_id: str) -> None:
    await registry.propose(
        capability_id,
        domain="support",
        version="1.0.0",
        source="https://github.com/example/onboarded-tool",
        risk_profile=[RiskProfileEntry(action="default", tier=PolicyTier.EXECUTIVE_APPROVAL, reasoning="p14 test")],
        proposed_by="onboarding-agent",
    )
    await registry.record_sandbox_evidence(capability_id, "ran ok", actor="onboarding-agent")
    await registry.activate(capability_id, actor="admin-1", reason="approved for p14 test")


# ---------------------------------------------------------------------
# Baseline / enabled / unknown
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enabled_capability_executes_via_authoritative_path():
    manifests, connector, hub = _fresh_worker()
    cap_id = "p14.enabled_baseline"
    await _propose_sandbox_activate(manifests, cap_id)
    connector.register(cap_id, DynamicDispatchConfig(track="fake"))

    response = await hub.invoke(_call(cap_id))
    assert response.status == CallStatus.SUCCEEDED
    assert connector._test_calls_seen == [cap_id]


@pytest.mark.asyncio
async def test_unknown_capability_id_is_refused_via_authoritative_path():
    _manifests, connector, _hub = _fresh_worker()
    response = await connector.execute(_call("p14.never-proposed"))
    assert response.status == CallStatus.FAILED
    assert "no capability manifest registered" in response.error


# ---------------------------------------------------------------------
# Case 1 — disable propagation, no restart
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hot_disable_from_worker_a_is_observed_by_worker_b_without_restart():
    cap_id = "p14.disable_propagation"
    manifests_a, connector_a, hub_a = _fresh_worker()
    manifests_b, connector_b, hub_b = _fresh_worker()

    # Both workers "start" with the capability enabled (Case 1's own
    # setup), and both independently warm their own cache to ACTIVE via a
    # real successful call — proving this isn't a "never cached" scenario.
    await _propose_sandbox_activate(manifests_a, cap_id)
    connector_a.register(cap_id, DynamicDispatchConfig(track="fake"))
    connector_b.register(cap_id, DynamicDispatchConfig(track="fake"))
    assert (await hub_a.invoke(_call(cap_id))).status == CallStatus.SUCCEEDED
    assert (await hub_b.invoke(_call(cap_id))).status == CallStatus.SUCCEEDED
    assert manifests_b.manifest_for(cap_id).status is CapabilityStatus.ACTIVE  # B's cache really is warm

    # Worker A disables it — the authoritative action.
    await manifests_a.hot_disable(cap_id, actor="admin-1", reason="misbehaving")

    # Worker B — the SAME already-running connector/hub instance, no
    # restart, no explicit refresh call of its own — must refuse.
    response = await hub_b.invoke(_call(cap_id))
    assert response.status == CallStatus.FAILED
    assert "hot-disabled" in response.error or "not active" in response.error
    # No external side effect: the executor must not have run again.
    assert connector_b._test_calls_seen == [cap_id]  # only the earlier, legitimate warm-up call


@pytest.mark.asyncio
async def test_stale_cache_alone_cannot_authorize_execution():
    """Case 4 — deliberately poke a worker's in-memory cache to say ACTIVE
    while the authoritative Postgres row says HOT_DISABLED, and prove the
    stale cache is never trusted."""
    cap_id = "p14.stale_cache_alone"
    manifests_a, connector_a, hub_a = _fresh_worker()
    manifests_b, connector_b, hub_b = _fresh_worker()

    await _propose_sandbox_activate(manifests_a, cap_id)
    connector_b.register(cap_id, DynamicDispatchConfig(track="fake"))
    await manifests_a.hot_disable(cap_id, actor="admin-1", reason="pulled")

    # Worker B's cache has NEVER been touched for this id — force-seed it
    # with a fabricated, wrong, ACTIVE manifest, simulating the worst-case
    # staleness (not just "old", but actively wrong).
    manifests_b._manifests[cap_id] = CapabilityManifest(
        capability_id=cap_id, domain="support", version="1.0.0", source="fabricated-for-test",
        proposed_by="onboarding-agent", status=CapabilityStatus.ACTIVE,
    )
    assert manifests_b.manifest_for(cap_id).status is CapabilityStatus.ACTIVE  # confirm the poke took

    response = await connector_b.execute(_call(cap_id))
    assert response.status == CallStatus.FAILED
    assert connector_b._test_calls_seen == []  # never reached the executor


# ---------------------------------------------------------------------
# Case 2 — enable propagation (both halves: status, and dispatch config)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_is_observed_by_a_different_worker_without_restart():
    cap_id = "p14.enable_propagation_status"
    manifests_a, connector_a, hub_a = _fresh_worker()
    manifests_b, connector_b, hub_b = _fresh_worker()

    await _propose_sandbox_activate(manifests_a, cap_id)
    connector_b.register(cap_id, DynamicDispatchConfig(track="fake"))
    await manifests_a.hot_disable(cap_id, actor="admin-1", reason="pulled")

    refused = await connector_b.execute(_call(cap_id))
    assert refused.status == CallStatus.FAILED

    await manifests_a.resume(cap_id, actor="admin-1", reason="fixed upstream")

    allowed = await connector_b.execute(_call(cap_id))
    assert allowed.status == CallStatus.SUCCEEDED
    assert connector_b._test_calls_seen == [cap_id]


async def _insert_activated_onboarding_session(capability_id: str) -> None:
    from datetime import datetime, timezone
    import uuid

    async with async_session_factory() as session:
        session.add(
            OnboardingSessionRow(
                id=str(uuid.uuid4()), track="fake", status="activated",
                source_url="https://github.com/example/p14-tool", domain="support",
                capability_id=capability_id, selected_tool_name="do_thing",
                synthesized_manifest={"key": "do_thing", "description": "p14 test tool", "estimated_cost_usd": 0.0, "runtime": {}},
                audit_log=[], created_by="admin-1", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dispatch_config_propagates_to_a_worker_that_never_activated_it_itself():
    """The other half of Case 2 — DynamicCapabilityConnector's resolver
    (P14 Fix B, wired via set_resolver) lets a worker whose own _dispatch
    dict has NEVER seen this capability_id self-heal from Postgres/the
    onboarding_sessions row on its very first attempt, closing the P13-
    deferred dispatch-config propagation gap."""
    cap_id = "p14.resolver_propagation"
    manifests_a, connector_a, hub_a = _fresh_worker()
    await _propose_sandbox_activate(manifests_a, cap_id)
    await _insert_activated_onboarding_session(cap_id)
    # Deliberately NOT calling connector_a.register(...) — activation
    # happened only through the manifest registry + the onboarding row,
    # exactly as backend/app/routers/capabilities.py's real /promote
    # endpoint leaves it (register_runtime is a separate, best-effort step).

    manifests_c, connector_c, hub_c = _fresh_worker()
    connector_c.set_resolver(
        lambda capability_id: onboarding_runtime_registry.resolve_dispatch_config(async_session_factory, capability_id)
    )
    assert cap_id not in connector_c._dispatch  # confirm this worker never cached it

    response = await connector_c.execute(_call(cap_id))
    assert response.status == CallStatus.SUCCEEDED
    assert connector_c._test_calls_seen == [cap_id]
    assert cap_id in connector_c._dispatch  # self-healed for next time


@pytest.mark.asyncio
async def test_without_the_resolver_wired_a_never_seen_capability_stays_uninvokable():
    """Negative-shaped control proving the resolver is actually doing the
    work above, not some other mechanism: the identical setup, but on a
    worker with NO resolver wired, must still fail with the pre-existing
    'no runtime dispatch config' message."""
    cap_id = "p14.resolver_propagation_control"
    manifests_a, connector_a, hub_a = _fresh_worker()
    await _propose_sandbox_activate(manifests_a, cap_id)
    await _insert_activated_onboarding_session(cap_id)

    manifests_c, connector_c, hub_c = _fresh_worker()  # no set_resolver call
    response = await connector_c.execute(_call(cap_id))
    assert response.status == CallStatus.FAILED
    assert "no runtime dispatch config" in response.error


# ---------------------------------------------------------------------
# Case 3 — concurrent disable vs execution, real repeated concurrency
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_hot_disable_and_execute_converges_correctly_across_many_trials():
    """Real concurrency (asyncio.gather -> two independent, interleaved
    Postgres round trips, not a simulation) repeated many times. The
    invariant asserted is NOT "execute always loses the race" (a request
    whose authoritative read legitimately preceded the disable's commit
    is allowed to complete — see the P14 report's documented semantics
    for "disabled while in flight"). It is: (a) every single attempt is
    genuinely gated by the authoritative check (never silently bypassed —
    corroborated independently via the metric counter), and (b) the
    system always converges to the correct, consistently-enforced state
    immediately afterward, regardless of which side of the race won."""
    trials = 20
    outcomes = []
    before_lookups = sum(
        _counter_value(metrics.capability_registry_authoritative_lookups_total, result=r)
        for r in ("allowed", "not_active", "hot_disabled", "not_found", "lookup_failed")
    )

    for i in range(trials):
        cap_id = f"p14.concurrent_race_{i}"
        manifests_a, connector_a, hub_a = _fresh_worker()
        manifests_b, connector_b, hub_b = _fresh_worker()
        await _propose_sandbox_activate(manifests_a, cap_id)
        connector_b.register(cap_id, DynamicDispatchConfig(track="fake"))

        disable_result, execute_result = await asyncio.gather(
            manifests_a.hot_disable(cap_id, actor="admin-1", reason="race"),
            connector_b.execute(_call(cap_id)),
            return_exceptions=True,
        )
        assert not isinstance(disable_result, Exception)  # the only writer in this trial, never contended
        outcomes.append(execute_result.status if not isinstance(execute_result, Exception) else "raised")

        # Regardless of which side won the race, a POST-race attempt must
        # be unambiguously and consistently refused — no residual
        # inconsistency survives the race.
        post_race = await connector_b.execute(_call(cap_id))
        assert post_race.status == CallStatus.FAILED

    assert "raised" not in outcomes  # never an unhandled exception, always a structured response
    assert all(o in (CallStatus.SUCCEEDED, CallStatus.FAILED) for o in outcomes)

    after_lookups = sum(
        _counter_value(metrics.capability_registry_authoritative_lookups_total, result=r)
        for r in ("allowed", "not_active", "hot_disabled", "not_found", "lookup_failed")
    )
    # 2 authoritative reads per trial: the raced attempt + the post-race
    # confirmation attempt — proves the gate ran every single time, not
    # just on the trials that happened to refuse.
    assert after_lookups - before_lookups == trials * 2


# ---------------------------------------------------------------------
# Case 5 — restart
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_freshly_constructed_registry_sees_the_same_authoritative_state_as_an_existing_one():
    """Simulates a process restart: a brand-new CapabilityManifestRegistry
    has an empty in-memory cache (no warm-up at all), yet must see the
    exact same up-to-date HOT_DISABLED state an already-running worker
    would see — Postgres, not any process's memory, is the ground truth."""
    cap_id = "p14.restart_consistency"
    manifests_a, connector_a, hub_a = _fresh_worker()
    await _propose_sandbox_activate(manifests_a, cap_id)
    await manifests_a.hot_disable(cap_id, actor="admin-1", reason="pulled before B ever started")

    # "Restarted" worker — never touched this capability_id before.
    manifests_restarted, connector_restarted, hub_restarted = _fresh_worker()
    assert manifests_restarted.manifest_for(cap_id) is None  # empty cache, confirmed

    response = await connector_restarted.execute(_call(cap_id))
    assert response.status == CallStatus.FAILED


# ---------------------------------------------------------------------
# Case 6 — alternate execution paths, within one running app
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_reachable_paths_refuse_a_hot_disabled_capability_consistently():
    """Within one real app lifespan: hub.invoke(), connector.execute()
    directly, and the real HTTP POST /capabilities/invoke endpoint all
    refuse the same hot-disabled capability. hub.state's registry is
    warmed to ACTIVE first (a real prior successful call, so this isn't
    just "never cached"), then disabled through an INDEPENDENT registry
    instance (standing in for "another worker's admin action") — proving
    every path an already-running process exposes is consistently
    protected, not just the one that happens to notice first."""
    cap_id = "p14.alternate_paths"
    async with app.router.lifespan_context(app):
        manifests = app.state.integration_hub.manifests
        connector = app.state.integration_hub.dynamic_capability_connector
        await _propose_sandbox_activate(manifests, cap_id)
        connector.register(cap_id, DynamicDispatchConfig(track="fake"))

        async def _fake_executor(config, call):
            return {"ok": True}

        connector.register_executor("fake", _fake_executor)

        warm = await app.state.integration_hub.invoke(_call(cap_id))
        assert warm.status == CallStatus.SUCCEEDED

        other_worker_manifests = CapabilityManifestRegistry(session_factory=async_session_factory)
        await other_worker_manifests.hot_disable(cap_id, actor="admin-1", reason="pulled by another worker")

        direct_hub = await app.state.integration_hub.invoke(_call(cap_id))
        assert direct_hub.status == CallStatus.FAILED

        direct_connector = await connector.execute(_call(cap_id))
        assert direct_connector.status == CallStatus.FAILED

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            http_response = await client.post(
                "/capabilities/invoke",
                json={
                    "capability": "DynamicCapability",
                    "incidentId": "inc-p14-http",
                    "requestedBy": "tests/test_capability_registry_multiworker_safety",
                    "input": {"capability_id": cap_id},
                    "governance": {"policyTier": 0, "approvedBy": None},
                },
                headers=_ADMIN_AUTH,
            )
    assert http_response.status_code == 200
    assert http_response.json()["status"] == "failed"


# ---------------------------------------------------------------------
# Fail-closed on authoritative-lookup failure (database unavailable)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authoritative_lookup_failure_fails_closed(monkeypatch):
    cap_id = "p14.db_unavailable"
    manifests, connector, hub = _fresh_worker()
    await _propose_sandbox_activate(manifests, cap_id)
    connector.register(cap_id, DynamicDispatchConfig(track="fake"))
    # Warm the cache first — proving a PRIOR good read does not let a
    # subsequent lookup failure silently fall back to it.
    assert (await connector.execute(_call(cap_id))).status == CallStatus.SUCCEEDED

    class _BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("simulated Postgres outage")

    monkeypatch.setattr(manifests, "_session_factory", _BrokenSessionFactory())

    before_failed = _counter_value(metrics.capability_registry_authoritative_lookups_total, result="lookup_failed")
    response = await connector.execute(_call(cap_id))
    assert response.status == CallStatus.FAILED
    assert "authoritative lookup failed" in response.error
    assert _counter_value(metrics.capability_registry_authoritative_lookups_total, result="lookup_failed") == before_failed + 1

    # A routing/infrastructure failure, not evidence the capability itself
    # misbehaved — must not count against its track record.
    assert manifests.manifest_for(cap_id).failure_count == 0


# ---------------------------------------------------------------------
# Observability — the stale-cache-detected signal is not vacuous
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_cache_detected_metric_fires_only_on_genuine_disagreement():
    cap_id = "p14.stale_metric"
    manifests_a, connector_a, hub_a = _fresh_worker()
    manifests_b, connector_b, hub_b = _fresh_worker()
    await _propose_sandbox_activate(manifests_a, cap_id)
    connector_b.register(cap_id, DynamicDispatchConfig(track="fake"))

    before = _counter_value(metrics.capability_registry_stale_cache_detected_total)
    await connector_b.execute(_call(cap_id))  # first-ever read for B: no prior cache to disagree with
    assert _counter_value(metrics.capability_registry_stale_cache_detected_total) == before

    await manifests_a.hot_disable(cap_id, actor="admin-1", reason="pulled")
    await connector_b.execute(_call(cap_id))  # B's cache (ACTIVE) now genuinely disagrees
    assert _counter_value(metrics.capability_registry_stale_cache_detected_total) == before + 1

    await connector_b.execute(_call(cap_id))  # re-read, no change since — must not double-fire
    assert _counter_value(metrics.capability_registry_stale_cache_detected_total) == before + 1
