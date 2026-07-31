# Novus Studio Copilot — Demo Question Script
**Platform**: ADOS (Autonomous Defect & Orchestration System)
**Document Version**: 2.0
**Status**: Presenter reference, not enforced policy
**Route**: `/novus-studio` → `06 / COPILOT` tab (`frontend-next/src/app/novus-studio/page.tsx`)

---

## 1. Read This Before Demoing

As of Document Version 2.0, governance/policy questions are answered live.
`handleChatSubmit` (`novus-studio/page.tsx`) still special-cases the two
narrative keyword branches in §2 below (they're flavor text about the
specific opening incident, not policy, so they stay scripted for demo
continuity) — but everything else is sent to `POST /copilot/ask`
(`backend/app/routers/copilot.py` → `knowledge/policy_docs_qa.py`), which
retrieves the most relevant sections of `documentation/08`–`12` and, when
an LLM provider is configured (`knowledge/local_llm_client.py` — NVIDIA
NIM/OpenAI/Anthropic/Ollama failover), synthesizes a real cited answer. If
no provider is configured, it falls back to returning the best-matching
policy text directly rather than a dead end — labeled `extractive_fallback`
in the response, never presented as a live answer it isn't.

This script still exists for two reasons:

1. **Verification:** the "Grounded answer" under each §3 question is what
   a presenter should expect the live Copilot to say (in substance — exact
   wording varies call to call). If a live demo response contradicts it,
   that's a real bug to chase, not a documentation gap.
2. **Fallback:** if the LLM provider is briefly unreachable, the presenter
   still has the correct talking point to say out loud while the extractive
   fallback (real policy text, just not prose-synthesized) shows on screen.

## 2. Questions That Hit the Existing Scripted Branches

These will actually change the widget's reply — useful to open a demo with
something that visibly "engages."

### Q: "What happened on Line 2 last night?"
*(matches the `"line 2"` keyword branch)*

**Widget reply (verbatim, scripted):**
> "Line 2 CNC Spindle #04 bore breach is currently isolated. Option B
> (Cartridge replacement) was executed via ServiceNow CHG0048201. MTTR is
> estimated at 39 minutes (-84% vs manual baseline)."

**Grounded elaboration for the presenter:** this is the Workflow 1 scenario
from the Product Design Spec — optical inspection detects a bore tolerance
breach (0.031mm vs 0.020mm spec), `CausalIsolationAgent` isolates CNC
Spindle tool wear + humidity, `ImpactSimulationAgent` ranks resolution
options, and — because estimated cost exceeded the Tier 0 confidence/cost
bar — it held at Tier 1 for Emma's approval. See
[11_Incident_Escalation_Maintenance_Policy.md](11_Incident_Escalation_Maintenance_Policy.md)
§2.

### Q: "What's the spindle status right now?"
*(also matches `"spindle"`)*
Same scripted reply as above.

### Q: "What's the cost impact of this decision?"
*(matches the `"cost"` / `"revenue"` keyword branch)*

**Widget reply (verbatim, scripted):**
> "The current resolution action protects $142,500 in shift revenue at a
> total component cost of $1,250."

**Grounded elaboration:** a $1,250 component cost is well under the
$25,000 low-exposure ceiling — if the deciding agent's confidence was also
>90%, this class of decision is exactly what qualifies for Tier 0
autonomous dispatch. See
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §3.

## 3. Governance & Policy Questions (Answered Live via `/copilot/ask`)

Anything not matching the two §2 branches is sent to the backend and
answered from `documentation/08`–`12`. Expect a few seconds' delay (the
input disables and the button reads "THINKING…" while the LLM call is in
flight — cloud providers can take up to ~90s worst case, per
`knowledge/local_llm_client.py`). The "Grounded answer" below is what the
live response should match in substance, plus a citation back to the
source document.

### Q: "Who can approve a Tier 2 decision?"
**Grounded answer:** Only `executive` or `admin` role users, and only
within their own `approval_limit_usd` — a manager cannot decide Tier 2
regardless of their dollar limit. Auditors can never decide anything, at
any tier. See
[09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md) §3.

### Q: "Why did this decision need approval instead of running automatically?"
**Grounded answer:** Either the estimated cost was ≥ $25,000, the deciding
agent's confidence was ≤ 90%, or the capability itself (e.g. a purchase
order or change request) is classified `high`-risk and is always Tier 2
regardless of cost or confidence. See
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §3.

### Q: "What stops the system from executing a $2M purchase order on its own?"
**Grounded answer:** Two independent facts both force Tier 2: cost is over
the $250,000 high-exposure ceiling, and `CreatePurchaseOrder` is a
`high`-risk capability by itself — either fact alone would already be
enough. See
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §3–4.

### Q: "Can this decision class ever become fully autonomous?"
**Grounded answer:** Only through demonstrated operator trust, not a
manual override — a condition class is promoted to Tier 0 once it has ≥2
historical incidents, ≥80% operator acceptance, and ≥85% average
confidence, and even then it ships with hard safety guardrails (±0.10mm
cap, 3-sigma confirmation, auto-halt after 2 consecutive failed autonomous
adjustments). See
[11_Incident_Escalation_Maintenance_Policy.md](11_Incident_Escalation_Maintenance_Policy.md)
§3.

### Q: "Is this ServiceNow ticket real, or a simulated one?"
**Grounded answer:** Depends on two independent environment flags. A
ticket is only genuinely written to ServiceNow if both
`WO_ITSM_INTEGRATION_ENABLED=true` (connector selectable) *and*
`WO_ITSM_LIVE_WRITES_ENABLED=true` (writes actually authorized) are set —
otherwise the call fails closed with an explicit error rather than
silently no-op'ing. The Autonomy tab's governance panel shows both flags'
live state. See
[10_Integration_Security_Policy.md](10_Integration_Security_Policy.md) §3.

### Q: "What happens if the auditor tries to approve an incident?"
**Grounded answer:** Rejected with `403` before any tier or dollar check
even runs — the auditor role is blocked first, unconditionally. See
[09_RBAC_Approval_Policy.md](09_RBAC_Approval_Policy.md) §3 step 1.

### Q: "What evidence has to exist before any decision — autonomous or approved — can execute?"
**Grounded answer:** Evidence path, agent confidence, causal chain,
alternatives considered, and full audit history. Missing any one of these
blocks the decision back to `Diagnosing`/`Failed` — this check happens
before tier assignment is even relevant, so it applies identically at
Tier 0. See
[08_Governance_Autonomy_Policy.md](08_Governance_Autonomy_Policy.md) §5.

## 4. Suggested Demo Order

1. Open with a §2 question (instant scripted reply) to establish the
   Copilot "feels" live from the first message.
2. Move into 2–3 §3 governance questions and let the real "THINKING…" →
   cited-answer round trip play out on screen — this is the actual
   product capability, not a scripted illusion, and is worth letting the
   audience see happen.
3. Close on the Tier 0 promotion question (§3) — it's the strongest
   "self-learning" story in the product.
4. If asked "is this really reading the documents," it's a fair question
   to answer directly: yes — point at the `(see 0X_...md)` citation in the
   reply, which names the actual source section retrieved for that
   question.
