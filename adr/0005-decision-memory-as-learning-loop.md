# ADR-0005: Decision Memory as a first-class learning store

Status: Accepted
Date: 2026-07-22

## Context

Without recording what was decided and what actually happened, the Causal
Graph's weights ([003-causal-graph](../docs/003-causal-graph.md)) can only
ever reflect initial domain priors, and ADOS has no way to demonstrate
improving diagnostic accuracy over time — an explicit goal in
[000-vision](../docs/000-vision.md).

## Decision

Treat Decision Memory as a first-class L2 knowledge store, not a
side-effect log: every incident's evidence, decision, and outcome are
recorded, and a dedicated Feedback & Calibration Agent periodically
replays these records to update Causal Graph weights. See
[003-causal-graph](../docs/003-causal-graph.md#calibration-loop) and
[004-agent-framework](../docs/004-agent-framework.md).

## Consequences

- The Causal Graph improves from real outcomes instead of staying fixed at
  initial priors, and that improvement is measurable (feeds the Autonomy
  Index / diagnostic-accuracy KPIs in
  [008-executive-intelligence](../docs/008-executive-intelligence.md)).
- Decision Memory becomes a system of record that must be retained and
  queryable long after an incident resolves — a data retention
  responsibility, not just an operational log
  ([009-security](../docs/009-security.md#data-classification)).
- Requires a defined minimum-evidence threshold before recalibration acts
  on a record, to avoid overfitting to a small number of incidents (open
  question in [003-causal-graph](../docs/003-causal-graph.md)).

## Alternatives Considered

- **No persistent decision/outcome record; causal weights fixed from
  domain priors only.** Rejected — the system could never demonstrate or
  achieve improving accuracy, undermining the case for expanding Tier 0
  autonomy over time.
