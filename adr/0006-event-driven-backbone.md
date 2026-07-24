# ADR-0006: Event-driven backbone over synchronous coupling

Status: Accepted
Date: 2026-07-22

## Context

The Decision Orchestrator needs to preempt in-flight incidents when a
higher-priority one competes for the same resource, and every incident
needs to be replayable end-to-end for audit
([005-decision-orchestrator](../docs/005-decision-orchestrator.md),
[007-governance](../docs/007-governance.md)). Synchronous, direct calls
between layers/agents make both of those hard: an in-flight synchronous
call chain can't be cleanly abandoned mid-flight, and a call chain that
isn't logged as discrete messages can't be replayed from a log.

## Decision

L1→L2 ingestion, L2 agent coordination, and L4 state transitions are
event-driven: producers publish to the bus, consumers react, and the
orchestrator sequences stages by publishing `StageRequested` and consuming
`AgentCompletedEvent` rather than calling agents synchronously. See
[001-system-architecture](../docs/001-system-architecture.md) and
[010-api-contracts](../docs/010-api-contracts.md#event-envelope).

## Consequences

- An incident's full history is reconstructable from the event log alone,
  which is what makes audit and preemption/resume
  ([005-decision-orchestrator](../docs/005-decision-orchestrator.md))
  tractable.
- Adds eventual-consistency and message-ordering considerations that a
  synchronous call chain wouldn't have — contracts must be explicit about
  `incidentId` correlation ([010-api-contracts](../docs/010-api-contracts.md)).
- Requires event bus infrastructure to be operated as a critical-path
  dependency (see [`../infrastructure/README.md`](../infrastructure/README.md)).

## Alternatives Considered

- **Synchronous REST calls between all layers.** Rejected — breaks
  replayability and preemption; see Context.
- **Choreography with no central orchestrator sequencing stages.**
  Rejected — see
  [005-decision-orchestrator](../docs/005-decision-orchestrator.md#alternatives-considered);
  no single place to compute cross-incident priority or guarantee an
  approval gate is never skipped.
