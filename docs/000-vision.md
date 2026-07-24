---
rfc: 000
title: Vision
status: Accepted
layer: —
related_adrs: [ADR-0001, ADR-0002]
---

## Summary

ADOS (Autonomous Defect & Orchestration System) is an enterprise decision
operating system for manufacturing and supply chains. It closes the loop
between **defect detection** and **production recovery**: it observes a
factory through its existing systems, reasons about root cause and options,
proposes a recommendation with evidence, routes it through the right level of
human approval, and executes it through the enterprise's existing systems of
record.

## Motivation

In most plants today, the gap between "a defect is detected" and "production
is recovered" is dominated by human coordination overhead: someone has to
notice the anomaly, pull data from three or four disconnected systems (MES,
ERP, PLM, supplier portals), figure out what changed, decide what to do about
it, and then manually operate half a dozen enterprise tools to make it
happen. That coordination tax, not the underlying diagnosis, is usually the
largest component of Mean Time To Recovery (MTTR).

ADOS is built to compress that gap without removing the human from decisions
that deserve one.

### Core principle

> AI decides **what** should happen. Enterprise integrations decide **how**
> it happens.

Reasoning and integration execution are kept as separate concerns on purpose
— see [001-system-architecture](001-system-architecture.md). This is what
lets ADOS swap its reasoning stack or its connector stack independently, and
is why the Integration Hub speaks in capabilities ("reserve inventory") never
in vendor APIs ("call this SAP BAPI").

## Goals

- Reduce the time between defect detection and a *recoverable* production
  state, not just the time to raise a ticket.
- Make every autonomous or human-approved action explainable: evidence,
  confidence, causal chain, and alternatives considered must be attached to
  the decision, not reconstructed after the fact.
- Keep humans in control of consequential actions via tiered approval
  ([007-governance](007-governance.md)), while allowing genuinely low-risk,
  high-confidence actions to execute autonomously.
- Integrate with the enterprise systems a plant already runs (SAP, Oracle
  ERP, ServiceNow, Maximo, MES/PLC/OPC-UA feeds) without hard-coding to any
  one of them.
- Get better over time: every incident's evidence, decision, and outcome
  feed back into the system's causal model
  ([003-causal-graph](003-causal-graph.md)).

## Non-Goals

- ADOS does not replace MES, ERP, or PLM systems — it orchestrates and
  reasons across them.
- ADOS does not aim for full autonomy on day one. Tier 0 (autonomous)
  actions are earned through demonstrated confidence, not assumed.
- ADOS is not a generic BPM/workflow product; its state machine and
  reasoning are specialized for defect-to-recovery decisions.

## Design

### The decision loop

Every incident, from detection to learning, moves through the same loop:

```
Observe → Understand → Reason → Generate Options → Simulate →
Reserve Resources → Recommend → Approve → Execute → Measure Outcome → Learn
```

This loop is the spine of the system. Each stage maps to a layer in
[001-system-architecture](001-system-architecture.md): perception feeds
Observe/Understand, the reasoning agents drive Reason/Generate
Options/Simulate, global planning handles Reserve Resources, the
orchestrator drives Recommend/Approve/Execute, and Decision Memory captures
Measure Outcome/Learn.

### Illustrative flow (defect → recovery)

1. A Vision Agent detects a defect on the line.
2. A CAD & Spec Comparison Agent validates it against a tolerance
   specification.
3. A Causal Isolation Agent performs root-cause analysis using the causal
   graph.
4. The Knowledge Graph identifies affected products and approved
   alternatives.
5. A Substitution Agent proposes compliant alternative parts or suppliers.
6. An Impact Simulation Agent evaluates cost, delay, and quality risk for
   each option.
7. The Global Planner soft-reserves the inventory and production capacity
   an option would need.
8. The Decision Orchestrator assembles a ranked recommendation with
   evidence.
9. A human approves (or the policy tier allows autonomous execution).
10. The Integration Hub invokes the necessary enterprise systems (e.g.
    ServiceNow, SAP) through capabilities, not direct API calls.
11. The audit trail and Decision Memory are updated with the outcome.
12. The Executive Intelligence dashboard reflects the business impact.

This flow is the acceptance test for the architecture: every layer in
[001-system-architecture](001-system-architecture.md) exists because one of
these twelve steps needs it.

### Roadmap

| Phase | Scope |
|-------|-------|
| 1 | Monorepo, FastAPI backend, event bus, contracts, Integration Hub, auth |
| 2 | Knowledge Graph, Causal Graph, Digital Twin, Agent SDK |
| 3 | Orchestration workflows, ServiceNow connector, SAP connector, Executive Dashboard, Recommendation Engine |
| 4 | Decision Memory, learning engine, marketplace connectors, autonomous optimization |

### Guiding principles

- Event-driven architecture
- Human-in-the-loop by default, autonomy earned per policy tier
- Explainable AI — every decision carries evidence
- Enterprise-first security ([009-security](009-security.md))
- Capability-driven integrations, not point-to-point connectors
- Vendor-neutral execution
- Modular microservices
- Decision-centric AI — the unit of value is a *decision*, not a dashboard

## Alternatives Considered

- **A generic BPM/RPA platform configured for this use case.** Rejected:
  RPA optimizes for replaying fixed steps, not for reasoning under
  uncertainty with explainable, ranked alternatives.
- **A recommendation-only tool with no execution path.** Rejected: leaves
  the coordination tax — manually operating SAP/ServiceNow/MES — exactly
  where it is today, which is the actual bottleneck.
- **Full autonomy from day one.** Rejected: unacceptable risk in a
  manufacturing safety context; see the tiered model in
  [007-governance](007-governance.md).

## Open Questions

- What confidence/impact thresholds justify promoting an action from Tier 1
  to Tier 0 for a given plant, and who owns that decision?
- How much of the MVP demo flow above should be hard-coded for the
  hackathon demo versus driven by the real Knowledge/Causal graphs?

## References

- [`../Blueprints/ADOS_Enterprise_Architecture_Blueprint.md`](../Blueprints/ADOS_Enterprise_Architecture_Blueprint.md)
- [001-system-architecture](001-system-architecture.md)
- [007-governance](007-governance.md)
