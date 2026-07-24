# ADR-0007: Separate Knowledge Graph and Causal Graph

Status: Accepted
Date: 2026-07-22

## Context

L2 needs two different kinds of relational reasoning: "what is connected
to what" (products, parts, suppliers, approved substitutes — relatively
stable, sourced from PLM/ERP change events) and "what causes what" (defect
conditions and outcomes, weighted by evidence, continuously recalibrated
from incident outcomes). These have different write paths, different
update cadences, and different consistency requirements.

## Decision

Maintain the Enterprise Knowledge Graph and the Causal Graph as two
distinct L2 stores, cross-referenced by entity ID rather than merged into
one graph. See [002-knowledge-graph](../docs/002-knowledge-graph.md) and
[003-causal-graph](../docs/003-causal-graph.md).

## Consequences

- Each store can be updated on its natural cadence — Knowledge Graph from
  PLM/ERP change events, Causal Graph from the Feedback & Calibration
  Agent's recalibration cycle — without one write path's consistency
  requirements constraining the other.
- Agents that only need entity relationships (e.g. Substitution Agent)
  don't pay the cost of querying a graph also carrying continuously
  shifting causal weights, and vice versa for the Causal Isolation Agent.
- Requires agents that need both (e.g. Impact Simulation Agent joining
  causal likelihood with substitution cost) to query and join across two
  stores rather than one.

## Alternatives Considered

- **Single unified graph combining entities and causal weights.**
  Rejected — couples two write paths with materially different update
  cadences and consistency needs; see Context.
