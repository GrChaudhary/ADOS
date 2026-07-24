# ADOS Documentation

This directory is the design record for the Autonomous Defect & Orchestration
System (ADOS). It follows the same split used by Kubernetes, Temporal, and
Backstage:

- **`docs/NNN-*.md`** — RFC-style chapters. Each one is a complete design for
  a subsystem: motivation, goals/non-goals, detailed design, alternatives
  considered, open questions. These are living documents — amend them as the
  system evolves (like Kubernetes KEPs or Temporal's `proposals` repo).
- **[`../adr/`](../adr/)** — Architecture Decision Records. Each ADR captures
  one specific, hard-to-reverse decision at the moment it was made, and is
  frozen once accepted (like Backstage's ADRs). If a decision changes, a new
  ADR supersedes the old one rather than editing it in place.

Read order for newcomers: `000` → `001`, then whichever subsystem chapter is
relevant to the work at hand. `000` and `001` are the only two chapters
everyone touching the codebase is expected to have read.

## Chapters

| # | Title | Layer |
|---|-------|-------|
| [000](000-vision.md) | Vision | — |
| [001](001-system-architecture.md) | System Architecture | L1–L6 |
| [002](002-knowledge-graph.md) | Knowledge Graph | L2 |
| [003](003-causal-graph.md) | Causal Graph | L2 |
| [004](004-agent-framework.md) | Agent Framework | L2 |
| [005](005-decision-orchestrator.md) | Decision Orchestrator | L4 |
| [006](006-integration-hub.md) | Integration Hub | L4 |
| [007](007-governance.md) | Governance | L5 |
| [008](008-executive-intelligence.md) | Executive Intelligence | L6 |
| [009](009-security.md) | Security | cross-cutting |
| [010](010-api-contracts.md) | API & Event Contracts | cross-cutting |
| [011](011-ui-ux.md) | UI/UX | L6 |

[`diagrams/`](diagrams/) holds the Mermaid sources rendered inline in these
chapters.

[`handoff-phase2-antigravity.md`](handoff-phase2-antigravity.md) and
[`handoff-phase3b-antigravity.md`](handoff-phase3b-antigravity.md) are
working coordination docs (not RFCs) — kickoff prompts for running
Antigravity's half of a phase in parallel with Claude Code's.

## Chapter template

```markdown
---
rfc: NNN
title: ...
status: Draft | Accepted | Superseded
layer: L#
related_adrs: [ADR-000x]
---

## Summary
## Motivation
## Goals
## Non-Goals
## Design
## Alternatives Considered
## Open Questions
## References
```

## Source

These chapters formalize and expand
[`../Blueprints/ADOS_Enterprise_Architecture_Blueprint.md`](../Blueprints/ADOS_Enterprise_Architecture_Blueprint.md),
which remains the single-page executive summary of the system.
