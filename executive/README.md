# executive/

L6 Executive Intelligence: KPI Engine, Recommendation Engine, EDI
(Enterprise Decision Intelligence), Predictive Risk Analytics, and the
Natural Language Executive Copilot.

See [ADR-0009](../adr/0009-executive-intelligence-module.md) for the architectural decision recording this module's placement.

Reads from (never writes to) `contracts.IncidentRecord` — the audit-trail
entries `orchestrate/` (Phase 3A, built in parallel) produces. Also reads
`knowledge/` (Knowledge Graph, Causal Graph) for recommendation reasoning
and predictive risk signals.

Relevant chapters: [008-executive-intelligence](../docs/008-executive-intelligence.md)
(the design this module implements), [007-governance](../docs/007-governance.md)
(audit trail as KPI source), [003-causal-graph](../docs/003-causal-graph.md)
(condition trends for Predictive Risk Analytics).

Roadmap: Phase 3.
