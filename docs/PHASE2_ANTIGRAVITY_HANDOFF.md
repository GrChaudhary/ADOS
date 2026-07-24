# ADOS Phase 2 — Live Agent Timeline (SSE) (Context Prompt for Antigravity)

Paste this whole document as your starting context. It is self-contained —
you don't need anything from a prior conversation.

## Project

ADOS (Autonomous Defect & Orchestration System) is a multi-agent AI system
for manufacturing defect detection and root-cause resolution. Repo root:
`/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
(git repo; run `git log --oneline` and confirm you're on top of commit
`642964e` before editing).

Read `docs/handoff.md` first for full system architecture. Read
`Blueprints/ADOS_Demo_Product_Experience_Blueprint.md` for the judge-facing
demo narrative: a "Mission Control" dashboard where judges watch agents
resolve a Motor Housing incident in real time —

```
09:41 Vision ✓
09:41 CAD ✓
09:42 Knowledge Graph ✓
09:42 Supplier Analysis ✓
09:43 Simulation ✓
09:43 Recommendation ✓
```

— that live-updating timeline is what you're building.

## What's already done (not your job)

Phase 0 (Nova Motors demo dataset), Phase 1 (multi-line digital twin, `GET
/digital-twin/lines`), and Phase 3 (per-incident Option A/B/C recommendation
comparison, `GET /executive/incidents/{id}/options`) all just landed in
parallel with your work and are already committed. **None of those files
overlap with what you're touching** — go ahead without waiting on them. Do
not touch `executive/*`, `orchestrate/orchestrator.py`,
`backend/app/routers/executive.py`, `knowledge/digital_twin.py`,
`knowledge/asset_model.py`, or `backend/app/routers/digital_twin.py`.

## Your job: Phase 2 — SSE live agent timeline

### 1. The event bus already works — verify, don't rebuild

`backend/app/eventbus/base.py` defines `EventBus.stream(self) -> AsyncIterator[EventEnvelope]`,
implemented by both `memory_bus.py` (`InMemoryEventBus`, the default —
registers an `asyncio.Queue` and yields as `publish()` pushes to it) and
`redis_bus.py` (`RedisEventBus`, opt-in via `EVENT_BUS_BACKEND=redis` —
blocking `XREAD` loop). Both are fully working today, not stubs. **`stream()`
takes no filter argument** — it's an unfiltered feed of every event across
every incident. Any `incident_id` filtering has to happen in your route,
not the bus.

Confirm every agent stage really does publish events by running:
```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/python scripts/run_orchestrator_demo.py
```
You'll see `[EVENT BUS] 16 events published for this incident` — a
`StageRequested`/`AgentCompleted` pair per stage
(vision → cad → causal → substitution → parameter_adjustment →
impact_simulation → rerouting → feedback_calibration). This is confirmed
real, not something you need to build — `orchestrate/agent_runner.py`
already publishes both events per stage, and `agents/sdk/base.py`'s
`AgentCompleted` payload already contains `agent_id, stage_name,
execution_time_ms, confidence, result, evidence, alternatives`. That
payload shape is what your timeline widget will render per row.

### 2. New SSE route — but NOT on the existing `events.router`

`backend/app/routers/events.py` currently has `POST /events` and
`GET /events` (a polling snapshot via `event_bus.recent()`), both gated by
`dependencies=[Depends(require_service_auth)]` **at the router level** —
every route on that router requires a bearer token in the `Authorization`
header. The file's own docstring already anticipates you: *"Real
intra-process consumers should use `app.state.event_bus.stream()` directly
rather than polling this."*

**The problem**: a browser's native `EventSource` API cannot set custom
request headers, so it can never satisfy `Authorization: Bearer ...`. Do
**not** just add a `/stream` route to the existing `events.router` — it will
inherit the header-only auth and silently 401 every browser connection.

**The fix** (this is a real design decision, already made for you — don't
reinvent it): create a **new, separate router file**
`backend/app/routers/events_stream.py` with its own query-param-tolerant
auth, since `EventSource` can only pass the token via the URL:

```python
"""
SSE live event stream for the Mission Control agent timeline (Phase 2).
Separate router from events.py because browser EventSource can't set an
Authorization header — this accepts the service token via ?token= instead,
same shared-secret trust model as require_service_auth (backend/app/auth.py).
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events(request: Request, token: str = Query(...), incident_id: Optional[str] = None):
    if token != settings.service_auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")

    async def event_generator():
        async for envelope in request.app.state.event_bus.stream():
            if incident_id is not None and envelope.incident_id != incident_id:
                continue
            yield f"data: {envelope.model_dump_json(by_alias=True)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Register it in `backend/app/main.py` next to the other routers (one import
line, one `app.include_router(events_stream.router)` line — same pattern
Phase 1 used for `digital_twin.router`).

Verify manually that a disconnecting client doesn't hang the server (the
generator should stop cleanly when the HTTP connection closes — FastAPI/
Starlette handle this via `asyncio.CancelledError` on the generator, but
confirm it with a real client disconnect, not just reasoning about it).

### 3. Frontend timeline consumer

Add a live timeline panel to the existing ops dashboard
(`frontend/index.html` / `app.js` / `styles.css` — plain HTML/JS, no build
step). Use the browser's native `EventSource`:

```js
const es = new EventSource(`/events/stream?token=${token}`);
es.onmessage = (e) => {
  const envelope = JSON.parse(e.data);
  if (envelope.eventType !== "AgentCompleted") return; // skip StageRequested, or render them as "in progress" rows if you want both
  appendTimelineRow(envelope.payload); // { agentId, stageName, confidence, result, ... }
};
```

Reuse the existing `dev-local-only-token` already stored in `localStorage`
by the current dashboard for the header-based endpoints — same token, just
passed as a query param here instead. Render one row per `AgentCompleted`
event: stage name, agent id, confidence, and a short summary from
`payload.result` (the exact keys vary per agent — e.g. vision's has
`defect_detected`/`measured_value`, causal's has `primary_root_cause`, so
just show whatever's present rather than hardcoding one shape). Keep it
additive/self-contained in the shared frontend files (its own clearly
delimited section/function, e.g. `renderAgentTimeline()`), matching how
Phase 1's `refreshDigitalTwinLines()` was added as its own isolated block —
don't restructure existing dashboard code while you're in there.

### 4. Tests

Add `tests/test_events_stream_router.py` (or similar) covering:
- `GET /events/stream` with no/wrong token → 401
- `GET /events/stream?token=<valid>` → 200, `text/event-stream` content type
- Publish an event via `POST /events` (existing route) during an open stream
  and confirm it comes through (FastAPI's `TestClient` supports streaming
  responses; iterate the response with a short timeout/limited read count
  rather than consuming an infinite generator forever in a test).

## Verification

```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/pytest tests/ backend/tests/ -q
```
86 tests currently pass on top of your starting commit — must stay green.

```bash
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
# open http://localhost:8000/dashboard/, token: dev-local-only-token
```
Trigger a real incident (there's already a "start incident" control on the
dashboard, or `POST /incidents`) and confirm the timeline panel fills in
live, stage by stage, without a page refresh.

## Do not touch

`executive/*`, `orchestrate/orchestrator.py`,
`backend/app/routers/executive.py`, `knowledge/digital_twin.py`,
`knowledge/asset_model.py`, `backend/app/routers/digital_twin.py`,
`knowledge/seed_data.py`, `executive/seed_data.py`,
`executive/incident_generator.py`, `knowledge/causal_graph.py`,
`agents/*.py`, `scripts/run_phase3_options_demo.py`. You may add to
`backend/app/main.py` (one import + one `include_router` line) and to
`frontend/app.js` / `index.html` / `styles.css` (additive only, your own
new section/functions).

When done, commit your changes with a clear message.
