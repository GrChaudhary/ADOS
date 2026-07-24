# ADR-0003: Capability-based integration abstraction

Status: Accepted
Date: 2026-07-22

## Context

ADOS must execute actions against enterprise systems that vary by
customer/plant (SAP vs. Oracle ERP, ServiceNow vs. Maximo) and change over
a multi-year deployment. If orchestration or agent code called vendor APIs
directly, every vendor swap would require touching reasoning/orchestration
code, and there would be no single point to apply governance rules
(budget, region, compliance, least privilege) across every vendor
uniformly.

## Decision

The Integration Hub exposes abstract **capabilities** (Create Purchase
Order, Reserve Inventory, Notify Operator, ...) as the only interface L4/
L5/L6 code against. A Connector Policy Engine resolves each capability to
a concrete connector at execution time and enforces governance rules
during that resolution. See
[006-integration-hub](../docs/006-integration-hub.md).

## Consequences

- Adding or swapping an enterprise system is a new/changed connector
  implementation; orchestration and agent code never change.
- Governance rules are enforced once, centrally, per capability call —
  not reimplemented per connector.
- Adds an indirection layer (capability → policy resolution → connector)
  that must be understood when debugging why a given action executed
  through a particular system.

## Alternatives Considered

- **Direct point-to-point connectors called from orchestration/agent
  code.** Rejected — couples reasoning/orchestration to vendor APIs and
  removes the single governance enforcement point; violates the core
  principle in [000-vision](../docs/000-vision.md) that AI decides *what*,
  integrations decide *how*.
