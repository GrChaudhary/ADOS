from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from integrations import default_hub
from orchestrate import DecisionOrchestrator

from .config import settings
from .eventbus import get_event_bus
from .routers import capabilities, digital_twin, events, events_stream, executive, health, incidents, knowledge_graph, learning, memory

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    kwargs = {}
    if settings.event_bus_backend == "redis":
        kwargs = {"url": settings.event_bus_url, "stream": settings.event_bus_stream}
    app.state.event_bus = get_event_bus(settings.event_bus_backend, **kwargs)
    app.state.integration_hub = default_hub()
    app.state.orchestrator = DecisionOrchestrator(
        event_bus=app.state.event_bus, integration_hub=app.state.integration_hub
    )
    app.state.incident_tasks = {}
    yield


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
    health.router, events.router, capabilities.router, incidents.router,
    executive.router, memory.router, learning.router, digital_twin.router,
    events_stream.router, knowledge_graph.router,
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
