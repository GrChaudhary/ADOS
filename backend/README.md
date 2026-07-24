# backend/

Core service code: the FastAPI backend, event bus wiring, and the L1–L5
services that don't have their own top-level module (perception ingestion,
Global Planning / L3, Decision Memory persistence).

Not here: reasoning agents ([`../agents/`](../agents/)), orchestration
workflows ([`../orchestrate/`](../orchestrate/)), connectors
([`../integrations/`](../integrations/)), schemas
([`../contracts/`](../contracts/)), or graph stores
([`../knowledge/`](../knowledge/)).

Relevant chapters: [001-system-architecture](../docs/001-system-architecture.md),
[010-api-contracts](../docs/010-api-contracts.md).

## Status: Phase 3A — orchestrator wired in

```
app/
  config.py       Settings (pydantic-settings, reads ../.env)
  auth.py         shared-secret bearer auth (MVP — see docs/009-security.md)
  eventbus/       EventBus abstraction: InMemoryEventBus (default) / RedisEventBus
  routers/        health.py, events.py, capabilities.py, incidents.py, executive.py
  main.py         FastAPI app + lifespan wiring event bus, Integration Hub
                  & DecisionOrchestrator (../orchestrate/)
tests/            pytest suite (health, events, capabilities, incidents)
```

Run it:

```bash
../scripts/run-backend.sh        # http://localhost:8000
../.venv/bin/pytest               # from the ADOS root
```

`../frontend/` (the approval surface + executive dashboard) is mounted at
`/dashboard/` — open http://localhost:8000/dashboard/ once the server's
running. See `../frontend/README.md`.

All routes except `/healthz` require `Authorization: Bearer <SERVICE_AUTH_TOKEN>`
(see `../.env.example`). `/capabilities/invoke` runs a `CapabilityCall`
through `integrations/`'s Capability Registry → Connector Policy Engine →
Connector chain — real ServiceNow/SAP connectors are wired in (Phase 3A),
falling back to the `console` connector when they're not configured (no
sandbox credentials yet — see `../integrations/README.md`).

### Incident lifecycle (`/incidents`) — orchestrate/'s DecisionOrchestrator

```
POST /incidents                      start an incident, returns incidentId immediately
GET  /incidents                      recent audit trail (resolved/failed/preempted)
GET  /incidents/{id}                 status — in_progress (+ pending approval) or final IncidentRecord
GET  /approvals                      Tier 1/2 decisions currently awaiting a human
POST /incidents/{id}/approve|reject|escalate   { "approved_by": "..." }
```

A run is a background asyncio task — Tier 1/2 incidents block on
`GET /approvals` + one of the decision endpoints before executing, per
[007-governance](../docs/007-governance.md). See
`../scripts/run_orchestrator_demo.py` for the same flow without HTTP.

Event bus defaults to in-memory (zero external deps); set
`EVENT_BUS_BACKEND=redis` + `EVENT_BUS_URL` in `.env` to switch to the
Redis Streams implementation for multi-process setups.

### Executive Intelligence (`/executive`) — Phase 3B's `executive/` package

```
GET  /executive/kpis[?plant_id=]         KPI Engine — docs/008's five KPIs
GET  /executive/kpis/what-if?condition_id=   promote-to-Tier-0 simulation
GET  /executive/recommendations          strategic recommendations
GET  /executive/risk                     predictive plant/line risk signals
GET  /executive/edi/root-causes          EDI root-cause clustering
GET  /executive/edi/benchmarks           EDI plant benchmarking
POST /executive/copilot/ask              { "query": "..." } -> evidence-grounded answer
```

Every endpoint here reads `orchestrator.audit_trail.all()` — the **real**
`IncidentRecord`s this process's orchestrator produced — explicitly, so
`executive/`'s classes never fall back to `executive/seed_data.py`'s demo
fixtures (their default when `records=None`). On a fresh boot with no
incidents run yet, `/executive/kpis` correctly returns all zeros rather
than seed data — verified in
`../tests/test_phase3_cross_integration.py`, which runs real incidents
through the orchestrator and feeds the resulting audit trail into
`KPIEngine`/`RecommendationEngine` directly (no HTTP layer), the same
role `../tests/test_cross_phase_integration.py` played for Phase 1/2.

The What-If MTTR/revenue-delta issue noted earlier is fixed:
`_calculate_duration_minutes` now prefers `actual_downtime_min` (what the
simulation adjusts) over the timestamp delta, and cost reduction was
added alongside it. Verified independently — `run_what_if_simulation`
now returns a real MTTR delta (42.4 → 25.6 min on seed data) and a real
revenue delta (+$7,375), not the `0`s from before.
