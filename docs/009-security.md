---
rfc: 009
title: Security
status: Draft
layer: cross-cutting
related_adrs: [ADR-0003, ADR-0004]
---

## Summary

Security in ADOS is enforced at the same two chokepoints governance already
uses: the orchestrator's approval gate ([007-governance](007-governance.md))
for *what* is allowed to happen, and the Integration Hub's Connector Policy
Engine ([006-integration-hub](006-integration-hub.md)) for *how* it's
carried out and with what credentials. This chapter defines the
cross-cutting posture — identity, secrets, network, and data — that both
of those depend on.

## Motivation

ADOS sits between plant floor systems (PLC, OPC-UA, vision systems) and
enterprise systems of record (SAP, ERP, ServiceNow) with the ability to
initiate real-world actions (purchase orders, maintenance tickets,
production changes). That combination — OT-adjacent ingestion plus
enterprise write access plus autonomous execution at Tier 0 — is exactly
the profile that needs an explicit, reviewed security posture rather than
one that accretes connector by connector.

## Goals

- Every enterprise action ADOS takes is attributable to a specific
  incident, decision, and (for Tier 1/2) approver.
  ([007-governance](007-governance.md) already requires this for
  explainability; security requires it independently for accountability.)
- No connector holds long-lived credentials; all secrets are brokered.
- Least-privilege scoping per capability, not per connector — a connector
  that *can* create purchase orders and schedule maintenance should not
  hold both privileges for every call.
- L1 ingestion from OT systems (PLC, OPC-UA) is one-directional by default;
  write-back to OT requires the same governance gate as any other action.

## Non-Goals

- This chapter does not specify a full threat model or penetration-test
  plan — that belongs in a dedicated security review once the MVP
  connectors are chosen.
- Physical/OT network segmentation is a plant IT concern; ADOS's
  responsibility ends at the L1 ingestion boundary.

## Design

### Identity and access

- Human approvers ([007-governance](007-governance.md)) authenticate
  through the enterprise identity provider; approval actions are recorded
  against that identity in the audit trail, not a shared service account.
- Service-to-service calls between layers (L1→L2, L4→L5, L4→Integration
  Hub) are authenticated and scoped per [010-api-contracts](010-api-contracts.md);
  no layer accepts unauthenticated internal traffic.

### Secrets

Owned by the Integration Hub's Secrets Manager
([006-integration-hub](006-integration-hub.md)): OAuth2 tokens, API keys,
and Vault-backed secrets are brokered per-call to connectors, never
embedded in connector configuration or agent code.

### Least privilege, capability-scoped

The Connector Policy Engine enforces least privilege at the *capability*
level (Create Purchase Order vs. Schedule Maintenance), not just at the
connector level, so a compromised or misbehaving capability request can't
be laundered through a connector's broader credential scope.

### Data classification

- **Plant telemetry (L1)** — operational data, retained per Decision
  Memory's incident-replay needs, not indefinitely.
- **Enterprise master data (products, suppliers, cost)** — sourced from
  and remaining authoritative in PLM/ERP; the Knowledge Graph
  ([002-knowledge-graph](002-knowledge-graph.md)) holds a derived,
  re-buildable copy, not the system of record.
- **Audit trail** — append-only, tamper-evident, retained per compliance
  requirement; this is the record regulators or internal audit would
  request after an autonomous Tier 0 action.

### Autonomous action containment

Tier 0 (autonomous) actions are the highest-risk security surface because
no human reviews them before execution. They are scoped to capabilities
explicitly allow-listed for autonomy by the Policy Engine
([007-governance](007-governance.md)), not simply "high confidence" —
confidence is necessary but not sufficient for a capability to be eligible
for Tier 0 at all.

## Alternatives Considered

- **Per-connector credentials held by each connector.** Rejected — no
  central revocation point, no capability-level least privilege; see
  Secrets Manager design in
  [006-integration-hub](006-integration-hub.md).
- **Confidence-threshold-only gating for autonomy (no capability
  allow-list).** Rejected — a novel high-confidence action on a capability
  never reviewed for autonomy risk is exactly the failure mode this
  section exists to prevent.

## Open Questions

- What's the retention policy for raw L1 vision/camera data versus derived
  structured events — full retention is likely both costly and
  unnecessary once an incident is resolved.
- Does the MVP need a formal OT/IT network segmentation review before any
  live PLC/OPC-UA connector goes beyond a demo environment?

## References

- [006-integration-hub](006-integration-hub.md) — Secrets Manager,
  Connector Policy Engine
- [007-governance](007-governance.md) — policy tiers, audit trail
- [010-api-contracts](010-api-contracts.md) — service-to-service auth
