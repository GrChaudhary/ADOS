# Policy: Incident Lifecycle, Escalation & Tier 0 Promotion
**Platform**: ADOS (Autonomous Defect & Orchestration System)
**Document Version**: 1.0
**Status**: Enforced Policy + Design Contract
**Owner**: Decision Orchestrator (L4) / Governance Policy Engine (L5)
**Enforcing code**: `executive/autonomy_optimizer.py:AutonomyPolicyOptimizer`
**Design record**: `docs/005-decision-orchestrator.md`, `docs/007-governance.md`

---

## 1. Purpose

Defines how a plant-floor incident moves from detection to resolution, when
it escalates to a human, and — separately — the policy for promoting a
recurring, low-risk decision class from Tier 1 (approval-required) to Tier
0 (autonomous) based on operator behavior, not a one-time judgment call.

## 2. Incident Lifecycle

```
Telemetry Alert → Multi-Agent Diagnosis → Governance Check → 
   (Tier 0: dispatch immediately) 
   (Tier 1/2: hold in AwaitingApproval → human decides → dispatch)
→ Resolution → Decision Memory
```

1. **Detection.** A telemetry or optical-inspection alert (e.g. a bore
   diameter tolerance breach) triggers diagnosis.
2. **Multi-agent diagnosis.** `VisionSpecAgent` and `CADSpecAgent` extract
   and align the defect; `CausalIsolationAgent` queries the Causal Graph
   for root cause; `ImpactSimulationAgent` produces ranked resolution
   options.
3. **Governance check.** The assembled decision is evaluated against
   [08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md).
   Missing evidence blocks here — see that document §5.
4. **Hold or dispatch.** Tier 0 dispatches immediately. Tier 1/2 holds in
   `AwaitingApproval`, visible in the incident workspace, until a user
   authorized per
   [09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md) approves,
   rejects, or escalates it.
5. **Resolution & audit.** The outcome, whoever decided it, and the full
   evidence trail are written to Decision Memory (see
   [10_Integration_Security_Policy.md](10_Integration_Security_Policy.md)
   §4).

## 3. Tier 0 Promotion Policy (Self-Learning Loop)

Rather than manually re-classifying a capability's risk, ADOS evaluates
historical Decision Memory to find recurring decision *classes* (grouped by
root-cause condition) that have earned autonomy through demonstrated
operator trust. This is evaluated by
`AutonomyPolicyOptimizer.evaluate_promotion_candidates`.

### 3.1 Eligibility thresholds

A condition class is eligible for Tier 0 promotion when **all** of the
following hold across its historical Tier 1 decisions:

| Criterion | Threshold |
|---|---|
| Sample volume | ≥ 2 incidents |
| Operator acceptance rate | ≥ 80% |
| Average agent confidence | ≥ 85% |

Sample volume only counts non-autonomous (Tier 1/2) historical records for
that condition — a class already running at Tier 0 is not re-evaluated
against itself.

### 3.2 Worked examples (matches live Autonomy tab behavior)

- **95.0% acceptance across 20 incidents, avg. confidence 0.89** → eligible.
  All three thresholds cleared with margin.
- **50% acceptance, avg. confidence 0.92** → **not eligible**, despite high
  confidence — acceptance rate is the binding constraint at 50% < 80%.
  High model confidence does not substitute for operator trust.
- **85% acceptance, avg. confidence 0.85, but only 1 historical sample** →
  **not eligible** — sample volume (1) is below the minimum of 2 regardless
  of the other two numbers.

### 3.3 Mandatory safety guardrails on promotion

Promoting a class to Tier 0 does not remove safety bounds — it removes the
*human-wait*, not the *limits*. Every promoted class ships with:

- Parameter adjustments capped at **±0.10mm** nominal offset.
- Requires **3-sigma confidence confirmation** from the Vision & Spec
  Agents before the autonomous action triggers.
- **Automatic line halt** if 2 consecutive autonomous adjustments fail to
  clear the defect — autonomy is revoked in-line, not just flagged for
  later review.

## 4. Escalation

Any pending Tier 1/2 decision can be escalated (not just approved or
rejected) by an authorized user per
[09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md). Escalation is
recorded in the audit trail identically to an approve/reject action —
there is no silent escalation path.

## 5. Relationship to Other Policies

- Tier computation itself:
  [08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md).
- Who may act on a held decision:
  [09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md).
- Where the dispatched action actually lands:
  [10_Integration_Security_Policy.md](10_Integration_Security_Policy.md).
