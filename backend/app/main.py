import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.engine import async_session_factory, engine as db_engine
from db.health import check_connectivity_or_raise
from integrations import CapabilityManifestRegistry, default_hub
from orchestrate import DecisionOrchestrator
from orchestrate.onboarding import runtime_registry as onboarding_runtime_registry

from . import user_store
from .config import settings
from .eventbus import get_event_bus
from .routers import ai_services, agents_registry, auth, capabilities, capability_onboarding, copilot, digital_twin, events, events_stream, executive, governance, health, incidents, integrations, knowledge_graph, langgraph_agents, learning, memory, moa, settings as settings_router

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


from knowledge.local_llm_client import local_llm_client
from executive.seed_data import INCIDENT_RECORDS_SEED


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast and loud if Postgres is unreachable — matches the existing
    # "honest status" convention already used for Cloudant/NLU/TTS (never
    # silently degrade). Schema itself isn't applied here (see db/README
    # notes in the plan this was built from): `alembic upgrade head` is a
    # separate, deliberate step, not run automatically on boot.
    await check_connectivity_or_raise()

    kwargs = {}
    if settings.event_bus_backend == "redis":
        kwargs = {"url": settings.event_bus_url, "stream": settings.event_bus_stream}
    elif settings.event_bus_backend == "kafka":
        kwargs = {"bootstrap_servers": settings.kafka_bootstrap_servers, "topic": settings.kafka_topic}
    app.state.event_bus = get_event_bus(settings.event_bus_backend, **kwargs)
    await app.state.event_bus.start()
    app.state.integration_hub = default_hub(manifests=CapabilityManifestRegistry(session_factory=async_session_factory))
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
        print(f"[Startup] Rehydrated {hydrated} onboarded capability(ies) into the dynamic connector + MOA")
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
    app.state.itsm_pending_proposals = {}
    # task_id -> (compiled LangGraph, config) for a MOA HR-domain action
    # paused on interrupt() — see backend/app/routers/moa.py. Same shape as
    # itsm_pending_proposals above.
    app.state.moa_pending_tasks = {}

    loaded = await app.state.orchestrator.audit_trail.hydrate_from_db()
    print(f"[Startup] Hydrated {loaded} incident(s) from Postgres into the audit trail")
    # Same Postgres rows, loaded into the *separate* in-memory index
    # backend/app/routers/memory.py's /memory/search uses — hydrated
    # independently (not by copying audit_trail.all()) because that list
    # may already include seed_records, and the index applies the same
    # SEED_DEMO_DATA gate to its own construction; copying would duplicate it.
    await memory.get_memory_index().hydrate_from_db(async_session_factory)
    resumed = await app.state.orchestrator.resume_pending_approvals()
    if resumed:
        print(f"[Startup] Reconstituted {resumed} pending approval(s) stranded by the last restart")

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
        print("[Startup] Seeded RBAC accounts with generated passwords (change via POST /auth/users):")
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

    yield

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
    capability_onboarding.router,
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
