# ADR-0002: IBM Orchestrate as the L4 orchestration kernel

Status: Accepted
Date: 2026-07-22

## Context

L4 needs incident lifecycle management, multi-agent coordination, human
approval workflows, and retry/rollback semantics
([005-decision-orchestrator](../docs/005-decision-orchestrator.md)).
Building this from scratch is a significant, ongoing investment
(durable execution, workflow versioning, approval-step primitives) that
competes for build time against the parts of ADOS that are actually
domain-differentiated (the reasoning stack, the causal model).

## Decision

Use IBM Orchestrate as the L4 orchestration kernel: incident lifecycle,
decision orchestration, multi-agent coordination, preemption, retry/
rollback, and human approval workflow are built on it rather than a
custom-built engine. See the IBM stack mapping in
[001-system-architecture](../docs/001-system-architecture.md#ibm-stack-mapping).

## Consequences

- L4's durable-execution and approval-workflow primitives come largely
  "for free," letting engineering effort focus on the incident state
  machine's domain logic (priority scoring, preemption rules) rather than
  workflow infrastructure.
- Couples L4 to IBM Orchestrate's execution model and operational
  characteristics (versioning, scaling, deployment) — an infrastructure
  dependency the team needs to operate and understand deeply.
- The Decision Orchestrator's *domain* logic (state machine, priority
  score, agent sequencing) is still ADOS-owned code; only the durable-
  execution substrate is external, keeping the coupling at the
  infrastructure layer rather than the business-logic layer.

## Alternatives Considered

- **Custom-built workflow engine.** Rejected for the MVP — the highest
  differentiated value in ADOS is the reasoning/causal model, not workflow
  infrastructure; building a competitive durable-execution engine from
  scratch is a multi-quarter distraction from that.
- **Generic workflow engine (e.g. a plain job queue with manual retry
  logic).** Rejected — lacks the human-approval-step and durable-execution
  primitives the incident lifecycle needs out of the box.
