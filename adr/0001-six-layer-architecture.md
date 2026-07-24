# ADR-0001: Six-layer architecture

Status: Accepted
Date: 2026-07-22

## Context

ADOS has to support exploratory, retry-heavy AI reasoning (root cause
analysis, option generation) and reliable, auditable enterprise execution
(purchase orders, maintenance tickets) in the same system. These two
concerns want different properties: reasoning wants to iterate and be
allowed to be uncertain; execution needs to be deterministic, governed, and
replayable.

## Decision

Organize the system into six logical layers — L1 Perception & Ingestion,
L2 Knowledge & Reasoning, L3 Global Planning, L4 Orchestration & Control,
L5 Governance, L6 Executive Intelligence — each with a single
responsibility, communicating only through events and typed contracts
(never shared internal state). See
[001-system-architecture](../docs/001-system-architecture.md).

## Consequences

- The boundary between "allowed to be non-deterministic" (L2) and "must be
  deterministic and governed" (L4 downward) is architectural, not a
  convention teams have to remember.
- Any layer can be replaced independently as long as its contract holds
  (e.g. swap the reasoning stack without touching governance or
  execution).
- Adds cross-layer communication overhead (events, contracts) compared to
  direct in-process calls — accepted as the cost of the isolation
  guarantee.

## Alternatives Considered

- **Flat microservice mesh** — no natural place to enforce the
  determinism/governance boundary; rejected.
- **Monolith with internal module boundaries** — layers need to scale and
  fail independently, and a monolith obscures the IBM Orchestrate/ADK
  integration seams; rejected.
