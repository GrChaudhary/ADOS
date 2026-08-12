import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.engine import async_session_factory, engine as db_engine
from db.health import check_connectivity_or_raise
from integrations import CapabilityManifestRegistry, default_hub
from integrations.admission_control import AdmissionControl
from orchestrate import DecisionOrchestrator
from orchestrate.onboarding import runtime_registry as onboarding_runtime_registry

from . import user_store
from .config import settings
from .mcp_gateway import mcp_http_app
from .eventbus import get_event_bus
from .observability import RequestIdMiddleware, configure_logging
from .routers import ai_services, agents_registry, auth, capabilities, capability_onboarding, copilot, digital_twin, events, events_stream, executive, governance, health, incidents, integrations, knowledge_graph, langgraph_agents, learning, memory, metrics as metrics_router, moa, runtime_approvals, settings as settings_router

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


from knowledge.local_llm_client import local_llm_client
from executive.seed_data import INCIDENT_RECORDS_SEED


# Before any logger is used, including during lifespan.
configure_logging(level=settings.log_level, json_output=settings.log_json)

logger = logging.getLogger("ados.startup")


async def _refresh_llm_settings_periodically() -> None:
    """Re-reads llm_provider_settings into local_llm_client's in-process
    cache on a fixed interval, so a key saved on one replica becomes visible
    on the others without a restart.

    Deliberately never lets a transient DB error kill the loop -- a failed
    refresh just means the cache stays as it was until the next tick, which
    is strictly better than the task dying silently and the process drifting
    permanently stale.
    """
    interval = settings.llm_settings_refresh_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session_factory() as session:
                local_llm_client.hydrate_settings_cache(
                    await settings_router.load_all_provider_settings(session)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("LLM settings refresh failed; keeping previous cache", exc_info=True)


async def _reconcile_and_sweep_orphans_periodically() -> None:
    """Reconciles sessions abandoned by a process failure (orchestrate/
    runtime/session_reconcile.py), then sweeps whatever is now — or was
    already — marked orphaned (orchestrate/runtime/orphan_sweep.py), on a
    fixed interval. Reconcile first: a session an earlier ADOS process died
    on has to become terminal-and-marked before the sweeper's own, unchanged
    claim query will ever see it.

    Same failure posture as _refresh_llm_settings_periodically: a bad pass
    is logged and the loop keeps ticking, rather than a transient DB or
    Docker hiccup silently ending background cleanup for the rest of the
    process's life.
    """
    from orchestrate.runtime.orphan_sweep import sweep_once
    from orchestrate.runtime.session_reconcile import reconcile_abandoned_sessions

    interval = settings.orphan_reconcile_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            reconciled = await reconcile_abandoned_sessions(async_session_factory)
            if reconciled:
                logger.info(
                    "Reconciled sessions abandoned by a prior process failure",
                    extra={"count": len(reconciled)},
                )
            report = await sweep_once(async_session_factory)
            if report.claimed:
                logger.info(
                    "Orphan sweep",
                    extra={
                        "claimed": report.claimed, "cleaned": report.cleaned,
                        "absent": report.absent, "failed": report.failed, "refused": report.refused,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Orphan reconcile/sweep pass failed; will retry next interval", exc_info=True)


# The MCP sub-app is rebuilt for EVERY lifespan run, not once at import.
#
# FastMCP's StreamableHTTPSessionManager refuses to .run() twice on the same
# instance, and the test suite starts this app's lifespan once per TestClient —
# dozens of times per session. A single import-time instance therefore works in
# production and detonates the moment a second TestClient opens, which is
# exactly what it did: 30 failures and 55 errors across files that have nothing
# to do with MCP.
#
# So the mount below is a thin delegator to whichever instance the current
# lifespan created, and _mcp_current is None outside a lifespan (the endpoint
# is genuinely not available then, which is honest).
_mcp_current: Any = None


async def _mcp_delegator(scope, receive, send):
    if _mcp_current is None:
        raise RuntimeError("MCP gateway addressed outside the application lifespan")
    await _mcp_current(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast and loud if Postgres is unreachable — matches the existing
    # "honest status" convention already used for Cloudant/NLU/TTS (never
    # silently degrade). Schema itself isn't applied here (see db/README
    # notes in the plan this was built from): `alembic upgrade head` is a
    # separate, deliberate step, not run automatically on boot.
    await check_connectivity_or_raise()

    # The LangGraph checkpointer's four tables are created by the library's
    # own migration mechanism, not Alembic. P10 moved the actual `setup()`
    # call from here into alembic/env.py's online migration path: it is DDL
    # (`CREATE TABLE IF NOT EXISTS`), and this process now connects as
    # `ados_app`, a non-superuser role with no CREATE grant (revision
    # f4a5b6c7d8e9) -- it can no longer perform that setup itself, only use
    # the tables `alembic upgrade head` already prepared. Every documented
    # boot path runs that command before starting the app regardless (the
    # rest of the schema doesn't exist without it either), so nothing here
    # lost the "converges on a ready schema" property -- it moved to the
    # step that was always the real precondition.

    kwargs = {}
    if settings.event_bus_backend == "redis":
        kwargs = {"url": settings.event_bus_url, "stream": settings.event_bus_stream}
    elif settings.event_bus_backend == "kafka":
        kwargs = {"bootstrap_servers": settings.kafka_bootstrap_servers, "topic": settings.kafka_topic}
    app.state.event_bus = get_event_bus(settings.event_bus_backend, **kwargs)
    await app.state.event_bus.start()
    app.state.integration_hub = default_hub(
        manifests=CapabilityManifestRegistry(session_factory=async_session_factory),
        admission_control=AdmissionControl(
            max_concurrent_capability_executions=settings.max_concurrent_capability_executions,
            max_concurrent_missions=settings.max_concurrent_prime_missions,
        ),
    )
    # Capability onboarding (orchestrate/onboarding/) — static track ->
    # executor wiring (independent of any specific capability), then
    # rehydrate the dynamic connector's dispatch table and MOA's
    # dynamic_registry for every capability already ACTIVE from a prior
    # process (see runtime_registry.py's module docstring for why both
    # this restart path and the two live activation endpoints all funnel
    # through the same register_runtime()).
    onboarding_runtime_registry.register_default_executors(app.state.integration_hub.dynamic_capability_connector)
    hydrated = await onboarding_runtime_registry.hydrate_all(
        async_session_factory, app.state.integration_hub.manifests, app.state.integration_hub.dynamic_capability_connector
    )
    if hydrated:
        logger.info("Rehydrated onboarded capabilities", extra={"capability_count": hydrated})
    app.state.orchestrator = DecisionOrchestrator(
        event_bus=app.state.event_bus,
        integration_hub=app.state.integration_hub,
        # 20 hero + 200 generated demo incidents (executive/seed_data.py),
        # opt-in via SEED_DEMO_DATA. These feed the dashboard, the KPI
        # baseline, and every /executive/* analytic (which read
        # orchestrator.audit_trail.all()), so leaving them on by default
        # meant a fresh deployment opened full of incidents that never
        # happened. Additive with real Postgres-backed incidents hydrated
        # below, not a replacement: different incident_id namespace
        # (INC-2026-* vs real UUIDs), so turning this on or off never
        # disturbs real records either way.
        seed_records=INCIDENT_RECORDS_SEED if settings.seed_demo_data else None,
        session_factory=async_session_factory,
    )
    app.state.incident_tasks = {}
    # request_id -> (compiled LangGraph, config) for an ITSM create-incident
    # proposal paused on interrupt() — see backend/app/routers/
    # langgraph_agents.py. Same shape as incident_tasks above: an in-memory
    # dict of live, in-process objects a later request needs to find again.
    # NOTE: there are deliberately no app.state.moa_pending_tasks /
    # itsm_pending_proposals dicts any more. Paused approvals used to live in
    # dicts here, which meant a restart dropped every pending approval on the
    # floor and a second replica could not see, let alone resume, a task it
    # had not started. That state now lives in the LangGraph checkpointer
    # (db/checkpointer.py), plus the moa_task_breakers table
    # (backend/app/moa_breaker_store.py) for the one piece a rebuilt graph
    # cannot reconstruct: the cascade breaker's streak.

    loaded = await app.state.orchestrator.audit_trail.hydrate_from_db()
    logger.info("Hydrated incidents from Postgres", extra={"incident_count": loaded})
    # Same Postgres rows, loaded into the *separate* in-memory index
    # backend/app/routers/memory.py's /memory/search uses — hydrated
    # independently (not by copying audit_trail.all()) because that list
    # may already include seed_records, and the index applies the same
    # SEED_DEMO_DATA gate to its own construction; copying would duplicate it.
    await memory.get_memory_index().hydrate_from_db(async_session_factory)
    resumed = await app.state.orchestrator.resume_pending_approvals()
    if resumed:
        logger.info(
            "Reconstituted pending approvals stranded by the last restart",
            extra={"approval_count": resumed},
        )

    # RBAC (backend/app/user_store.py) - seeds the 5 demo accounts only if
    # the user store is empty; never resets existing accounts/passwords.
    # No Depends(get_db_session) here — lifespan isn't a request — so this
    # opens and commits its own session directly, same as
    # CapabilityManifestRegistry's injected-session_factory methods do.
    async with async_session_factory() as _startup_session:
        generated_passwords = await user_store.bootstrap_users(_startup_session)
        await _startup_session.commit()
        # LLM provider settings (backend/app/routers/settings.py) - pushes
        # whatever's persisted into local_llm_client's in-memory cache once
        # at startup; the router re-pushes it after every save/delete. See
        # local_llm_client.hydrate_settings_cache()'s docstring for why
        # this is push- rather than pull-based.
        local_llm_client.hydrate_settings_cache(await settings_router.load_all_provider_settings(_startup_session))
    if generated_passwords:
        # Passwords stay on print(): they are shown once, for a human reading
        # the console, and must NOT flow into a log shipper or get indexed.
        source = "SEED_PASSWORD" if settings.seed_password else "generated, shown once and never again"
        print(f"[Startup] Seeded RBAC accounts ({source}). Reset later with scripts/reset_user_password.py:")
        for username, password in generated_passwords.items():
            print(f"  {username} / {password}")

    # Real-Time Obsidian Vault Projection Listener (§9).
    # The listener only projects the event types producers actually publish
    # (GovernancePendingApproval / GovernanceApprovalDecision) — see
    # orchestrate/obsidian/listener.py. Producers must publish to THIS bus
    # (app.state.event_bus), not orchestrate/async_approvals.py's module-level
    # fallback bus, or nothing here ever sees them.
    # The subscription registers on the task's first step rather than here, so
    # anything published in the same tick as startup is dropped. Harmless in
    # practice: uvicorn finishes lifespan before serving, and nothing publishes
    # during startup.
    from orchestrate.obsidian.listener import ObsidianProjectionListener
    app.state.obsidian_listener = ObsidianProjectionListener()
    await app.state.obsidian_listener.start()
    app.state.obsidian_listener_task = asyncio.create_task(app.state.obsidian_listener.listen_to_bus(app.state.event_bus))

    # Keeps this process's LLM provider cache in step with what other
    # processes have saved — see settings.llm_settings_refresh_seconds for
    # why a pull loop rather than a read-through cache.
    app.state.llm_settings_refresh_task = (
        asyncio.create_task(_refresh_llm_settings_periodically())
        if settings.llm_settings_refresh_seconds > 0
        else None
    )

    # Reconciles sessions abandoned by a prior process failure, then sweeps
    # whatever is (now, or already) marked orphaned — see
    # orchestrate/runtime/session_reconcile.py and orphan_sweep.py for the
    # safety argument each guard makes on its own. scripts/sweep_orphans.py
    # remains available for an operator who wants to run either by hand or
    # from their own cron instead; this is purely additive automation on top
    # of the same, unmodified mechanisms.
    app.state.orphan_reconcile_task = (
        asyncio.create_task(_reconcile_and_sweep_orphans_periodically())
        if settings.orphan_reconcile_interval_seconds > 0
        else None
    )

    # The MCP capability gateway is a mounted ASGI sub-app with its own
    # session manager, and that manager only starts if its lifespan runs.
    # Mounting alone is NOT enough — a mounted app's lifespan is not invoked
    # by Starlette, so without this the endpoint would accept connections and
    # then fail on the first tool call. Nesting it here keeps ADOS's lifespan
    # the single owner of startup order.
    global _mcp_current
    _mcp_gateway = mcp_http_app()
    async with _mcp_gateway.router.lifespan_context(app):
        _mcp_current = _mcp_gateway
        try:
            yield
        finally:
            _mcp_current = None

    if getattr(app.state, "llm_settings_refresh_task", None):
        app.state.llm_settings_refresh_task.cancel()
    if getattr(app.state, "orphan_reconcile_task", None):
        app.state.orphan_reconcile_task.cancel()
    if hasattr(app.state, "obsidian_listener_task") and app.state.obsidian_listener_task:
        app.state.obsidian_listener_task.cancel()
    if hasattr(app.state, "obsidian_listener") and app.state.obsidian_listener:
        await app.state.obsidian_listener.stop()
    await app.state.event_bus.aclose()
    await db_engine.dispose()


app = FastAPI(title="ADOS Backend", version="0.1.0", lifespan=lifespan)

# frontend-next/ (Phase 5B, React/Next.js) runs on a different origin than
# frontend/'s same-origin static mount and needs CORS. Explicit origin, not
# "*" — the bearer token is honest-but-simple shared-secret auth (docs/009),
# no cookies involved, but there's no reason to widen this beyond the one
# known dev origin.
# Outermost so every request gets an id before anything else runs, and so
# the id is still set while CORS/error responses are produced.
app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_dev_origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ROUTERS = (
    health.router, auth.router, events.router, capabilities.router, incidents.router,
    executive.router, memory.router, learning.router, digital_twin.router,
    events_stream.router, knowledge_graph.router, integrations.router,
    ai_services.router, agents_registry.router, governance.router,
    settings_router.router, copilot.router, langgraph_agents.router, moa.router,
    capability_onboarding.router, runtime_approvals.router, metrics_router.router,
)

for _router in _ROUTERS:
    app.include_router(_router)

# /api/v1 aliases of the exact same routes, per documentation/04_Demo_UI_Architecture.md's
# API table — mirrors every real endpoint under the versioned prefix with
# zero logic duplication (same router objects, re-mounted). The doc's own
# sub-paths that don't correspond to any real capability (e.g.
# /api/v1/digital-twin/status, /api/v1/incidents/{id}/evidence) are treated
# as informal shorthand for the real endpoints below, not built as new routes.
for _router in _ROUTERS:
    app.include_router(_router, prefix="/api/v1")

if _FRONTEND_DIR.exists():
    # docs/011-ui-ux.md's approval surface + executive dashboard — plain
    # HTML/JS, no build step, served from the same origin as the API so
    # frontend/app.js's fetch() calls need no CORS configuration.
    app.mount("/dashboard", StaticFiles(directory=_FRONTEND_DIR, html=True), name="dashboard")

# The Prime Agent runtime's only route back into ADOS. Mounted OUTSIDE the
# /api/v1 routers deliberately: it carries opaque per-session runtime tokens,
# not user JWTs, so it must not sit behind get_current_user.
app.mount("/mcp", _mcp_delegator)
# Reload trigger: agency agents registry updated

