# Architecture Decision Records

An ADR captures one specific, hard-to-reverse decision at the point it was
made — context, decision, consequences — frozen once accepted (Backstage's
model). Contrast with [`../docs/`](../docs/), which holds living RFC-style
chapters that get amended as designs evolve.

If a decision changes, write a new ADR that supersedes the old one; don't
edit an accepted ADR's decision in place. Status changes (e.g. Accepted →
Superseded) are the one thing that can be edited.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-six-layer-architecture.md) | Six-layer architecture | Accepted |
| [0002](0002-ibm-orchestrate-as-kernel.md) | IBM Orchestrate as the L4 orchestration kernel | Accepted |
| [0003](0003-capability-based-integration.md) | Capability-based integration abstraction | Accepted |
| [0004](0004-tiered-governance-policy.md) | Tiered governance policy (Tier 0/1/2) | Accepted |
| [0005](0005-decision-memory-as-learning-loop.md) | Decision Memory as a first-class learning store | Accepted |
| [0006](0006-event-driven-backbone.md) | Event-driven backbone over synchronous coupling | Accepted |
| [0007](0007-separate-knowledge-and-causal-graphs.md) | Separate Knowledge Graph and Causal Graph | Accepted |
| [0008](0008-digital-twin-placement.md) | Digital Twin placement under `knowledge/digital_twin.py` | Accepted |
| [0009](0009-executive-intelligence-module.md) | Executive Intelligence module placement under `executive/` | Accepted |

## Template

```markdown
# ADR-NNNN: Title

Status: Proposed | Accepted | Superseded by ADR-XXXX
Date: YYYY-MM-DD

## Context
## Decision
## Consequences
## Alternatives Considered
```
