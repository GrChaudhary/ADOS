# Policy: Integration Hub Security & Audit
**Platform**: ADOS (Autonomous Defect & Orchestration System)
**Document Version**: 1.0
**Status**: Enforced Policy (server-side gates) + Design Contract
**Owner**: Integration Hub — Layer 6 (Capability Registry) / Layer 5 (Audit)
**Enforcing code**: `integrations/connectors/watsonx_itsm.py`,
`integrations/connectors/sap.py`, `integrations/connectors/marketplace.py`,
`backend/app/routers/governance.py`
**Design record**: `docs/006-integration-hub.md`, `docs/007-governance.md`

---

## 1. Purpose

Orchestration and agent code never talks to a vendor API directly — it
calls an abstract `Capability` (e.g. `CreatePurchaseOrder`) and the
Integration Hub resolves it to a concrete connector. This keeps governance
tier assignment (which is keyed on the capability, not the vendor) stable
even if the underlying system changes, and gives every external write a
single, auditable choke point.

## 2. Capability → Connector Matrix

| Capability | Connector | Target System | Auth |
|---|---|---|---|
| `CreateIncident`, `CreateChangeRequest`, `NotifyOperator` | `watsonx_itsm.py` | IBM watsonx Orchestrate ITSM | IBM IAM OAuth 2.0 |
| `CreatePurchaseOrder`, `ReserveInventory` | `sap.py` | SAP S/4HANA ERP | BAPI / OData REST |
| `QueryExternalStock`, `GetFreightQuote`, `CreateExternalPO` | `marketplace.py` | External B2B Marketplace | REST API |
| `UpdateMES` | `knowledge/digital_twin.py` | Factory MES / PLC | OPC-UA / Modbus |

Cross-reference: risk class per capability is defined in
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §4.

## 3. The Two-Gate Live-Write Pattern (ITSM connector, reference model)

A single "integration enabled" flag is deliberately insufficient for a
connector attached to a capability that can fire *autonomously* — a
`low`-risk capability like `CreateIncident` can execute at Tier 0 with no
human in the loop, so enabling the integration must never, by itself, be
enough to let every qualifying incident silently write a real record.
The ITSM connector enforces two independent gates:

1. **`WO_ITSM_INTEGRATION_ENABLED=true`** — controls whether the connector
   is even *selectable* by the policy engine at all (`is_configured()`).
   Requires `WO_INSTANCE` and `WO_API_KEY` to also be set.
2. **`WO_ITSM_LIVE_WRITES_ENABLED=true`** — the last line of defense,
   checked inside `execute()` before any network call is made. Without it,
   a state-changing call fails closed with an explicit error rather than
   silently no-op'ing or silently writing.

`test_connection()` (a read-only IAM token exchange + `GET
/v1/orchestrate/agents`) is exempt from both gates — reachability checks
never touch either gate because they make no state-changing calls.

This same eligible-vs-live-writes distinction is what the Governance page's
"ITSM live-write gate" panel reports, sourced live from
`GET /governance/policies` → `itsmLiveWriteGate` (`connectorEligible`,
`liveWritesEnabled`) — not a hardcoded illustrative value.

**Policy for any new connector attached to a capability that can reach
Tier 0:** implement the same two-gate pattern. One flag selects the
connector; a second, independently-set flag authorizes it to actually
write.

## 4. Audit Trail Contract

Every capability call resolves to one of three outcomes
(`contracts/capabilities.py:CallStatus`):

- `succeeded`
- `failed`
- `rolled_back`

Every incident's full lifecycle is recorded as an **append-only** trail:
state transitions, the evidence present at each stage, who approved/
rejected/escalated and when (see
[09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md)), and the eventual
outcome as captured in Decision Memory. This is the record:

- Compliance and security review draw on directly (nothing is
  reconstructed after the fact from logs — the trail *is* the record).
- Executive Intelligence draws on for recommendation-acceptance KPIs.
- The Feedback Calibration Agent replays to update Causal Graph edge
  weights (see
  [11_Incident_Escalation_Maintenance_Policy.md](11_Incident_Escalation_Maintenance_Policy.md)
  §3).

## 5. Evidence Requirement Applies Before Any Write

No capability call is dispatched — autonomously or after human approval —
for a decision missing the evidence set required by
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §5
(evidence path, confidence, causal chain, alternatives, audit history).
The Integration Hub is the execution boundary; the evidence gate sits
upstream of it in Layer 5 and is never bypassed by connector configuration.

## 6. What This Policy Does Not Cover

- It does not define how tier is computed — see
  [08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md).
- It does not define who is authorized to approve a held decision — see
  [09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md).
- Per-plant connector credential rotation and secrets management are out of
  scope for this document.
