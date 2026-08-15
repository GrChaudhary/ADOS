"""
Dynamic Capability connector — orchestration-platform-vision.md §8, the
"Bring Your Own Capability" onboarding flow (orchestrate/onboarding/).

Bridges a fundamental mismatch: CapabilityCall.capability is a closed,
Pydantic-enforced Capability enum (rejected at the FastAPI request-body
layer for anything else), while CapabilityManifestRegistry tracks onboarded
capabilities by free-text capability_id (e.g. "zendesk.read_ticket"). Every
dynamically onboarded capability is called with the one sentinel
Capability.DYNAMIC_CAPABILITY; the real id travels in
CapabilityCall.input["capability_id"] instead — that field is already an
untyped payload bag used this way elsewhere (see orchestrate/moa/hr_domain.py
callers).

CapabilityRegistry.connectors_for() is a per-capability enum-keyed dict
lookup, not a can_handle() broadcast, so one connector pre-registered under
this single sentinel key — dispatching internally on the free-text id — is
the shape that lookup already expects.

Governance note: IntegrationHub.invoke()'s own authoritative check
(integrations/hub.py, P14) only blocks HOT_DISABLED. A capability still
sitting in PROPOSED/SANDBOX_TESTED (not yet vetted, sandbox not run, admin
hasn't activated it) would sail straight through that check, since it only
checks for one specific status — and any authenticated user can reach
POST /capabilities/invoke. This connector independently gates on
manifest.status is ACTIVE so "not yet activated" fails closed here too,
not just "explicitly disabled".

Execution itself is pluggable per track (executors registered by track
name, e.g. "mcp_native" / "openapi") rather than hardcoded here, so
orchestrate/onboarding/sandbox_runner.py and wrapper_generator.py can wire
their real dispatch logic in later without this file changing.
"""

from typing import Awaitable, Callable, Dict, Optional

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from ..capability_manifest import CapabilityManifestRegistry, CapabilityStatus
from .base import Connector


class DynamicDispatchConfig:
    """Runtime dispatch info for one onboarded capability — populated at
    onboarding-activation time (orchestrate/onboarding/runtime_registry.py)
    and rehydrated at app startup. `track` selects which registered executor
    handles the call; `runtime` is whatever that track's executor needs
    (launch command, base URL, etc.)."""

    def __init__(self, track: str, **runtime: object):
        self.track = track
        self.runtime = runtime


ExecutorFn = Callable[["DynamicDispatchConfig", CapabilityCall], Awaitable[Dict[str, object]]]
ResolverFn = Callable[[str], Awaitable[Optional[DynamicDispatchConfig]]]


class DynamicCapabilityConnector(Connector):
    name = "dynamic_capability"
    capabilities = {Capability.DYNAMIC_CAPABILITY}

    def __init__(self, manifests: CapabilityManifestRegistry, resolver: Optional[ResolverFn] = None):
        """`resolver` is an optional async cache-miss fallback (capability_id
        -> DynamicDispatchConfig | None), wired to
        orchestrate.onboarding.runtime_registry so this connector self-heals
        regardless of which endpoint activated the manifest — see that
        module's docstring for why activation can happen via more than one
        code path."""
        self._manifests = manifests
        self._resolver = resolver
        self._dispatch: Dict[str, DynamicDispatchConfig] = {}
        self._executors: Dict[str, ExecutorFn] = {}

    def register(self, capability_id: str, config: DynamicDispatchConfig) -> None:
        self._dispatch[capability_id] = config

    def register_executor(self, track: str, executor: ExecutorFn) -> None:
        self._executors[track] = executor

    def set_resolver(self, resolver: ResolverFn) -> None:
        """P14 — lets the wiring layer (backend/app/main.py, which is
        allowed to import orchestrate/onboarding/ — this module itself
        cannot, see its own docstring on import direction) attach the
        cache-miss fallback after construction rather than only at
        __init__ time."""
        self._resolver = resolver

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        capability_id = call.input.get("capability_id")
        if not capability_id:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="dynamic capability call missing required input.capability_id",
            )

        # P14 — always an authoritative Postgres read (when persisted),
        # never a trust-the-cache-if-present lookup. manifest_for()'s old
        # self-heal only triggered on a cache MISS (None); a capability
        # this process already cached as ACTIVE stayed ACTIVE here forever
        # once hot-disabled through a DIFFERENT worker's registry instance
        # — the real multi-process safety gap this closes. See
        # CapabilityManifestRegistry.refresh_from_db()'s own docstring.
        from backend.app.metrics import capability_registry_authoritative_lookups_total

        try:
            manifest = await self._manifests.refresh_from_db(capability_id)
        except Exception as e:  # noqa: BLE001 — DB unavailable must refuse, never trust a stale cache
            capability_registry_authoritative_lookups_total.labels(result="lookup_failed").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"capability registry authoritative lookup failed ({type(e).__name__}: {e}) — "
                "refusing to execute without a fresh authorization decision",
            )
        if manifest is None:
            capability_registry_authoritative_lookups_total.labels(result="not_found").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"no capability manifest registered for {capability_id}",
            )
        if manifest.status is not CapabilityStatus.ACTIVE:
            capability_registry_authoritative_lookups_total.labels(result="not_active").inc()
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"capability {capability_id} is not active (status={manifest.status.value}) "
                "— sandbox testing and admin activation must complete before it can be invoked",
            )
        capability_registry_authoritative_lookups_total.labels(result="allowed").inc()

        config = self._dispatch.get(capability_id)
        if config is None and self._resolver is not None:
            config = await self._resolver(capability_id)
            if config is not None:
                self._dispatch[capability_id] = config
        if config is None:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"no runtime dispatch config registered for {capability_id}",
            )

        executor = self._executors.get(config.track)
        if executor is None:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"no executor registered for track {config.track!r}",
            )

        try:
            output = await executor(config, call)
        except Exception as e:  # noqa: BLE001 — vendor/runtime errors become a FAILED response, never a raise
            # A genuine executor failure is real evidence about THIS
            # capability's behavior (unlike the not-active/no-manifest/
            # no-dispatch-config early returns above, which are routing/
            # config errors, not the capability misbehaving) — counted
            # separately from record_usage() so calibrate_tier() can tell
            # "used a lot" apart from "used a lot, several failures."
            await self._manifests.record_failure(capability_id)
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"{type(e).__name__}: {e}",
            )

        await self._manifests.record_usage(capability_id)
        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output=output,
        )
