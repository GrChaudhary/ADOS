---
rfc: 006
title: Integration Hub
status: Draft
layer: L4
related_adrs: [ADR-0003, ADR-0006]
---

## Summary

The Integration Hub is how ADOS acts on the enterprise without being
written against any specific enterprise system. It exposes abstract
**capabilities** ("Reserve Inventory", "Create Change Request") to the rest
of ADOS; a Connector Policy Engine resolves each capability to a concrete
connector (SAP, ServiceNow, Maximo, ...) at execution time, subject to
governance rules.

## Motivation

Plants run different ERP/ITSM/MES stacks, and the same plant's stack
changes over a multi-year deployment. If the Decision Orchestrator or any
agent called `ServiceNowClient.createIncident()` directly, every one of
those integrations would need to be re-touched on every vendor swap, and
governance would have no single point to apply budget/regional/compliance
rules across vendors. The Integration Hub exists so "what needs to happen"
(decided in L2/L4) stays decoupled from "which system does it" (resolved
in the Hub), matching the core principle in
[000-vision](000-vision.md).

## Goals

- A stable capability contract that L4/L5/L6 code against, independent of
  which connector fulfills it.
- Centralized policy enforcement (budget thresholds, regional
  restrictions, compliance, approval routing, preferred systems, least
  privilege) applied uniformly across every connector.
- Adding a new enterprise system is a new connector implementation, not a
  change to orchestration or agent code.

## Non-Goals

- The Hub does not decide *whether* an action should happen — that's
  [007-governance](007-governance.md) and the orchestrator's approval gate.
  The Hub only decides *how* an already-approved action is carried out.

## Design

### Components

**Capability Registry** — the abstract action catalog: Create Purchase
Order, Create Incident, Reserve Inventory, Notify Operator, Update MES,
Create Change Request, Schedule Maintenance. Each capability defines a
typed input/output contract (see [010-api-contracts](010-api-contracts.md)),
independent of any vendor's API shape.

**Connector Manager** — owns the set of live connectors: SAP, Oracle ERP,
ServiceNow, Jira Service Management, IBM Maximo, Teams, Slack, MQTT, Kafka,
OPC-UA, REST, GraphQL. Each connector implements one or more capabilities.

**Connector Policy Engine** — resolves a capability request to a specific
connector and validates the call against governance rules before
execution:

- Budget thresholds
- Regional restrictions
- Compliance
- Approval routing
- Preferred systems
- Least privilege

**Secrets Manager** — OAuth2, API keys, Vault integration; connectors never
hold long-lived credentials themselves.

**API Gateway** — the boundary for external API access into ADOS.

### Example resolution

```
Need: Create Maintenance Ticket
  → Capability Registry (resolves capability contract)
  → Connector Policy Engine (selects connector, validates permissions & governance)
  → ServiceNow Connector
  → Execute
```

If policy routes maintenance tickets to Maximo instead of ServiceNow for a
given plant/region, only the Connector Policy Engine's routing rule
changes — nothing upstream is touched.

### Relationship to governance

Every capability invocation the Hub executes was already cleared by
[007-governance](007-governance.md)'s policy tiers at the orchestrator
level; the Connector Policy Engine's checks (budget, region, least
privilege) are a second, execution-time layer of the same governance
posture, not a duplicate approval step.

## Alternatives Considered

- **Direct point-to-point connectors called from orchestration/agent
  code.** Rejected — see Motivation; couples reasoning/orchestration code
  to vendor APIs and gives governance no single enforcement point. See
  [ADR-0003](../adr/0003-capability-based-integration.md).
- **iPaaS/generic integration platform (e.g. off-the-shelf ESB) instead of
  a purpose-built Hub.** Rejected for the MVP — generic iPaaS tools don't
  natively understand ADOS's capability/policy-tier model; revisit if
  connector count grows beyond what's maintainable in-house.

## Open Questions

- Does the Connector Policy Engine need per-tenant (per-plant) policy
  overrides in the MVP, or is a single global policy set sufficient for
  the demo?

## References

- [000-vision](000-vision.md) — core principle
- [005-decision-orchestrator](005-decision-orchestrator.md)
- [007-governance](007-governance.md)
- [010-api-contracts](010-api-contracts.md)
- [ADR-0003](../adr/0003-capability-based-integration.md)
- [../integrations/README.md](../integrations/README.md)
