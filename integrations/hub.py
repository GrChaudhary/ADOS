"""
Integration Hub facade — wires the Capability Registry, Connector Policy
Engine, and connectors together for callers (the backend API for now;
the Decision Orchestrator in Phase 3). See docs/006-integration-hub.md's
example resolution:

    Need -> Capability Registry -> Connector Policy Engine -> Connector -> Execute
"""

import logging
from typing import Optional

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .admission_control import AdmissionControl
from .rate_limiter import RateLimiter
from .capability_manifest import (
    CapabilityManifestRegistry,
    CapabilityStatus,
    resolve_capability_lookup_id,
)
from .capability_registry import CapabilityRegistry
from .connectors.console import ConsoleConnector
from .connectors.dynamic import DynamicCapabilityConnector
from .connectors.sap import SAPConnector
from .connectors.servicenow import ServiceNowConnector
from .connectors.marketplace import MarketplaceConnector
from .connectors.mission_evidence import MissionEvidenceConnector
from .connectors.prime_runtime import PrimeRuntimeConnector
from .connectors.smart_factory import SmartFactoryConnector
from .policy_engine import ConnectorPolicyEngine, PolicyViolation, require_governance

logger = logging.getLogger("ados.integration_hub")


class IntegrationHub:
    def __init__(
        self,
        manifests: Optional[CapabilityManifestRegistry] = None,
        admission_control: Optional[AdmissionControl] = None,
        rate_limiter: Optional[RateLimiter] = None,
        mission_start_rate_limit_max: int = 0,
        mission_start_rate_limit_window_seconds: float = 60.0,
    ):
        self.registry = CapabilityRegistry()
        # manifests defaults to a fresh, empty registry rather than None so
        # this is always wired in — an empty registry is a safe no-op today
        # (nothing has been onboarded through §8 yet) and starts mattering
        # the moment something calls self.manifests.propose(...).
        self.manifests = manifests if manifests is not None else CapabilityManifestRegistry()
        # Always constructed (mirrors self.manifests) so callers/tests always
        # have a handle to attach track executors (register_executor) or
        # dispatch configs to — but, like every other connector, it's only
        # *registered* (made reachable by hub.invoke()) where a hub
        # explicitly opts in, i.e. default_hub() below.
        self.dynamic_capability_connector = DynamicCapabilityConnector(self.manifests)
        # P14 — no hot_disable_policy_rule here anymore. It used to be a
        # PolicyRule (synchronous, cache-only) doing this exact check
        # inside select_connector(); it is now done, freshly, inside
        # invoke() itself (below) via refresh_from_db(). Keeping BOTH was
        # tried and found actively wrong, not just redundant: the
        # synchronous rule reads the SAME self.manifests._manifests cache
        # invoke()'s own authoritative read writes to, so the first
        # authoritative read that ever caches HOT_DISABLED poisons the
        # synchronous rule going forward — a LATER resume() (authoritative
        # in Postgres) would update the cache too, but only if invoke()'s
        # check ever got to run, and the synchronous rule raises and
        # short-circuits select_connector() BEFORE that check runs. Proven
        # wrong live: scripts/p14_multiprocess_capability_proof.py caught
        # this exact case (a real hot_disable -> resume sequence across two
        # real OS processes) — hub.invoke() kept refusing a genuinely
        # re-activated capability while connector.execute() (which never
        # went through select_connector()) correctly allowed it, an actual
        # cross-path inconsistency, not just staleness.
        self.policy_engine = ConnectorPolicyEngine(self.registry, rules=[require_governance])
        # P11: per-instance, not a module-level singleton — see
        # admission_control.py's own docstring for why (~800 tests each
        # construct their own hub; a global would leak concurrency state
        # between them).
        self.admission_control = admission_control if admission_control is not None else AdmissionControl()
        # P12: default max=0 -- disabled unless the real app wires one in
        # (backend/app/main.py) with a real limit; every test that builds
        # its own hub without one keeps today's unbounded-rate behavior,
        # matching how AdmissionControl(session_factory=None) is a no-op.
        self.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()
        self._mission_start_rate_limit_max = mission_start_rate_limit_max
        self._mission_start_rate_limit_window_seconds = mission_start_rate_limit_window_seconds

    async def invoke(self, call: CapabilityCall) -> CapabilityResponse:
        # Local imports: backend.app.metrics is an outer-layer module and
        # importing it at module scope here would invert the dependency
        # direction (integrations/ is imported BY backend/app, not the other
        # way around) — the same reasoning prime_runtime.py's own local
        # `from backend.app.mcp_gateway import hash_token` import already
        # documents.
        from backend.app.metrics import (
            admission_rejections_total,
            authorization_denials_total,
            capability_execution_duration_seconds,
            capability_executions_total,
            capability_registry_authoritative_lookups_total,
        )

        try:
            connector = self.policy_engine.select_connector(call)
        except PolicyViolation as e:
            authorization_denials_total.labels(reason="policy_violation").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                error=str(e),
            )

        # P14 — §8.7's capability-level circuit breaker (hot-disable),
        # enforced here with a fresh Postgres read rather than a
        # synchronous, cache-based PolicyRule (see integrations/
        # capability_manifest.py's own git history / this module's
        # __init__ comment for why that used to exist and was removed —
        # a cache-based pre-filter running before this authoritative check
        # can poison itself, blocking a legitimately re-activated
        # capability with no way for this check to ever correct it). This
        # is the one place every capability call passes through regardless
        # of caller (MOA, mcp_gateway in-mission calls, POST /capabilities/
        # invoke), so a fresh Postgres read here, immediately before any
        # connector runs, is what actually makes a hot_disable() issued
        # through a different worker's registry instance take effect here
        # without a restart. Fails closed: an authoritative-lookup failure
        # (e.g. the database is unreachable) refuses the call rather than
        # silently falling back to a possibly-stale cached verdict.
        lookup_id = resolve_capability_lookup_id(call)
        try:
            manifest = await self.manifests.refresh_from_db(lookup_id)
        except Exception as e:  # noqa: BLE001 — DB unavailable must refuse, never trust a stale cache
            capability_registry_authoritative_lookups_total.labels(result="lookup_failed").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=connector.name,
                error=f"capability registry authoritative lookup failed ({type(e).__name__}: {e}) — "
                "refusing to execute without a fresh authorization decision",
            )
        if manifest is not None and manifest.status is CapabilityStatus.HOT_DISABLED:
            capability_registry_authoritative_lookups_total.labels(result="hot_disabled").inc()
            authorization_denials_total.labels(reason="policy_violation").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=connector.name,
                error=f"capability {lookup_id} is hot-disabled and cannot be invoked",
            )
        capability_registry_authoritative_lookups_total.labels(result="allowed").inc()

        # P11 admission control — BEFORE connector.execute(), i.e. before any
        # external side effect (Docker container start, an HTTP call to
        # ServiceNow/SAP/etc.). Two gates: a general ceiling on every
        # capability execution in flight, and — only for the capability that
        # starts a Docker container — a tighter, specific ceiling on
        # concurrent Prime Agent missions, the heaviest resource in this
        # system. Both are checked server-side only: nothing in `call.input`
        # (agent-supplied) is ever consulted here.
        #
        # P12 — each local acquire above is followed by a global (Postgres)
        # acquire when the hub's AdmissionControl is wired with a
        # session_factory (see admission_control.py's own docstring). The
        # local check runs first because it's free and correct for the
        # overwhelmingly common single-process case; the global check is
        # what makes the ceiling correct even when a second process exists.
        # A local pass + global reject releases the local slot immediately
        # — the two are never left inconsistent.
        if not self.admission_control.try_acquire_capability_slot():
            admission_rejections_total.labels(gate="capability_concurrency").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=connector.name,
                error="admission control: too many concurrent capability executions; try again shortly",
            )

        # P15 — everything from here on is inside one try/finally so the
        # local slot just acquired above is UNCONDITIONALLY released,
        # including when the global (Postgres) acquire immediately below
        # raises. It used to leak: the global acquire await sat between the
        # local acquire and the try/finally that was meant to guarantee its
        # release, so a transient database outage there (or a failure in
        # any one of the global *release* calls in `finally`, which used to
        # be able to short-circuit the local release lines after it) leaked
        # one local slot permanently — nothing else ever resets
        # `_current_capability`/`_current_missions`. Not an authorization
        # bypass (a leak only ever makes this gate MORE restrictive over
        # time), but a genuine self-inflicted-availability defect this
        # phase's audit of every crash/DB-unavailable point (Phase 1) found
        # — see docs/prime-agent-integration/26-p15-concurrency-atomicity-
        # review.md. Each global release below is independently try/except
        # guarded for the same reason: one failing must never prevent the
        # others, or the local releases, from running.
        capability_lease = None
        mission_slot_acquired = False
        mission_lease = None
        try:
            try:
                capability_lease = await self.admission_control.try_acquire_capability_slot_global()
            except Exception as e:  # noqa: BLE001 — DB unavailable must refuse, never leave the gate silently open
                admission_rejections_total.labels(gate="capability_concurrency").inc()
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=connector.name,
                    error=(
                        f"admission control: global admission check failed ({type(e).__name__}: {e}) "
                        "— refusing to execute"
                    ),
                )
            if self.admission_control.globally_coordinated and capability_lease is None:
                admission_rejections_total.labels(gate="capability_concurrency").inc()
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=connector.name,
                    error="admission control: too many concurrent capability executions; try again shortly",
                )

            if call.capability == Capability.RUN_PRIME_RLM_AGENT:
                if not self.admission_control.try_acquire_mission_slot():
                    admission_rejections_total.labels(gate="mission_concurrency").inc()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=connector.name,
                        error="admission control: too many concurrent Prime Agent missions; try again shortly",
                    )
                mission_slot_acquired = True
                try:
                    mission_lease = await self.admission_control.try_acquire_mission_slot_global()
                except Exception as e:  # noqa: BLE001 — same fail-closed posture as the capability gate above
                    admission_rejections_total.labels(gate="mission_concurrency").inc()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=connector.name,
                        error=(
                            f"admission control: global admission check failed ({type(e).__name__}: {e}) "
                            "— refusing to execute"
                        ),
                    )
                if self.admission_control.globally_coordinated and mission_lease is None:
                    admission_rejections_total.labels(gate="mission_concurrency").inc()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=connector.name,
                        error="admission control: too many concurrent Prime Agent missions; try again shortly",
                    )

                # P12 rate limit — distinct from the concurrency gate just
                # above: bounds how often a mission can be STARTED, not how
                # many are in flight. See rate_limiter.py's own docstring.
                admitted = await self.rate_limiter.try_admit_mission_start(
                    limit=self._mission_start_rate_limit_max,
                    window_seconds=self._mission_start_rate_limit_window_seconds,
                )
                if not admitted:
                    admission_rejections_total.labels(gate="mission_start_rate").inc()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=connector.name,
                        error="rate limit: too many Prime Agent mission starts in this window; try again shortly",
                    )

            with capability_execution_duration_seconds.labels(capability=call.capability.value).time():
                response = await connector.execute(call)
        finally:
            if mission_slot_acquired:
                self.admission_control.release_mission_slot()
                try:
                    await self.admission_control.release_mission_slot_global(mission_lease)
                except Exception:  # noqa: BLE001 — must not prevent the capability-slot release below
                    logger.exception("failed to release global mission admission lease")
            self.admission_control.release_capability_slot()
            try:
                await self.admission_control.release_capability_slot_global(capability_lease)
            except Exception:  # noqa: BLE001 — logged, not raised: the periodic reclaim sweep is the backstop
                logger.exception("failed to release global capability admission lease")

        _OUTCOME_LABEL = {
            CallStatus.SUCCEEDED: "executed",
            CallStatus.FAILED: "failed",
            CallStatus.UNKNOWN: "outcome_unknown",
        }
        capability_executions_total.labels(
            capability=call.capability.value,
            outcome=_OUTCOME_LABEL.get(response.status, "failed"),
        ).inc()
        return response


def default_hub(
    manifests: Optional[CapabilityManifestRegistry] = None,
    admission_control: Optional[AdmissionControl] = None,
    rate_limiter: Optional[RateLimiter] = None,
    mission_start_rate_limit_max: int = 0,
    mission_start_rate_limit_window_seconds: float = 60.0,
) -> IntegrationHub:
    """Real connectors registered first so the Connector Policy Engine's
    "preferred systems" rule (docs/006-integration-hub.md) picks them once
    configured; Console registered last as the universal fallback for
    everything else (NotifyOperator, UpdateMES) and for capabilities whose
    real connector isn't configured yet.

    `manifests` lets the real app (backend/app/main.py) pass a
    Postgres-backed CapabilityManifestRegistry instead of the default
    empty in-memory one — see integrations/capability_manifest.py's
    session_factory docstring.

    dynamic_capability_connector is registered before ConsoleConnector for
    the same "preferred systems" reason: ConsoleConnector's
    capabilities = set(Capability) covers Capability.DYNAMIC_CAPABILITY too
    (it's re-evaluated fresh, so it picks up the sentinel automatically),
    and both connectors report is_configured() = True by default — without
    this ordering, ConsoleConnector would silently win and no dynamically
    onboarded capability would ever actually execute."""
    hub = IntegrationHub(
        manifests=manifests,
        admission_control=admission_control,
        rate_limiter=rate_limiter,
        mission_start_rate_limit_max=mission_start_rate_limit_max,
        mission_start_rate_limit_window_seconds=mission_start_rate_limit_window_seconds,
    )
    # Before ConsoleConnector for a reason worth stating plainly: Console
    # declares `capabilities = set(Capability)` and is_configured() = True, so
    # if it won the selection for FetchIncidentEvidence it would return
    # status=SUCCEEDED with output {"message": "[console] simulated
    # FetchIncidentEvidence"} — a green capability row, an audit trail that
    # says the evidence was fetched, and no evidence. Registration order is
    # what keeps a read capability honest.
    hub.registry.register(MissionEvidenceConnector())
    # Before ConsoleConnector for the same reason as MissionEvidenceConnector:
    # RunPrimeRLMAgent had NO connector, so Console won it and returned
    # "[console] simulated RunPrimeRLMAgent" — a green audit row for an agent
    # that never ran.
    hub.registry.register(PrimeRuntimeConnector())
    hub.registry.register(MarketplaceConnector())
    hub.registry.register(ServiceNowConnector())
    hub.registry.register(SAPConnector())
    hub.registry.register(SmartFactoryConnector())
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    return hub
