# agents/

The L2 reasoning agent roster, each implementing the common agent contract:
Vision & Spec Agent, Causal Isolation Agent, CAD & Spec Comparison Agent,
Substitution Agent, Parameter Adjustment Agent, Impact Simulation Agent,
Re-routing Agent, Feedback & Calibration Agent. Built on IBM ADK.

Every agent here reads/writes the stores in [`../knowledge/`](../knowledge/)
and emits completion events consumed by
[`../orchestrate/`](../orchestrate/) — agents never call each other
directly.

Relevant chapters: [004-agent-framework](../docs/004-agent-framework.md)
(the contract every agent here must implement),
[002-knowledge-graph](../docs/002-knowledge-graph.md),
[003-causal-graph](../docs/003-causal-graph.md).

Roadmap: Phase 2 (Agent SDK).
