---
rfc: 004
title: Agent Framework
status: Draft
layer: L2
related_adrs: [ADR-0001]
---

## Summary

L2's reasoning is done by a roster of single-purpose agents, each
implementing a common contract, coordinated by the Decision Orchestrator
(L4) but built and run on IBM ADK. No agent calls another agent directly;
they communicate by reading/writing L2 knowledge stores and by emitting
events the orchestrator sequences.

## Motivation

A single "do everything" reasoning agent is hard to evaluate, hard to give
partial autonomy to (per [007-governance](007-governance.md) policy tiers
you may trust substitution suggestions more than causal diagnosis), and
hard to swap out piecewise as models improve. Splitting reasoning into
single-purpose agents with a common contract lets each one be tested,
scored, and governed independently.

## Goals

- A uniform agent contract so the orchestrator can sequence any agent the
  same way, regardless of what's inside it.
- Independent testability and independent confidence scoring per agent.
- Clear ownership: each agent reads/writes specific L2 stores and nothing
  else.

## Non-Goals

- This chapter does not define the orchestration state machine itself —
  see [005-decision-orchestrator](005-decision-orchestrator.md).
- It does not mandate a specific model per agent; agents are swappable
  implementations behind the contract.

## Design

### Agent roster

| Stage | Agent | Reads | Writes |
|---|---|---|---|
| Perception | Vision & Spec Agent | camera/vision streams | structured defect events |
| Reasoning | Causal Isolation Agent | Causal Graph | candidate root causes |
| Reasoning | CAD & Spec Comparison Agent | CAD/PLM Semantic Index | tolerance violation findings |
| Candidate Generation | Substitution Agent | Knowledge Graph | candidate substitutions |
| Candidate Generation | Parameter Adjustment Agent | Knowledge Graph, Digital Twin | candidate parameter changes |
| Evaluation | Impact Simulation Agent | Cost & Supply Graph, L3 Global Planning | ranked options w/ cost, delay, quality risk |
| Execution | Re-routing Agent | L3 reservation state | execution requests to L4 |
| Learning | Feedback & Calibration Agent | Decision Memory | updated causal weights |
| Control | Decision Orchestrator | all of the above | incident state (L4) |

### Agent contract

Every agent implements the same shape, regardless of stage:

```
Agent {
  input: IncidentContext + StageInput
  output: StageOutput { result, confidence, evidence[], alternatives[] }
  emits: AgentCompletedEvent(stage, output) on the event bus
}
```

- `confidence` is mandatory and feeds directly into
  [007-governance](007-governance.md) policy-tier routing.
- `evidence[]` must reference concrete Knowledge/Causal Graph nodes or
  source events, not free-text justification — this is what makes the
  eventual decision explainable rather than merely plausible-sounding.
- `alternatives[]` captures options the agent considered and rejected, not
  just its top pick, because [007-governance](007-governance.md) requires
  alternatives on every decision.

### Coordination model

Agents do not call each other. The Decision Orchestrator (L4) sequences
stages by publishing a `StageRequested` event and consuming the matching
`AgentCompletedEvent`; see
[005-decision-orchestrator](005-decision-orchestrator.md#multi-agent-coordination).
This keeps every inter-agent handoff visible on the event bus, which is
what makes the incident replayable and auditable end to end.

### IBM ADK boundary

Agents are implemented and run on IBM ADK; ADOS's own code treats an agent
as the contract above and nothing more. This is what lets the reasoning
stack evolve (new models, new ADK versions) without changes to L4/L5/L6.

## Alternatives Considered

- **One monolithic reasoning agent.** Rejected — see Motivation; kills
  independent testability, confidence scoring, and per-capability policy
  tiers.
- **Direct agent-to-agent calls.** Rejected — makes the incident
  non-replayable from the event log and bypasses the orchestrator's
  preemption/retry control, described in
  [005-decision-orchestrator](005-decision-orchestrator.md).

## Open Questions

- Should Impact Simulation Agent's output format be standardized enough
  that L6's what-if simulation ([008-executive-intelligence](008-executive-intelligence.md))
  can reuse it directly, or does executive-level simulation need a coarser
  model?

## References

- [002-knowledge-graph](002-knowledge-graph.md), [003-causal-graph](003-causal-graph.md)
- [005-decision-orchestrator](005-decision-orchestrator.md)
- [../agents/README.md](../agents/README.md)
