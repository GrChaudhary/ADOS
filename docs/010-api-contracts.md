---
rfc: 010
title: API & Event Contracts
status: Draft
layer: cross-cutting
related_adrs: [ADR-0003, ADR-0006]
---

## Summary

Every cross-layer interaction in ADOS happens through one of two contract
types: **events** on the bus (L1→L2, agent completion, state transitions)
or **capability calls** (L4→Integration Hub). This chapter defines the
envelope both share and the versioning rule that keeps layers independently
deployable.

## Motivation

[001-system-architecture](001-system-architecture.md) promises that a
layer can be replaced without its neighbors noticing, as long as the
contract holds. That promise is only real if the contracts are written
down and versioned somewhere other than "whatever the current code
happens to send." This chapter is that source of truth; per-domain payload
schemas belong in [`../contracts/`](../contracts/), not here.

## Goals

- One envelope shape for every event and every capability call, so
  tooling (logging, replay, audit) doesn't need special cases per domain.
- Backward-compatible evolution: adding a field never breaks an existing
  consumer.
- A capability's contract is stable even when the connector fulfilling it
  changes ([006-integration-hub](006-integration-hub.md)).

## Non-Goals

- This chapter does not enumerate every event/capability schema — those
  live as versioned schema files in [`../contracts/`](../contracts/) and
  are referenced, not duplicated, here.

## Design

### Event envelope

```json
{
  "eventId": "uuid",
  "eventType": "IncidentDetected | AgentCompleted | StateTransitioned | ...",
  "incidentId": "uuid",
  "occurredAt": "ISO-8601",
  "producedBy": "layer/service identifier",
  "schemaVersion": "semver",
  "payload": { "...": "domain-specific, defined in contracts/" }
}
```

- `incidentId` is present on every event from `Detected` onward, which is
  what makes an incident's full history reconstructable purely from the
  event log — the mechanism [005-decision-orchestrator](005-decision-orchestrator.md)
  relies on for replay and audit.
- `schemaVersion` is per-`eventType`, not global — bumping one event's
  schema doesn't force a coordinated redeploy of unrelated consumers.

### Capability call contract

```json
{
  "capability": "ReserveInventory | CreatePurchaseOrder | ...",
  "requestId": "uuid",
  "incidentId": "uuid",
  "requestedBy": "orchestrator | agent id",
  "schemaVersion": "semver",
  "input": { "...": "capability-specific, defined in contracts/" },
  "governance": { "policyTier": "0 | 1 | 2", "approvedBy": "identity | null" }
}
```

- `governance` is mandatory on every capability call — the Integration Hub
  ([006-integration-hub](006-integration-hub.md)) rejects a call missing
  tier/approval information rather than assuming Tier 0.
- The response carries a `status` (`succeeded | failed | rolled_back`) and,
  on failure, whether a compensating action already ran (see
  [005-decision-orchestrator](005-decision-orchestrator.md#retry--rollback)).

### Versioning rule

Additive changes (new optional field) never bump `schemaVersion`'s major
component. Breaking changes (removed/renamed field, changed semantics) bump
major and require the producer to support both versions for a deprecation
window — the same discipline Kubernetes API versioning uses, applied here
at event/capability granularity instead of whole-API granularity.

### Where payload schemas live

`contracts/` holds the actual schema definitions (event payloads,
capability input/output types) as the single source both backend code and
this documentation reference — see [`../contracts/README.md`](../contracts/README.md).

## Alternatives Considered

- **Synchronous REST calls between all layers instead of an event bus for
  L1-L4 interactions.** Rejected — breaks replayability and the
  preemption/retry model in
  [005-decision-orchestrator](005-decision-orchestrator.md), which depends
  on stages being resumable, not just callable.
- **Schema-per-service with no shared envelope.** Rejected — makes
  cross-cutting tooling (audit trail construction, incident replay) need
  per-service special-casing instead of one envelope parser.

## Open Questions

- ~~Kafka vs. a managed event bus for the MVP~~ **Decided 2026-08-04,
  revised same day** — real Apache Kafka (KRaft mode) is now a supported
  `EVENT_BUS_BACKEND=kafka` option (`backend/app/eventbus/kafka_bus.py`),
  adopted ahead of the original evaluation's "wait for domain-pod
  decoupling" trigger, by explicit choice. Default stays `memory` for a
  fresh clone/test run. See
  [`../infrastructure/EVENT_BUS_COMPARISON.md`](../infrastructure/EVENT_BUS_COMPARISON.md)
  for both the original reasoning and the reversal note at the top of that
  file.

## References

- [001-system-architecture](001-system-architecture.md)
- [005-decision-orchestrator](005-decision-orchestrator.md)
- [006-integration-hub](006-integration-hub.md)
- [`../contracts/README.md`](../contracts/README.md)
