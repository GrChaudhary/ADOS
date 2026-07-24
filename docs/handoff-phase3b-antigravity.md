# Phase 3B handoff — Antigravity kickoff prompt

Coordination note, not an RFC chapter — same role as
[handoff-phase2-antigravity.md](handoff-phase2-antigravity.md), which
worked cleanly: Phase 1/2 ran in parallel and integrated with zero rework
because both sides built against contracts written down in advance
(`contracts/event_envelope.py`, the agent contract in
[004-agent-framework.md](004-agent-framework.md)). This does the same
thing for Phase 3.

## Why Phase 3 splits into two, and why they can run in parallel

Phase 3 (`docs/000-vision.md` roadmap: "IBM Orchestrate workflows,
ServiceNow connector, SAP connector, Executive Dashboard, Recommendation
Engine") splits along the same seam Phase 1/2 did:

- **3A — Orchestration & Enterprise Execution** (Claude Code): the
  Decision Orchestrator (state machine, priority score, preemption,
  retry/rollback), real governance enforcement, the audit trail, and the
  ServiceNow/SAP connectors. This is "infrastructure/backend/integrations"
  territory, same as Phase 1.
- **3B — Executive Intelligence & Strategic Reasoning** (Antigravity):
  KPI Engine, Recommendation Engine, EDI, Predictive Risk Analytics, NL
  Executive Copilot. This is reasoning-over-data territory, same shape as
  the Phase 2 work already done (Knowledge Graph, Causal Graph, agents).

The dependency that would normally block 3B (it reasons over incident
outcomes, which only exist once 3A's orchestrator is producing them) is
resolved the same way Phase 1/2's was: a new shared contract,
`contracts/incident_record.py` (`IncidentRecord`, `CausalChainEntry`),
defines the audit-trail entry shape *before* either side needs to run.
3A produces these as incidents resolve; 3B can build and test its entire
scope against hand-seeded `IncidentRecord` fixtures — it does not need to
wait for a live orchestrator, exactly as your Phase 2 agents didn't need
to wait for a live backend.

## Scope (Phase 3B — yours)

New module: `executive/` (not pre-allocated in the original layout — see
`executive/README.md`, and consider an ADR the way `adr/0008` recorded
`knowledge/digital_twin.py`'s placement).

1. **KPI Engine** — compute the five KPIs from `docs/008-executive-intelligence.md`'s
   table over a collection of `IncidentRecord`s:
   - MTTR: `resolved_at - detected_at`
   - Revenue Protected: `estimated_cost_usd`/`estimated_downtime_min` vs.
     `actual_cost_usd`/`actual_downtime_min`
   - Supplier Resilience: aggregate by `supplier_id` where present
   - Autonomy Index: share of records with `policy_tier == 0`
   - Recommendation Acceptance: share of `recommendation_accepted == true`
     among non-null (Tier 1/2) records
2. **Recommendation Engine** — cross-incident strategic recommendations
   (e.g. "Supplier X's substitution rate suggests requalification"),
   reasoning over `knowledge/` (Knowledge Graph + Causal Graph) joined
   with `IncidentRecord` history.
3. **EDI (Enterprise Decision Intelligence)** — cross-incident pattern
   analysis; your call on scope for this pass, document what you
   implement vs. defer in `docs/008-executive-intelligence.md`'s Open
   Questions.
4. **Predictive Risk Analytics** — forward-looking risk signals derived
   from Causal Graph condition trends (`knowledge/causal_graph.py` already
   has the weighted condition→outcome model from Phase 2).
5. **NL Executive Copilot** — question-answering scoped to what the KPI
   Engine and audit trail (`IncidentRecord` collection) can actually
   answer. Don't let it free-reason beyond that data — same
   evidence-over-vibes principle as the agent roster's `evidence[]`
   requirement in Phase 2.

For all five: since there's no live orchestrator yet, build and test
against a seed set of `IncidentRecord`s (same spirit as `knowledge/seed_data.py`
from Phase 2 — feel free to add an `executive/seed_data.py` following that
precedent). A `scripts/run_demo_pipeline.py`-style script demonstrating
KPI Engine + Recommendation Engine + Predictive Risk Analytics over the
seed set would mirror how Phase 2 verified itself and is the right bar
here too.

## Contract you must honor

- Read `contracts.IncidentRecord` fields exactly as defined — don't
  reinterpret `policy_tier` (int enum: 0/1/2) or add fields your code
  needs without adding them to `contracts/incident_record.py` first (same
  rule as `contracts/README.md`: shared shapes live in `contracts/`, not
  locally reinvented).
- `recommendation_accepted` is `null` for Tier 0 records (no human
  decision was made) — the Recommendation Acceptance KPI must only
  average over non-null records, not treat null as false.

## Stay out of

- `orchestrate/`, `integrations/` — 3A's territory; assume `IncidentRecord`
  is what it produces, don't build a competing incident state model.
- Don't change `docs/005`, `docs/006`, `docs/007`, `docs/010` without
  flagging it (same rule as Phase 2's handoff) — propose in the relevant
  chapter's Open Questions instead of editing the decision outright.

## Skills

Same install as Phase 2 if not already done:

    npx antigravity-awesome-skills --antigravity

Relevant ones for this scope specifically (verified present in the
installed catalog):

- `@kpi-dashboard-design` — KPI Engine's metric definitions and how
  they'd eventually surface on a dashboard
- `@risk-manager` / `@risk-metrics-calculation` — Predictive Risk
  Analytics
- `@prompt-engineering-patterns` / `@rag-engineer` — NL Executive
  Copilot, scoping its answers to the KPI Engine + audit trail rather
  than open-ended generation
- `@llm-evaluation` — validating the Copilot doesn't answer beyond what
  the data supports
- `@database-architect` — carried over from Phase 2, still relevant for
  how you index/query the `IncidentRecord` collection

## Deliverables for this pass

1. `executive/` — KPI Engine + Recommendation Engine + Predictive Risk
   Analytics + NL Copilot, each with unit tests (mirror
   `tests/test_phase2_integration.py`'s structure — a
   `tests/test_phase3b_integration.py` would be the natural continuation).
2. `executive/seed_data.py` — a set of `IncidentRecord` fixtures covering
   at least: a Tier 0 autonomous resolution, a Tier 1 approved
   recommendation, a Tier 1 rejected/modified recommendation, and one
   record with a `supplier_id` set.
3. A demo script analogous to `scripts/run_demo_pipeline.py` showing all
   four components running over the seed data.
4. Status notes in `docs/008-executive-intelligence.md`'s Open Questions
   for anything this brief didn't pin down (mirrors how you resolved
   `docs/002` and `docs/003`'s open questions in Phase 2).

Ask before changing the `IncidentRecord` shape in a way 3A would need to
react to — same rule that kept Phase 1/2 collision-free.
