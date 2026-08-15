# P13 — Horizontal Scale-Out / Multi-Process Production Readiness (2026-08-14)

Answers the question P12 left explicitly open: can ADOS safely run with
multiple worker processes (`--workers 2+`) against the same Postgres
database? P12's own limitation note blamed "MOA/ITSM state... still
process-local." **That specific claim turned out to be stale** — re-derived
from the current code, not copied from P12's report, per this phase's own
instructions.

**No commit was made during this phase**, per explicit instruction — every
file below is a real, uncommitted change in the working tree.

## 1. Fresh baseline

- **HEAD:** `7464902fb07efdef590493e92f0dec27be8b88d6` — unchanged since
  P11. **There is no separate "P12 commit"** — the P12 work (docs 22/23,
  `infrastructure/prometheus/`, admission control, the NULL-expiry fix,
  the rate limiter) exists entirely as uncommitted working-tree state on
  top of this same HEAD, exactly as P12's own report said ("no commit was
  made"). P13 is uncommitted on top of that same tree.
- **Working tree, pre-existing, untouched throughout P13:** the same
  unrelated agents-registry/novus-studio frontend feature and ~25
  untracked scratch scripts P11/P12 already left alone — verified via
  `git status --short` before and after, identical set outside the files
  this document lists as P13's own.
- **Fresh full-suite baseline** (`pytest -q`, before any P13 code
  changed): **866 passed, 0 failed, 19 deselected** — identical to P12's
  own final numbers, confirming no drift occurred between sessions.
  `pytest -m docker -q`: **17 passed, 0 failed**.
- Docker/Postgres confirmed clean before and after (only the four
  persistent compose containers; `admission_leases`/`rate_limit_events`
  at 0 rows).

## 2. Survey — every stateful component, re-derived from code

A dedicated research pass traced all 20 areas this phase's instructions
named (IntegrationHub state, MOA/ITSM state, admission control, the
approval queue, sessions/missions/capability_requests, idempotency,
reconciliation, build identity, auth, metrics, background tasks, Docker
ownership, singleton caches, asyncio locks, startup/shutdown, and the
DecisionOrchestrator/MOA graph state specifically), classifying each as
**A** (process-local, safe), **B** (process-local, unsafe), **C** (already
shared through Postgres, safe), **D** (shared but incorrectly
synchronized), or **E** (needs a live test to confirm). Full detail kept
in this phase's working notes; the load-bearing findings:

| Area | Classification | Note |
|---|---|---|
| MOA breaker/store, MOA graph state | **C** | Fully Postgres-backed (`db/checkpointer.py`, `moa_task_breakers`) — proven by the pre-existing `test_moa_durability.py`. The Dockerfile's own `--workers` comment describing `app.state.moa_pending_tasks` + an in-memory `InMemorySaver` is **stale** — `backend/app/main.py`'s own lifespan comment already says that dict was deliberately removed. |
| ITSM chat agent (LangGraph) | **C** | Same checkpointer-backed rebuild-by-`thread_id` shape as MOA. |
| **Manufacturing-incident `ApprovalQueue`** | **B — the actual blocker** | `orchestrate/governance.py::ApprovalQueue` — a plain in-memory dict, one per `DecisionOrchestrator`, one per process. The Dockerfile's stated *mechanism* is wrong; the *symptom* it warned about is real, just caused by this un-migrated, older pipeline instead. See §3. |
| Admission control (`app.state.integration_hub` path) | **C** | Confirmed wired exactly as P12 built it — `session_factory=async_session_factory` reaches every caller that uses `app.state.integration_hub` (MOA, ITSM, the manufacturing-incident pipeline). |
| **Admission control (Prime Agent/MCP-gateway path)** | **was N — not wired at all** | `mcp_gateway.py::_execute_capability` called `default_hub()` fresh on every call — a brand-new, always-`session_factory=None` `AdmissionControl` every time. Pre-existing since P11, not introduced by P13, and not multi-process-specific (broken even at `--workers 1`) — but directly relevant to this phase's own admission-control claims. See §4. |
| Approval queue / session-activity gates (`mcp_gateway.py`) | **C** | Unchanged, confirmed still Postgres-serialized. |
| Sessions/missions/capability_requests | **C** | No in-memory shadow cache found anywhere in the read/write paths. |
| Idempotency | **C** | Real DB unique constraint (`uq_capability_requests_session_idempotency`), not an in-memory check. |
| Reconciliation (all 4 periodic-loop passes, incl. P12's admission-lease reclaim) | **C** | All use `FOR UPDATE SKIP LOCKED` or a plain idempotent `DELETE ... WHERE age < cutoff` — two processes running the loop concurrently cost extra query overhead, never a correctness issue. |
| Build identity | **A** | Exists to catch a stale process vs. the repo on disk, never process A vs. process B. |
| Auth/session resolution | **A** | JWTs are stateless; `_resolve_session` queries Postgres fresh every call. |
| Metrics | **A** | Per-process, unaggregated, exactly as documented (doc 19 §Scope boundary) — nothing in application *logic* reads back an in-process counter to make a decision. |
| Background periodic tasks | **A/C** | The Obsidian listener's per-process `_pending_context` is harmless with the default in-memory event bus (each process only sees its own events) and self-corrects (idempotent overwrite) even with Kafka's fan-out consumer groups. |
| Docker resource ownership | **C** | Unchanged since P12 — no new process-local cache found. |
| `local_llm_client` settings cache | **B, already mitigated** | P11's own periodic refresh (`llm_settings_refresh_seconds`) already bounds the staleness window — not re-opened here. |
| `orchestrate/moa/dynamic_registry._ENTRIES` | **B** | Explicitly documented "process-global" in its own comment. See §5. |
| `DynamicCapabilityConnector._dispatch` | **B, with dead self-heal code** | A `resolver` callback exists by design but `default_hub()` never wires one. See §5. |
| `hot_disable_policy_rule` reading `CapabilityManifestRegistry._manifests` | **D** | Self-heals on a cache *miss*, not on present-but-stale data — a genuine safety-circuit-breaker staleness gap. See §5. |
| `backend/app/routers/memory.py`'s in-memory search index | **B** | `/memory/search` results can diverge across workers until restart — an observability/search-freshness gap, not a governance one. Not pursued this phase (lower severity than §3/§4). |
| `app.state.incident_tasks`, `orchestrate/audit_trail.py`'s in-memory list | **B, the mechanism §3's fix targets** | See §3. |
| asyncio locks (`agent_runner.py`, `obsidian/writer.py`) | **A** | Each correctly scoped to protect only its own process-local, unpersisted objects. |
| Startup/shutdown | **A**, one item **E** | Migrations run once via a dedicated one-shot `migrate` compose service (`depends_on: condition: service_completed_successfully` — confirmed N backend containers cannot race applying the same migration). `user_store.bootstrap_users`'s behavior under two truly-simultaneous first-boot workers was flagged but not exercised — low-severity (first-boot-only, RBAC seeding) and not pursued this phase. |

## 3. Fix #1 — the real blocker: `ApprovalQueue` cross-worker visibility and the race that fixing it could have introduced

**The bug, precisely:** `orchestrate/governance.py::ApprovalQueue` — its
own docstring already said "In-memory... for the MVP." One instance per
`DecisionOrchestrator`, one per process (`app.state.orchestrator`).
`POST /incidents/{id}/approve|reject|escalate` on a worker that never ran
that incident's `run_incident()` coroutine returned a bare 404 — even
though the incident was genuinely, durably `AwaitingApproval` in Postgres
(`orchestrator.py::_snapshot_pending`, already existed pre-P13). `GET
/incidents/{id}` had the same gap on the read side. This is the exact
symptom the Dockerfile's `--workers` comment describes; the *mechanism* it
names (MOA's old in-memory dict) no longer exists, but the outcome it
predicted was real, caused by this different, un-migrated pipeline.

**The fix, additive, reusing 100% of the existing restart-recovery
machinery** (`resume_pending_approvals`/`resume_after_decision`, both
already built and unmodified in logic):

- `orchestrate/audit_trail.py` gained two methods: `get_from_db(incident_id)`
  (a live Postgres read, bypassing the in-memory list every other read in
  this module still uses) and `claim_awaiting_approval(incident_id)` (a
  single atomic `UPDATE ... WHERE final_state = 'AwaitingApproval'` —
  `rowcount == 1` means this caller won; `IncidentState.EXECUTING`, an
  already-defined, already-meaningful state, not a new invented one).
- `orchestrate/orchestrator.py`: the reconstruction logic
  `resume_pending_approvals` (batch, startup-only) already had was factored
  into a shared `_reconstitute_pending_approval(record)` helper. A new
  `resolve_pending_approval(incident_id)` method is its on-demand,
  single-incident sibling — checks the fast in-process path first, falls
  back to `get_from_db` + reconstruction otherwise.
- `backend/app/routers/incidents.py`: `_get_pending_or_404` (used by
  `/approve`/`/reject`/`/escalate`) and `GET /incidents/{id}` both now call
  `resolve_pending_approval`/`get_from_db` instead of the bare, always-
  process-local `orchestrator.approvals.get(...)`/`orchestrator.audit_trail.get(...)`.

**The race this fix could have introduced, also closed:** making a
reconstructed `PendingApproval` visible to *any* worker makes it newly
possible for two workers to reconstruct and act on the same decision at
once — something structurally impossible before (only the originating
worker could ever see it). `resume_after_decision` now calls
`claim_awaiting_approval` before doing anything with a side effect
(mirroring P9's own "durable checkpoint before any external call"
discipline, applied to this pipeline for the first time); a lost claim
raises `DecisionAlreadyInProgress`, surfaced as `409`, never a silent
false-success. Not applied to the `"escalated"` branch, which has no
external side effect (only creates a second pending decision) — a race
there produces at worst a harmless duplicate.

**Tests** (`backend/tests/test_incident_approval_multiworker.py`, 7,
mirroring `test_moa_durability.py`'s own proven 2-`TestClient`-instance
pattern, real Postgres throughout):
- A second, independent app instance approves/rejects an incident it never
  started (the bug, closed).
- A third instance correctly reports the resolved state (the GET-side fix).
- A double-decide attempt after real resolution is refused (404), not
  repeated.
- **A direct, isolated proof of the on-demand mechanism specifically**
  (`test_resolve_pending_approval_finds_an_incident_a_live_process_never_saw_at_its_own_startup`):
  two `DecisionOrchestrator` instances constructed directly (not via
  `TestClient`/`app.state`, which can only ever hold one "current"
  instance at a time — see that test's own docstring for why the HTTP-level
  tests above cannot cleanly isolate this from the pre-existing startup-time
  `resume_pending_approvals`). `orchestrator_b` deliberately never calls
  `resume_pending_approvals()` — standing in for a process already running,
  past its own startup, before the incident existed — and still finds it.
- **The actual race, not a sequential simulation**
  (`test_concurrent_approve_from_two_real_threads_executes_exactly_once`):
  two real OS threads, each driving its own independent `TestClient`/app
  instance, both `POST /approve` for the same incident via a
  `threading.Barrier`. Real Postgres serializes the underlying claim
  regardless of exact timing; the test proves the *application* correctly
  respects that serialization. Result, every run: exactly one `200` and
  one `409`; the capability connector invoked exactly once (verified via a
  class-level `IntegrationHub.invoke` counting wrapper, not trusted from
  HTTP status alone). Confirmed non-flaky across 4 repeated runs.
- A direct, deterministic unit test of `claim_awaiting_approval`'s
  atomicity itself (two claims, same still-AwaitingApproval row: first
  `True`, second `False`), independent of any threading/timing.

## 4. Fix #2 — `mcp_gateway.py` bypassing admission control entirely for in-mission capability calls

**Found while re-deriving whether P12's own admission-control claims still
held** (this phase's own "do not assume previous reports are correct"
instruction, applied one layer deeper than P12 itself went):
`backend/app/mcp_gateway.py::_execute_capability` — the Prime Agent
in-mission capability path (`FetchIncidentEvidence`, `NotifyITHelpdesk`,
...) — called `default_hub()` with **no arguments** on every single call.
`default_hub()` constructs a **brand-new** `IntegrationHub`, and therefore
a brand-new `AdmissionControl` with `session_factory=None` and a zeroed
local counter, every time. This is a real, pre-existing correctness gap —
not introduced by P13, not specific to multi-process (already broken with
one worker, since even the *local* in-process counter never accumulated
across calls) — but it directly undercuts the "admission control is wired"
claim for exactly the traffic surface most real Prime Agent missions
generate.

**Why:** `mcp_gateway.py`'s `FastMCP` instance is a separate ASGI sub-app
with no `Depends()`/`request.app.state` access — `get_http_headers()` is a
*different*, request-scoped mechanism that also doesn't reach `app.state`.

**The fix, mirroring an already-established pattern in this exact file**
(`_mcp_current`/`_mcp_delegator`, a module-level slot set for the lifetime
of the real lifespan): a new module-level `mcp_gateway._active_hub`, set to
`app.state.integration_hub` inside `backend/app/main.py`'s lifespan
(alongside `_mcp_current`, same `finally` block resets both to `None`).
`_execute_capability` now calls a small `_hub_for_execution()` helper.

**A real regression this fix itself introduced, found by the full
regression suite and fixed before this phase's own evidence was
considered final:** the first version of `_hub_for_execution()`
unconditionally preferred `_active_hub` whenever a real lifespan was
active. Five pre-existing tests
(`test_capability_request_provenance.py` x2,
`test_runtime_approval_round_trip.py` x3) broke — all five use the
established, pre-P13 convention `monkeypatch.setattr("integrations.hub.
default_hub", lambda: hub)` to inject a controlled/mocked connector, even
while running inside a real `TestClient(app)` lifespan (via the `client`
fixture). `_active_hub` unconditionally won, so those tests' own
monkeypatched hub was silently never used — real ServiceNow-shaped HTTP
calls went out to the *unmocked* configured instance instead, and failed
on the (real, but not the mock's) response shape. Fixed by capturing the
original `default_hub` function object at import time
(`_original_default_hub`) and only preferring `_active_hub` when
`integrations.hub.default_hub` is still that exact object — a
monkeypatched `default_hub` (a different object) always wins, so every
pre-existing test's own explicit injection keeps meaning what it says.
Re-confirmed: all 5 originally-broken tests pass again, all of this
phase's own new tests still pass, full regression clean (§7).

**Tests** (`backend/tests/test_mcp_gateway_hub_wiring.py`, 3):
- Identity: `mcp_gateway._active_hub is app.state.integration_hub` during a
  real lifespan.
- `_active_hub is None` outside one (every other test file's own
  `default_hub()`/bare-hub construction stays exactly as before).
- **The functional proof**: two concurrent `request_capability.fn()` calls
  through a real `TestClient(app)` lifespan, against a deliberately tiny
  (`=1`) capability-concurrency limit set directly on the real
  `app.state.integration_hub`. Before this fix, both would have been
  silently admitted (each getting its own fresh, always-permissive
  `AdmissionControl`) regardless of the limit. After: the second is
  correctly refused with `"admission control: too many concurrent
  capability executions"`, and the connector spy confirms it. **Also
  incidentally found and fixed**: a stale-lease-row test-isolation gap
  (`test_hub_global_admission.py`'s own fixture cleans up on its next
  setup, not on teardown — a pre-existing, harmless-until-now convention
  that contaminated this new test's tiny limit until a `_clean` fixture was
  added here, matching the established per-file truncate pattern).

## 5. Found, precisely characterized, and deliberately deferred

Two further real gaps the survey found, both genuinely multi-process-
specific, both narrower in blast radius than §3/§4 (only affect the
dynamic-capability-onboarding feature, not the core mission/incident/MOA
flows) and both left unfixed this phase, per the "smallest set of concrete
issues" instruction:

- **`orchestrate/moa/dynamic_registry._ENTRIES`** (explicitly documented
  "process-global" in its own comment) **and
  `DynamicCapabilityConnector._dispatch`** (`integrations/connectors/
  dynamic.py`): a capability activated on worker A is invisible/
  uninvokable on every other worker until that worker restarts. The
  dispatch-side gap has an existing, designed self-heal — a `resolver`
  callback the connector's own `__init__` already accepts — that
  `default_hub()` simply never wires in (`integrations/hub.py:50`,
  `DynamicCapabilityConnector(self.manifests)`, no second argument). A
  future fix likely only needs to construct and pass one, pointed at
  `orchestrate/onboarding/runtime_registry.py`'s existing
  `_latest_activated_session`-shaped lookup — a small, well-scoped next
  step, not a redesign.
- **`hot_disable_policy_rule` reading `CapabilityManifestRegistry.
  _manifests`** (`integrations/capability_manifest.py`): the synchronous
  hot-path lookup (`manifest_for`) self-heals on a cache *miss* but not on
  present-but-stale data. Hot-disabling a misbehaving capability (an
  explicit, designed emergency circuit breaker) on one worker does not
  reliably stop other workers from continuing to invoke it until something
  else on that worker happens to call `list_manifests()` for an unrelated
  reason. A real gap in a safety mechanism, not just a UX inconvenience —
  named precisely here rather than rushed, since a correct fix (periodic
  refresh via the same centralized loop P12 built, or an explicit
  invalidate/broadcast) deserves its own focused pass rather than being
  bolted onto this one.

Neither was fixed this phase. Both are documented here precisely enough —
exact file/mechanism, exact failure scenario, a concrete lead on the
smallest fix — that a future phase does not need to re-derive them from
scratch.

**Update (P14, 2026-08-14): both closed.** See
[25-p14-capability-registry-consistency.md](25-p14-capability-registry-consistency.md)
— the dispatch-config gap was closed by wiring the exact resolver callback
named above; the hot_disable_policy_rule staleness gap was closed by
replacing that synchronous, cache-based rule with an authoritative,
per-call Postgres read at the actual execution boundary (not "periodic
refresh via the centralized loop," the other lead named above — a live
multi-process proof found that approach's most natural shape, keeping the
rule alongside a periodic refresh, would still race; removing the
cache-based rule entirely in favor of a fresh read was the correct fix,
not a periodic-refresh variant of the same cache).

## 6. Negative controls

Four, each: guard disabled directly in real source, targeted evidence
re-gathered and confirmed to fail for the expected reason, guard restored,
`shasum -a 256` confirmed byte-identical before/after.

| # | Guard disabled | File | Targeted evidence | Observed failure |
|---|---|---|---|---|
| 1 | `resolve_pending_approval`'s live-DB fallback | `orchestrate/orchestrator.py` | The isolated on-demand test (§3) | Correctly returns `None` — an incident a process never saw at its own startup stays invisible to it |
| 2 | `claim_awaiting_approval` guard in `resume_after_decision` | `orchestrate/orchestrator.py` | The real 2-thread concurrent race test | Both requests succeeded (`[200, 200]` instead of `[200, 409]`) — the real double-execution race, reproduced on demand, 3/3 runs |
| 3 | `mcp_gateway._active_hub` wiring | `backend/app/main.py` | The identity test + the functional concurrency test | Both failed — `_active_hub` stayed `None`; the tiny-limit concurrency proof could no longer even reach its own spy connector |
| 4 | The monkeypatch-detection check in `_hub_for_execution` (§4's own regression fix) | `backend/app/mcp_gateway.py` | The 5 pre-existing tests that regression originally broke | All 5 failed again, reproduced exactly (`test_capability_request_provenance.py` x2, `test_runtime_approval_round_trip.py` x3) — confirms the fix is load-bearing, not incidental |

All four files' final SHA-256 matches their pre-control value.

## 7. Full regression

Fresh run, after all P13 fixes and negative-control restorations, default
suite: **876 passed, 0 failed, 19 deselected, 1 warning in 277.27s**
(pre-existing `AuthlibDeprecationWarning`, unrelated to this phase).

`docker`-marked: **17 passed, 0 failed, 878 deselected in 37.45s**.

**Arithmetic:** baseline before any P13 code changed was 866 passed / 0
failed / 19 deselected = 885 total collected (identical to P12's own final
state — confirmed, not assumed, in §1). P13 added 10 new tests
(`test_incident_approval_multiworker.py` 7, `test_mcp_gateway_hub_wiring.py`
3). 866 + 10 = 876 — matches the final run exactly, with the deselected
count unchanged at 19 (the new tests are not `docker`/`external`-marked, so
none shift into or out of the deselected set). The `docker`-marked count
(17 passed) is unchanged from P12's own final state — neither P13 fix
touched a docker-marked code path, and none of the 10 new tests are
docker-marked. Zero failures anywhere, zero regressions.

## 8. External side effects

**None.** No ServiceNow record was created or touched. The manufacturing-
incident capability connectors are already simulated by design (doc 18's
own connector table) — the double-execution race test's "exactly once"
proof is a real, meaningful correctness property regardless (the same
serialization property a real connector would also depend on), achieved
with zero real external side effects.

## 9. Cleanup verification

- `docker ps -a` / `docker network ls`: only the persistent compose-stack
  containers before and after every test run.
- `admission_leases`, `rate_limit_events`: 0 rows in the test database at
  the end of this phase's work (the stale-lease contamination found and
  fixed in §4 was cleaned up, not just worked around).
- No P13 proof/test data (`p13-*` incident ids) remain in Postgres —
  every test either truncates its own tables or deletes its own rows.
- `git status --short`: identical pre-existing unrelated dirty-file set,
  plus exactly the files this document lists, plus P12's own
  already-uncommitted files (unchanged, untouched this phase).

## 10. Model A / B / C verdict

### Model A — Controlled Internal Production

**Still READY.** Nothing in P13 regressed any Model A guarantee — every
change is additive (`resolve_pending_approval` falls back to, never
replaces, the fast in-process path; `_active_hub` defaults to `None`,
preserving `default_hub()`'s exact prior behavior for every caller outside
a real lifespan), and the full regression suite confirms zero regressions.

### Model B — Production Long-Running Service

**Still READY**, unaffected by this phase — Model B was, and remains, a
single-process claim; nothing here changes that verdict's own evidence
(doc 23).

### Model C — Distributed Multi-Tenant / Horizontal Scale-Out

**This was the actual target of this phase.** With Fix #1 and Fix #2 in
place:

- The manufacturing-incident approval pipeline — the one genuinely
  process-local, unsafe-for-multiple-workers mechanism this phase's own
  fresh audit found — is now correctly visible and safely decidable across
  workers, with a real, proven-under-genuine-concurrent-load guard against
  the double-execution race that visibility alone would have introduced.
- Admission control now actually protects the traffic surface (in-mission
  Prime Agent capability calls) it was always documented as covering.
- MOA and ITSM were already safe (re-confirmed, not assumed).

**Still not a "Model C: READY" verdict, honestly:** two real,
narrower-scope gaps remain, named precisely in §5 (dynamic-capability
propagation, hot-disable staleness) — both affect a newer, less-core
feature, not the mission/incident/approval flows this phase's evidence
covers. Multi-host Docker ownership, a tenancy concept, and distributed
rate limiting beyond the single-database mechanism P12 built are still
`NOT BUILT`, unattempted, exactly as every prior phase already said. **The
honest claim this phase's evidence supports:** the specific, concrete
blockers that would make `--workers 2+` unsafe *for the core mission/
incident/approval/admission-control flows* are closed and proven under
real concurrent load; two narrower, lower-severity gaps remain, named
precisely rather than hidden; and Model C's full distributed-platform
requirements (multi-tenancy, multi-host) remain unattempted and out of
scope, as instructed.

---

**STOP after P13. P14 was not started.**
