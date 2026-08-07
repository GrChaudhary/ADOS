# orchestrate_langgraph/

LangGraph reimplementation of a **representative slice** of `orchestrate/`'s
decision pipeline, built to answer one question as ADOS moves from
hackathon project to product: should the hand-rolled orchestration engine
eventually be rebuilt on LangGraph? See **[COMPARISON.md](COMPARISON.md)**
for the full evaluation and recommendation — short version: not yet, the
data doesn't support it.

This module is purely additive and self-contained — `orchestrate/` is
never imported for modification, only reused (`orchestrate.governance.assign_policy_tier`),
and the whole evaluation (code, benchmark data, write-up) can be deleted as
one unit if the recommendation is "don't adopt."

## Status: evaluation complete

```
scenario_defaults.py  Shared canonical scenario + governance stand-in constants
                       (capability/cost), imported by both implementations
                       so results are directly comparable.
state.py               IncidentGraphState — the graph's TypedDict state shape.
nodes.py                 vision_spec_node / causal_isolation_node wrap the
                       REAL agents/*.py classes unmodified; governance_gate_node
                       uses LangGraph's interrupt()/Command for the human
                       approval gate; execute_capability_node is a
                       deterministic mock (ConsoleConnector only).
graph.py                  StateGraph wiring + InMemorySaver checkpointer +
                       run_incident_langgraph()/resume_incident_langgraph()
                       entrypoints.
baseline_slice.py         The SAME 4 stages, hand-sequenced with orchestrate/'s
                       own primitives (not DecisionOrchestrator.run_incident(),
                       which always runs all 8 stages) — exists so the
                       comparison is 4-stage-vs-4-stage, not 8-vs-4.
bench_latency.py           Per-mechanism latency harness -> bench_results.json.
demo.py                     Standalone run, mirrors scripts/run_orchestrator_demo.py.
extensibility_experiment/    "Add one new stage" experiment: diffs + protocol.
```

Run the standalone demo:

```bash
.venv/bin/python -m orchestrate_langgraph.demo
```

Run the tests (mirrors `tests/test_orchestrate.py`'s two most relevant
scenarios, plus a cross-engine equivalence test):

```bash
.venv/bin/pytest tests/test_orchestrate_langgraph.py -v
```

Regenerate the latency benchmark:

```bash
.venv/bin/python -m orchestrate_langgraph.bench_latency
```

## Scope — what this slice covers and what it doesn't

**In scope:** `vision_spec` → `causal_isolation` → governance/approval gate
→ mocked capability execution → terminal Resolved/Failed, reusing the real
`VisionSpecAgent`/`CausalIsolationAgent`/`assign_policy_tier` unmodified.

**Deliberately out of scope:** `CandidateGeneration`/`Reserving`
(Substitution/Parameter-Adjustment/Impact-Simulation), `feedback_calibration`,
and **preemption** — the single most bespoke piece of the custom engine
(cross-run resource arbitration via `asyncio.Event`s), which has no natural
LangGraph analogue and was judged too high-risk to under-scope for a
first evaluation. See `COMPARISON.md`'s "Preemption — design note" section
for how it would map onto LangGraph without having been built here.

## A structural difference worth knowing before using this module

The custom engine blocks a live coroutine on `PendingApproval.wait()` until
a human decides — `run_incident_langgraph()` instead **returns immediately**
once it hits the approval gate (no live coroutine left waiting); resuming
means a separate call to `resume_incident_langgraph()` against the
persisted checkpoint. Both are correct, but they're different concurrency
models — see `COMPARISON.md`'s Correctness section and
`tests/test_orchestrate_langgraph.py` for both in action.

**Resuming re-executes the interrupting node from its top** (confirmed
against the installed `langgraph==1.2.10` API, documented in
`interrupt()`'s own docstring) — `governance_gate_node` is written with
this in mind (nothing with side effects below the `interrupt()` call). Any
new node using `interrupt()` in this module must keep that same invariant.

## Still open

- Preemption's LangGraph mapping is a design note, not implemented or tested.
- The latency benchmark's "LLM-backed node" mechanism measures framework
  overhead around the rule-based fallback path only — no live-LLM timing
  was collected (see `COMPARISON.md`).
- `InMemorySaver` is non-durable, matching the custom engine's equally
  in-memory-only `ApprovalQueue` — a durability comparison (Postgres/SQLite
  checkpointer vs. Cloudant-backed audit trail) was identified but not run.
