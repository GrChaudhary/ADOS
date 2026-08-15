# P12 — Production Operational Hardening: Model B Readiness (2026-08-13)

Answers the question P8 first posed and P10/P11 progressively narrowed:
can ADOS honestly operate as a bounded, observable, recoverable
long-running production service (**Model B**)? Re-derived from the current
repository and live infrastructure, not copied from prior reports — several
claims in [18](18-production-readiness-review.md)/[19](19-metrics-and-alerting.md)/[21](21-p11-acceptance-report.md)
turned out to be either stale (reconciliation's scheduling status) or
subtly inaccurate (the NULL-expiry guard's actual coverage), and both are
corrected here with evidence, not just asserted.

**No commit was made during this phase**, per explicit instruction — every
file below is a real, uncommitted change in the working tree, verifiable
with `git status`/`git diff`.

## 1. Fresh baseline

- **HEAD:** `7464902fb07efdef590493e92f0dec27be8b88d6` — "P11: fill in the
  self-referential commit hash in the doc's own §1." Parent chain: P11
  (`0017369`), P10 (`7381122`), P9 (`6e5ef45`), P8 (`3813ced`).
- **Metrics/alerting operationalization** (Prometheus/Alertmanager wiring —
  `infrastructure/prometheus/`, doc 22): present as **uncommitted working-tree
  changes** on top of HEAD, from the immediately-preceding session. Not a
  separate commit.
- **Working tree, pre-existing, untouched throughout P12:** an unrelated
  agents-registry/novus-studio frontend feature (`backend/app/routers/
  agents_registry.py`, `db/models/custom_agent.py`, several `frontend-next/`
  files, `backend/tests/test_agents_registry.py`) and ~25 untracked scratch
  scripts (`scripts/*.js`, `scripts/*.json`, `agency-agents-repo/`). Verified
  via `git status --short` before and after — identical set, byte-for-byte,
  outside the files this document lists as P12's own.
- **Docker, at start:** `ados-backend-1` (healthy, but serving a pre-P12
  image), `ados-postgres-1` (healthy), `ados-kafka-1` (up). No leaked
  `ados-prime-*`/`ados-relay-*`/`ados-rt-*` resources.
- **Postgres, at start:** `ados_app` role confirmed live-querying to have no
  `DELETE` on `missions`/`runtime_sessions`/`capability_requests`/
  `capability_promotion_events` and no `CREATE` anywhere; backend connects as
  `ados_app` (`docker exec ados-backend-1 printenv DATABASE_URL`), migrate
  connects as `ados` (superuser).
- **Prometheus/Alertmanager/webhook receiver:** all three still running,
  continuously, from the prior session (`prometheus`, `alertmanager`,
  `webhook_receiver.py` — confirmed via `ps aux`). Reused throughout, not
  restarted, except for the config reloads this phase's own changes required.
- **Fresh full-suite baseline** (`pytest -q`, before any P12 code changed):
  **845 passed, 2 failed, 19 deselected, 466.87s.** Both failures
  independently re-run in isolation and passed cleanly
  (`test_executive_incident_options.py::test_incident_options_reflects_live_orchestrator_run`,
  2.42s; `tests/test_onboarding_sandbox_runner.py::
  test_second_call_against_unchanged_source_reuses_the_cached_image`,
  17.86s) — confirmed full-suite-only, resource-contention flakes, not
  regressions, and not touching any file this phase modified. This is the
  same class of transient failure P11's own report already documented for
  two different tests under the same full-suite-load conditions.

## 2. Model B code-area audit — what P11's own reports claimed vs. what the code actually does

A dedicated research pass re-derived every P12-relevant claim directly from
the code (not trusted from docs 18/21), plus a live query against the
running containers. Full findings condensed:

| Area | Claimed (doc 18/21) | Actually found | Verdict |
|---|---|---|---|
| Admission control | "single-process, in-memory... or Postgres-transaction-serialized" | **Accurate, and the docs said so honestly** — 2 of 4 gates (`mission_concurrency`, `capability_concurrency`) genuinely in-process only; 2 (`approval_queue`, `session_activity`) genuinely Postgres-global already | Real gap for Model B, not a doc error — **closed this phase, §3** |
| Docker resource ownership | Claim/lease/label mechanism, P7-C | Confirmed exactly as described: `FOR UPDATE SKIP LOCKED` claim, 300s lease, independent Docker-label re-verification before every delete | Accurate — **verified with real concurrent processes, §4, no code changes needed** |
| Process crash recovery | Automatic, `_reconcile_and_sweep_orphans_periodically` | Confirmed: real function, real `asyncio.create_task`, real 300s-default interval | Accurate |
| Capability-request reconciliation | "not auto-scheduled... deliberate" | Accurate as of P10/P11 — confirmed zero call sites outside scripts/tests | Correct at the time; **narrowed this phase, §5** — now also automatic |
| `outcome_unknown` lifecycle | Positive-evidence-only, never retries | Confirmed — `reconcile_outcome_unknown` only ever queries, never re-invokes `connector.execute()` | Accurate, unaffected by P12 |
| **NULL-expiry protection (P10)** | "approval refused... execution refused" (doc 18 §16.6 implies both) | **`_resolve_session` (the function `request_capability`, `list_capabilities`, and `get_capability_request` all share) did NOT check for NULL — only for expiry in the past.** A NULL-expiry fossil session with a still-live `state` could reach autonomous auto-execution with zero human involvement. | **Real, previously-uncalled-out gap — closed this phase, §6** |
| Build identity | Single raise site, no-op inside Docker image | Confirmed live: `commit:"unknown"` inside the real running container, matches doc 18 §16.4 exactly | Accurate, unaffected |
| Postgres security | `ados_app` least-privilege, no DELETE on audit tables | Confirmed live via direct privilege queries against the running container | Accurate, unaffected |
| Rate limiting | "None... including ones that call a paid LLM per request" (doc 18 §D) | Confirmed by exhaustive grep — no token-bucket/sliding-window/requests-per-window mechanism anywhere, distinct from admission control's concurrency ceilings | Real gap — **closed this phase, §7** |

## 3. Distributed admission control — audit, fix, and multi-process proof

**Audit result:** `integrations/admission_control.py`'s `AdmissionControl`
was plain Python (`self._current_capability`/`self._current_missions`,
`int`s, no lock, no DB) — its own docstring already said plainly *"this
does NOT extend across processes."* Two ADOS processes sharing one Postgres
database would each independently enforce `max_concurrent_prime_missions`/
`max_concurrent_capability_executions`, together admitting up to **2x (Nx)**
the configured global limit.

**Fix, additive, not a replacement:** `AdmissionControl` gained an optional
`session_factory`. When set, `try_acquire_{capability,mission}_slot_global()`
(new, async) claim a row in a new table, `admission_leases`
(`db/models/admission_lease.py`, migration `b2c3d4e5f6a7`), under
`pg_advisory_xact_lock` — the same idiom `mcp_gateway.py`'s
`approval_queue` gate already used. The existing synchronous, in-process
methods are **unchanged** and still run first (cheap local pre-check); the
global check is what makes the ceiling correct once a second process
exists. `session_factory=None` (every one of the ~800 pre-existing tests)
preserves P11's exact behavior — verified by re-running
`test_admission_control.py`/`test_integration_hub_admission.py`/
`test_mcp_gateway_admission.py` unchanged: **22 passed.**

**`integrations/hub.py::invoke()`** now calls the global acquire
immediately after each local one, releasing the local slot if the global
check refuses (never left inconsistent), and releases both (local + global)
in the same `finally` regardless of how the call ends.

**A crashed process's lease is reclaimed, not left to leak forever:** the
same centralized periodic loop (§5) also runs
`orchestrate/runtime/admission_lease_reclaim.py::reclaim_stale_admission_state`,
deleting any lease older than `Settings.admission_lease_max_age_seconds`
(default 1800s — matching the same ceiling `scripts/
prime_agent_servicenow_e2e.py`/`prime_agent_approval_e2e.py` already use for
`max_wall_clock_seconds`, not an arbitrary number).

### Real, separate-OS-process proof — `scripts/p12_multiprocess_admission_proof.py`

Four parts, all against the real dev Postgres database, using
`multiprocessing` with the `spawn` context (a genuinely fresh interpreter
per worker — nothing shared with the parent except the database):

- **Part 1 — reproduces the gap.** 6 real OS processes, each with a
  `session_factory=None` `AdmissionControl(limit=3)`, all attempt
  acquisition at the exact same instant (a real `multiprocessing.Barrier`,
  not a hopeful sleep). Result: **6 admitted against a limit of 3** — every
  process enforced its own local ceiling, oblivious to the others.
- **Part 2 — the fix.** Same 6 processes, same limit, `session_factory`
  wired to the real database. Result: **exactly 3 admitted, 3 rejected**,
  verified independently by querying `admission_leases` row count after
  (matches the admitted count exactly) and confirming 0 rows remain after
  release.
- **Part 3 — the two already-global gates, proven with real processes too
  (not just asyncio.gather in one process).** 2 real OS processes, each
  calling the real `request_capability` MCP tool function (not a
  reimplementation) 4 times against a shared mission: `approval_queue`
  (limit 3, 8 real attempts across 2 sessions) → exactly 3 parked, 5 denied;
  `session_activity` (limit 3, 8 real attempts against **one shared
  session**) → exactly 3 admitted, 5 denied.
- **Part 4 — process crash.** A worker acquires a global lease, signals
  ready, then is `SIGKILL`ed (a real crash, not a clean exit). The lease row
  is confirmed still present immediately after (nothing releases it
  automatically — a real leak, as designed). The same reclaim pass
  `backend/app/main.py`'s scheduler calls is then run directly: reclaims
  exactly 1, independently re-verified at 0 rows remaining.

All four parts: **PASSED.** Exact counts throughout — no "no exception
occurred" reasoning anywhere in this script. Postgres and the dev database
confirmed clean of test rows both during and after (`admission_leases`,
`rate_limit_events`, and the proof's own mission rows all at 0).

## 4. Docker resource ownership — verification against real Docker, real concurrent processes

No code changes were needed here — the audit (§2) found P7-C's existing
mechanism already correct. `scripts/p12_docker_ownership_proof.py` verifies
all four cases this phase named, against real Docker containers
(lightweight `alpine sleep` containers carrying the exact same
`ados.session_id`/`ados.managed_by`/`ados.component` labels
`orchestrate/runtime/egress.py` uses for real Prime Agent containers —
`orphan_sweep.py`'s claim/verify/delete logic only ever inspects labels,
never what's running inside):

- **Case B (legitimate recovery only):** a still-`running`, non-orphan-
  marked session claims **0** resources — `claim_batch`'s own `WHERE`
  clause excludes it before Docker is ever even asked.
- **Case C (simultaneous recovery, exactly one claims):** 3 real OS
  processes call `claim_batch` at the exact same instant against the same
  orphaned session (`multiprocessing.Barrier`). Exactly 1 claimed (4
  candidates); the other 2 claimed 0.
- **Case A (owner protection):** a further claim attempt for the same
  session, still inside the 300s lease window, claims 0 — the resource is
  still "owned" by the first winner. Confirmed claiming ≠ deleting (the
  container is still present at this point).
- **Case D (stale-row protection):** a DB row claiming session id `X` for a
  container **actually** labeled with a different session id `Y` (a
  simulated stale/incorrect row) → `process_claimed` returns `status:
  "refused"`, `detail: "ownership label mismatch..."`. The container is
  confirmed still present afterward — not deleted on the row's say-so alone.

All four: **PASSED.** Docker and Postgres confirmed clean after (no leaked
`ados-prime-*` containers, no leftover proof-mission rows).

## 5. Automatic reconciliation and sweeping — centralized, not scattered

**Before P12:** `session_reconcile.reconcile_abandoned_sessions` +
`orphan_sweep.sweep_once` were already automatic
(`_reconcile_and_sweep_orphans_periodically`, `backend/app/main.py`, one
`asyncio.create_task`, `Settings.orphan_reconcile_interval_seconds` default
300s). `capability_reconcile.mark_stalled_executions_unknown` +
`reconcile_outcome_unknown` were **manual-only** — confirmed by grep, zero
call sites outside `scripts/reconcile_capability_requests.py` and
`scripts/p9_crash_recovery_e2e.py`. Both functions' own module docstrings
say this is deliberate: the correctness guarantee (never silently
re-executed) never depended on either running automatically.

**P12's judgment call:** safety and Model B readiness are different bars.
An `outcome_unknown` row sitting unresolved until an operator remembers a
command fails "recovery does not depend on a human remembering manual
commands" even though it never fails "never silently duplicates a side
effect." Both functions are now **also** called from the exact same
centralized loop — not a second independent scheduler (this phase's own
instruction: "do not scatter independent background loops"). Each of the
now-four passes (reconcile sessions, sweep orphans, mark-stalled +
reconcile-outcome-unknown, reclaim admission state) is independently
try/excepted, so one pass's failure never blocks the others in the same
tick.

**Live proof, against the real running backend, not a manual function
call:** a genuinely stalled `capability_requests` row (status `executing`,
backdated 120s past the 60s stall bound) was inserted directly into the real
dev Postgres database the real `ados-backend-1`-equivalent process reads
from (a one-off container running current code, `ORPHAN_RECONCILE_INTERVAL_
SECONDS=8` for a fast observable tick). Within 15s, **with no operator
action of any kind**, the container's own logs showed:

```
"Capability executions stalled — moved to outcome_unknown" count=1
"Marked stalled capability executions outcome_unknown" count=1
"Reconciliation pass complete" checked=1 resolved=0 still_unknown=1
```

Independently re-verified via `psql`: `status = 'outcome_unknown'`. It
stayed there on every subsequent tick (no ServiceNow configured to provide
positive evidence) — never guessed, never auto-retried, matching P9's
design exactly. **This is the strongest single piece of evidence in this
phase**: automatic recovery, live, unattended, real infrastructure, zero
manual commands.

The same live container also proved admission-lease reclaim automatically:
a stale lease (backdated 3000s) was reclaimed on the next tick with a
`WARNING`-level log line, independently confirmed at 0 rows in Postgres
afterward.

## 6. NULL-expiry protection — the asymmetry closed

**Found:** `mcp_gateway.py::_resolve_session` — shared by `request_capability`,
`list_capabilities`, and `get_capability_request` — checked
`row.token_expires_at is not None and expired`, silently skipping the
entire branch when `token_expires_at IS NULL`. P10 taught this exact
reasoning to `runtime_approvals.py::_confirm_token_expiry_recorded_or_409`
(the approval endpoint) but never extended it to the earlier, more general
choke point every MCP tool shares. A NULL-expiry fossil session (the exact
shape doc 18 §16.6 already found 31 of, pre-P6-D or created by a debugging
tool bypassing the real creation path) whose `state` still read a live
value could call `request_capability` and reach **autonomous
auto-execution** — no human approval step, no `pending_approval` row for an
operator to notice, nothing.

**Fix:** `_resolve_session` now refuses `token_expires_at IS NULL`
unconditionally, incrementing the same `ados_token_expiry_refusals_total`
metric the expired-token branch already used. No new metric, no schema
change — the session rows themselves remain untouched, matching P10's own
"do not reinterpret existing rows" precedent.

**Regression from the fixture change:** four pre-existing test files
constructed sessions without `token_expires_at`, which the new guard
correctly now refuses — the same class of fixture update P10 itself needed
for two files. Fixed identically (`token_expiry(1800.0)`, the real creation
path's own helper): `test_capability_execution_state.py`,
`test_capability_grant_authorization.py`, `test_observability_logging.py`,
`test_mcp_gateway_admission.py`, `test_metrics.py`
(36 + 19 = 55 tests, all passing after the fixture fix — not weakened, each
now sets the value the real creation path always sets).

**New, dedicated tests:** `test_a_null_expiry_session_cannot_call_request_
capability` (test_approval_crash_recovery.py) and
`test_a_null_expiry_session_is_dead_even_while_state_is_live`
(test_runtime_session_auth.py) pin the new refusal directly. The
pre-existing `test_a_null_expiry_session_cannot_authorize_approval` was
**rewritten**, not just left passing: it now constructs the
`pending_approval` row directly (bypassing `request_capability`, which the
new upstream guard makes impossible for this session shape), since it is
now specifically testing the approval endpoint's own defense-in-depth for a
row that already exists — however it got there — not relying on the newer
guard as the only line of defense.

## 7. Rate limiting — the gap doc 18 named, closed minimally

**Distinct from admission control** (bounds in-flight count, not start
rate): doc 18 §D named this specifically — "None, on any endpoint,
including ones that call a paid LLM per request... a hard TPM ceiling was
already hit in testing." Confirmed by grep: zero token-bucket/sliding-
window/requests-per-window mechanisms existed anywhere.

**One limiter, scoped to the one capability the risk is named against:**
`integrations/rate_limiter.py::RateLimiter`, a fixed-window count against a
new table (`rate_limit_events`, migration `c4d5e6f7a8b9`) — bounds how
often `RunPrimeRLMAgent` (the capability that starts a real Docker
container and makes real paid-LLM calls) can be **started**, independent of
concurrency. `Settings.mission_start_rate_limit_max` (default 20) /
`_window_seconds` (default 300s) — generous relative to
`max_concurrent_prime_missions=3` but bounds a genuine restart-loop
(start → fail/refuse → restart) to a small multiple rather than leaving it
unbounded. `limit<=0` disables it (operator opt-out).

Enforced in `hub.invoke()`, immediately after the mission-concurrency gate
and before `connector.execute()` — before any Docker container or LLM call.
Server-side only; no `_`-prefixed governance hint or `call.input` field is
ever consulted.

**Tests:** `backend/tests/test_rate_limiter_hub.py` (3) — admits up to the
limit then refuses before the connector, records exactly one rejection
metric, releases concurrency slots it had taken before the rate-limit
refusal; disabled cleanly at `limit<=0`; scoped to `RunPrimeRLMAgent` only
(an ordinary capability call is unaffected even with the mission-start
limit exhausted). `backend/tests/test_admission_control_global.py` also
covers the limiter directly: below/at/over limit, a real concurrent race
(12 real `asyncio.gather` tasks, limit 4 → exactly 4 admitted), and window
expiry (an event outside the window is correctly ignored).

## 8. Observability — new metrics, live-verified against the real running process

Two new gauges (`backend/app/metrics.py`, computed live at scrape time in
`backend/app/routers/metrics.py`, same pattern as `ados_approval_queue_
depth`): `ados_admission_leases_active{gate}`, `ados_admission_lease_
oldest_age_seconds{gate}`. `ados_admission_rejections_total` gained a fifth
`gate` value, `mission_start_rate` (reusing the existing metric family and
label, not a parallel one). No high-cardinality label added anywhere — both
new gauges are labeled only by the same fixed, closed `gate` enum every
other admission metric already uses; `holder` (hostname:pid, on the
`admission_leases` row itself) is a plain DB column an operator can query,
never a Prometheus label.

**Live-verified**, not just unit-tested: rebuilt and recreated the real
`ados-backend-1` with current source, confirmed `GET /metrics` renders both
new gauges (`0.0` at rest for both gates), confirmed a real backdated lease
row moves `ados_admission_lease_oldest_age_seconds` to the correct value on
the very next scrape.

## 9. Alerting — two new rules, one proven live end-to-end

`infrastructure/prometheus/alert_rules.yml` grew from 16 to **18** rules
(both `promtool`-validated):

- **`ADOSMissionStartRateLimited`** — `increase(ados_admission_rejections_
  total{gate="mission_start_rate"}[15m]) > 0`, `for: 5m`.
- **`ADOSAdmissionLeaseStuck`** — `ados_admission_lease_oldest_age_seconds >
  1200`, `for: 5m` — an early warning before the automatic reclaim pass
  (1800s) would otherwise resolve it silently.

Descriptions on three pre-existing rules
(`ADOSMissionConcurrencyLimitHit`/`ADOSCapabilityConcurrencyLimitHit`/
`ADOSTokenExpiryRefusalBurst`) updated to state the P12 behavior change
(now globally enforced / now also covers NULL-expiry) — no `expr`/`for`
changed on any pre-existing rule.

**Live, end-to-end fire→deliver→resolve→deliver proof for
`ADOSAdmissionLeaseStuck`** — a real stale lease (1230s old, safely inside
the 1800s reclaim window so it wouldn't self-resolve mid-test) inserted
into the real dev database the real Prometheus target scrapes:

```
20:00:26  Prometheus: pending
20:03:22  Prometheus: firing
          Alertmanager: 1 alert (gate=capability_concurrency, severity=warning)
          webhook_receiver.log: status=firing
[lease deleted]
20:04:45  Prometheus: resolved (alert absent)
          webhook_receiver.log: status=resolved
```

`ADOSMissionStartRateLimited`'s underlying rejection mechanism (the metric
increment, real Postgres, real hub.invoke() call) is unit-proven in §7 —
a live Prometheus/Alertmanager cycle for this one specifically was not
additionally run, because triggering it for real requires passing
`RunPrimeRLMAgent`'s admission-control gate first, which means starting a
real Docker container/LLM call purely to exercise an alert — a heavier,
less-safe action than this phase's own "smallest safe test possible"
standard justifies for a rule whose PromQL condition and delivery path are
otherwise identical (byte-for-byte the same `expr`/`for`/receiver shape) to
`ADOSAdmissionLeaseStuck`, already proven live above, and to
`ADOSAuthFailureRateHigh`/`ADOSTargetDown`, already proven live in the prior
session (doc 22).

## 10. Postgres security — re-confirmed, unaffected

`ados_app`'s privileges re-verified live against the running container:
`SELECT, INSERT, UPDATE` on the three audit tables (no `DELETE`), no
`CREATE` on schema or database. The two new tables this phase added
(`admission_leases`, `rate_limit_events`) automatically inherited
`SELECT/INSERT/UPDATE/DELETE` via the existing `ALTER DEFAULT PRIVILEGES`
(migration `f4a5b6c7d8e9`) — confirmed live via `information_schema.role_
table_grants` immediately after each new migration ran. `DELETE` is
correctly granted on both (they are ephemeral concurrency-control state,
not audit tables — conflating them with the audit spine would have been
the wrong design, see `db/models/admission_lease.py`'s own docstring).
`backend/tests/test_database_role_privileges.py` (12 tests) re-run fresh:
**12 passed.**

## 11. Exactly-once / ambiguous-external-effect regression — unaffected, re-confirmed

P9's core invariant (never automatically retry an ambiguous external
effect) was not modified this phase. `capability_reconcile.py`'s own logic
is untouched; only its **scheduling** changed (§5). Re-ran fresh:
`test_capability_execution_state.py` (14), `test_capability_reconcile.py`
(10), `test_approval_crash_recovery.py` (9, incl. 2 new P12 tests),
`test_ados_skill_run_capability.py` (11), `test_capability_path_build_
identity.py` (3), `test_database_role_privileges.py` (12) — **58 passed
fresh**, zero regressions.

## 12. Negative controls

Six, covering every new/modified guard this phase's own instructions
named (a seventh, exactly-once, is unchanged by P12 — see §11; P9's own
six negative controls for it remain valid and were not re-run destructively
against production state again this phase). Each: guard disabled directly
in real source, targeted evidence re-gathered against real infrastructure,
confirmed to fail for the expected reason, guard restored, `shasum -a 256`
confirmed byte-identical before/after.

| # | Guard disabled | File | Targeted evidence | Observed failure |
|---|---|---|---|---|
| 1 | Global capability-slot rejection in `hub.invoke()` | `integrations/hub.py` | New test `test_hub_invoke_rejects_globally_even_when_this_processs_own_local_counter_is_fresh` (a "phantom other process" pre-seeded via `admission_leases`, isolating the global check from the always-correct local one) | Call **succeeded** when it should have been refused (local counter alone can't see another process's usage) |
| 2 | Docker ownership-label mismatch refusal | `orchestrate/runtime/orphan_sweep.py` | `scripts/p12_docker_ownership_proof.py` Case D, real Docker | Mismatched container **deleted** (`status: "cleaned"`) instead of refused |
| 3 | Automatic capability-request reconciliation call sites | `backend/app/main.py` | Live: real one-off backend container, real stalled row, 8s interval, 15s wait | Row stayed at `executing` — no log lines, no automatic transition at all |
| 4 | NULL-expiry refusal in `_resolve_session` | `backend/app/mcp_gateway.py` | 2 targeted tests (capability-path + auth-path) | Both failed — one with a `TypeError` from comparing `None`, itself evidence of the original unguarded gap |
| 5 | `mission_start_rate` rejection-metric increment | `integrations/hub.py` | `test_admitted_up_to_the_limit_then_refused_before_the_connector` | Counter delta `0`, expected `1` |
| 6 | Malformed PromQL in `ADOSAdmissionLeaseStuck` | `infrastructure/prometheus/alert_rules.yml` | `promtool check rules` + live Prometheus reload | `promtool` FAILED with a parse error; live reload refused it, keeping all 18 previously-valid rules active throughout |

All six files' final SHA-256 matches their pre-control value.

## 13. Full regression

Fresh, one pass, after all P12 changes (default suite):

```
866 passed, 19 deselected, 1 warning in 274.45s (0:04:34)
```

Zero failures this run — the two full-suite-only flakes seen in the
pre-P12-code baseline (§1) did not recur, consistent with them being
resource-contention artifacts rather than anything code-related.

`docker`-marked (requires Docker + built images):

```
17 passed, 868 deselected, 1 warning in 34.72s
```

`external`-marked: still 2 (unchanged — collected, not run, per this
repository's own safety convention; P12 created zero external side
effects, §14).

**Arithmetic, reconciled exactly:** baseline before any P12 code changed
was 845 passed + 2 failed (both isolated-pass, confirmed non-regressions,
§1) + 19 deselected = 866 total collected. P12 added 19 new tests
(`test_admission_control_global.py` 13, `test_hub_global_admission.py` 1,
`test_rate_limiter_hub.py` 3, plus 2 new tests inside existing files:
`test_a_null_expiry_session_cannot_call_request_capability`,
`test_a_null_expiry_session_is_dead_even_while_state_is_live`) = 866 + 19 =
**885 total collected** — exactly matching the fresh run's `866 passed +
19 deselected = 885`. The 19 deselected are unchanged in composition (17 `docker` + 2
`external`, both counts identical to P11) — P12 added no new
`docker`-marked test, since every new admission/rate-limiter test uses a
spy connector, never real Docker; real-Docker evidence for this phase
instead came from the two standalone proof scripts (§3, §4), run directly,
not as part of the pytest suite, matching `scripts/p9_crash_recovery_e2e.py`'s
own convention.

## 14. External side effects

**None.** No ServiceNow record was created or touched this phase (the
NULL-expiry fix's own regression test constructs a `pending_approval` row
directly rather than through a real park, specifically to avoid needing
one; the mission-start rate limiter's proof stayed at the unit-test tier
precisely to avoid a real Docker/LLM call — see §9). All real infrastructure
touched was local: Postgres (dev + test databases), Docker (lightweight
`alpine` containers + one rebuilt backend image), Prometheus, Alertmanager,
the local webhook receiver.

## 15. Cleanup verification

- `docker ps -a` / `docker network ls`: only the five persistent
  compose-stack containers/one default network before and after every proof
  script and every live-container exercise — confirmed via direct query
  after each one, not assumed.
- `admission_leases`, `rate_limit_events`: 0 rows in both the dev and test
  databases at the end of every phase of work.
- No proof-script mission/session/capability-request rows remain (`SELECT
  count(*) FROM missions WHERE title LIKE 'p12%'` → 0).
- `git status --short`: identical pre-existing unrelated dirty-file set,
  plus exactly the files listed in this document — verified by diffing
  against the session's own opening `git status` output.

## 16. Limitations, stated explicitly

- **Model C remains out of scope and NOT READY**, unaffected by this phase
  by explicit instruction: multi-host Docker ownership, tenant isolation,
  and distributed rate limiting beyond the single mechanism built here are
  all still `NOT BUILT`.
- **`--workers` is still absent from the Dockerfile, for a reason P12 did
  not touch:** MOA/ITSM paused-approval state is still per-process
  in-memory in places (`app.state`-adjacent structures noted in that
  comment), which is a separate, larger blocker to real horizontal scale-out
  than admission control ever was. P12 closes the admission-control-specific
  gap; it does not claim ADOS can safely run `--workers 2` today. The
  practical value of this phase's fix is Model B resilience against
  *accidental* double-start (a botched restart overlap, a deploy script
  race) and a real foundation for the day the MOA-state blocker is also
  closed — not a claim that horizontal scale-out is ready now.
- **`ADOSMissionStartRateLimited`'s live Alertmanager delivery was not
  additionally proven** beyond the unit/mechanism tier, for the safety
  reason given in §9 — the underlying rejection and metric increment are
  fully proven against real Postgres and a real `hub.invoke()` call.
- **Reclaim/rate-limit-window defaults are operator-tunable ceilings, not
  load-tested capacity numbers** — same posture every other Settings default
  in this codebase already carries (doc 18's own recurring caveat).
- **The `docker compose build backend` vs. `migrate` image-staleness trap**
  (§2 of the runbook, newly documented) is a real operational hazard
  discovered while preparing this phase's own evidence — not fixed at the
  `docker-compose.yml` level (a Compose behavior, not a bug in this
  repository's config), only documented so an operator doesn't lose time to
  it.
- **Build identity remains a no-op inside the shipped Docker image**
  (`commit: "unknown"`, no `.git` in the build context) — inherited,
  unchanged, confirmed live again this phase.

## 17. Acceptance matrix

| Area | Status |
|---|---|
| Metrics endpoint | DEMONSTRATED (P11; live-reconfirmed this phase) |
| Prometheus scraping | DEMONSTRATED (doc 22; live-reconfirmed this phase) |
| Alertmanager delivery | DEMONSTRATED (doc 22; `ADOSAdmissionLeaseStuck` proven live this phase) |
| Alert resolution | DEMONSTRATED (`ADOSAdmissionLeaseStuck` fire→deliver→resolve→deliver, live) |
| Distributed admission — concurrency ceilings | **TESTED** (real, separate OS processes; exact admitted/rejected counts) |
| Distributed admission — approval/session gates | CONFIRMED already-global; DEMONSTRATED with 2 real OS processes this phase |
| Rate limiting | TESTED (real Postgres concurrent race; hub-level rejection-before-connector proof) |
| Process crash recovery — sessions/orphans | DEMONSTRATED (P7-C/D; unaffected, re-confirmed) |
| Process crash recovery — admission leases | DEMONSTRATED (real `SIGKILL`, real reclaim pass, live container) |
| Docker recovery (ownership/lease/mismatch) | CONFIRMED (P7-C mechanism; DEMONSTRATED with real concurrent processes this phase, 4/4 cases) |
| Automatic reconciliation (sessions/orphans) | DEMONSTRATED (P7-D; unaffected) |
| Automatic reconciliation (capability_requests) | **DEMONSTRATED live this phase** (was DESIGNED/manual-only through P11) |
| Orphan sweeping | DEMONSTRATED (P7-C/D; unaffected) |
| Exactly-once protection | DEMONSTRATED (P9; unaffected, re-confirmed fresh this phase) |
| NULL-expiry protection — approval path | DEMONSTRATED (P10; unaffected) |
| NULL-expiry protection — capability-execution path | **TESTED — closed this phase** (was a real, undocumented gap through P11) |
| Postgres security | DEMONSTRATED (P10; live-reconfirmed this phase, incl. 2 new tables) |
| Build identity | TESTED (P7-B/D/P10; unaffected, no-op inside shipped image, confirmed live) |
| Operator runbook | DESIGNED, extended this phase (§13, §13a, §2, §7, §9 updated/added) |
| Negative controls (P12-specific) | 6/6 DEMONSTRATED, byte-identical restoration confirmed |
| Model A | READY |
| Model B | **READY** (named limitation: `--workers`-based horizontal scale-out remains separately blocked, not attempted) |
| Model C | NOT READY (out of scope, unaffected) |

## 18. Model A / B / C verdict

### Model A — Controlled Internal Production

**Still READY.** Nothing in P12 regressed any Model A guarantee — the 58
P9/build-identity/Postgres-security tests re-run fresh all pass, the
admission-control/rate-limiter additions are purely additive
(`session_factory=None`/`limit<=0` preserve prior behavior exactly), and
every negative control confirmed restoration to byte-identical source.

### Model B — Production Long-Running Service

**READY**, on the evidence gathered this phase:

- **Global admission control is safe across processes** — proven with real,
  separate OS processes, exact admitted/rejected counts, zero "no exception
  occurred" reasoning (§3).
- **Recovery does not depend on a human remembering manual commands** —
  proven live, on the real running process, for both stalled-execution
  reconciliation and admission-lease reclaim, with zero operator action
  taken during the observation window (§5).
- **Critical failures are observable** — two new metrics, two new alert
  rules, one proven live fire→deliver→resolve→deliver end to end (§8, §9).
- **Prometheus actually scrapes ADOS; Alertmanager actually receives and
  delivers; alerts resolve correctly** — re-confirmed fresh this phase, not
  assumed from the prior session (§9).
- **Exactly-once ambiguity remains safe** — unchanged, re-confirmed via
  fresh regression (§11).
- **Postgres security remains intact** — re-confirmed live, including for
  the two new tables (§10).
- **A previously-unknown, more serious NULL-expiry gap (autonomous
  auto-execution, not just approval) was found and closed** — the kind of
  finding this phase's own "do not assume previous phase reports are
  correct" instruction exists to surface (§6).
- **Rate limiting**, the other item doc 18 named and no prior phase built,
  is now real, minimal, and justified against the specific named risk (§7).

**Named, not hidden, limitation:** true horizontal scale-out
(`--workers 2`+) is still blocked by MOA/ITSM state being per-process —
P12 did not attempt to close that, and Model B as scoped here means "one
long-running process, bounded, observable, and recoverable without a human
babysitting it," not "N processes." That is the correct, smaller claim this
evidence actually supports.

### Model C — Distributed Multi-Tenant

**NOT READY, unaffected by this phase, by explicit instruction.**
Multi-host Docker ownership, a tenancy concept, and distributed rate
limiting beyond the single-database mechanism built here remain `NOT
BUILT`. Not attempted; not claimed.

---

**STOP after P12. P13 was not started.**
