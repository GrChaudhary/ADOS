# Policy: Governance & Autonomy Tiers
**Platform**: ADOS (Autonomous Defect & Orchestration System)
**Document Version**: 1.0
**Status**: Enforced Policy (server-side, non-overridable by caller)
**Owner**: Governance Policy Engine — Layer 5
**Enforcing code**: `orchestrate/governance.py:assign_policy_tier`
**Design record**: `docs/007-governance.md`, `adr/0004-tiered-governance-policy.md`

---

## 1. Purpose

Every capability call the Decision Orchestrator wants to dispatch — dispatch
a purchase order, schedule maintenance, notify an operator — is evaluated
against this policy before it executes. The tier is **computed server-side**
from the capability's risk class, the deciding agent's confidence, and the
decision's estimated financial exposure. It is never accepted from the
caller. This makes the human-oversight trade-off an explicit, auditable
policy instead of an implicit property of whichever agent produced the
recommendation.

## 2. The Three Tiers

| Tier | Name | Behavior |
|---|---|---|
| **0** | Autonomous | Executes immediately, no human in the loop |
| **1** | Approval Required | Blocks in `AwaitingApproval` until a `manager`, `executive`, or `admin` acts |
| **2** | Executive Approval | Blocks until an `executive` or `admin` acts |

## 3. Tier Assignment Rule

Evaluated in this order, per `assign_policy_tier`:

1. **Critical capability, always Tier 2.** If the capability's risk class is
   `high` — today that's `CreateChangeRequest`, `CreatePurchaseOrder`,
   `CreateExternalPO` — it is Tier 2 **regardless of cost or confidence**.
   An unrecognized capability fails safe into this same bucket.
2. **High financial exposure, always Tier 2.** Estimated cost
   **> $250,000** is Tier 2 regardless of confidence.
3. **Low exposure + high confidence, Tier 0.** Estimated cost
   **< $25,000** *and* agent confidence **> 90%** clears autonomously.
4. **Everything else is Tier 1.** This includes the entire
   $25,000–$250,000 band at any confidence level — that band never reaches
   Tier 0 in this policy.

```
Estimated Cost          Confidence     Capability Risk    → Tier
─────────────────────────────────────────────────────────────────
< $25,000                > 90%          low / medium       → 0  (Autonomous)
< $25,000                ≤ 90%          low / medium       → 1  (Approval)
$25,000 – $250,000       any            low / medium       → 1  (Approval)
> $250,000                any            any                 → 2  (Executive)
any                      any            high (critical)     → 2  (Executive)
```

> **Known drift, called out deliberately, not hidden:** an earlier internal
> reference (the Product Bible's "Governance Autonomy Tier Matrix") describes
> the medium ($25k–$250k) band as reachable at Tier 0 with >80% confidence.
> The enforced code does not implement that — that band is always Tier 1.
> Treat `orchestrate/governance.py` as the source of truth for what actually
> gates execution; narrative docs describe intent and are not always current.

## 4. Capability Risk Classes (current registry)

| Capability | Risk Class | Connector |
|---|---|---|
| `NotifyOperator` | low | watsonx Orchestrate ITSM |
| `CreateIncident` | low | watsonx Orchestrate ITSM |
| `QueryExternalStock` | low | External B2B Marketplace |
| `GetFreightQuote` | low | External B2B Marketplace |
| `UpdateMES` | medium | Factory MES / PLC |
| `ScheduleMaintenance` | medium | Factory MES / PLC |
| `ReserveInventory` | medium | SAP S/4HANA ERP |
| `CreateChangeRequest` | **high** | watsonx Orchestrate ITSM |
| `CreatePurchaseOrder` | **high** | SAP S/4HANA ERP |
| `CreateExternalPO` | **high** | External B2B Marketplace |

A capability's risk class can be promoted downward (e.g. `high` → `medium`)
only through the Tier 0 promotion workflow in
[11_Incident_Escalation_Maintenance_Policy.md](11_Incident_Escalation_Maintenance_Policy.md)
— never by editing a single decision's governance field.

## 5. Required Evidence Before Any Tier Evaluation

Per `docs/007-governance.md`, Layer 5 rejects (routes back to `Diagnosing`
or `Failed`) any decision missing:

- **Evidence path** — the concrete Knowledge/Causal Graph nodes and source
  events the decision rests on
- **Confidence** — the score from the agents that produced the decision
- **Causal chain** — from the Causal Isolation Agent
- **Alternative options** — the options considered and why they ranked lower
- **Audit history** — every state transition the incident has been through

Incomplete evidence is a hard block — a decision is never approved (or
auto-executed) on partial reasoning, at any tier.

## 6. Why Not Simpler Policies

- **"Always require human approval"** was rejected — it defeats the
  product's core value of cutting MTTR from hours to minutes.
- **"Confidence-only gating, no tiers"** was rejected — impact class
  matters independently of confidence. A 95%-confidence recommendation to
  spend $400,000 still warrants a human signature; a 95%-confidence
  recommendation to notify an operator does not.

## 7. Open Question (unresolved, tracked in `docs/007-governance.md`)

Who owns tier-threshold tuning per plant in production: a central
governance team, or plant-local admins operating within guardrails? Not yet
decided — do not represent this policy's thresholds as globally fixed
forever.
