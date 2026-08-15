# P15 — Distributed Concurrency Semantics & Atomicity Review

## 1. Verdict

**PASS**, with two real defects found, fixed, and proven closed — neither
was an authorization bypass, but both were genuine correctness gaps this
phase's own audit found, not ones any prior phase's report claimed to have
closed.

P14 named one open question explicitly: "the disable-vs-execution race
outcome is an empirical observation, not an atomicity guarantee." P15's job
was to determine exactly what ADOS guarantees under concurrent governance
changes, approvals, executions, and crashes — and to fix anything that
doesn't hold, not merely to re-assert that it does.

## 2. Fresh baseline — re-derived, not assumed

Baseline HEAD: `7464902` (unchanged — no P11–P15 commit exists; all remain
uncommitted working-tree state, per this phase's own instruction not to
commit).

Every mechanism this report describes was re-read from source during this
phase, not taken from P11–P14's own reports: `integrations/hub.py`,
`integrations/admission_control.py`, `integrations/rate_limiter.py`,
`backend/app/mcp_gateway.py`, `backend/app/routers/runtime_approvals.py`,
`orchestrate/runtime/capability_execution.py`,
`orchestrate/runtime/capability_reconcile.py`,
`orchestrate/runtime/admission_lease_reclaim.py`, `orchestrate/audit_trail.py`
(`claim_awaiting_approval`), `db/engine.py`, `db/models/mission.py`,
`db/models/admission_lease.py`, `backend/app/main.py`'s lifespan and
periodic-reconciliation loop. Postgres's actual isolation level was queried
live rather than assumed: `SHOW default_transaction_isolation` on
`ados_test` (PostgreSQL 16.14) returns `read committed`.

## 3. Exact files changed

- `backend/app/mcp_gateway.py` — the autonomous-tier completion-write fix
  (Finding #1, §5).
- `integrations/hub.py` — the admission-control leak-safety fix
  (Finding #2, §5).
- `backend/app/routers/runtime_approvals.py` — one new observability
  counter increment (§9), no behavior change.
- `backend/app/metrics.py` — `authorization_denials_total`'s `reason` enum
  documentation extended with `already_decided` (no new metric object).
- New: `backend/tests/test_capability_completion_race.py` (4 focused
  regression tests for both fixes).
- New: `scripts/p15_multiprocess_concurrency_proof.py` (the mandatory real
  multi-process proof, §7).
- `backend/tests/test_metrics.py` — one new test
  (`test_authorization_denials_total_already_decided`).

Nothing else was touched. No commit was made.

## 4. Concurrency architecture discovered

Two governance surfaces exist in this codebase, independently:

1. **MOA / manufacturing-incident approvals** — `orchestrate/governance.py`
   `ApprovalQueue` + `orchestrate/audit_trail.py`
   `AuditTrail.claim_awaiting_approval`, a single conditional
   `UPDATE incidents SET final_state='Executing' WHERE final_state=
   'AwaitingApproval'`. P13 built and proved this atomic-claim mechanism;
   re-read in full here and confirmed unchanged and correct — Postgres
   itself serializes the conditional UPDATE, so of any number of racing
   processes exactly one ever sees `rowcount == 1`.

2. **Prime Agent runtime capability requests**
   (`db.models.mission.CapabilityRequestRow`, driven by
   `backend/app/mcp_gateway.py` for the autonomous path and
   `backend/app/routers/runtime_approvals.py` for the human-approval path)
   — this phase's primary subject.

For (2), the state machine (`orchestrate/runtime/capability_execution.py`,
P9) is: `pending_approval -> executing -> {executed | failed |
outcome_unknown}`, with `outcome_unknown` resolvable only by
`orchestrate/runtime/capability_reconcile.py`'s two functions, run
periodically from `backend/app/main.py`'s one centralized scheduler
(`_reconcile_and_sweep_orphans_periodically`, P12) and available on demand
via `scripts/reconcile_capability_requests.py`.

Layered on top, independently: dynamic-capability governance state
(`integrations/capability_manifest.py`, P14 — unaffected by this phase,
re-confirmed live in §7) and admission control
(`integrations/admission_control.py` + `integrations/rate_limiter.py`, P11
local counters + P12 Postgres-backed global leases in `admission_leases`,
reclaimed by `orchestrate/runtime/admission_lease_reclaim.py`).

## 5. The two defects found, and the fixes

Both were found by tracing every crash/DB-unavailable point Phase 1
required — not by any pre-existing test, and not suspected in any P11–P14
report.

### Finding #1 — late autonomous completion could overwrite reconciliation's decision

`backend/app/routers/runtime_approvals.py::approve_capability_request`'s
own Phase 3 comment already documents the hazard: after the durable
`executing` checkpoint, the external call runs with **no lock held**
(deliberate — P9's own design, so a slow connector never blocks a decision
lock). That means the periodic reconciliation pass
(`mark_stalled_executions_unknown`) can legitimately move a row to
`outcome_unknown` **while the owning process is still alive and genuinely
working**, not crashed — any call slower than the stall bound
(`EXECUTION_STALL_SECONDS_DEFAULT = 60s`) is enough, and the row is not
locked during that window by construction. `approve_capability_request`
already guards against this: `await session.refresh(row); if row.status !=
STATUS_EXECUTING: <keep the row's own state, log, return>`.

`backend/app/mcp_gateway.py::request_capability`'s autonomous-tier
completion write — the OTHER writer of a `capability_requests` completion —
had no equivalent guard. It unconditionally did:

```python
row.status = outcome_status
row.result = result
...
await db.commit()
```

A late-arriving result could silently reverse reconciliation's own,
independently-made (and potentially evidence-backed, via
`reconcile_outcome_unknown`) decision — including, in principle, turning a
row reconciliation had resolved to `executed` on real external evidence
back into a locally-reported `failed`, which is exactly the shape of defect
that could motivate a human to re-trigger an action that already happened.

**Fix**: mirrored `runtime_approvals.py`'s own guard exactly — re-fetch the
row fresh, and if its status is no longer `executing`, keep the row's own
state (do not overwrite `status`/`result`/`reason`/`decided_by`) and report
that state back to the caller instead. The pre-existing
`outcome_unknown_total` increment is skipped in this branch specifically,
since reconciliation already counted the same real event once —
incrementing it again here would double-count one occurrence.

### Finding #2 — admission-control local-slot leak on a DB failure during acquire or release

`integrations/hub.py::IntegrationHub.invoke()`'s admission-control block
acquired the LOCAL (in-process, synchronous) capability slot, then awaited
the GLOBAL (Postgres) acquire **outside any try/finally**. If that await
raised — a transient database outage during exactly that call — the
exception propagated straight out of `invoke()`, and the local slot,
already taken, was never released. Nothing else in this codebase ever
resets `AdmissionControl._current_capability`/`_current_missions`, so this
was a permanent, cumulative leak: enough transient DB blips would
eventually exhaust the local ceiling entirely, refusing work this process
should otherwise have admitted, until a restart.

A second, related gap sat in the `finally` block itself: if
`release_mission_slot_global(...)` (a real DB DELETE) raised, the
subsequent lines — `release_capability_slot()` (local) and
`release_capability_slot_global(...)` — never ran, because a raise
partway through a `finally` block aborts the rest of that block too.

Neither is an authorization bypass — a leak only ever makes this gate MORE
restrictive over time, never less. Both are genuine, reproducible
availability defects, squarely in scope for Phase 1's explicit requirement
to record "what happens if the process crashes / the database is
unavailable" at every state transition.

**Fix**: restructured so the ENTIRE admission sequence, from the global
acquire onward, sits inside one try/finally that unconditionally releases
the local slot(s) already acquired, regardless of what happens afterward.
The global acquire itself is now wrapped so a raised exception converts to
a structured, fail-closed `FAILED` `CapabilityResponse` (never a silent
fallback, matching this codebase's established DB-unavailable posture —
e.g. `capability_manifest.py::refresh_from_db`'s identical fail-closed
handling in `hub.invoke()`'s capability-registry check). Each global
*release* call in `finally` is now independently try/except-guarded — one
release failing (logged, not raised) can no longer prevent the others,
local or global, from running. What this does NOT claim: a genuinely
failed global lease DELETE still leaves that one lease row behind in
Postgres — nothing can un-leak a row a failed DELETE didn't delete. That
row's cleanup is exactly what the existing periodic
`admission_lease_reclaim.py` sweep (P12, unmodified) already exists for,
and is proven as the correct backstop in
`backend/tests/test_capability_completion_race.py::
test_a_failing_global_release_does_not_prevent_the_local_capability_release`.

## 6. Invariants, stated explicitly

- **A — Capability disable.** If a disable transaction commits before
  execution authorization is evaluated, no worker may execute that
  capability. **Formally safe** (P14, re-confirmed live in §7): every
  execution boundary re-reads Postgres immediately before dispatch
  (`refresh_from_db`), so a committed disable is visible to the very next
  authorization check on any worker, with no restart required.
- **B — Capability enable.** Symmetric to A, same mechanism, same
  guarantee — re-confirmed live in §7.
- **C — Approval.** A capability request cannot be approved/executed twice.
  **Formally safe**, database-enforced: `SELECT ... FOR UPDATE` in
  `_load_pending_or_404` serializes the read-then-decide sequence; the
  post-lock `status != 'pending_approval'` check makes a second decision
  attempt a 409, never a second execution. Proven live (§7, Case 1) and
  proven load-bearing by negative control (§8, Control #3).
- **D — External side effect (at-most-one automatic attempt).** Formally
  safe, database-enforced: `uq_capability_requests_session_idempotency`
  (a partial unique index on `(session_id, idempotency_key)`) turns the
  check-then-insert into a database fact, not a hope — a losing racer's
  `IntegrityError` is caught and resolved by replaying the winner's row
  (`_replay_or_raise`), never by retrying the insert. This is **not**
  exactly-once external execution — ServiceNow itself makes no such
  guarantee, and this codebase never claims one; it is exactly "at most one
  ADOS-initiated attempt per canonical request."
- **E — Outcome unknown.** A row moved to `outcome_unknown` must never be
  silently reverted by an unrelated process. **Was an open defect (Finding
  #1), now fixed and formally safe** on both writers (autonomous and
  human-approval paths agree).
- **F — Admission control.** Two workers must never both believe they hold
  the same global slot; the admitted count must never exceed the
  configured global limit under real concurrency. **Formally safe**
  (Postgres-serialized via `pg_advisory_xact_lock` + a transactional
  count-then-insert), proven live across 10 genuinely separate OS processes
  racing for a limit of 3 (§7, Case 4) and proven load-bearing by negative
  control (§8, Control #4). The **local-slot leak (Finding #2)** was a
  separate, orthogonal availability defect in the SAME code path — never a
  violation of the admitted-count ceiling itself.
- **G — Token expiry.** No expired or NULL-expiry session may authorize any
  action, under concurrent load, from any process. **Formally safe**:
  `_resolve_session` re-reads `token_expires_at` fresh from Postgres on
  every single call and compares against wall-clock time — there is no
  cache to go stale. Proven live across 3 separate processes racing a
  NULL-expiry session, a past-expiry session, and a valid control session
  simultaneously (§7, Case 5).
- **H — Governance state vs. execution.** Disable/approve/admit/execute are
  each individually atomic (their own transaction or advisory-locked
  section) but are **not** wrapped in one larger transaction spanning all
  of them — by design: holding a DB transaction open across a real external
  HTTP call (or a Docker `run_objective`) is exactly the P9 defect this
  codebase was already built to avoid. Each individual boundary is proven
  safe on its own (§6 A–G); their composition is safe because each one's
  own guard (the FOR UPDATE lock, the advisory lock, the unique index, the
  authoritative capability read) is evaluated fresh, immediately before the
  step it gates, not inherited from an earlier step's now-possibly-stale
  read.

## 7. Real multi-process proof (Phase 5 — mandatory)

`scripts/p15_multiprocess_concurrency_proof.py`, same convention as P14's
own script: `multiprocessing.get_context("spawn")` for genuinely separate
OS processes and fresh interpreters, real `ados_test` Postgres throughout,
independently re-verified cleanup. Final clean run — **PASS, all checks**:

```
=== Case 1 — double approval race (Invariant C) ===
  [PASS] exactly one worker wins the decision lock
  [PASS] the loser is refused with 409 (already decided), not a silent second success
  [PASS] the row shows exactly the one decision made, durably

=== Case 2 — double execution / idempotency race (Invariant D) ===
  [PASS] both callers resolve to the SAME request_id
  [PASS] exactly one of the two calls is the original, the other a replay
  [PASS] exactly one durable row exists for this canonical request, not two

=== Case 3a — reconciliation vs. a genuinely-still-executing row (Invariant E, the P15 fix) ===
  [PASS] the slow call started
  [PASS] the row reached the durable executing checkpoint while the call is genuinely still in flight
  [PASS] reconciliation (a DIFFERENT process) marks the row outcome_unknown while worker_slow is still alive and working
  [PASS] row durably reads outcome_unknown after reconciliation, before the slow call ever returns
  [PASS] the late completion reports outcome_unknown (reconciliation's decision), not executed
  [PASS] the late completion did NOT overwrite reconciliation's decision or its reason
  [PASS] the late completion did not claim to have decided this row

=== Case 3b — real crash boundary: SIGKILL mid-external-call (Invariant E / H) ===
  [PASS] the second slow call started (about to be killed)
  [PASS] the row reached the durable executing checkpoint before the kill
  [PASS] the worker process is genuinely dead (no finally, no teardown ran)
  [PASS] reconciliation recovers the row abandoned by the killed process
  [PASS] the row durably reads outcome_unknown after a real process kill, never silently re-executable

=== Case 4 — admission race at the real configured limit: 10 real processes, limit=3 ===
  3 admitted, 7 refused across 10 real, separate OS processes (limit=3)
  [PASS] admitted count equals the configured limit exactly (3), not merely 'close to it'
  [PASS] refused count makes up the rest

=== Case 5 — token-expiry race (Invariant G) ===
  [PASS] NULL-expiry session refused from worker A
  [PASS] NULL-expiry session refused from worker B, concurrently, from a DIFFERENT process
  [PASS] already-past-expiry session refused from worker C
  [PASS] a genuinely valid session succeeds concurrently with a refused one, from separate processes
  [PASS] the NULL-expiry session is STILL refused on a second, concurrent attempt
  [PASS] independent post-cleanup verification: 0 P15-tagged missions remain
  [PASS] independent post-cleanup verification: 0 orphaned runtime_sessions remain

RESULT: PASS — all checks passed across real, separate OS processes.
```

Case 3b is a **genuine crash**, not a simulated exception: the driver sends
real `SIGKILL` to the worker's OS process mid-external-call, confirmed dead
(`process.is_alive() is False`) before reconciliation runs from a
completely separate process. This is a stronger proof than the existing
pytest-level crash test
(`test_a_crash_between_marking_executing_and_the_connector_call_leaves_it_
durably_executing`, which raises `asyncio.CancelledError` to escape the
autonomous path's own `except Exception` guard) — that test remains valid
or the OTHER crash boundary (before the connector call is ever reached);
this phase's live proof covers the boundary DURING the call.

**Invariants A/B** (disable/enable propagation) were re-confirmed, not
re-implemented: `scripts/p14_multiprocess_capability_proof.py` was re-run
unmodified, fresh, after this phase's `hub.py` edits — full PASS, including
its own 15/15 concurrent-race trials, its stale-worker case, its restart
case, and its alternate-path case. Reproduced in full in that script's own
output; not duplicated in this document.

## 8. Negative controls (Phase 7)

Four, each: disable one load-bearing guard → reproduce the expected
failure live → restore → SHA-256 byte-identical verification.

| # | Guard disabled | File | Reproduced failure | SHA-256 restored |
|---|---|---|---|---|
| 1 | P15's own late-completion guard (`if row.status != STATUS_EXECUTING`) | `backend/app/mcp_gateway.py` | `test_late_autonomous_completion_does_not_overwrite_a_row_reconciliation_already_resolved` fails: `assert 'executed' == 'outcome_unknown'` — the late completion silently reverses reconciliation's decision | `9a33fb6d...81cbe0` ✓ |
| 2 | P15's own leak-safety wrapping around the global capability acquire | `integrations/hub.py` | `test_a_failing_global_acquire_does_not_leak_the_local_capability_slot` fails: unhandled `ConnectionRefusedError` escapes `invoke()` — the pre-fix bug, reproduced exactly | `32141b40...d07ac` ✓ |
| 3 | `SELECT ... FOR UPDATE` row lock in `_load_pending_or_404` | `backend/app/routers/runtime_approvals.py` | Live, multi-process Case 1: **both** workers report `ok: True` — the double-approval guard is gone entirely | `b8c0ef23...5fa27` ✓ |
| 4 | `pg_advisory_xact_lock` in `AdmissionControl._try_acquire_global` | `integrations/admission_control.py` | Live, multi-process Case 4: **10/10 admitted** against a configured limit of 3 — the global ceiling is not enforced at all | `309243573...522b4` ✓ |

Every control failed for exactly the reason predicted before being
restored; none needed strengthening. Controls #3 and #4 target
pre-existing (P12/P13) mechanisms this phase independently re-derived and
depends on for its own safety claims — re-verifying them live, not merely
trusting their prior reports, is exactly what Phase 1's "do not assume
prior conclusions are correct" instruction requires.

## 9. Tests

Focused: `backend/tests/test_capability_completion_race.py` — 4/4 passed
(2 for Finding #1, 2 for Finding #2). `backend/tests/test_metrics.py` — 20/20
passed (19 pre-existing + 1 new, `test_authorization_denials_total_already_decided`).

**Full suite** (`pytest -q`, default `-m 'not external and not docker'`,
run alone with no other pytest process concurrently touching the same
Postgres): **893 passed, 0 failed, 19 deselected.** Reconciles exactly:
888 (P14's own final count) + 5 new (4 completion-race + 1 metrics) = 893.

**Docker-marked** (`pytest -m docker`, run alone): **17 passed, 0 failed,
895 deselected** — unchanged from P14's own baseline.

**External-marked**: 1 test exists (mutates real ServiceNow), intentionally
not run — matching Phase 9's own preference and this phase's own finding
that no live external verification was needed to prove any P15 claim.

An earlier attempt running the full suite and the Docker suite as two
concurrent pytest processes against the same live Postgres produced 2
spurious Docker-suite failures (an admission/Docker container-count
assertion and a backup/restore round-trip) and 3 spurious full-suite
failures (auth, observability-logging, orphan-sweep — none in code this
phase touched). Re-run sequentially and in isolation, both suites pass
cleanly; the concurrent run's failures are attributed to resource
contention between the two simultaneous test processes, not to any P15
code change.

## 10. External side effects

None. No ServiceNow record was created, read, or modified anywhere in this
phase. Every live proof used real Postgres, real separate OS processes,
and — for Case 3b only — a real `SIGKILL`; no external system was ever
reachable from any of it.

Docker/Postgres cleanliness: only the 5 persistent compose-stack
containers present before and after (`ados-backend-1`, `ados-migrate-1`,
`ados-frontend-1`, `ados-postgres-1`, `ados-kafka-1`), no leaked networks,
0 residual rows across `capability_requests`/`missions`/`runtime_sessions`/
`admission_leases` from any P15 script or test run. One incidental,
pre-existing artifact was found and cleaned: 2 `missions` rows titled
"live session A"/"live session B" and 1 `rate_limit_events` row, left by
`backend/tests/test_two_session_isolation.py`'s own truncate-on-setup (not
teardown) convention from the last Docker-suite run — the exact same
pattern already documented in P13's own report, unrelated to any file this
phase touched.

## 11. Observability

Reviewed against this phase's own required signal list:

- **capability refusal** — `authorization_denials_total`,
  `admission_rejections_total` (pre-existing, unchanged, confirmed
  exercised live in §7 Cases 4/5).
- **admission rejection** — `admission_rejections_total{gate=...}`
  (pre-existing, confirmed exercised live in §7 Case 4: 7/10 real refusals
  recorded).
- **duplicate approval refusal** — **a genuine gap, found and closed**: the
  409 in `_load_pending_or_404` had no Prometheus signal at all before this
  phase. Fixed by reusing the existing `authorization_denials_total`
  counter with one new `reason="already_decided"` label value — no new
  metric object, matching this codebase's established "extend an existing
  fixed enum before inventing a new metric" convention (the same one P12's
  `mission_start_rate` gate value already set). Covered by a new delta-based
  test, `test_authorization_denials_total_already_decided`.
- **idempotency replay** — surfaced in the `request_capability` response
  itself (`"replayed": true`); not separately metriced, matching the
  existing convention (no dedicated counter for this before P15 either) —
  judged sufficient since a replay is not a refusal or an anomaly.
- **outcome_unknown** — `outcome_unknown_total` (pre-existing). Finding #1's
  fix deliberately does NOT increment this a second time when a late
  completion observes a row reconciliation already moved there — reconciliation
  already counted that same real event once; double-counting would
  misrepresent the metric's own meaning ("one row transitioned").
- **reconciliation** — `reconciliation_runs_total{result}` (pre-existing),
  confirmed exercised live in §7 Case 3a/3b.
- **stale-state detection** — `capability_registry_stale_cache_detected_total`
  (P14, unrelated to this phase's own findings, unaffected).
- **concurrency guard failures** — the two `logger.exception(...)` calls
  added in `hub.py`'s `finally` block (Finding #2's fix, for a genuinely
  failed global release) are log-only, deliberately not a new metric: this
  is a rare, DB-outage-only path already backstopped by the existing
  periodic lease-reclaim sweep, and Phase 10's own instruction is not to
  add metrics without a genuine gap — an operator-visible log line plus an
  existing recovery mechanism is judged sufficient here, unlike the
  duplicate-approval-refusal case above, which had NO existing signal at
  all.

No new high-cardinality label was introduced anywhere (`already_decided`
joins the same fixed, closed `reason` enum every other value already
belongs to).

## 12. Remaining limitations, honestly

- The admission-control local-slot leak's OWN release-failure path (a
  genuinely failed global lease DELETE) still leaves that one lease row in
  Postgres until the next periodic reclaim tick
  (`admission_lease_max_age_seconds`, default 1800s) — this is the existing,
  intentional backstop, not a new gap, and is proven to work as intended in
  `test_a_failing_global_release_does_not_prevent_the_local_capability_
  release`.
- Case 3's "race outcome distribution" question from P14 (disable-vs-execute)
  remains, honestly, an empirical observation about relative operation cost
  under the conditions measured (15/15 in P14's own re-run) — this phase did
  not attempt to convert it into a designed ratio guarantee, because the
  actual safety property (no execution ever violates the authoritative
  state) does not require one, and inventing one would overclaim.
- Multi-tenancy and multi-host container ownership remain unattempted, as
  every prior phase has already stated — out of this phase's explicit scope
  boundary.
- LISTEN/NOTIFY-based push invalidation for the capability registry (an
  optional future improvement named in P14's own report) remains
  unattempted — still not required, since every execution boundary already
  performs a fresh authoritative read regardless.

## 13. Model A / B / C readiness impact

**Model A**: unaffected, still READY. **Model B**: unaffected, still
READY — Finding #1 and #2 are real correctness improvements but neither
was a Model B blocker on its own (P12 already closed the named Model B
gaps); this phase closes two gaps P12–P14 did not know existed. **Model
C**: the specific concurrency races this phase was chartered to resolve
(approval, execution, admission, token expiry, reconciliation, crash
recovery) are now proven safe under real, separate-process concurrency —
still not "Model C: READY" for the same reasons every prior phase has
already stated (no multi-tenancy, no multi-host container ownership
proven).

## 14. Exact remaining blockers

None found in this phase's own scope. The two defects this phase found
(Findings #1 and #2) are fixed, tested, and proven closed live. Everything
named in §12 is a stated limitation, not a blocker for the production
posture this program has already committed to (Model A/B).

---

STOP after P15. P16 was not started, per this phase's own explicit
instruction.
