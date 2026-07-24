---
rfc: 007
title: Governance
status: Draft
layer: L5
related_adrs: [ADR-0004]
---

## Summary

L5 is the layer that decides *whether* a decision the Decision Orchestrator
has assembled is allowed to execute, and at what level of human oversight.
Every decision — autonomous or approved — carries evidence, a confidence
score, a causal chain, alternatives considered, and an audit history.
Approval routing follows a three-tier policy model.

## Motivation

Manufacturing actions have safety and financial consequences, and blanket
"always ask a human" defeats the purpose of automation while "always act
autonomously" is unacceptable risk. Governance exists to make that
trade-off an explicit, auditable policy rather than an implicit property of
whichever agent happened to produce the recommendation.

## Goals

- A deterministic mapping from decision risk/confidence to required
  approval level.
- Every decision is explainable *before* it executes, not reconstructable
  only after an incident review.
- A complete, immutable audit trail for every decision, approved or not.

## Non-Goals

- Governance does not generate decisions or evidence — it evaluates and
  gates what L2/L4 already produced.
- It does not define *how* an approved action is carried out — that's the
  Integration Hub ([006-integration-hub](006-integration-hub.md)).

## Design

### Policy tiers

| Tier | Name | Behavior |
|---|---|---|
| 0 | Autonomous | Executes without human approval |
| 1 | Approval Required | Blocks in `AwaitingApproval` for a designated approver |
| 2 | Executive Approval | Blocks for approval at an executive/escalated level |

Tier assignment is a function of the decision's confidence score, impact
class (safety, cost, customer), and the capability being invoked — a
high-confidence "Notify Operator" and a high-confidence "Create Purchase
Order over $50k" do not belong in the same tier even with identical
confidence.

### Required decision evidence

Every decision the orchestrator submits to L5, regardless of tier, must
carry:

- **Evidence path** — the concrete Knowledge/Causal Graph nodes and source
  events the decision rests on
- **Confidence** — from the agents that produced it
  ([004-agent-framework](004-agent-framework.md))
- **Causal chain** — from the Causal Isolation Agent
  ([003-causal-graph](003-causal-graph.md))
- **Alternative options** — options considered and why they ranked lower
- **Audit history** — every state transition the incident has been through

L5 rejects (returns to `Diagnosing` or `Failed`) any decision missing a
required field rather than approving on incomplete evidence.

### Policy engine

Evaluates tier assignment and, for Tier 1/2, resolves the correct approver
(role- and capability-specific) and routes the approval request to
[011-ui-ux](011-ui-ux.md). Policy rules are data, not code, so tier
thresholds can be tuned per plant/capability without a deployment.

### Explainability and confidence scoring

Confidence scoring is not a single opaque number: it decomposes into the
per-agent confidence from L2 ([004-agent-framework](004-agent-framework.md))
plus the causal weight backing the diagnosis
([003-causal-graph](003-causal-graph.md)), so an approver (or an auditor,
after the fact) can see which part of the reasoning chain was weakest.

### Audit trail

Append-only record of every incident's full lifecycle: state transitions,
evidence at each stage, who approved what and when, and the eventual
outcome as recorded in Decision Memory
([003-causal-graph](003-causal-graph.md#calibration-loop)). This is the
record referenced by [009-security](009-security.md) for compliance and by
[008-executive-intelligence](008-executive-intelligence.md) for
recommendation-acceptance KPIs.

## Alternatives Considered

- **Uniform "always require approval" policy.** Rejected — defeats the
  system's core value proposition of reducing MTTR; see
  [000-vision](000-vision.md).
- **Confidence-only gating with no explicit tiers.** Rejected — impact
  class matters independent of confidence (a highly confident but
  high-cost action still warrants human sign-off); see
  [ADR-0004](../adr/0004-tiered-governance-policy.md).

## Open Questions

- Who owns tier-threshold tuning per plant in production — a central
  governance team, or plant-local admins within guardrails?

## References

- [000-vision](000-vision.md)
- [004-agent-framework](004-agent-framework.md), [003-causal-graph](003-causal-graph.md)
- [005-decision-orchestrator](005-decision-orchestrator.md) — `AwaitingApproval` state
- [008-executive-intelligence](008-executive-intelligence.md) — Recommendation Acceptance KPI
- [ADR-0004](../adr/0004-tiered-governance-policy.md)
