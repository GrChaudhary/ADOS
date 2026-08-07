# Extensibility experiment — protocol + results

Concrete, falsifiable "add one new stage" test: the same new agent,
`agents/severity_triage_agent.py`'s `SeverityTriageAgent` (pure, deterministic
— buckets `deviation_mm` into a severity label, no branching that could bias
either side), wired into both engines between `vision_spec` and
`causal_isolation`/`cad_spec`. Only the *wiring* diff is measured — the
agent's own code and its export in `agents/__init__.py` are shared,
one-time infrastructure counted toward neither engine (both sides benefit
from that export equally, so attributing it to one side would bias the
comparison against the other).

## Custom engine

Applied directly to `orchestrate/agent_runner.py` (register the agent) and
`orchestrate/orchestrator.py` (insert one `run_stage()` call into the
pipeline), verified against the real test suite
(`pytest tests/test_orchestrate.py` — 17/17 still passing), diff captured
via `git diff --stat`, then **reverted** (`git checkout --`) so
`orchestrate/` stays untouched in the final repo state — see
[`custom_engine_add_stage.diff`](custom_engine_add_stage.diff).

**Result: 2 files, +7/-0 lines.**

## LangGraph

Applied for real and kept — `orchestrate_langgraph/state.py` (+1 field),
`nodes.py` (+1 import, +1 agent instance, +1 node function), `graph.py`
(+1 import, +1 `add_node`, 1 edge replaced by 2) — verified against
`pytest tests/test_orchestrate_langgraph.py` (all 3 tests, including the
cross-engine equivalence test, still passing) and the full combined suite.
See [`langgraph_add_stage.diff`](langgraph_add_stage.diff) (hand-reconstructed,
not a real `git diff` — these files were new and uncommitted at the time of
the experiment, so there's no prior committed version to diff against).

**Result: 3 files, +15/-1 lines (net +14).**

## Time-to-add

Wall-clock, one run, one engineer (this session) — anecdotal, not
statistically rigorous, consistent with how this codebase already
self-labels its own MVP estimates:

- Custom engine: **~3 minutes** (find the two call sites, make the edits,
  re-run the real test suite for verification).
- LangGraph: **~16 minutes** (three files instead of two, a full node
  function instead of one stage call, plus re-running both the new
  slice's tests and the cross-engine equivalence test).

Caveat worth stating plainly: both numbers include this session's own
tool-call/verification overhead, not pure typing time, and the LangGraph
side did strictly more work (one more file touched, ~2x the lines, a
second test file re-verified). The LOC/files-touched numbers above are the
more trustworthy signal of the two; the wall-clock numbers are a rough
secondary data point, not the headline result.

## Reading

For a single new **linear** stage with no new branching/interruption
behavior, the custom engine's wiring cost is lower — one call added to an
already-linear sequence of `await self._runner.run_stage(...)` calls. The
LangGraph side pays a fixed "define a node function + wire two edges"
overhead per stage regardless of how trivial the stage is, which is
where its extra lines come from. This experiment does *not* test the
scenario where the custom engine's cost stops being cheap — branching,
conditional stages, or anything touching preemption — where LangGraph's
graph-based model would be expected to close or reverse this gap; that's
out of scope for this slice (see the main `COMPARISON.md`).
