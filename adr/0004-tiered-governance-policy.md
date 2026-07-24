# ADR-0004: Tiered governance policy (Tier 0/1/2)

Status: Accepted
Date: 2026-07-22

## Context

ADOS's value proposition depends on reducing the human coordination tax in
incident resolution, but manufacturing actions carry real safety and
financial risk. A policy that always requires human approval defeats the
purpose; a policy that always executes autonomously is unacceptable risk.
Confidence score alone is also not a sufficient gating signal — a
high-confidence recommendation to place a large purchase order and a
high-confidence recommendation to notify an operator do not carry the same
risk even at identical confidence.

## Decision

Adopt a three-tier policy model: Tier 0 (Autonomous), Tier 1 (Approval
Required), Tier 2 (Executive Approval). Tier assignment is a function of
confidence, impact class (safety/cost/customer), and the specific
capability being invoked — not confidence alone. See
[007-governance](../docs/007-governance.md).

## Consequences

- Low-risk, high-confidence actions can execute without human latency in
  the loop, directly improving MTTR.
- High-impact actions always route through human judgment regardless of
  how confident the system is, bounding the blast radius of a
  miscalibrated model.
- Requires an explicit, maintained mapping from capability × impact class
  to tier — this is policy data that has to be owned and kept current
  (open question in [007-governance](../docs/007-governance.md)), not a
  one-time setup.

## Alternatives Considered

- **Uniform "always require approval."** Rejected — negates the system's
  core purpose.
- **Confidence-only autonomy gating.** Rejected — ignores impact class;
  see [009-security](../docs/009-security.md#autonomous-action-containment)
  for why capability allow-listing, not confidence alone, bounds Tier 0
  risk.
