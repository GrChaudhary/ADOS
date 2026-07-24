---
rfc: 011
title: UI/UX
status: Draft
layer: L6
related_adrs: []
---

## Summary

ADOS has two distinct user surfaces with different jobs: an **approval
surface**, where a Tier 1/2 approver decides whether a specific
recommendation executes, and the **Executive Intelligence Dashboard**,
where an executive reads aggregate system performance. Both are built
around the same principle: explainability is a UI requirement, not a
backend implementation detail that gets summarized away.

## Motivation

[007-governance](007-governance.md) requires every decision to carry
evidence, confidence, causal chain, and alternatives. That requirement is
pointless if the UI presents an approver with a bare "Approve / Reject"
button and a one-line summary — the human-in-the-loop control the whole
system is built around only works if the human can actually evaluate what
they're approving in the time they realistically have.

## Goals

- An approver can see evidence, confidence, causal chain, and alternatives
  for a decision without leaving the approval screen.
- Approval latency is visible and tracked — a slow approval surface
  directly worsens MTTR, which is the system's headline KPI
  ([008-executive-intelligence](008-executive-intelligence.md)).
- The Executive Dashboard's KPIs are traceable back to the incidents that
  produced them — no number without a drill-down.

## Non-Goals

- This chapter does not specify visual design system details (component
  library, theming) — those live in [`../frontend/README.md`](../frontend/README.md).

## Design

### Approval surface

Surfaces one incident at a time (or a prioritized queue, ordered by the
same priority score the orchestrator uses —
[005-decision-orchestrator](005-decision-orchestrator.md)):

- Recommendation and the capability it would invoke
- Confidence score, decomposed by contributing agent
  ([004-agent-framework](004-agent-framework.md))
- Causal chain with evidence path
  ([003-causal-graph](003-causal-graph.md))
- Ranked alternatives that were not recommended, and why
- One-click Approve / Reject / Escalate, each of which is itself an
  audited action ([007-governance](007-governance.md))

### Executive Intelligence Dashboard

- KPI tiles (MTTR, Revenue Protected, Supplier Resilience, Autonomy Index,
  Recommendation Acceptance) per [008-executive-intelligence](008-executive-intelligence.md),
  each drillable to the underlying incidents
- Plant benchmarking views
- What-if simulation entry point
- Natural-language copilot for ad hoc questions, scoped to what the KPI
  engine and audit trail can answer

### Incident timeline view

A shared component (used by both surfaces) rendering an incident's full
state-machine history ([005-decision-orchestrator](005-decision-orchestrator.md))
as a timeline — this is the UI expression of the event log's
replayability, and it's what makes an audit review or a post-incident
retro tractable without reading raw logs.

## Alternatives Considered

- **Summarized approval cards with evidence available only on click-through
  to a separate detail page.** Rejected for the primary flow — adds
  friction to the highest-frequency human action in the system; detail
  click-through is fine for the *dashboard*, not for approvals, where
  speed and MTTR are directly coupled.

## Open Questions

- Does the approval surface need mobile support for the MVP, given
  approvers may not be at a workstation when a Tier 1 incident fires?

## References

- [007-governance](007-governance.md)
- [008-executive-intelligence](008-executive-intelligence.md)
- [005-decision-orchestrator](005-decision-orchestrator.md)
- [`../frontend/README.md`](../frontend/README.md)
