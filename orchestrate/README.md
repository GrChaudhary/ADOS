# orchestrate/

L4 Orchestration & Control: the incident state machine, the Decision
Orchestrator's agent-sequencing logic, priority scoring, preemption, and
retry/rollback, built on IBM Orchestrate.

Governance's approval-gate integration ([`../docs/007-governance.md`](../docs/007-governance.md))
lives at the boundary of this module — the `AwaitingApproval` state here
calls out to governance, it doesn't implement policy evaluation itself.

Relevant chapters: [005-decision-orchestrator](../docs/005-decision-orchestrator.md)
(state machine, priority score, retry/rollback — the design this module
implements), [001-system-architecture](../docs/001-system-architecture.md).

Roadmap: Phase 3 (orchestration workflows).

## Status: Phase 3A running

```
state_machine.py   IncidentStateMachine — enforces docs/005's transition graph
priority.py        compute_priority_score() — safety-weighted MVP scoring
preemption.py       PreemptionEngine — one occupant per line_id, signals
                     the lower-priority occupant's preempt_event on bump
governance.py        assign_policy_tier() (financial exposure x confidence
                     x capability risk class — never Tier 0 for high-risk/
                     "critical" capabilities or exposure over $250k
                     regardless of confidence; documentation/05_Product_Bible.md's
                     dollar-threshold matrix) + ApprovalQueue (Tier 1/2
                     human-in-the-loop, backend/app/routers/incidents.py)
agent_runner.py       bridges to the Phase 2 agent roster (agents/) —
                     publishes StageRequested + the agent's AgentCompleted
                     to the event bus per stage (see module docstring for
                     the MVP fidelity note on what "event-driven" means here)
audit_trail.py        append-only IncidentRecord store
orchestrator.py        DecisionOrchestrator — ties all of the above into
                     the full Detected -> ... -> Resolved/Failed/Preempted
                     lifecycle
```

Run the standalone demo (mirrors `scripts/run_demo_pipeline.py`'s style,
but through the real orchestrator instead of a hand-scripted agent
sequence):

```bash
../.venv/bin/python ../scripts/run_orchestrator_demo.py
```

Or via the API — see `backend/README.md`'s incident lifecycle endpoints
(`POST /incidents`, `GET /approvals`, `POST /incidents/{id}/approve`).

**Capability mapping** is option-aware (`orchestrator.py`'s
`_capability_for_option`): parameter adjustment → `ScheduleMaintenance`;
substitution → `ReserveInventory` if the Substitution Agent found stock,
else `CreatePurchaseOrder`. Still simplified — see that method's
docstring for what's left (re-routing → `CreateChangeRequest`, quantity-
aware stock checks).

**Preemption is checked between state-machine states**, not mid-agent-call
— matches the state diagram's actual branch points (`Diagnosing`/
`CandidateGeneration`/`Reserving` → `Preempted`), not a compromise. A
bumped incident **auto-resumes**: it waits on `PreemptionEngine.wait_for_line_free()`
and restarts diagnosis from scratch under the *same* `incident_id` (not a
new incident), up to `max_resume_attempts` (default 5) before settling as
Preempted for good. Verified end-to-end in
`../tests/test_orchestrate.py::test_preempted_incident_auto_resumes_under_same_incident_id`
— a low-priority incident genuinely gets bumped, waits, and resolves once
the line frees.

**Still open**:
- Governance's dollar-threshold bands (`governance.py`'s
  `_LOW_EXPOSURE_MAX_USD`/`_HIGH_EXPOSURE_MIN_USD`) and the
  `CAPABILITY_RISK_CLASS` -> "critical" mapping are a starting policy, not
  a tuned one — same open question docs/007-governance.md already flags.

## Local ADK setup — live and activated

The IBM watsonx Orchestrate ADK is installed at the project root (`../.venv`,
`../requirements.txt`) since it's shared with `../agents/`:

```bash
source ../.venv/bin/activate
orchestrate --version

cp ../.env.example ../.env   # fill in WO_INSTANCE / WO_API_KEY, then:
orchestrate env add -n dev -u "$WO_INSTANCE"
orchestrate env activate dev --api-key "$WO_API_KEY"   # non-interactive
```

`.env` is gitignored — see [../.env.example](../.env.example) and
[../docs/009-security.md](../docs/009-security.md).

**Registered on the live instance** (`watsonx_tools.py` — a standalone,
stdlib-only file since the ADK packages it independently onto IBM's
infra):

```bash
orchestrate tools import -k python -f orchestrate/watsonx_tools.py
orchestrate agents create --name ados_executive_copilot --kind native \
  --provider watsonx --llm "groq/openai/gpt-oss-120b" \
  --tools get_ados_executive_kpis --tools get_ados_pending_approvals \
  --instructions "..." --output orchestrate/ados_executive_copilot.agent.yaml
```

`get_ados_executive_kpis`/`get_ados_pending_approvals` call a running ADOS
backend over HTTP (`ADOS_BACKEND_URL`, `ADOS_SERVICE_TOKEN` env vars on
the Orchestrate side — default to `http://localhost:8000`). Confirmed
live: `orchestrate tools list` / `orchestrate agents list` show both
registered against the real `br-sao` instance.

See `integrations/connectors/watsonx_itsm.py` for a *separate* effort —
routing `CreateIncident`/`ScheduleMaintenance`/etc. capability calls
through a watsonx Orchestrate ITSM agent endpoint. That one is **not**
verified against a live instance and requires its own explicit opt-in
(`WO_ITSM_INTEGRATION_ENABLED=true`) precisely because `WO_INSTANCE`/
`WO_API_KEY` alone (used above for the ADK CLI) aren't sufficient
evidence that endpoint is real.
