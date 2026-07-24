from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from integrations import default_hub
from orchestrate import DecisionOrchestrator

from .config import settings
from .eventbus import get_event_bus
from .routers import capabilities, digital_twin, events, events_stream, executive, health, incidents, learning, memory

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

app.include_router(health.router)
app.include_router(events.router)
app.include_router(capabilities.router)
app.include_router(incidents.router)
app.include_router(executive.router)
app.include_router(memory.router)
app.include_router(learning.router)
app.include_router(digital_twin.router)
app.include_router(events_stream.router)

if _FRONTEND_DIR.exists():
    # docs/011-ui-ux.md's approval surface + executive dashboard — plain
    # HTML/JS, no build step, served from the same origin as the API so
    # frontend/app.js's fetch() calls need no CORS configuration.
    app.mount("/dashboard", StaticFiles(directory=_FRONTEND_DIR, html=True), name="dashboard")
