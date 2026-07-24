---
rfc: 008
title: Executive Intelligence
status: Accepted
layer: L6
related_adrs: [ADR-0009]
---

## Summary

L6 turns the operational state L4/L5 produce into strategic visibility:
recommendations, forecasts, business impact, plant benchmarking, what-if
simulation, and a KPI engine — surfaced through the Executive Intelligence
Dashboard and a natural-language copilot.

## Motivation

Individual incident resolutions are an operational concern; whether ADOS is
*working* — reducing MTTR, protecting revenue, being trusted enough that
recommendations get accepted — is an executive concern that has to be
answered in aggregate, across incidents and across plants. L6 exists so
that answer doesn't require manually mining the audit trail.

## Goals

- Aggregate incident outcomes into KPIs executives actually track.
- Support what-if simulation ("if we approved this class of Tier 1
  decisions autonomously, what would the impact have been?") using real
  historical incident data.
- Provide plant-to-plant benchmarking on the same metrics.
- Offer a natural-language interface for ad hoc executive questions,
  scoped to what the audit trail and KPI engine can actually answer.

## Non-Goals

- L6 does not make or approve operational decisions — it reports on them.
  Any action an executive takes as a result of an L6 recommendation flows
  back through the normal decision loop and governance tiers.

## Design

### Components

- **Executive Intelligence Dashboard** — the primary surface; see
  [011-ui-ux](011-ui-ux.md).
- **Recommendation Engine** — surfaces strategic (not per-incident)
  recommendations, e.g. "Supplier X's substitution rate suggests
  requalification."
- **Enterprise Decision Intelligence (EDI)** — cross-incident pattern
  analysis over Decision Memory.
- **Predictive Risk Analytics** — forward-looking risk signals derived from
  the Causal Graph's condition trends ([003-causal-graph](003-causal-graph.md)).
- **Natural Language Executive Copilot** — question-answering over the KPI
  engine and audit trail.
- **KPI Engine** — computes: MTTR, Revenue Protected, Supplier Resilience,
  Autonomy Index, Recommendation Acceptance.

### KPI definitions (initial)

| KPI | Derived from |
|---|---|
| MTTR | Incident `Detected` → `Resolved` timestamps ([005-decision-orchestrator](005-decision-orchestrator.md)) |
| Revenue Protected | Impact Simulation Agent's cost/delay estimates vs. actual outcome |
| Supplier Resilience | Substitution Agent success rate per supplier over time |
| Autonomy Index | Share of resolved incidents executed at Tier 0 vs. Tier 1/2 |
| Recommendation Acceptance | Approved vs. rejected/modified recommendations at Tier 1/2 |

### Outputs

Executive recommendations, forecasts, business impact analysis, plant
benchmarking, what-if simulations — all read-only projections over L4/L5
state; L6 has no write path back into the incident state machine.

## Alternatives Considered

- **Generic BI tool pointed at the audit trail.** Rejected for the MVP —
  loses the domain-specific KPI definitions and the natural-language
  copilot's need to reason about causal chains and confidence, not just
  aggregate numbers. Worth revisiting for ad hoc analyst access alongside
  L6, not instead of it.

## Open Questions & Phase 3B Resolution

- **What-If Simulation Scope:**
  *Phase 3B Resolution*: What-If Simulation operates on `IncidentRecord` audit trail collections in `executive/kpi_engine.py`, re-computing KPI deltas (MTTR reduction, protected revenue, autonomy index shift) when simulating promoting specific decision categories to Tier 0 autonomy.
- **Enterprise Decision Intelligence (EDI):**
  *Phase 3B Resolution*: Implemented in `executive/edi.py`, analyzing defect category distributions, root cause frequencies, cost variance, and plant-level benchmarking across incident records.

## References

- [007-governance](007-governance.md) — audit trail as KPI source
- [011-ui-ux](011-ui-ux.md)
- [000-vision](000-vision.md)
