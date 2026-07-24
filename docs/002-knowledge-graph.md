---
rfc: 002
title: Knowledge Graph
status: Accepted
layer: L2
related_adrs: [ADR-0007]
---

## Summary

The Enterprise Knowledge Graph is the entity/relationship backbone of L2: it
answers "what is connected to what" (products, parts, suppliers,
specifications, facilities) so that reasoning agents can find affected
products and approved alternatives without querying five source systems
directly. It is one of five knowledge stores in L2 and is deliberately kept
separate from the Causal Graph ([003-causal-graph](003-causal-graph.md)),
which answers "what causes what."

## Motivation

Steps 3–5 of the MVP demo flow (root-cause analysis, discovering affected
products/approved alternatives, proposing substitutions) all require
traversing relationships that live natively in PLM, ERP, and supplier
systems but are never colocated. Querying those systems live, per incident,
is both slow and fragile. The Knowledge Graph is a materialized,
incident-time-fast view over those relationships.

## Goals

- Answer "what products/lines are affected by defect X" and "what
  approved substitutes exist for part Y" in milliseconds, not by fanning
  out to source systems.
- Stay consistent with source-of-truth systems (PLM, ERP, MES) via
  event-driven sync, not batch ETL that goes stale for hours.
- Be queryable by reasoning agents (Substitution Agent, CAD & Spec
  Comparison Agent) through a stable contract, independent of which graph
  database backs it.

## Non-Goals

- The Knowledge Graph does not model causality or temporal defect
  propagation — that is the Causal Graph's job.
- It is not the system of record for any entity it stores; PLM/ERP/MES
  remain authoritative, and the graph is rebuilt from them.

## Design

### Entity model (representative, not exhaustive)

- **Product** — SKU, revision, associated specifications
- **Part** — part number, tolerance spec, approved suppliers
- **Supplier** — capacity, region, qualification status, lead time
- **Facility** — plant, line, cell
- **Specification** — CAD/PLM tolerance and material requirements
- **Substitution** — approved part-to-part or supplier-to-supplier
  equivalences, with the conditions under which they're valid

### Relationships

```
Product --uses--> Part --sourcedFrom--> Supplier
Part --governedBy--> Specification
Part --approvedSubstitute--> Part
Facility --produces--> Product
```

### Population

Populated incrementally from L1 structured events (PLM change events, ERP
master-data events, supplier qualification events) via the event bus, not
batch jobs — this keeps "approved substitutes" current, which is the field
the Substitution Agent depends on most.

### Query surface

Reasoning agents query through a typed capability, not raw graph query
language, so the underlying store (e.g. a property graph DB) can change
without touching agent code:

- `findAffectedProducts(defectSpec) -> [Product]`
- `findApprovedSubstitutes(part) -> [Part]`
- `getSpecification(part) -> Specification`

### Relationship to other L2 stores

- **CAD/PLM Semantic Index** feeds Specification nodes and geometric
  tolerance data into the graph; it is the source, the graph is the
  queryable projection.
- **Cost & Supply Graph** is joined at query time with Knowledge Graph
  substitution candidates to produce cost-ranked options for the Impact
  Simulation Agent.
- **Decision Memory** references Knowledge Graph entity IDs in its incident
  records so past decisions can be replayed against the *current* graph
  state.

## Alternatives Considered

- **Query source systems live per incident.** Rejected — latency and
  availability risk on the decision-critical path; PLM/ERP systems are not
  built for this query pattern.
- **Single unified graph combining knowledge + causality.** Rejected — see
  [003-causal-graph](003-causal-graph.md) and
  [ADR-0007](../adr/0007-separate-knowledge-and-causal-graphs.md); the two
  have different update cadences and different consistency requirements.

## Open Questions & Phase 2 Resolution

- **Which graph database backs the MVP?**
  *Phase 2 Resolution*: The Knowledge Graph MVP is implemented via Pydantic entity models and an in-memory indexed graph store (`knowledge/knowledge_graph.py`) exposing typed python capabilities (`findAffectedProducts`, `findApprovedSubstitutes`, `getSpecification`). The capability interface decouples agents completely from the underlying storage mechanism.

## References

- [000-vision](000-vision.md) — demo flow steps 3–5
- [003-causal-graph](003-causal-graph.md)
- [004-agent-framework](004-agent-framework.md)
- [ADR-0007](../adr/0007-separate-knowledge-and-causal-graphs.md)
