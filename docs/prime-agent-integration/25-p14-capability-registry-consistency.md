# P14 — Dynamic Capability Consistency & Hot-Disable Safety

**Date:** 2026-08-14
**Baseline:** working tree on top of `7464902` (unchanged — no P11/P12/P13/P14 commit exists; all four phases remain uncommitted working-tree state, confirmed by `git log -1` and `git status`, not assumed).

## 1. Verdict

**PASS.** The specific question this phase asked — *if worker A changes,
disables, enables, or otherwise updates a capability, can worker B continue
operating from stale in-process capability state and accidentally execute
something the current server-side policy says is disabled? — is now
provably **no**, demonstrated live across real, separate OS processes
(`scripts/p14_multiprocess_capability_proof.py`), not merely covered by
tests that happen to pass.

Both gaps P13 explicitly deferred are closed:

1. `hot_disable_policy_rule` cache staleness (P13's own named gap) — closed.
2. Dynamic capability registry / dispatch-config propagation (P13's other
   named gap) — closed.

A third, related gap not previously documented anywhere was found and
closed during this phase's own live proof (§4, Fix #1 note) — a real
regression the fix's *first* implementation introduced, caught by the
mandatory real-process proof, not by any of the lighter pytest-level tests
written first.

## 2. Fresh baseline — re-derived, not assumed

Per this phase's explicit instruction not to trust P13's own conclusions:

- `git log -1`: `7464902` — same commit P12/P13 both built on top of.
- `git status --short`: only P14's own files below, plus P11/P12/P13's
  already-uncommitted files (untouched), plus the same pre-existing
  unrelated dirty tree (untouched) already noted in every prior phase's
  report.
- Fresh default suite before any P14 change: 876 passed / 0 failed / 19
  deselected — matches P13's own final reported state exactly (zero drift
  between sessions, confirmed not assumed).
- Fresh docker-marked suite before any P14 change: 17 passed / 0 failed —
  same.
- Docker/Postgres clean before starting: only the 5 persistent compose
  containers, no leaked networks, `admission_leases`/`rate_limit_events`
  at 0 rows.

## 3. Architecture actually discovered (Phase 1 audit, from source)

Traced directly from code, not from documentation:

- **`orchestrate/moa/dynamic_registry.py`'s `_ENTRIES`** — process-local
  dict (MOA action-menu visibility only). Filters live against whatever
  `CapabilityManifestRegistry` instance it's given at read time — safe by
  construction as long as that registry is itself authoritative (see next
  point); on its own this only controls whether the LLM is *offered* an
  action, never whether an attempted invocation succeeds.
- **`integrations/capability_manifest.py`'s `CapabilityManifestRegistry`**
  — the actual governance state machine (PROPOSED → SANDBOX_TESTED →
  ACTIVE → HOT_DISABLED/DEPRECATED). **Authoritative in Postgres** when
  constructed with a `session_factory` (the real app always does this,
  `backend/app/main.py`). **Process-local and NOT authoritative** in its
  own `self._manifests` in-memory dict — this dict is the actual hot-path
  read every governance decision consults, and before this phase it was
  updated **only** by a mutating call *this specific instance* made, or by
  `list_manifests()`. A `hot_disable()` issued through a *different*
  worker's own registry instance — the normal case under `--workers 2+`,
  or simply two separate ADOS processes — writes Postgres correctly but
  never touches this instance's cache. A status this process had already
  cached as ACTIVE stayed ACTIVE here **forever**, not just briefly.
- **`hot_disable_policy_rule`** (former mechanism, removed this phase) —
  a synchronous `ConnectorPolicyEngine` `PolicyRule`
  (`Callable[[CapabilityCall], None]`, no `await` possible — see
  `integrations/policy_engine.py`), reading the same stale in-memory dict.
  This was the exact gap P13 named as `hot_disable_policy_rule reading
  CapabilityManifestRegistry._manifests` — "self-heals on a cache *miss*,
  not on present-but-stale data."
- **`integrations/connectors/dynamic.py`'s `DynamicCapabilityConnector`**
  — the actual execution choke point for every dynamically onboarded
  ("Bring Your Own Capability") call. Independently required `manifest.
  status is ACTIVE` (a broader, stricter check than hot-disable alone —
  also correctly refuses PROPOSED/SANDBOX_TESTED/DEPRECATED), but — a
  gap **not named by P13**, found fresh by this phase's own re-derivation
  — that check also read the same process-local, self-heal-on-miss-only
  cache. Once warmed (by any prior successful call), it never refreshed
  again on its own.
- **`integrations/hub.py`'s `IntegrationHub.invoke()`** — confirmed, by
  direct grep, the *only* call site of `connector.execute()` anywhere in
  the codebase. Every caller (MOA/orchestrator, `mcp_gateway.py`'s
  in-mission calls, the direct `POST /capabilities/invoke` endpoint) funnels
  through this one function — the correct, single, universal execution
  boundary (Phase 1 Q8 — "does the MCP path and incident/Prime Agent path
  behave consistently" — trivially yes, by construction, since it is
  literally the same function).
- **`DynamicCapabilityConnector`'s `resolver`** — a designed, pre-existing
  cache-miss fallback (`ResolverFn`, an optional constructor argument)
  that `default_hub()` had simply never wired to anything real. This is
  the exact mechanism P13's own report named as the smallest fix for its
  first deferred gap ("dynamic capability registry propagation") —
  confirmed still unwired at the start of this phase, and wired in as
  Fix #2 below.
- **Admission control, rate limiting, ITSM/manufacturing-incident
  approval, MOA/ITSM checkpointer state** — re-confirmed (not re-derived
  from scratch; already exhaustively proven safe in P12/P13, unaffected by
  anything in this phase's scope) unchanged and unaffected by this fix.

### Classification (Phase 1's A/B/C/D/E taxonomy)

| Component | Class | Note |
|---|---|---|
| `dynamic_registry._ENTRIES` | A | Process-local, safe to remain so — LLM-menu visibility only, never authorizes execution on its own |
| `CapabilityManifestRegistry._manifests` (in-memory cache) | **D → fixed to C** | Was: shared-in-concept, incorrectly synchronized (staleness with no bound). Now: a cache that is always refreshed authoritatively at the two real execution boundaries before it can matter |
| `CapabilityManifestRegistry` Postgres rows | C | Already shared, already correct — the fix makes the in-memory layer defer to this properly, not a change to the source of truth itself |
| `hot_disable_policy_rule` | **D, removed** | Was actively harmful once an authoritative read could poison its cache (see Fix #1's regression note) — removed, not just patched |
| `DynamicCapabilityConnector._dispatch` (dispatch config cache) | **D → fixed to C** | Same staleness shape as the manifest cache, for a different piece of state; closed by wiring the resolver (Fix #2) |
| `IntegrationHub.invoke()` | A | Already the single universal choke point; unaffected in shape, extended with the new authoritative check |
| Admission control, rate limiting, approval queue, idempotency, audit, provenance, build identity | C | Unaffected by this phase; already Postgres-authoritative per P11/P12/P13 |

## 4. The safety invariant (Phase 2)

> No worker may execute a capability based solely on stale process-local
> registry state when the authoritative server-side state says that
> capability is disabled, revoked, unavailable, or otherwise prohibited.

Intended behavior, as implemented:

| Scenario | Behavior |
|---|---|
| Registry update (any mutating call) | Persists to Postgres first, inside the existing row-locked transaction (unchanged from P8's migration); the *local* cache of the writer updates too, but no other process's cache is touched — propagation to other workers happens at their own next authoritative read, not by push/broadcast |
| Capability disable | Blocked at both real execution boundaries (§5) with a fresh Postgres read, not a cache — see live proof §7 |
| Capability enable (resume) | Symmetric — a resume is visible at the next authoritative read exactly as fast as a disable is; proven live, not assumed (§7 Case 2) |
| Capability deletion | Not supported by this system (no `delete()`/`remove()` exists) — the two real "this no longer works" states are `hot_disable()` (hard, immediate) and `deprecate()` (soft, no invocation block) |
| Unknown capability (never proposed) | Refused, `result=not_found`; unaffected by this phase, already correct before it (proven not to have regressed, §9) |
| Worker restart | A brand-new registry instance has an empty cache and gets the correct current state on its very first read — no special-case "hydrate" logic needed for correctness, only the existing `hydrate_all()`'s already-separate concern of *dispatch config* warm-up for MOA's own convenience |
| Database unavailable | **Fails closed.** An authoritative-lookup exception refuses the call (`result=lookup_failed`) rather than falling back to a stale cache. A DB outage is treated as "cannot confirm this is safe," never as "assume yesterday's cache is still right" |
| Registry refresh failure | Same as above — refresh failure and lookup failure are the same code path (`refresh_from_db`'s own exception propagates to the caller, which converts it to a structured FAILED response) |
| Concurrent update + execution | Documented precisely, not hand-waved — see §7 Case 3. A request whose authoritative read genuinely precedes a disable's commit is allowed to complete; this is not a bug, it mirrors what "disabled while in flight" already meant everywhere else in this codebase (no claim of cancelling in-flight external work is made here either — consistent with the rest of this program's existing posture) |

No new distributed-coordination mechanism was introduced. Per Phase 3's
own explicit preference, the fix is **Option A — a per-request
authoritative Postgres lookup at the execution boundary**, not a cache
invalidation broadcast, not a TTL, not Redis/Kafka/any new service.

## 5. The fix (Phase 3/4)

**Alternatives considered, explicitly:**

- **A. Per-request authoritative DB lookup** — chosen. Simplest, reuses
  existing Postgres-as-source-of-truth idiom this codebase already applies
  everywhere else (P11/P12's admission leases, P13's approval-queue claim),
  no new infrastructure, no new failure mode beyond "the DB call itself can
  fail," which is already handled everywhere else in this codebase by
  failing closed.
- **B. Short-lived cache with bounded TTL** — rejected. Trades an unbounded
  staleness window for a *bounded but still real* one, and adds a second
  thing to reason about (what TTL is safe? measured against what
  attacker/incident-response SLA?) for no benefit over A given this
  system's actual capability-call volume (governed enterprise actions, not
  high-QPS traffic).
- **C. Postgres LISTEN/NOTIFY invalidation** — rejected. Genuinely more
  correct in theory (push instead of poll) but adds a persistent
  subscription per worker, a reconnect/backfill story, and an entirely new
  failure mode ("the notification channel silently stopped delivering") for
  a system whose real call volume does not need it.
  `db/engine.py`'s own documented `NullPool` choice (a fresh connection per
  checkout, closed on checkin — see that module's docstring) is actively in
  tension with a long-lived LISTEN connection, which would need its own,
  different pooling story.
  Deferred to a future phase if real load ever demands it.
- **D. Versioned registry with worker refresh** — rejected as unnecessary
  complexity: this is a version of C with extra bookkeeping (a version
  counter, a refresh-on-version-mismatch protocol) for the same benefit A
  already provides at a fraction of the implementation and reasoning cost.
- **E. None found** — the existing architecture (Postgres as the one
  source of truth, already used this way for every other governance
  mechanism in this codebase) does not require anything beyond A.

**Two independent execution-boundary checks were touched, both using one
new shared primitive:**

`CapabilityManifestRegistry.refresh_from_db(capability_id)`
(`integrations/capability_manifest.py`) — a fresh, non-locking
`SELECT` immediately before a capability may run, replacing the previous
`manifest_for()` self-heal-only-on-a-cache-miss behavior. Repairs the
in-memory cache to match as a side effect (so other, non-execution-path
readers — the MOA action menu, `_effective_policy_tier`'s tier lookup —
also benefit opportunistically, though neither is itself a safety
boundary). In pure in-memory mode (`session_factory=None`, every bare test
construction) this degrades to exactly the old `manifest_for()` behavior —
zero change for ~800 existing tests that never pass a `session_factory`.

1. **`IntegrationHub.invoke()`** (`integrations/hub.py`) — the universal
   choke point for every capability call, dynamic or built-in. Right after
   `select_connector()` succeeds, before admission control, before any
   connector runs: an authoritative HOT_DISABLED check (the same condition
   `hot_disable_policy_rule` used to enforce from a stale cache, now fresh).
2. **`DynamicCapabilityConnector.execute()`** (`integrations/connectors/
   dynamic.py`) — the dynamic-capability-specific, broader
   ACTIVE-required check (also blocks PROPOSED/SANDBOX_TESTED/DEPRECATED,
   not just HOT_DISABLED), now also authoritative.

**`hot_disable_policy_rule` was removed, not just supplemented** — see
the regression note below for why keeping it alongside the new checks was
actively wrong, not merely redundant.

**Fix #2 — dispatch-config propagation** (`orchestrate/onboarding/
runtime_registry.py`, `integrations/connectors/dynamic.py`, `backend/app/
main.py`): a new `resolve_dispatch_config()` function (reusing the exact
DB lookup `register_runtime()` already performs) is wired into
`DynamicCapabilityConnector` via a new `set_resolver()` method, called
once at app startup. A capability activated on worker A is now invocable
on worker B on its very first attempt, no restart — closing P13's other
named gap.

### A real regression found by the mandatory live proof, not by any pytest test

The first implementation of Fix #1 kept `hot_disable_policy_rule`
registered *alongside* the new authoritative `invoke()` check, reasoning
it was harmless "defense in depth." `scripts/p14_multiprocess_capability_
proof.py`'s Case 2 (resume-after-disable, across two real OS processes)
caught a genuine bug this created: the synchronous rule reads the *same*
`self.manifests._manifests` cache the new authoritative check writes to.
The first authoritative read that ever caches HOT_DISABLED poisons the
synchronous rule going forward — a later `resume()` (authoritative in
Postgres) updates the *authoritative* check's own next read correctly, but
`select_connector()` raises from the *stale* synchronous rule **before**
that authoritative check ever runs, permanently and incorrectly blocking a
legitimately re-activated capability. Worse, this was **inconsistent
across paths**: `connector.execute()` (which never goes through
`select_connector()`) correctly allowed the same call `hub.invoke()`
incorrectly refused — a real answer to Phase 1's own Q7/Q8 ("can a
disabled capability still be invoked through an alternate path" / "do the
MCP and incident paths behave consistently") that only the genuine
two-process, resume-after-disable sequence exposed. None of the
single-process pytest tests written first happened to exercise a
disable-then-resume sequence through `hub.invoke()` specifically, which is
exactly why Phase 5 mandates real infrastructure rather than trusting
tests that merely pass.

**Fix:** `hot_disable_policy_rule` was deleted (`integrations/
capability_manifest.py`) and its registration removed from
`IntegrationHub.__init__` (`integrations/hub.py`) — the authoritative
`invoke()` check fully subsumes its exact behavior (same condition, same
error wording) with none of the cache-poisoning failure mode, since it
never trusts anything cached before it runs. Re-verified: the full
multi-process script now passes all cases (§7); the existing
`hot_disable_policy_rule`-adjacent tests
(`tests/test_connectors.py::test_hub_blocks_invocation_of_a_hot_disabled_
capability` and neighbors) still pass unchanged, since the new check
produces byte-identical error wording.

## 6. Why this is safe under multiple workers

- **Single choke point per concern.** `connector.execute()` has exactly
  one call site (`hub.invoke()`, confirmed by grep). Every caller —
  MOA/orchestrator, `mcp_gateway.py`'s in-mission MCP calls, `POST
  /capabilities/invoke` — is the same function, so there is no second,
  differently-guarded path to a real side effect.
- **No caller-supplied field is ever trusted.** The lookup id resolution
  (`resolve_capability_lookup_id`) reads only `call.capability` and, for
  the one sentinel case, `call.input["capability_id"]` — the identity of
  *which* capability, never *whether* it's authorized; authorization is
  always a fresh server-side Postgres read, exactly matching this
  program's pre-existing "nothing in `call.input` is ever consulted for
  admission" posture (P11).
- **Fails closed on ambiguity.** A DB-unavailable authoritative lookup
  refuses rather than assumes.
- **No claim of stronger consistency than is actually provided.** A
  request whose authoritative read precedes a disable's commit by a
  microsecond is allowed to complete — documented, not hidden (§4, §7
  Case 3).

## 7. Real multi-process proof (Phase 5 — mandatory)

`scripts/p14_multiprocess_capability_proof.py` — real `multiprocessing.
Process` (`spawn` context: fresh interpreters, no inherited Python state),
real Postgres (`ados_test`), real `IntegrationHub`/`DynamicCapability
Connector` instances constructed independently per process. Not pytest —
same standalone-script convention as `scripts/p9_crash_recovery_e2e.py`
and `scripts/p11_orphan_recovery_exercise.py`, chosen specifically because
P13's own report found that multiple `TestClient(app)` instances inside
one pytest process all share **one** process's `app.state` — not a valid
multi-process proof at all. Run twice: once exposing the regression above
(§5), once clean after the fix. Full clean transcript, all cases:

```
=== Case 1 — disable propagation (no restart) ===
  [PASS] worker A activated the capability
  [PASS] worker A's own warm-up call succeeds
  [PASS] worker B's warm-up call succeeds (B independently caches ACTIVE)
  [PASS] worker B and worker A are genuinely different OS processes
  [PASS] worker A's hot_disable succeeds
  [PASS] worker B refuses the SAME already-running process, no restart, no explicit refresh
  [PASS] worker B's executor did not run again (no external side effect)

=== Case 2a — enable propagation, status half (resume, no restart) ===
  [PASS] worker A's resume succeeds
  [PASS] worker B (same process) can execute again after resume, no restart

=== Case 2b — enable propagation, dispatch-config half (resolver) ===
  [PASS] worker A activated the capability
  [PASS] worker C never cached this capability before its first attempt
  [PASS] worker C's FIRST-EVER attempt succeeds via the resolver self-heal (no restart, never activated locally)

=== Case 3 — concurrent disable vs execution, 15 real-process trials ===
  [PASS] (all 15 trials) post-race state is consistently refused
  race outcome distribution across 15 trials: 0 succeeded (read won), 15 refused (disable won)
  [PASS] every trial produced a structured status, never a raise/timeout
  [PASS] the race is genuinely exercised (not artificially serialized to one side)

=== Case 4 — stale worker: a deliberately wrong local cache authorizes nothing ===
  [PASS] stale worker's cache was force-poked to ACTIVE
  [PASS] the poke actually took effect in that process's own memory
  [PASS] execution is refused despite the process's own cache insisting ACTIVE

=== Case 5 — restart: a brand-new process sees the same authoritative state ===
  [PASS] restarted worker's cache starts genuinely empty
  [PASS] restarted worker correctly refuses the already-disabled capability, first attempt
  [PASS] restarted worker correctly ALLOWS a genuinely active capability, first attempt (not just 'always refuses')

=== Case 6 — alternate execution path: hub.invoke() vs connector.execute() directly ===
  [PASS] hub.invoke() and connector.execute() agree on the same worker for the same capability
  [PASS] independent post-cleanup verification: 0 capability_manifests rows remain
  [PASS] independent post-cleanup verification: 0 capability_promotion_events rows remain
  [PASS] independent post-cleanup verification: 0 onboarding_sessions rows remain

RESULT: PASS — all checks passed across real, separate OS processes.
```

### Case 3, honestly characterized

Across 15 real, genuinely concurrent trials (`asyncio.gather` firing a
`hot_disable` on one real OS process and an `execute` on a different real
OS process against the same Postgres row, with no artificial
synchronization forcing an order), the disable won every trial (15/15
refused, 0/15 executed) in this measurement. This is an **empirical
observation about the current relative cost of the two operations**
(`hot_disable` is a single row-locked write; `execute` performs a
`select_connector` call, an admission-control round trip, and its own
independent authoritative read before ever reaching this point) — **not a
designed guarantee**. The actual guarantee, proven independently of that
distribution: every single one of the 15 post-race confirmation attempts
(a second, unraced `execute()` immediately after) was refused —
demonstrating the system always converges to the correct state regardless
of which side of a genuine race happens to win, and the authoritative-
lookup counter's delta (verified in the equivalent pytest-level test,
`backend/tests/test_capability_registry_multiworker_safety.py::
test_concurrent_hot_disable_and_execute_converges_correctly_across_many_
trials`) confirms every single attempt was actually gated, never silently
bypassed.

### Cleanup

All `capability_manifests` / `capability_promotion_events` /
`onboarding_sessions` rows this script created (prefixed
`p14.mp_proof.<run-id>.*`) are deleted at the end of every run, and
deletion is independently re-verified with a fresh `COUNT` query before
the script reports success — confirmed 0/0/0 remaining in the clean run
above.

## 8. Negative controls (Phase 6)

Four, each: guard disabled directly in real source, targeted evidence
re-gathered and confirmed to fail for the expected reason, guard restored,
`shasum -a 256` confirmed byte-identical before/after.

| # | Guard disabled | File | Targeted evidence | Observed failure |
|---|---|---|---|---|
| 1 | The connector's authoritative ACTIVE-status gate | `integrations/connectors/dynamic.py` | `test_stale_cache_alone_cannot_authorize_execution` | Execution succeeded via a deliberately wrong, fabricated ACTIVE cache entry — the connector-level protection is load-bearing (`hub.invoke()`'s own independent check still caught the *other*, hub-level test, correctly demonstrating defense-in-depth rather than a single point of failure) |
| 2 | `refresh_from_db`'s actual Postgres consultation (stubbed to always return the cache) | `integrations/capability_manifest.py` | `test_hot_disable_from_worker_a_is_observed_by_worker_b_without_restart` | Failed even earlier than the disable step itself — without ever consulting Postgres, worker B's cache can never converge to the correct state via any path, an even stronger demonstration that this consultation is load-bearing |
| 3 | The hub-level authoritative hot-disable check | `integrations/hub.py` | `tests/test_connectors.py::test_hub_blocks_invocation_of_a_hot_disabled_capability` (a **built-in** capability with a manifest — the one case with no independent connector-level check to fall back on) | Execution succeeded for a hot-disabled capability — this specific guard is the *only* protection for built-in capabilities carrying a manifest, proven by disabling it in isolation |
| 4 | The write side: `hot_disable()`'s actual `row.status = HOT_DISABLED` assignment | `integrations/capability_manifest.py` | `test_hot_disable_from_worker_a_is_observed_by_worker_b_without_restart` | Worker B correctly kept reading ACTIVE — the disable never actually persisted, proving the read-side fix alone is meaningless without a working write side, and that this test suite is actually exercising real Postgres state, not a mock |

All three touched files' final SHA-256 match their pre-control baseline.

## 9. Tests (Phase 7)

New: `backend/tests/test_capability_registry_multiworker_safety.py` — 12
focused tests (enabled/unknown/disable-propagation/stale-cache/resume-
propagation/resolver-propagation/resolver-negative-control/concurrent-
race/restart/alternate-paths/DB-failure-fails-closed/stale-cache-metric).
Renamed for accuracy (no count change): `tests/
test_dynamic_capability_connector.py::
test_hot_disabled_dynamic_capability_blocked_by_hub_check_not_just_
connector` (was `..._by_policy_rule_not_just_connector`, since the
mechanism it distinguishes moved from a `PolicyRule` to `invoke()`'s own
check).

- **Focused set** (all capability-manifest/dynamic-connector/onboarding
  files + the new P14 file): 106 passed / 0 failed.
- **Full default suite, fresh, final:** 888 passed / 0 failed / 19
  deselected. Arithmetic: 876 (P13's own final baseline) + 12 (this
  phase's new tests) = 888 — matches exactly.
- **Docker-marked suite, fresh, final:** 17 passed / 0 failed — unchanged
  from P13 (this phase touched no docker-marked code path; none of the 12
  new tests are docker-marked — the real multi-process proof is a
  standalone script, per this program's own established convention for
  infrastructure-heavy proofs, not a pytest test).

## 10. External side effects (Phase 8)

**None.** No ServiceNow record was created or touched — this phase's
entire proof (both the pytest-level tests and the real multi-process
script) uses fake in-repo executors and real Postgres/onboarding_sessions
rows, all independently verified as cleaned up. Consistent with this
program's own established bar ("create external records only when
genuinely necessary to prove the specific invariant") — nothing about
registry propagation or hot-disable safety requires a real external
system to demonstrate.

## 11. Observability (Phase 9)

Two new metrics (`backend/app/metrics.py`):

- `ados_capability_registry_authoritative_lookups_total{result}` —
  `allowed | hot_disabled | not_active | not_found | lookup_failed`.
  Fires at both execution boundaries. Directly answers "capability
  disabled/refused" (`hot_disabled`/`not_active`), "authoritative lookup
  failure" (`lookup_failed`).
- `ados_capability_registry_stale_cache_detected_total` — increments only
  when a fresh authoritative read genuinely disagrees with what this
  process had already cached (not on a first-ever/cache-miss read) —
  directly the "stale registry detection" *and* "successful propagation"
  signal Phase 9 asked for: an operator seeing this counter move is
  observing a worker catch up to a change made elsewhere, live.

Not vacuous, proven by delta-based tests (this codebase's own established
convention, since `prometheus_client`'s registry is process-global across
the whole pytest session):
`test_stale_cache_detected_metric_fires_only_on_genuine_disagreement`,
`test_authoritative_lookup_failure_fails_closed` (asserts the
`lookup_failed` delta), and the concurrent-race test's own delta check
(exactly 2 authoritative-lookup increments per trial, proving the gate ran
every single time, never bypassed). `GET /metrics`'s existing exhaustive
name-presence test
(`backend/tests/test_metrics.py::test_metrics_endpoint_renders_valid_
prometheus_text`) extended to include both new metric names.

No new alert added to `docs/prime-agent-integration/19-metrics-and-
alerting.md` — neither new counter has an obvious threshold-based alert
shape (a *rate* of `hot_disabled`/`not_active` refusals could indicate a
misconfigured capability being repeatedly retried, but that is an
operational tuning question better answered with real production traffic
data than guessed at here; `stale_cache_detected_total` moving is
*expected, healthy* behavior, not an incident signal, in the same way a
cache hit-rate metric alone doesn't warrant an alert).

## 12. Remaining limitations, honestly

- **The empirical Case 3 distribution (§7) is a measurement, not a
  guarantee.** Under different relative latencies (e.g., a much slower
  `hot_disable` write, or a much faster `execute` path), a real request
  could legitimately win a race against a concurrently-issued disable —
  documented as correct, expected behavior (§4), not a defect, but worth
  restating here: this phase did not, and does not claim to, make
  disable-vs-execute atomic across the two operations. Achieving that
  would require holding the same row lock `hot_disable()`/`resume()`
  already use for the authoritative read too — deliberately not done,
  since holding a write-serializing lock for the duration of every
  capability *read* would let a slow capability execution stall every
  other worker's disable/resume/activate call on that same capability,
  a strictly worse tradeoff for this system's actual needs.
- **MOA action-menu staleness is unfixed, by design.** `dynamic_registry.
  _ENTRIES`'s own visibility can still lag a disable/enable by however
  long it takes for something to next call `list_manifests()` on that
  worker. This is explicitly not a safety issue (§3's classification: a
  stale-but-offered action still cannot actually execute, since both real
  execution boundaries are now authoritative regardless of what the LLM
  was shown) — it is a minor UX/wasted-turn cost, correctly out of this
  phase's invariant.
- **Built-in capabilities with a manifest are a narrow, real, but
  low-priority edge case.** The onboarding pipeline is designed for
  dynamically onboarded ("BYOC") capabilities; nothing in the current
  admin UI proposes a manifest for a *built-in* `Capability` enum value.
  The mechanism exists and is tested (`tests/test_connectors.py`) and is
  now correctly authoritative (negative control 3, §8), but has no live
  operational path exercising it today.
- **Postgres LISTEN/NOTIFY-based push invalidation remains unbuilt, by
  choice** (§5, Option C) — the per-request read this phase implements is
  the smallest correct mechanism for this system's actual scale; revisit
  only if real capability-call volume ever makes the added per-call
  Postgres round trip a measured problem.

## 13. Model A / B / C readiness impact

- **Model A (Controlled Internal Production):** unaffected, still READY.
  Every change is additive to the two execution boundaries; the full
  regression suite confirms zero regressions among the ~876 pre-existing
  tests.
- **Model B (Production Long-Running Service):** unaffected, still READY
  — a single-process claim, untouched by this phase.
- **Model C (Distributed Multi-Tenant / Horizontal Scale-Out):** this
  phase closes both of P13's own named remaining gaps for the specific
  invariant "a disabled capability cannot execute on a stale worker."
  Combined with P13's own fixes (manufacturing-incident approval
  visibility, admission-control wiring), the concrete, named blockers this
  program has found for `--workers 2+` across mission/incident/approval/
  admission-control/dynamic-capability flows are now closed and proven
  under real concurrent, multi-process load. **Still not a "Model C:
  READY" verdict** — multi-tenancy and multi-host Docker/container
  ownership remain entirely unattempted and out of scope, exactly as every
  prior phase already said; this phase closes a specific, named class of
  bug, not the full distributed-platform requirement set.

## 14. Exact remaining blockers

None found in this phase's scope (dynamic capability consistency /
hot-disable safety) that were not already closed. Carried forward,
unattempted by any phase, per the honest Model C scoping above:
multi-tenancy, multi-host container ownership, and (§12) push-based
registry invalidation if a future load profile ever needs it instead of
this phase's per-request read.

---

**STOP after P14. P15 was not started.**
