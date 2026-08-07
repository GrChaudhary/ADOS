"""
Glue layer bridging orchestrate/onboarding/'s session pipeline into the two
runtime halves this whole feature exists for: making an onboarded
capability actually invocable
(integrations/connectors/dynamic.py's DynamicCapabilityConnector) and
actually choosable by MOA (orchestrate/moa/dynamic_registry.py).

Deliberately lives in orchestrate/, not integrations/ — the existing
import direction throughout this codebase is orchestrate/ -> integrations/,
never the reverse (see integrations/connectors/dynamic.py's own module
docstring), and this module needs both orchestrate.moa and
integrations.capability_manifest, so putting it in integrations/ would
invert that.

register_runtime() is idempotent and meant to be called from more than one
place: backend/app/main.py's startup (hydrate_all, rehydrating every
already-ACTIVE capability after a process restart) and both of the two
REST paths that can flip a manifest to ACTIVE — this package's own
/activate endpoint, and the pre-existing generic
POST /capabilities/manifests/{id}/promote (backend/app/routers/
capabilities.py) — an admin can reach ACTIVE via either one, and both must
leave the capability equally live afterward.
"""

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from contracts import Capability, CapabilityCall
from db.models.onboarding_session import OnboardingSessionRow
from integrations.capability_manifest import CapabilityManifestRegistry, CapabilityStatus
from integrations.connectors.dynamic import DynamicCapabilityConnector, DynamicDispatchConfig
from orchestrate.moa import dynamic_registry
from orchestrate.moa.dynamic_registry import DynamicAction

from . import sandbox_runner
from .models import OnboardingSessionStatus


def _filter_to_tool_arguments(call_input: Dict[str, Any], input_schema: Dict[str, Any]) -> Dict[str, Any]:
    """CapabilityCall.input carries MOA-loop bookkeeping alongside real tool
    arguments — capability_id (this bridge's own routing key), and for
    actions that flow through orchestrate/moa/graph.py's fixed HR_ACTIONS-
    style payload shape, employee_name/action too (see graph.py's
    _action_input()). None of that is a real parameter the MCP tool itself
    declared, and passing it straight through would make FastMCP reject
    the call for any tool whose signature doesn't happen to also have a
    same-named parameter. Filter down to exactly what the tool's own
    input_schema declares instead of guessing which extra keys are safe to
    drop."""
    allowed = set((input_schema or {}).get("properties", {}).keys())
    return {k: v for k, v in call_input.items() if k in allowed}


async def _mcp_native_executor(config: DynamicDispatchConfig, call: CapabilityCall) -> Dict[str, Any]:
    arguments = _filter_to_tool_arguments(call.input, config.runtime.get("input_schema", {}))
    return await sandbox_runner.run_mcp_live_call(
        local_path=config.runtime["local_path"],
        launch_command=config.runtime["launch_command"],
        tool_name=config.runtime["tool_name"],
        arguments=arguments,
    )


async def _openapi_executor(config: DynamicDispatchConfig, call: CapabilityCall) -> Dict[str, Any]:
    arguments = _filter_to_tool_arguments(call.input, config.runtime.get("input_schema", {}))
    base_url = config.runtime.get("base_url")
    if not base_url:
        raise RuntimeError(
            "no production base_url recorded for this capability — synthesize_openapi_action "
            "couldn't resolve one from the spec and no production_base_url was supplied at onboarding time"
        )
    return await sandbox_runner.run_openapi_live_call(
        base_url=base_url,
        method=config.runtime["method"],
        path_template=config.runtime["path_template"],
        arguments=arguments,
    )


async def _raw_code_executor(config: DynamicDispatchConfig, call: CapabilityCall) -> Dict[str, Any]:
    arguments = _filter_to_tool_arguments(call.input, config.runtime.get("input_schema", {}))
    return await sandbox_runner.run_raw_code_live_call(
        local_path=config.runtime["local_path"],
        entrypoint_path=config.runtime["entrypoint_path"],
        function_name=config.runtime["function_name"],
        arguments=arguments,
        install_dependencies=config.runtime.get("install_dependencies", False),
    )


def register_default_executors(dynamic_connector: DynamicCapabilityConnector) -> None:
    """Static track -> executor wiring, independent of any specific
    onboarded capability — call once per process (backend/app/main.py's
    lifespan, right after default_hub()). Idempotent (register_executor
    just overwrites the dict entry), safe to call more than once."""
    dynamic_connector.register_executor("mcp_native", _mcp_native_executor)
    dynamic_connector.register_executor("openapi", _openapi_executor)
    dynamic_connector.register_executor("raw_code", _raw_code_executor)


async def _latest_activated_session(session_factory: async_sessionmaker, capability_id: str) -> "OnboardingSessionRow | None":
    async with session_factory() as session:
        return (
            await session.execute(
                select(OnboardingSessionRow)
                .where(OnboardingSessionRow.capability_id == capability_id)
                .where(OnboardingSessionRow.status == OnboardingSessionStatus.ACTIVATED.value)
                .order_by(OnboardingSessionRow.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def register_runtime(
    session_factory: async_sessionmaker,
    capability_id: str,
    dynamic_connector: DynamicCapabilityConnector,
) -> bool:
    """Returns False (a safe no-op, not an error) when no onboarding_sessions
    row exists for this capability_id — a manifest proposed outside this
    pipeline entirely (e.g. a built-in capability someone ran propose() on
    directly, as tests/test_connectors.py's hot-disable tests do) has
    nothing here to hydrate."""
    row = await _latest_activated_session(session_factory, capability_id)
    if row is None:
        return False

    synthesized = row.synthesized_manifest or {}
    runtime = synthesized.get("runtime", {})
    dynamic_connector.register(capability_id, DynamicDispatchConfig(track=row.track, **runtime))

    if row.domain:
        dynamic_registry.register(
            DynamicAction(
                key=synthesized.get("key", capability_id),
                description=synthesized.get("description", capability_id),
                capability=Capability.DYNAMIC_CAPABILITY,
                estimated_cost_usd=synthesized.get("estimated_cost_usd", 0.0),
                capability_id=capability_id,
                input_schema=runtime.get("input_schema", {}),
            )
        )
    return True


async def hydrate_all(
    session_factory: async_sessionmaker,
    manifests: CapabilityManifestRegistry,
    dynamic_connector: DynamicCapabilityConnector,
) -> int:
    """Startup path — repairs both the connector's dispatch cache and
    dynamic_registry's in-process action list after a restart, for every
    manifest that's currently ACTIVE. Returns the count actually hydrated
    (i.e. that had a real onboarding_sessions row to hydrate from)."""
    count = 0
    for manifest in await manifests.list_manifests():
        if manifest.status is not CapabilityStatus.ACTIVE:
            continue
        if await register_runtime(session_factory, manifest.capability_id, dynamic_connector):
            count += 1
    return count
