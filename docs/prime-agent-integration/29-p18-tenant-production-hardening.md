# P18 — Tenant Production Hardening & Model-C Readiness Review

Compiled 2026-08-15. **Baseline:** `7464902` (unchanged — no P11–P18 commit
exists; all remain uncommitted working-tree state, per this phase's own
instruction). This phase re-derives P17's own claims from source and live
state rather than trusting them, closes the gaps that evidence showed were
genuinely required, and declares — honestly, not optimistically — whether
Model C is ready.

Same taxonomy every prior phase in this programme has used:

| Category | Means |
|---|---|
| **DEMONSTRATED** | proven by a real, live, independently-checked run |
| **TESTED** | an automated test proves the mechanism; no live run exercised it |
| **CONFIRMED** | re-verified against a specific claim/requirement by direct inspection; no gap found |
| **DESIGNED** | the implementation exists (or a clear design exists); no test or live run independently proves it |
| **DEFERRED** | intentionally postponed, with the reason and prerequisite named |
| **NOT BUILT** | outside implemented scope |

---

## 1. Verdict

**PASS**, with one real, previously-undocumented tenant-isolation gap
found and closed, and everything else re-confirmed rather than assumed.

**The headline finding:** P16 and P17 both concluded "no user-facing
mission-creation endpoint exists" by searching for a direct Python caller
of `RunPrimeRLMAgent` (there genuinely is none). That search missed a
real one — `POST /capabilities/invoke`, a generic, pre-Prime-Agent
capability-invocation endpoint (`docs/006-integration-hub.md`) that
dispatches by capability *value*, not by a direct call, and is reachable
by any authenticated user regardless of role. A caller could already name
`RunPrimeRLMAgent` there and cause `PrimeRuntimeConnector._run()` to
create a real mission — which stamped every mission it created with the
hardcoded default tenant, *regardless of who actually called it*. Harmless
while only one tenant has any users (true today); a real cross-tenant
misattribution the moment a second tenant does (tenant B's mission would
land in tenant A's approval queue, visible to tenant A and invisible to
tenant B). **Fixed**: the endpoint now resolves the caller's tenant via
the same `get_tenant_context` dependency `runtime_approvals.py` already
uses, and `PrimeRuntimeConnector._run()` reads it from the same
`contextvars.ContextVar` `db/tenancy.py` already propagates through the
plain `await` call chain — no new plumbing through `CapabilityCall`/
`GovernanceInfo` needed. Proven end to end over real HTTP with a real
second tenant (§4).

Everything else audited this phase either **held up under independent
re-derivation** (the `do_orm_execute` mechanism, the 12 production
`use_all_tenants()` call sites, the MOA/incident boundary, the global
admission/rate-limit classification, the multi-host `owner_host`
mechanism, the metrics label discipline) or was **genuinely extended with
new, real evidence** the prior phases did not gather (a real
multi-process tenant-isolation proof — §7 — and two of P17's own
Docker/Postgres proof scripts re-executed live rather than merely
syntax-checked — §6).

**Postgres RLS remains DESIGNED, NOT BUILT** — re-evaluated independently
this phase, and a sharper, more concrete blocker was found than P17 named
(§2). **Model C is still NOT READY**, for reasons narrower and more
precisely evidenced than any prior phase's statement (§13).

---

## 2. Phase 1 — fresh tenant architecture audit

Traced end to end from source, not from doc 28's own narrative:

**Authentication → JWT → request context.** `backend/app/user_store.py::
verify_login` queries `tenant_memberships` and bakes the result into the
login JWT (`tenantIds` claim) before signing — re-confirmed by reading
`rbac.py::create_access_token`/`decode_access_token` directly.
`User.tenant_ids` defaults to `[DEFAULT_TENANT_ID]` (not `[]`) — a
deliberate, load-bearing design choice: every ad-hoc `User(...)`
construction across dozens of pre-existing tests (that have nothing to do
with tenancy) gets the honest default rather than a silent 403. Confirmed
by grep: exactly one test file (`test_tenant_isolation.py`) overrides
`tenant_ids` explicitly.

**Request context → ORM.** `backend/app/tenancy.py::get_tenant_context`
resolves one active tenant from the JWT's membership set, cross-checking
(never trusting alone) a caller-supplied `X-Tenant-Id` header, and enters
`db/tenancy.py::use_tenant()` — a `contextvars.ContextVar`, not a
process-global. `db/tenancy.py::_install_tenant_scoping()` registers a
single `Session.do_orm_execute` event at import time
(`db/engine.py` imports `db.tenancy` specifically to guarantee this
registration happens before any session can run a query) that injects
`with_loader_criteria` for `MissionRow`/`RuntimeSessionRow`/
`CapabilityRequestRow` on every SELECT/UPDATE/DELETE. No context set →
`sql_false()` → zero rows, never all rows.

**Enumerated every tenant-owned resource and every endpoint that can
touch it.** Exactly two routers touch the three tenant-owned models
(grep-confirmed across all 23 registered routers): `metrics.py`
(deliberately global, `use_all_tenants()`, unauthenticated infrastructure
endpoint) and `runtime_approvals.py` (`Depends(get_tenant_context)` at
router level — every list/get/approve/reject route automatically scoped).
No separate "missions" router exists. `POST /capabilities/invoke`
(`capabilities.py`) does not itself query a tenant-owned table, but *is*
a real path to one that creates a `MissionRow` — the §4 finding.

**Enumerated and audited every `use_all_tenants()`/`all_tenants_session()`
call site in production code** (excludes `backend/tests/` and `scripts/`):

| # | File | Count | Why it's safe |
|---|---|---|---|
| 1 | `backend/app/mcp_gateway.py` | 5 | Session-token-authenticated, not JWT/tenant-authenticated. Every query is a targeted lookup by an id the caller already possesses (never a list/enumerate) — a narrower, stronger proof than tenant membership |
| 2 | `backend/app/routers/metrics.py` | 1 | Unauthenticated infrastructure endpoint; the operator alerting it feeds needs the true global backlog, not one silently scoped to nothing |
| 3 | `orchestrate/runtime/session_reconcile.py` | 1 | Background job; scans every tenant's abandoned sessions by design |
| 4 | `orchestrate/runtime/capability_reconcile.py` | 2 | Background job; same reasoning, for stalled/`outcome_unknown` rows |
| 5 | `orchestrate/runtime/orphan_sweep.py` | 2 | Background job; same reasoning, for Docker/workspace orphans |
| 6 | `integrations/connectors/mission_evidence.py` | 1 | **Not named in doc 28's own count** (doc 28 said "8 specific... call sites"; this audit finds 12, one of which — this one — doc 28's own accounting appears to have folded into "mcp_gateway.py" generally rather than listing separately). Session-token-scoped: `call.incident_id` is set server-side by the gateway from the already-resolved session, never runtime-supplied — same reasoning as row 1 |

**Finding:** doc 28's own "8 call sites" underclaimed by one module (this
one), a documentation-completeness gap only — the call site itself was
already correct and safe, independently re-verified here. Corrected in
this report's own accounting; no code change needed.

**Confirmed for every one of the 12:** the caller cannot be reached by an
ordinary tenant-scoped HTTP request (mcp_gateway.py's own auth boundary is
a possessed session token, never a JWT; metrics.py is unauthenticated
infrastructure; the four background-job sites have no HTTP caller at
all), and none can be influenced by a caller-supplied tenant identifier
(none of the 12 ever reads a header or request field to decide which
tenant to scope to — `ALL_TENANTS` is a fixed sentinel, not a value).

**Searched for bypasses:** raw SQL (`text(...)`) touching a tenant-owned
table in production code — one hit, `mcp_gateway.py`'s
`pg_advisory_xact_lock` call, which touches no table at all (an advisory
lock keyed by a hardcoded string). Core-style `update()`/`delete()`
against a tenant-owned model — none in production code (test/script
files that construct `delete(RuntimeSessionRow)`/`delete(MissionRow)`
directly all do so through the ORM-enabled construct, which **is**
intercepted by `do_orm_execute` — re-confirmed live by P17's own negative
control #2 and independently re-verified this phase, §5). No bulk
`Table`-level (non-mapped) statement against any tenant-owned table
exists anywhere. Single-head Alembic chain (`alembic history` — no
branching), confirmed live: both `ados` (dev) and `ados_test` databases
sit at `e6f7a8b9c0d1`, zero `tenant_id IS NULL` rows in any of the three
tables, in either database.

**ContextVar concurrency safety, re-verified beyond P17's own claim.**
P17's own evidence was a pre-implementation spike plus a single-process,
sequential-HTTP-call proof script. This phase adds a genuinely concurrent
proof: §7's Case 2 fires 30 real, simultaneously-in-flight `asyncio.gather`
HTTP requests, alternating two different tenants' credentials against the
same running app instance and event loop, and independently checks every
individual response for cross-tenant contamination. Zero leaks. This is
materially stronger evidence than P17 gathered for this specific claim.

**Identity-map cache risk, evaluated and ruled out.** SQLAlchemy's
`Session.get()` can return an already-loaded object from the identity map
without re-running the `do_orm_execute` filter at all — a real, if
narrow, mechanism by which a *reused* `Session` object could leak a
previously-loaded row across a later, different tenant context.
`db/session.py::get_db_session` opens a fresh `AsyncSession` per HTTP
request (`async with async_session_factory() as session: yield session`)
and every background job opens its own fresh session inside
`all_tenants_session()`; no code path in this codebase reuses one
`Session` object across two different tenant contexts. Confirmed by
reading every session-opening call site — there are exactly two
(`get_db_session`, `all_tenants_session`) plus the two long-lived
singletons (`AuditTrail`, `CapabilityManifestRegistry`) named in
`db/session.py`'s own docstring, neither of which ever queries a
tenant-owned table (confirmed by grep — see §3).

---

## 3. Phase 2 — PostgreSQL RLS backstop: DESIGNED, DEFERRED (sharper reason)

Re-evaluated independently, not assumed from doc 28 §7.

**The precondition remains correct, re-confirmed live:** `ados_app` (the
role the real `backend` container connects as —
`docker exec ados-backend-1 printenv DATABASE_URL`, confirmed) does not
own `missions`/`runtime_sessions`/`capability_requests`/`tenants`/
`tenant_memberships` (`ados`, the migration role, does — confirmed via
`pg_tables.tableowner`). RLS policies would genuinely apply to `ados_app`
and not be silently bypassed by ownership.

**What makes it unsafe to build this phase, independently re-derived —
sharper than P17's own reasoning:** P17 named the shared-role problem
(one role, both tenant-scoped HTTP routes and cross-tenant background
jobs) and the async/sync GUC-propagation risk, and stopped there,
citing insufficient time to verify it. This phase traced the actual
transaction structure of the approval flow and found a concrete,
demonstrable failure mode a naive RLS implementation would hit:

`backend/app/routers/runtime_approvals.py::approve_capability_request`
uses **one** FastAPI-injected `AsyncSession` across **three** separate
transactions by design (P9's own three-phase structure — the *whole
point* is that no lock/transaction is held across the external connector
call): Phase 1 commits `status=executing`; Phase 2 makes the real
external call with no transaction open at all; Phase 3 calls
`await session.refresh(row)` — which, because Phase 1's commit already
ended the prior transaction, silently **begins a brand-new transaction**
on the same session object (SQLAlchemy's autobegin).

Any RLS implementation that sets the session-GUC (`app.tenant_id`) once,
at session-open time — the simplest, most obvious approach, and the one
this codebase's `NullPool` (no connection reuse across requests) would
otherwise make attractive — would have that GUC evaporate at Phase 1's
commit (`SET LOCAL`'s scope is exactly one transaction) and never be
re-set before Phase 3's implicit new transaction. Under RLS, that refresh
would then see **zero rows** for a row the application just legitimately
wrote and owns — not a security improvement, but a real functional
break in the exact flow P9 built to prevent a false-negative failure
mode (`session.refresh()` raising would either crash the request or, if
swallowed, misreport the row's outcome to the caller).

Making this safe requires re-issuing the tenant GUC on **every**
transaction boundary within a session — not once at open — which is
real, unverified engineering (a `SessionEvents`/`ConnectionEvents` hook
that can safely issue an additional statement from within a sync event
handler for an async session, without breaking the greenlet bridge
SQLAlchemy's asyncio support depends on) that this phase's own
smallest-safe-change discipline does not permit rushing.

**Why the current application-level filter remains safe without RLS:**
it is not "hoped" safe — it is proven fail-closed (§2, §5's negative
control #3: with the filter disabled entirely, 5/7
`test_tenant_isolation.py` tests fail exactly as predicted; with it
active, 7/7 pass), it covers SELECT/UPDATE/DELETE uniformly (not just
reads), and its correctness does not depend on transaction-boundary
timing the way a GUC-based backstop would — it re-evaluates on every
single statement, inside `do_orm_execute`, regardless of which
transaction that statement happens to be in.

**Classification: DESIGNED, DEFERRED.** Exact prerequisite for a future
phase: prove (with a dedicated spike, the same discipline P17 used for
the ContextVar claim) that a per-transaction GUC re-assertion mechanism
is correct under SQLAlchemy's autobegin semantics for a session that
spans multiple transactions — or, the alternative P17 also named, split
`ados_app` into a tenant-scoped role and a separate system/background
role (a real schema + deployment change). The exact policies remain as
P17 recorded them (doc 28 §7); nothing about them changed. Not attempted
this phase, per the task's own explicit permission not to fake safety.

---

## 4. Phase 3 — mission creation / tenant attribution: real gap found and closed

**The real mission-creation path.** `integrations/connectors/
prime_runtime.py::PrimeRuntimeConnector._run()` is the only code in this
codebase that constructs a `MissionRow`. It is reached exactly two ways:

1. Internal ADOS/MOA code calling `IntegrationHub.invoke()` directly —
   no HTTP request behind it, no caller identity to attribute.
2. **`POST /capabilities/invoke`** (`backend/app/routers/capabilities.py`)
   — predates the Prime Agent integration (`docs/006-integration-hub.md`),
   requires only `Depends(get_current_user)` (any authenticated role),
   and accepts a caller-supplied `governance` block that the endpoint's
   own docstring says it trusts without re-deriving
   (`integrations/policy_engine.py::require_governance` only checks
   `call.governance is not None`, never validates the tier against the
   caller's role). `test_dynamic_capability_connector.py`'s own docstring
   already documents this endpoint as reachable "by any authenticated
   user" — confirming this is known, intentional behavior for capability
   dispatch generally, just never examined for its tenant-attribution
   consequence specifically.

Before this phase, `_run()` unconditionally stamped
`tenant_id=DEFAULT_TENANT_ID` — correct for path 1, silently wrong for
path 2 the moment a second tenant with real users exists.

**Fixed, minimally:**
- `backend/app/routers/capabilities.py::invoke_capability` gained
  `Depends(get_tenant_context)` — the same dependency
  `runtime_approvals.py`'s router already uses, reused rather than
  reinvented. Resolves and activates the caller's tenant via the existing
  `contextvars.ContextVar` before the call ever reaches
  `IntegrationHub.invoke()`.
- `PrimeRuntimeConnector._run()` now reads `db.tenancy.current_tenant.get()`
  and uses it when it resolves to a concrete tenant UUID, falling back to
  `DEFAULT_TENANT_ID` for anything else (`None` — no context, the correct
  behavior for path 1 — or the background-job `ALL_TENANTS` sentinel,
  never expected on this path but not asserted unreachable). No new
  plumbing through `CapabilityCall`/`GovernanceInfo`: the whole call
  chain (HTTP handler → `hub.invoke()` → `policy_engine.select_connector()`
  → `connector.execute()` → `_run()`) runs as one plain `await` sequence
  in the same asyncio Task, so the `ContextVar` set by the router
  dependency is already visible by the time `_run()` reads it.

**Proven, not merely asserted** — `backend/tests/
test_mission_creation_tenant_attribution.py` (new, 4/4 passing):
1. No tenant context (the internal-caller case) → mission still gets the
   default tenant, unchanged behavior.
2. A resolved tenant context (`use_tenant(tenant_b)` directly around
   `PrimeRuntimeConnector.execute()`) → the mission gets tenant B, not the
   default.
3. **The full real HTTP path**: a real `POST /capabilities/invoke` call,
   authenticated as a real tenant-B user, with `capability:
   "RunPrimeRLMAgent"` in the body → the resulting `MissionRow` carries
   tenant B's id, independently re-queried. `PrimeAgentRuntime.start` is
   monkeypatched to fail immediately (mirroring
   `test_prime_agent.py::test_a_stale_process_refuses_the_mission_
   before_creating_any_row`'s own established pattern) so no real Docker
   container is ever touched — only the mission-row creation this test
   cares about, which happens before that call.
4. A caller with zero tenant memberships is refused (403) at the
   endpoint, fail-closed — not a silent fall-through to the default
   tenant.

Full suite re-run clean after this fix: **911 passed, 0 failed, 19
deselected** (907 pre-fix baseline + 4 new tests, exactly reconciled).

**What this is not:** not a new "start a mission" product feature — the
capability was already reachable this way before P18; only its tenant
attribution was wrong. Not a claim that `/capabilities/invoke` is now a
supported, documented mission-creation UX — it remains the generic,
Phase-3-era capability-dispatch endpoint it always was; this phase closed
the one tenant-isolation consequence of that endpoint's existing reach,
nothing broader.

---

## 5. Phase 10 — negative controls (reported here, ahead of §6/§7, since
§4's fix is what they primarily target)

Every control: guard disabled directly in real source, targeted evidence
gathered, confirmed to fail for the predicted reason, guard restored,
`shasum -a 256` confirmed byte-identical before/after.

| # | Guard disabled | File | Expected failure | Result |
|---|---|---|---|---|
| 1 | `Depends(get_tenant_context)` on `POST /invoke` (P18's own new guard) | `backend/app/routers/capabilities.py` | The tenant-attribution test and the no-membership-refused test fail; the two connector-level-only tests (no HTTP layer) are unaffected | **Confirmed** — exactly 2/4 new tests failed, the 2 that exercise the HTTP layer |
| 2 | `current_tenant.get()` resolution in `_run()` (P18's own new guard) | `integrations/connectors/prime_runtime.py` | The tenant-stamping tests fail; the no-context-still-works test is unaffected | **Confirmed** — exactly 2/4 new tests failed, the 2 that assert a non-default tenant lands on the row |
| 3 | `db/tenancy.py`'s entire `do_orm_execute` filter (SELECT+UPDATE+DELETE at once — a stronger disable than P17's own, which tested SELECT and UPDATE/DELETE separately) | `db/tenancy.py` | Cross-tenant read/mutate succeeds; same-tenant access still works | **Confirmed** — 5/7 `test_tenant_isolation.py` tests failed (the 2 that passed test same-tenant access and a tenant-id column value, neither of which needs the filter) |
| 4 | `get_tenant_context` router dependency | `backend/app/routers/runtime_approvals.py` | The exact P16 defect returns | **Confirmed** — 4/7 tests failed, precisely the four that assert cross-tenant refusal |

All four files' final SHA-256 verified byte-identical to their
pre-control value. P17's own six negative controls (doc 28 §11) were not
re-run destructively — nothing in their specific mechanisms changed this
phase, and their properties are independently re-exercised, not merely
re-asserted, by this phase's own live proof scripts (§6, §7) and the
full regression suite (§11) — re-running them again would duplicate
evidence, not add to it, matching the reasoning P16/P17 themselves used
for not re-proving already-proven, untouched mechanisms.

---

## 6. Phase 6 — P17's five modified live-proof scripts

Each classified, then run if safe:

| Script | Classification | Action | Result |
|---|---|---|---|
| `scripts/p9_crash_recovery_e2e.py` | **REQUIRES EXTERNAL SIDE EFFECT** — its entire point is a real ServiceNow incident | Not run | Syntax/import verified (`py_compile`, `ast.parse`); already exhaustively proven with real evidence in P9's own report; re-running would manufacture a real external record for a finding this phase's own scope does not require re-proving |
| `scripts/p11_orphan_recovery_exercise.py` | **SAFE** — real Docker + real Postgres, no ServiceNow | **Run** | **PASS**, live. Real container `ados-prime-8f70c715-afd`, real relay, real networks, real workspace — full failure→detection→diagnosis→remediation→independent-verification loop, exactly as P11 first proved. Confirms P17's tenant-compatibility fix for this script (`use_all_tenants()` around its own verification reads) actually works, not just imports cleanly |
| `scripts/p12_docker_ownership_proof.py` | **SAFE** — real Docker + real Postgres, no ServiceNow | **Run** | **PASS**, live, all 4 cases (owner protection, live-session non-claimability, exactly-one-of-3-simultaneous-real-processes claims, stale-row ownership-label mismatch refused) |
| `scripts/prime_agent_approval_e2e.py` | **REQUIRES EXTERNAL SIDE EFFECT** — creates a real ServiceNow change request | Not run | Syntax/import verified; already exhaustively proven live in its own original run |
| `scripts/prime_agent_servicenow_e2e.py` | **REQUIRES EXTERNAL SIDE EFFECT** — creates a real ServiceNow incident | Not run | Syntax/import verified; already exhaustively proven live in its own original run |

Both scripts actually run left the Docker daemon and both databases
clean, independently re-verified (`docker ps -a`, `docker network ls`,
direct Postgres queries) — one incidental mission row this phase's own
run of `p11_orphan_recovery_exercise.py` created was cleaned up
explicitly (matching the same convention every prior phase's own live
runs used); the pre-existing 2026-08-12 P11 mission row (from the
*original* P11 phase run) was left untouched, per this phase's
instruction not to touch unrelated prior state.

**Classification for the three not re-run: TESTED (syntax/import
verified), not DEMONSTRATED** — matching P17's own honest classification
exactly, independently re-confirmed rather than merely copied.

---

## 7. Phase 7 — real multi-process tenant isolation proof (new this phase)

P17 built no genuine multi-process tenant-isolation proof — its own
proof script (`p17_tenant_isolation_proof.py`) is real app / real
Postgres / real HTTP, but single-process, sequential HTTP calls. This
phase wrote and ran a new one:
**`scripts/p18_multiprocess_tenant_isolation_proof.py`** — same
`multiprocessing.get_context("spawn")` convention as
`p14_multiprocess_capability_proof.py`/`p15_multiprocess_concurrency_
proof.py`, real `ados_test` Postgres, no ServiceNow (every decision is
`reject`, zero external effect). Full clean run:

```
CASE 2 -- 30 genuinely concurrent asyncio Tasks (asyncio.gather), alternating
tenant-A/tenant-B credentials against the SAME running app instance/event loop
  [PASS] zero cross-tenant leaks across 30 concurrent calls

CASE 1 -- two real OS processes (confirmed distinct PIDs), different tenants,
racing on a real multiprocessing.Barrier to reject EACH OTHER's request at the
exact same instant
  [PASS] tenant A refused on tenant B's request (404)
  [PASS] tenant B refused on tenant A's request (404)
  [PASS] each tenant DID successfully decide its OWN request (200)

CASE 3 -- capability_reconcile.mark_stalled_executions_unknown() called from
INSIDE an ambient use_tenant(tenant_A) context
  [PASS] saw the ambient tenant's own stalled row
  [PASS] ALSO saw tenant B's stalled row -- proves the function's own internal
  use_all_tenants() overrides the caller's ambient context, not inherits it

CLEANUP -- independent post-run verification: missions=0 tenants=0 -> PASS
RESULT: PASS -- all cases passed across real, separate OS processes.
```

Directly answers the task's own Phase 7 list:
1. **Tenant A/B concurrent without context leakage** — Case 1 (process
   level) and Case 2 (asyncio-Task level within one process — the more
   exacting version, since `ContextVar` leakage risk is fundamentally an
   in-process, same-event-loop concern; cross-process leakage is
   structurally impossible, since separate OS processes have separate
   memory).
2. **Concurrent async requests cannot inherit the wrong tenant** —
   Case 2, directly.
3. **Two workers cannot claim the same tenant-owned approval
   incorrectly** — Case 1 (real Barrier-synchronized race).
4. **Tenant A cannot mutate tenant B's request** — Case 1.
5. **Tenant A cannot execute tenant B's capability request** — covered
   by Case 1 plus §4's admission-control reasoning (execution shares the
   identical authorization gates approve/reject do, per P16/P17's own
   established finding, re-confirmed by source reading this phase —
   `runtime_approvals.py`'s three gates are identical for both).
6. **Tenant-scoped admission/rate limits remain correct if implemented**
   — N/A; none exist (§8), by deliberate, re-confirmed design.
7. **Global infrastructure ceilings remain global while tenants race** —
   unaffected by any P18 change; the four admission/rate-limit gates
   (P11/P12) do not reference `tenant_id` anywhere (grep-confirmed, §8),
   so nothing about racing tenants changes their behavior — already
   proven under real multi-process load by P12's own script, re-run
   unmodified as part of this phase's regression (§11) and unaffected.
8. **Background all-tenant jobs cannot accidentally inherit a tenant
   context** — Case 3, directly, and the strongest form of this proof
   in the whole programme: not merely "the background job works when
   nothing else set a context" (the only shape prior phases tested) but
   "the background job works correctly even when something *else*
   deliberately set a narrower, wrong context first."

---

## 8. Phase 4 — MOA/incident tenancy boundary: CONFIRMED, stronger than before

Re-audited fresh, not trusted from doc 28 §5's own reasoning. Full-repo
grep for `MissionRow`/`RuntimeSessionRow`/`CapabilityRequestRow` across
`backend/`, `orchestrate/`, `integrations/`, `db/`,
`orchestrate_langgraph/`, and the top-level `executive/` directory finds
**zero references** in `db/models/incident.py`,
`backend/app/routers/{executive,learning,memory,moa,incidents,
knowledge_graph}.py`, or anywhere in `executive/`. This is a stronger,
more exhaustive check than P17's own scope-boundary reasoning (which
argued the separation was correct by design and by the size of the
seeded/tested surface, not by an exhaustive negative search for a shared
code path).

**Conclusion, CONFIRMED not merely re-asserted: the MOA/incidents
surface is structurally, completely isolated from tenant-owned Prime
Agent data.** There is no code path — direct query, join, shared model,
or shared identifier lookup — connecting the two. `mcp_gateway.py`'s
reuse of the field name `incident_id` on `CapabilityCall` (set to a
Prime Agent mission's id, for provenance) is a contract-shape coincidence
across two independently-governed concepts, never an actual database
join against the real `incidents` table.

Deliberately **not** retrofitted with tenant scoping this phase, for the
same three reasons doc 28 §5 already gave (220 seeded demo records with
hundreds of dependent tests; the task's own scope pointing at the Prime
Agent runtime surface specifically; blast-radius discipline) — none of
which this phase's own fresh audit found any reason to revisit.

---

## 9. Phase 5 — capacity/admission control classification: unchanged, confirmed correct

Re-read `integrations/admission_control.py`, `integrations/
rate_limiter.py`, and `backend/app/config.py`'s four admission-control
settings fields fresh. **No `tenant_id` column exists on
`admission_leases` or `rate_limit_events`** (confirmed by schema
inspection, unchanged since P12). All four gates — mission concurrency,
capability-execution concurrency, approval-queue depth, per-session
activity — remain global, for the same reasons P16/P17 already gave: they
bound genuinely shared physical resources (one Docker daemon, one paid
LLM budget, one human reviewer pool) that do not divide meaningfully per
tenant merely because a tenant concept now exists.

**§4's fix does not change this classification.** A tenant-B user could
already consume the shared admission ceiling by starting missions
through `/capabilities/invoke` before this phase's fix — nothing about
*capacity* changed; only the mission's *attribution* (which tenant owns
the resulting row) was wrong. No new tenant-scoped capacity requirement
was found or introduced.

**Conclusion: global controls remain correct and sufficient for
everything this phase's own evidence covers.** No per-tenant
admission/rate-limit layer was built — building one without a real
second tenant's actual capacity needs to design against would be
speculative engineering, not a fix for a demonstrated gap, matching the
task's own explicit instruction not to reflexively tenant-scope every
limit.

---

## 10. Phase 8 — multi-host ownership/failover: re-confirmed, still TESTED

No code in `orchestrate/runtime/orphan_sweep.py`, `db/models/mission.py`
(`owner_host` column), or `backend/app/config.py` (`node_id` setting)
was touched by this phase. Re-confirmed, not merely trusted:

- `Settings.node_id` is a server-side operator configuration value
  (`node_id: str = ""`, `.env`/environment-supplied) — never derived from
  any HTTP request or caller input. Cannot be caller-controlled.
- `backend/tests/test_orphan_sweep_multihost.py` (7),
  `test_orphan_sweep.py` (22), `test_orphan_sweep_docker.py` (6) — **35/35
  pass, fresh, this phase.**
- **`docker context ls`** on this machine shows exactly one real Docker
  context (`desktop-linux`) — no second real host is available in this
  environment, confirming P16's own honest classification still holds.
  **Not claiming DEMONSTRATED.**

**The dead-host problem, re-assessed, unchanged:** `owner_host` prevents
*misattribution* (host A can never mark host B's live container
"absent"); it adds no liveness detection. A permanently-dead host's
sessions are never automatically reclaimed by another host — an operator
still needs `--all-hosts` or a deliberate manual consolidation. Building
automatic cross-host reclaim would require a real lease/heartbeat
mechanism (a TTL'd claim an owning host must actively renew, with a
second host permitted to reclaim only after the lease genuinely expires)
— **not implemented this phase**, per the task's own explicit instruction
not to implement cross-host takeover without first being able to define
safe ownership semantics for it, which is a real design exercise this
phase's scope does not include.

---

## 11. Phase 9 — observability: CONFIRMED, no tenant exposure

Re-read every metric definition in `backend/app/metrics.py` (20 metric
objects — unchanged count since P12/P15) plus `backend/app/routers/
metrics.py`. **Zero occurrences of `tenant` as a label anywhere** — the
only `tenant` references in either file are the module-docstring
explanation of *why* the metrics endpoint deliberately runs under
`use_all_tenants()` (it needs the true global backlog for
`approval_queue_depth`/`outcome_unknown_open`, not one scoped to
nothing — the correct, already-established design, unaffected by this
phase). `infrastructure/prometheus/alert_rules.yml` — zero references to
`tenant` anywhere. `backend/tests/test_metrics.py::
test_no_sensitive_or_high_cardinality_data_in_metrics` re-run fresh:
**pass.**

**Conclusion: no tenant identifier was added to, or already existed in,
any Prometheus label or alert.** Nothing to fix; nothing to defer.

---

## 12. Phase 11 — full regression

Every suite run separately and sequentially, fresh, this phase:

| Suite | Result |
|---|---|
| Focused P18 (`test_mission_creation_tenant_attribution.py`) | **4/4 passed** |
| P17 tenant tests (`test_tenant_isolation.py`) | **7/7 passed** |
| P14 capability-registry (`test_capability_registry_multiworker_safety.py`, `tests/test_dynamic_capability_connector.py`) | **23/23 passed** |
| P15 concurrency (`test_capability_completion_race.py`, `test_metrics.py`) | **24/24 passed** |
| P12 admission/rate-limit (`test_admission_control_global.py`, `test_hub_global_admission.py`, `test_rate_limiter_hub.py`, `test_mcp_gateway_admission.py`, `test_mcp_gateway_hub_wiring.py`, `test_incident_approval_multiworker.py`) | **35/35 passed** |
| All Docker-marked (`pytest -m docker`) | **17/17 passed**, 913 deselected |
| **Full default suite** (`pytest -q`) | **911 passed, 0 failed, 19 deselected** |

**Arithmetic, reconciled exactly:** P17's own final baseline was 907
passed / 19 deselected (926 total collected). P18 added 4 new tests
(`test_mission_creation_tenant_attribution.py`); 907 + 4 = **911** —
matches the final run exactly. Deselected unchanged at 19 (17 `docker` +
2 `external`) — none of the 4 new tests are docker/external-marked.

**Live proof scripts run this phase (outside pytest):**
`scripts/p11_orphan_recovery_exercise.py` (PASS),
`scripts/p12_docker_ownership_proof.py` (PASS, 4/4 cases),
`scripts/p18_multiprocess_tenant_isolation_proof.py` (PASS, 3/3 cases).

**Cleanliness, independently re-verified after every run:**
- `docker ps -a`: only the five persistent compose-stack containers
  (`ados-backend-1`, `ados-postgres-1`, `ados-kafka-1`, `ados-migrate-1`,
  `ados-frontend-1`) before and after.
- `docker network ls`: no leaked `ados-rt-*`/`ados-relay-*`/`ados-prime-*`
  networks.
- Dev database (`ados`): zero rows matching this phase's markers
  (`%p18%`/`%P18%` in mission titles, `%p18%` in tenant slugs).
- Test database (`ados_test`): same, zero residue.
- No workspace directories leaked (`ados-mission-*` under the OS temp
  root — none found).
- No external (ServiceNow) side effects of any kind this phase — every
  live proof run used only local Docker/Postgres, or `reject` (zero
  external effect).

**Files changed this phase (exact):**
- `backend/app/routers/capabilities.py` — `Depends(get_tenant_context)`
  on `POST /invoke`.
- `integrations/connectors/prime_runtime.py` — reads
  `current_tenant.get()` instead of hardcoding `DEFAULT_TENANT_ID`.
- New: `backend/tests/test_mission_creation_tenant_attribution.py` (4
  tests).
- New: `scripts/p18_multiprocess_tenant_isolation_proof.py` (live proof,
  not pytest-collected).
- New: this document, plus the updates in §14.

**Unrelated pre-existing dirty-tree state — untouched, confirmed by
`git status --short` before and after:** `custom_agents.division`
plumbing, the agents-registry/novus-studio frontend work, and every
untracked scratch script (`scripts/audit_workspace.js`,
`scripts/behavioral_*`, `scripts/smoke_test_*`, `scripts/sync_agency_
agents.py`, `agency-agents-repo/`, etc.) — none of these are related to
the Prime Agent tenant-hardening programme and none were modified,
staged, or attributed to this review.

---

## 13. Final Model A / B / C verdict

### Model A — Controlled Internal Production

**Unaffected, still READY.** Both files this phase changed are additive:
`Depends(get_tenant_context)` on `/invoke` resolves to the default tenant
for every existing single-tenant caller exactly as before (every seeded
account has exactly one membership); `_run()`'s fallback to
`DEFAULT_TENANT_ID` when no context is resolved preserves every
pre-P18 internal-caller code path byte-for-byte. Full regression
confirms zero regressions among the 907 pre-existing tests.

### Model B — Production Long-Running Service

**Unaffected, still READY.** Nothing in this phase touches any
single-process, long-running-service guarantee; P12–P15's own evidence
is unchanged and was independently re-exercised (not merely re-run) by
this phase's regression suite.

### Model C — Distributed Multi-Tenant / Multi-Host Production

**Still NOT READY**, but every remaining requirement is now precisely
evidenced rather than assumed:

| Requirement | Status | Evidence |
|---|---|---|
| Tenant identity | **BUILT, DEMONSTRATED** | P17 + this phase's live multi-process proof (§7) |
| Tenant isolation (reads/writes) | **DEMONSTRATED** | P17's proof + this phase's negative controls (§5) + multi-process proof (§7) |
| Tenant isolation (mission creation) | **DEMONSTRATED — closed this phase** | §4; was a real, previously-open gap |
| Cross-process safety | **DEMONSTRATED** | §7, real separate OS processes, real Barrier-synchronized race |
| ContextVar / concurrent-request safety | **DEMONSTRATED, stronger than P17's own evidence** | §7 Case 2, genuinely concurrent asyncio Tasks |
| Background-job tenant isolation | **DEMONSTRATED, the strongest form tested in this programme** | §7 Case 3 — overrides an adversarial ambient context, not merely "works when nothing else set one" |
| Multi-host container ownership | **TESTED, not DEMONSTRATED** | §10 — misattribution fix re-confirmed unregressed; no second real Docker host available, unchanged from P16 |
| Dead-host recovery / liveness | **NOT BUILT — a real, named gap** | §10 — requires a lease/heartbeat design this phase did not attempt |
| Global concurrency limits under tenant load | **CONFIRMED unaffected, correctly global** | §9 |
| Tenant-scoped concurrency (where required) | **N/A — none required, by evidence, not by omission** | §9 |
| Rate limiting | **CONFIRMED unaffected, correctly global** | §9 (unchanged from P12) |
| No tenant-context leakage | **DEMONSTRATED, both process and Task level** | §7 |
| Observability (no tenant labels) | **CONFIRMED** | §11 |
| Safe Docker ownership | **CONFIRMED unregressed** | §10 |
| Safe approval/execution | **DEMONSTRATED** | §5, §7 Case 1 |
| Idempotency | **CONFIRMED unaffected** (P9's canonical-key scoping was already tenant-implicit via `session_id` — re-confirmed by source reading, unchanged) | — |
| Reconciliation | **CONFIRMED unaffected, and now proven adversarially** | §7 Case 3 |
| Build identity | **CONFIRMED unaffected**, process-level, unrelated to tenancy | — |
| Database security (RLS backstop) | **DESIGNED, DEFERRED** — sharper, more concrete blocker found this phase (§3) | §3 |

**Exact remaining blockers, each stated with what it needs:**

1. **PostgreSQL RLS backstop — DESIGNED, DEFERRED.** Needs: a verified
   per-transaction GUC re-assertion mechanism (proven safe under
   SQLAlchemy's autobegin semantics for a multi-transaction session,
   exactly the shape `approve_capability_request`'s Phase 1/2/3
   structure requires), *or* a role split (tenant-scoped `ados_app` vs.
   a separate system/background role). Not a blocker for the current
   application-level guarantee, which is independently fail-closed and
   proven so (§5) — RLS would be defense-in-depth, not the only
   protection, exactly as designed.
2. **Multi-host dead-host recovery — NOT BUILT.** Needs: a lease/
   heartbeat design (TTL'd ownership a host must actively renew) before
   any automatic cross-host reclaim can be built safely. `--all-hosts`
   plus manual operator consolidation remains the correct, honest
   answer today.
3. **Two-real-Docker-host verification remains unavailable** in this
   environment — the misattribution fix itself (§10) is TESTED, not
   DEMONSTRATED, for exactly this reason, unchanged from P16.
4. **Per-tenant admission/reviewer capacity remains a deliberate,
   undesigned product decision**, not a technical gap — correctly
   deferred until a real second tenant's actual needs exist to design
   against (§9).
5. **Three of P17's five modified live-proof scripts remain TESTED
   (syntax/import verified), not DEMONSTRATED** — `p9_crash_recovery_e2e.py`,
   `prime_agent_approval_e2e.py`, `prime_agent_servicenow_e2e.py` — each
   requires a real, unavoidable ServiceNow side effect to re-execute,
   and each already has real evidence from its own original run; two of
   the five (`p11_orphan_recovery_exercise.py`,
   `p12_docker_ownership_proof.py`) were re-executed live this phase
   and now carry current, fresh evidence (§6).

No other blocker was found. `custom_agents.division` and every other
unrelated dirty-tree item confirmed untouched (§12).

---

STOP after P18. P19 was not started. No commit was made.
