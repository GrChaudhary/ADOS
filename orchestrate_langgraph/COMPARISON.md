# LangGraph vs. Custom Orchestrator — Comparison

Head-to-head evaluation of ADOS's hand-rolled orchestration engine
(`orchestrate/orchestrator.py` + `agents/*.py`) against a LangGraph
reimplementation of a representative slice, run for the first time as
ADOS moves from hackathon project to product. Every number below comes
from code in this directory — nothing here is an unverified assertion.

## Scope & Methodology

**In scope (4 stages, both engines):** `vision_spec` → `causal_isolation`
→ governance/approval gate → mocked capability execution → terminal
Resolved/Failed. Both engines reuse the exact same, unmodified agent
classes (`agents/vision_spec_agent.py`'s `VisionSpecAgent`,
`agents/causal_isolation_agent.py`'s `CausalIsolationAgent`) and the exact
same `orchestrate/governance.py`'s `assign_policy_tier()` — the comparison
isolates the orchestration framework, not reimplemented business logic.
Capability execution uses `integrations.connectors.console.ConsoleConnector`
only, never real ServiceNow/SAP.

**Canonical scenario** (`scenario_defaults.py`, same as
`scripts/run_orchestrator_demo.py` / `tests/test_orchestrate.py`):
`plant_id="FAC-P04-L2"`, `line_id="Line 2"`, `part_number="MH-8820"`,
`vision_data={"measured_bore_diameter_mm": 45.085}`. Measured, not assumed:
`CausalIsolationAgent` returns **confidence 0.84** for this input (rule-based
fallback path — LLM disabled by default in this environment), which
`assign_policy_tier(SCHEDULE_MAINTENANCE, 0.84, $350)` resolves to
**`APPROVAL_REQUIRED`** — the same tier the full 8-stage pipeline lands on
for this scenario, so the slice genuinely exercises the approval-gate
mechanism on both sides rather than trivially skipping it.

**Out of scope:** `CandidateGeneration`/`Reserving` (Substitution,
Parameter-Adjustment, Impact-Simulation agents), `feedback_calibration`,
and preemption. Since CandidateGeneration/Reserving are skipped, the
governance gate needs a capability + cost figure from somewhere —
`scenario_defaults.py` reuses the real number the full pipeline already
computes for MH-8820 (`agents/impact_simulation_agent.py`'s
`_PARAMETER_ADJUSTMENT_NARRATIVE["MH-8820"] = {"cost": 350.0}` →
`Capability.SCHEDULE_MAINTENANCE`), imported by both implementations, so a
tier mismatch between engines could only be an orchestration bug, never
stand-in-data drift. Confidence, by contrast, is `causal_isolation`'s own
live output — a real number from a stage actually in the slice.

**Preemption — design note, not implementation.** Preemption
(`orchestrate/preemption.py`'s `PreemptionEngine`) is cross-run resource
arbitration via `asyncio.Event`s across independent `run_incident()`
coroutines, not an agent/stage. LangGraph has no native primitive for it —
implementing it would mostly test "does asyncio still work inside a
LangGraph node" (trivially yes), not anything framework-specific, and it's
the highest-risk item to under-scope (even the mature custom engine needed
careful async timing to pass
`test_preempted_incident_auto_resumes_under_same_incident_id`). It would map
onto LangGraph as an out-of-graph gate before `graph.ainvoke()`, mirroring
`claim_or_preempt()`'s role today. One real, checkable asymmetry is worth
recording without implementing it: LangGraph's checkpointer keys state
durably by `thread_id` (resumable after a process restart), whereas the
custom engine's `PreemptionEngine` and `PendingApproval` are both
in-process-only and lose pending state on restart — a gap
`orchestrate/README.md`'s own "Still open" section and `_snapshot_pending()`'s
docstring already admit.

**Implementation:** `nodes.py`/`graph.py` (LangGraph, checkpointer
`InMemorySaver`) and `baseline_slice.py` (hand-rolled, using the same
`agents`/`governance`/`IntegrationHub` primitives `orchestrator.py` itself
composes — built specifically because `DecisionOrchestrator.run_incident()`
always runs all 8 stages with no partial-pipeline entrypoint, so without
this baseline the comparison would silently become "8-stage custom vs.
4-stage LangGraph").

---

## Correctness & Reliability

`tests/test_orchestrate_langgraph.py`, 3/3 passing, in isolation and
combined with the existing 17-test suite (20/20 either import order):

- `test_langgraph_resolves_with_tier1_approval` / `test_langgraph_fails_on_rejected_approval`
  — mirror `tests/test_orchestrate.py`'s two most relevant scenarios against
  the LangGraph slice.
- `test_cross_engine_equivalence` — the falsifiable core: runs the
  canonical scenario through both `baseline_slice.py` and `graph.py` and
  asserts `causal_chain`, `confidence`, `alternatives`, `policy_tier`,
  `capability_invoked`, `capability_status`, and `final_state` are
  **identical**. They are — verified both via this automated test and by
  hand (both engines produce confidence `0.84`, the same 6-cause causal
  chain led by `COND-TOL-DRIFT` at weight `0.72`, tier `APPROVAL_REQUIRED`,
  capability `ScheduleMaintenance`).

The existing 17-test suite (`tests/test_orchestrate.py`) is untouched and
still fully green — confirmed by re-running it standalone and combined with
the new suite.

**One structural difference surfaced by writing these tests, not just a
result:** the custom engine's approval flow requires a concurrent
background task polling `orchestrator.approvals.list_pending()` while the
main run stays blocked on `PendingApproval.wait()` (see
`tests/test_orchestrate.py`'s own `auto_approve()` helper). LangGraph's
`run_incident_langgraph()` instead **returns immediately** once interrupted
— no live coroutine is left waiting — and a separate call to
`resume_incident_langgraph()` continues it later. Both are correct; they
are different concurrency models a caller needs to know about.

## Observability & Debuggability

Checklist, filled from actually running the canonical scenario through
both engines and inspecting what's available afterward (custom: `AgentRunner`
+ `InMemoryEventBus`, `bus.recent(incident_id)`; LangGraph: `graph.aget_state_history(config)`):

| Question | Custom engine | LangGraph |
|---|---|---|
| Exact stage sequence + timestamps? | Yes — `StageRequested`/`AgentCompleted` events, `occurred_at` per event (confirmed: e.g. `AgentCompleted` at `08:33:15.423509+00:00`, 46μs after its `StageRequested`) | Yes — `get_state_history()` returns one `StateSnapshot` per superstep with `created_at`; confirmed 7 snapshots for a 4-node run through one interrupt/resume |
| Confidence/evidence at each stage? | Yes — `AgentCompleted.payload` carries `confidence`, `evidence`, `alternatives`, `executionTimeMs` | Yes — each snapshot's `.values` accumulates the node's output fields directly (no separate envelope) |
| Exact input a paused/failed stage received? | `StageRequested.payload` | The `StateSnapshot.values` immediately before that node — confirmed: the snapshot with `next=('governance_gate',)` shows exactly the causal-isolation output present and nothing past it |
| Resume without re-running upstream stages? | **Yes** — `PendingApproval.wait()` resumes the same coroutine mid-function, upstream stages never re-execute | **No** — `interrupt()` re-executes the *whole interrupting node* from its top on resume (confirmed against installed API); upstream nodes are not re-run, but the gate node itself is — real, structural cost if that node ever gains a side effect above the `interrupt()` call |
| Survives a process restart? | Approvals: **no** (`_snapshot_pending()`'s own docstring admits this gap); terminal `IncidentRecord`: yes, if Cloudant configured | Yes, *if* the checkpointer is durable — `InMemorySaver` (used here, matching the custom engine's equally in-memory-only `ApprovalQueue`) is not; a Postgres/SQLite checkpointer would make this a real advantage, untested here |
| Out-of-the-box visualization? | None (hand-built frontend timeline) | Yes — `graph.get_graph().draw_mermaid()` ships with the library, no extra code; produced a correct 6-node diagram of this exact slice unprompted |

LangSmith tracing (`langsmith==0.10.9` already installed transitively) is a
plausible bonus but **not exercised** here — needs a live API key/network,
out of scope for this evaluation, not folded into the table above.

**Reading:** LangGraph's structured, queryable state history is a genuine
win for post-hoc debugging without any custom code — the mermaid diagram
alone is something the custom engine has no equivalent of today. The
resume-re-executes-the-node behavior is the one place it's *less*
transparent than the custom engine's continue-the-same-coroutine model,
and is easy to miss until you go looking for it.

## Extensibility

Concrete "add one new stage" experiment
(`extensibility_experiment/README.md` has full detail) — the same new
agent (`agents/severity_triage_agent.py`) wired into both engines between
`vision_spec` and `causal_isolation`:

| | Files touched | Lines | Wall-clock (anecdotal, 1 run) |
|---|---|---|---|
| Custom engine | 2 (`agent_runner.py`, `orchestrator.py`) | +7/-0 | ~3 min |
| LangGraph | 3 (`state.py`, `nodes.py`, `graph.py`) | +15/-1 | ~16 min |

Both verified against their real test suites after wiring (17/17 and 3/3
respectively) before the custom-engine side was reverted (`git checkout --`,
confirmed clean — `orchestrate/` carries no trace of this experiment).

**Reading:** for a single new *linear* stage, the custom engine is cheaper
— one more `await self._runner.run_stage(...)` call in an already-linear
sequence, versus LangGraph's fixed per-node overhead (define a node
function, register it, rewire two edges) regardless of how trivial the
stage is. This experiment deliberately does not test branching,
conditional stages, or anything touching preemption/resource arbitration —
exactly where a graph-based model would be expected to close or reverse
this gap. That's real, unanswered scope, not a hidden result.

## Latency & Cost

Per-mechanism, not whole-incident — the slice runs 4 of the custom
engine's 8 stages, so a whole-incident number would conflate "faster
framework" with "fewer stages run," which isn't a valid comparison. N=50
per mechanism, `time.perf_counter()`, full data in
[`bench_results.json`](bench_results.json):

| Mechanism | Custom engine (mean / p95) | LangGraph (mean / p95) |
|---|---|---|
| A — deterministic node (`vision_spec`) | 0.016 ms / 0.018 ms | 0.548 ms / 0.606 ms |
| B — "LLM-backed" node (`causal_isolation`, fallback path) | 0.141 ms / 0.146 ms | 0.660 ms / 0.734 ms |
| C — approval pause+resume round trip | 0.046 ms / 0.049 ms | 0.851 ms / 0.975 ms |
| D — mocked capability execution | 0.006 ms / 0.007 ms | 0.441 ms / 0.471 ms |

**B is explicitly not an LLM speed test** — the LLM is disabled by default
in this environment (same gate `conftest.py` applies to the whole existing
test suite), so both columns measure framework overhead around the
identical rule-based fallback path, not real model latency. A live-LLM
sub-experiment is flagged as optional/deferred, not attempted here.

**Reading:** LangGraph consistently costs more per node — roughly
0.4–0.85 ms of checkpointing/state-management overhead versus the custom
engine's raw async calls, a fairly consistent ~6–70x multiplier depending
on the mechanism. In absolute terms this is still sub-millisecond and
would be dwarfed by any real I/O — a live LLM call (hundreds of ms to
seconds) or a real ServiceNow/SAP round trip — so it's very unlikely to
matter for this product's actual bottleneck. It would start to matter only
at high call volume with a workload dominated by many cheap, fast stages.

**Cost:** $0 on both sides by default (no live LLM), so nothing meaningful
to compare in dollars here; operational cost (checkpoint writes vs. event-bus
publishes) is implicitly reflected in the timings above rather than
reported separately.

---

## Recommendation

**Don't replace the custom engine yet — the data doesn't support it, and
nothing here found a problem the custom engine actually has.**

Against the four criteria:
- **Correctness:** tied — both are correct for the tested scenarios;
  LangGraph's forced-node-re-execution-on-resume is a subtlety to design
  around, not a defect.
- **Observability:** LangGraph wins on stock tooling (state history,
  mermaid diagram) with zero custom code, at the cost of being less
  transparent about the resume-re-executes-the-node behavior specifically.
- **Extensibility:** custom engine wins for the one scenario actually
  tested (adding a simple linear stage); the scenario where LangGraph's
  model should pay off — branching/conditional pipelines — was
  deliberately not tested and remains open.
- **Latency:** custom engine wins outright, though the absolute cost is
  negligible next to any real I/O this system already does.

None of these are close enough, or found any concrete pain in the working
system, to justify a rewrite of `orchestrator.py`'s tested state machine —
including its preemption/auto-resume logic, which this evaluation
deliberately didn't attempt to reproduce because doing so safely is exactly
the scope a "representative slice" was meant to avoid. If a future need
does emerge — most plausibly a genuinely branching decision pipeline, or a
requirement for durable cross-restart approval state (where a real
Postgres/SQLite checkpointer would need to be evaluated, not just
`InMemorySaver`) — this module is the place to extend that investigation;
until then it stays as a reference implementation, not a migration target.
