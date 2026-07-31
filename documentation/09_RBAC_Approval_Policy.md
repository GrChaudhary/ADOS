# Policy: Role-Based Access Control & Approval Authority
**Platform**: ADOS (Autonomous Defect & Orchestration System)
**Document Version**: 1.0
**Status**: Enforced Policy (server-side)
**Owner**: Governance Policy Engine — Layer 5
**Enforcing code**: `backend/app/routers/incidents.py:_authorize_decision`,
`backend/app/rbac.py`, `backend/app/user_store.py`

---

## 1. Purpose

Tier assignment (see
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md)) decides
*whether* a decision needs a human. This policy decides *which* human is
allowed to act on it. Identity is taken from the verified session token —
never from a client-supplied field — and checked against both the
decision's tier and its dollar cost before an approve/reject/escalate call
is allowed to proceed.

## 2. Roles

| Role | Can approve/reject/escalate | Notes |
|---|---|---|
| `auditor` | **Never** | Read-only everywhere. Cannot decide incidents, cannot start incidents. |
| `manager` | Tier 1 only, within their `approval_limit_usd` | Cannot touch Tier 2 decisions regardless of limit. |
| `executive` | Tier 1 and Tier 2, within their `approval_limit_usd` | |
| `admin` | Tier 1 and Tier 2, within their `approval_limit_usd` | Operationally equivalent to `executive` for approval purposes. |

## 3. Authorization Rule (evaluated in order)

1. **Auditor gate.** If `role == auditor`, reject with `403` immediately —
   no further checks matter.
2. **Tier gate.** If the decision is Tier 2 (`EXECUTIVE_APPROVAL`) and the
   acting user's role is not `executive` or `admin`, reject with `403`.
   A `manager` cannot decide a Tier 2 case no matter how small their
   `approval_limit_usd` headroom looks.
3. **Dollar gate.** If the user's `approval_limit_usd` is less than the
   decision's `estimated_cost_usd`, reject with `403`, reporting both
   numbers in the error.

All three checks are server-side. There is no client-side override, and the
approval endpoint re-derives identity from the session on every call — a
user cannot raise their own limit by editing a request body.

## 4. Reference Approval Limits (demo user seed)

These are the seeded accounts used in the current build
(`backend/app/user_store.py`) — illustrative of how limits are assigned per
role, not a claim about production account provisioning.

| User | Role | `approval_limit_usd` |
|---|---|---|
| Emma Vance | manager | $250,000 |
| Marcus Vance | manager | $500,000 |
| Sophia Vance | executive | $5,000,000 |
| Compliance Auditor | auditor | $0 (irrelevant — auditors never reach the dollar gate) |
| System Administrator | admin | $1,000,000,000 |

Note two managers can carry different limits (Emma $250k vs. Marcus $500k)
— `approval_limit_usd` is a per-user field, not a fixed value derived from
role alone. A manager with a low limit can still be blocked from a Tier 1
decision that a higher-limit manager could approve.

## 5. Worked Examples

- **Emma (manager, $250k limit)** on a Tier 1 decision costing $180,000 →
  **allowed**. Tier 1 is within manager authority; $180k ≤ $250k.
- **Emma (manager, $250k limit)** on a Tier 1 decision costing $300,000 →
  **blocked** on the dollar gate, even though her role is otherwise
  permitted at Tier 1.
- **Marcus (manager, $500k limit)** on a Tier 2 decision costing $50,000 →
  **blocked** on the tier gate. Cost is irrelevant once the decision is
  Tier 2 and the role isn't `executive`/`admin`.
- **Sophia (executive, $5M limit)** on a Tier 2 decision costing $2,000,000
  → **allowed**.
- **Compliance Auditor** on any pending decision, any tier, any cost →
  **always blocked** at step 1.

## 6. Auditor Role — Explicit Scope

The auditor account exists to read incident history, decision memory,
governance policy, and integration status for compliance review — every
`GET` surface in the product is available to it. It has zero write
authority: it cannot approve, reject, escalate, or start an incident. This
is enforced at the same authorization function as the manager/executive
gates above, not by hiding UI controls client-side.

## 7. Relationship to Other Policies

- The tier a decision carries is computed by
  [08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) —
  this document only controls *who* may act once a tier is assigned.
- Every approve/reject/escalate action is written to the incident's audit
  history — see
  [10_Integration_Security_Policy.md](10_Integration_Security_Policy.md)
  §4 for the audit trail contract.
