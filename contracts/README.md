# contracts/

Versioned schema definitions for every event type and capability call —
the payload schemas referenced (not duplicated) by
[`../docs/010-api-contracts.md`](../docs/010-api-contracts.md). This is the
single source of truth both backend code and documentation point at.

Two schema families:

- **Events** — one schema per `eventType` (e.g. `IncidentDetected`,
  `AgentCompleted`, `StateTransitioned`), versioned independently.
- **Capabilities** — one input/output schema pair per capability (e.g.
  `CreatePurchaseOrder`, `ReserveInventory`), consumed by
  [`../integrations/`](../integrations/) connectors and produced by
  [`../orchestrate/`](../orchestrate/).

Relevant chapters: [010-api-contracts](../docs/010-api-contracts.md)
(envelope shape and versioning rule every schema here must follow).

Roadmap: Phase 1.

## Status: implemented as a shared Python package

Built jointly by Phase 1 (backend/integrations) and Phase 2
(agents/knowledge) — both import straight from `contracts` (run with the
ADOS repo root on `PYTHONPATH`, e.g. `pytest`/`uvicorn` from here). Every
model uses `ConfigDict(populate_by_name=True)` with snake_case fields and
camelCase aliases (`incident_id` / `incidentId`), matching the envelope
in [010-api-contracts.md](../docs/010-api-contracts.md).

```
event_envelope.py     EventEnvelope — the event bus envelope (Phase 2-owned)
agent_events.py        AgentCompletedPayload, IncidentDetectedPayload (Phase 2-owned)
capabilities.py         Capability, PolicyTier, CallStatus enums (Phase 1-owned)
capability_call.py      CapabilityCall, CapabilityResponse, GovernanceInfo (Phase 1-owned)
incident_record.py      IncidentRecord, CausalChainEntry — audit-trail entry
                         shape (Phase 3 decoupling contract: orchestrate/
                         produces these, executive/ reasons over them)
incident_state.py       IncidentState — the docs/005 lifecycle state names,
                         shared by orchestrate/'s state machine and
                         IncidentRecord.final_state readers (Phase 1-owned)
```

If you need a new event or capability type, add it here following the
existing alias convention rather than inventing a shape locally — both
phases import from this one package, so a local reinterpretation would
silently diverge.
