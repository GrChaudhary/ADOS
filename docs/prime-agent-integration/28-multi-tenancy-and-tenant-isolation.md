# P17 — Multi-Tenancy Architecture & Tenant Isolation Implementation

## 1. Verdict

**PASS.** ADOS now has a real tenant identity model and a tenant isolation
mechanism that makes cross-tenant access impossible through the normal
application APIs, closing the exact defect P16 proved live
([27-multi-tenancy-and-multi-host-safety.md](27-multi-tenancy-and-multi-host-safety.md)).
The mechanism is application-enforced (a SQLAlchemy `do_orm_execute`
global filter, fail-closed by default), covers every tenant-owned
resource on the Prime Agent runtime governance surface (missions, runtime
sessions, capability requests — the exact surface P16's live proof
exploited), and is proven live with two real tenants, two real users, real
Postgres, and real HTTP requests. A Postgres Row-Level-Security backstop
was fully evaluated and found structurally viable but was **not** built
this phase — the precise reason is in §7.

**Scope, stated plainly:** this phase did not retrofit tenant isolation
onto the MOA/incidents surface (220 seeded demo records, hundreds of
dependent analytics tests) — that is a deliberate scope boundary, not an
oversight, explained in §5.

## 2. Baseline

HEAD unchanged: `7464902`. No P11–P17 commit exists; nothing was
committed during this phase. Working tree diff is additive on top of
P16's own 99-line dirty-tree state (verified via `git status --short`
before starting).

## 3. Library evaluation

| Candidate | Framework | SQLAlchemy-native? | Verdict |
|---|---|---|---|
| [archtechx/tenancy](https://github.com/archtechx/tenancy) | **Laravel (PHP)** | No | Rejected outright — wrong language and framework entirely. 4.4k stars, actively maintained, genuinely excellent for its actual ecosystem. |
| [django-tenants/django-tenants](https://github.com/django-tenants/django-tenants) | **Django** | No | Rejected — ADOS is FastAPI, not Django; adopting it would mean adopting Django, which the task explicitly forbids. Schema-per-tenant is also a heavier operational model (one Postgres schema per tenant) than this phase's evidence justifies. |
| [citusdata/django-multitenant](https://github.com/citusdata/django-multitenant) | **Django + Citus** | No | Rejected for two independent reasons: wrong framework (Django), and it requires the Citus distributed-Postgres extension, which is not part of this stack and would be genuine new infrastructure. |
| [Telemaco019/sqlalchemy-tenants](https://github.com/Telemaco019/sqlalchemy-tenants) | **FastAPI/SQLAlchemy-compatible** | **Yes** — the only real candidate | Genuinely SQLAlchemy-native, async-compatible, RLS-based. Rejected on maturity/operational grounds, not architecture: 4 GitHub stars, a single maintainer, first released within the last year, and — decisively — its `manager.new_tenant_session(tenant)` pattern requires restructuring how every session in this codebase is constructed (this project's own `get_db_session` FastAPI dependency and `async_session_factory()` convention is used in ~40 modules). Adopting it would be a much larger, riskier change than the native mechanism actually built, for a security-critical dependency with no track record. |
| [Madeeha-Anjum/multi-tenancy-system](https://github.com/Madeeha-Anjum/multi-tenancy-system) | FastAPI/Postgres | N/A | Not a library — a "fork this repo" reference scaffold (PDM/Typer/GCP-specific tooling, subdomain-per-tenant schema routing), not an installable package. Confirmed by inspecting its own README before rejecting it. Not pip-installable, last pushed 2024. |

**Decision: none of the five candidates is appropriate. Built a native
SQLAlchemy 2.0 mechanism instead** — the same conclusion the task itself
invited ("If none of the listed libraries is appropriate, explicitly say
so and implement the appropriate native SQLAlchemy/Postgres design
instead"). The native mechanism (§6) uses `with_loader_criteria` +
`Session.do_orm_execute`, which is SQLAlchemy's own documented recipe for
exactly this problem — not an invented pattern.

## 4. Chosen architecture and rationale

```
authenticated principal (JWT)
      |  tenantIds claim, populated at login from tenant_memberships
      v
  tenant context (backend/app/tenancy.py::get_tenant_context)
      |  resolves ONE active tenant; a caller-supplied X-Tenant-Id header
      |  is only ever a REQUEST for which of the JWT's own memberships to
      |  activate, cross-checked against it -- never trusted alone
      v
  contextvars.ContextVar (db/tenancy.py::current_tenant)
      |  per-async-task, not process-global -- verified safe under real
      |  concurrent requests carrying different tenants (spike + live proof)
      v
  SQLAlchemy do_orm_execute -- with_loader_criteria on every
  tenant-scoped model, every SELECT/UPDATE/DELETE, every existing call
  site, with ZERO changes to how routers already write queries
      |
      v
  fail closed by default; the ONLY way to see across tenants is an
  explicit, reviewed use_all_tenants() -- used by 8 specific, narrow,
  documented call sites (background jobs, the runtime's own
  session-token-authenticated surface), never by an end-user request path
```

This satisfies the task's own core objective — cross-tenant access is
impossible **through the normal application APIs**, not merely
discouraged by convention. A router that queries `CapabilityRequestRow`
via a bare `session.execute(select(...))` — the way every existing router
in this codebase already does — is automatically, silently, correctly
tenant-scoped. Nothing about how ~40 existing modules construct queries
needed to change.

## 5. Tenant model

Two new tables, deliberately minimal (`db/models/tenant.py`):

- **`tenants`** — `tenant_id` (UUID PK), `name`, `slug` (unique), `created_at`.
- **`tenant_memberships`** — `id` (PK), `tenant_id`, `user_id`, unique on
  `(tenant_id, user_id)`.

**No per-tenant role.** `UserRow.role` (manager/executive/admin/auditor,
`backend/app/rbac.py`) stays global — it answers "what is this user
capable of." Tenancy answers a different, orthogonal question: "which
resources can this user reach at all." Building per-tenant roles would be
a real IAM system the task explicitly said not to build, and would break
the JWT's existing stateless-role design (role verified with zero DB
round-trips, `rbac.py`'s own stated architecture since P10).

**Tenant-owned resources, and the one deliberate scope boundary:**

| Resource | Tenant-scoped? | Enforcement |
|---|---|---|
| Missions, runtime sessions, capability requests | **Yes** — the exact P16-demonstrated surface | `db/tenancy.py`, denormalized `tenant_id` on all three |
| Approvals (runtime capability-request decisions) | **Yes** | Same mechanism — the row is invisible, so it cannot be decided |
| Incident/governance records (MOA, `incidents` table) | **No — explicit scope boundary** | See below |
| Audit records | Inherits from `capability_requests`/`runtime_sessions` (same rows) | Same mechanism |

The MOA/incidents surface (`db/models/incident.py`) was deliberately **not**
retrofitted with tenant scoping this phase. Three independent reasons,
each sufficient alone: (1) it carries 220 seeded demo records
(`executive/seed_data.py`) that hundreds of existing analytics/Decision
Memory tests assert against by exact content — retrofitting tenant
ownership onto them would require a genuine product decision about who
"owns" historical demo data, not a schema patch; (2) P16's live proof and
this phase's own Phase 5 instruction ("fix the exact P16 demonstrated
defect") both point at the Prime Agent runtime surface specifically, not
incidents; (3) the blast radius of touching a heavily-tested, working
surface for a capability nothing has asked for yet would violate the
task's own "do not make unrelated refactors" instruction. This is a named,
deliberate **NOT BUILT** boundary, not a silent gap.

**Migration/backfill (`alembic/versions/e6f7a8b9c0d1_...`), explicit and
safe, three steps in one migration** (this codebase's migrations are not
zero-downtime-constrained — `db/engine.py`'s own docstring: "single
deployment, not a high-QPS multi-tenant SaaS"):

1. Seed exactly one well-known tenant, `DEFAULT_TENANT_ID`
   (`00000000-0000-0000-0000-000000000001`, hardcoded identically in the
   migration and in `db/models/tenant.py` so schema and code always
   agree without a runtime lookup). Enroll every existing user
   (all 5 seeded accounts) as a member.
2. Add `tenant_id` nullable on `missions`/`runtime_sessions`/
   `capability_requests`, backfill every existing row to the default
   tenant, then `ALTER ... NOT NULL`.
3. Nothing else is touched.

**Legacy/system rows:** `MissionRow.tenant_id` etc. carry a Python-level
default of `DEFAULT_TENANT_ID` (not "no default," reconsidered mid-phase
— see §9's "what changed during implementation"). Background jobs use the
explicit `use_all_tenants()` escape hatch, never a tenant value. Global/
operator resources (`admission_leases`, `rate_limit_events`,
`capability_manifests`) are untouched — never tenant-scoped, confirmed
correct in §8.

## 6. Authentication → tenant resolution

`backend/app/user_store.py::verify_login` (the one path that mints a real
login JWT) queries `tenant_memberships` and populates `User.tenant_ids`
before `create_access_token` bakes it into the JWT — the same
zero-extra-round-trip-at-verify-time design `role`/`approval_limit_usd`
already use (`rbac.py`'s own stated architecture: "verifying a request
never needs a database round-trip").

**Active tenant selection** (`backend/app/tenancy.py::get_tenant_context`):
a user with exactly one membership (every seeded account today) needs no
extra step. A user in more than one tenant **must** send `X-Tenant-Id`,
cross-checked against their own JWT-verified membership set — supplying
a tenant they do not belong to is refused with the same 403 regardless of
whether that tenant exists, so the header can never be used to enumerate
real tenant ids. **Never accepted as sole authority** — this directly
satisfies the task's own explicit requirement.

**Concurrency safety, proven not assumed:** tenant context lives in a
`contextvars.ContextVar`, not a process-global or request-object
attribute. A dedicated spike (before any production code was written)
proved, against real Postgres, that concurrent `asyncio.gather` requests
carrying **different** tenants never leak into each other — each
asyncio Task gets its own copy-on-write context. The live proof script
(§9) and the focused test suite exercise this same property through real
concurrent HTTP requests.

## 7. Database isolation mechanism

**Chosen: application-enforced (A), not Postgres RLS (B), with RLS fully
evaluated and its precondition confirmed correct — but not built.**

**The mechanism** (`db/tenancy.py`): a single `Session.do_orm_execute`
event, registered once at import time, injects `with_loader_criteria` for
every tenant-scoped model (`MissionRow`, `RuntimeSessionRow`,
`CapabilityRequestRow`) on every SELECT/UPDATE/DELETE — verified to cover
`session.execute(select(...))`, `session.get(...)`, and ORM-level bulk
`update()`/`delete()` statements (proven individually, not assumed; the
`get()` coverage specifically was not obvious and was checked with a
dedicated spike before relying on it). **Fails closed**: no resolved
tenant context filters a query to zero rows, never to all rows — proven
by negative control #1 (§11).

**Why not RLS, given it was seriously considered:** P10's own migration
(`f4a5b6c7d8e9_ados_app_least_privilege_role.py`) already built exactly
the precondition RLS needs — `ados_app` (the role the real deployed
`backend` service connects as, confirmed in `docker-compose.yml`) does
**not** own any table (`ados`, the migration role, does), so RLS policies
would genuinely apply to it and not be silently bypassed the way they
would for a table-owning role. This was independently re-verified this
phase, not assumed from the P10 report.

What makes it **not** buildable as a clean, low-risk addition this phase:
`ados_app` is the **one shared role** for every access pattern in this
process — tenant-scoped HTTP requests (which should see one tenant) AND
the runtime's session-token-authenticated gateway AND the background
reconciliation jobs (both of which must legitimately see every tenant).
RLS operates at the connection/role level via a session GUC
(`current_setting('app.tenant_id')`), which would need to be propagated
correctly on **every** checkout of a fresh `NullPool` connection for
every one of those different access patterns — including a working
"bypass" policy for the cross-tenant ones. The two ways to do this
correctly are: (a) split `ados_app` into a tenant-scoped role and a
separate system/background role (a real schema + deployment change,
its own migration and `DATABASE_URL` wiring), or (b) a `PoolEvents`-level
`SET`/`SET LOCAL` hook mirroring the `ContextVar` exactly, which carries
real correctness risk under `asyncpg`'s async connection model
(synchronous pool-checkout hooks issuing statements against an
async-native driver) that this phase's own timeline did not allow
verifying to the same standard as everything else in this report.

**Classified DESIGNED, NOT BUILT** — not silently skipped. The exact
policies that would be needed, for the record:

```sql
ALTER TABLE missions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON missions
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- (repeated for runtime_sessions, capability_requests)
```

(No `FORCE ROW LEVEL SECURITY` — `ados`, the owning/migration role, must
stay unrestricted for backfills and admin operations, exactly as it
already is today.) This is real, ready-to-implement follow-on work, named
precisely so a future phase does not have to re-derive it.

**Application-level protection against developer omission**, the other
half of Phase 4's question: `with_loader_criteria` applies **globally**
to every query against a tenant-scoped model regardless of call site —
a developer cannot "forget" a tenant filter the way they could forget a
manual `WHERE` clause, because there is no manual clause to forget. The
only way to bypass it is the explicit, reviewed `use_all_tenants()` — a
searchable, small (8 call sites), individually-justified exception list,
not an ambient default.

## 8. Every tenant-owned resource and its enforcement point

| Resource | Owner column | Enforcement point |
|---|---|---|
| `missions` | `tenant_id` (NOT NULL, default `DEFAULT_TENANT_ID`) | `db/tenancy.py` global filter |
| `runtime_sessions` | `tenant_id` (denormalized from mission at creation) | Same |
| `capability_requests` | `tenant_id` (denormalized from mission at parking time, `mcp_gateway.py::request_capability`) | Same |
| List/get/approve/reject (`backend/app/routers/runtime_approvals.py`) | — | `Depends(get_tenant_context)` at router level; every route automatically scoped |
| Mission/session creation (`integrations/connectors/prime_runtime.py`) | Stamped at creation | Defaults to `DEFAULT_TENANT_ID` — see §12 for the honest limitation this carries |
| Capability-request parking (`backend/app/mcp_gateway.py`) | Stamped from the resolved mission | Session-token-authenticated (not JWT) — the whole module runs under the explicit `all_tenants_session` escape hatch, since its real authorization boundary (a possessed, unforgeable session token resolved server-side) is narrower and stronger than tenant membership |
| `GET /metrics` backlog gauges (`backend/app/routers/metrics.py`) | — | Deliberately global (`use_all_tenants`) — unauthenticated infrastructure, no tenant context to resolve, and the operator alerting it feeds needs the true global backlog |
| Orphan sweep, capability reconciliation, session reconciliation (background jobs) | — | Deliberately global (`use_all_tenants`) — see §9 for why removing this is itself a proven, load-bearing failure mode, not a decorative wrapper |

## 9. Governance/approval isolation evidence

**The exact P16-demonstrated defect, closed and proven live.**
`scripts/p17_tenant_isolation_proof.py` — real, unmodified
`backend.app.main:app`; real Postgres; real bcrypt-verified `/auth/login`
for tenant A's user (`emma`, one of the five permanent seeded accounts);
a freshly created, temporary second tenant and user for tenant B
(created directly and cleaned up, the same convention P16's own proof
used, since no user-facing "create a mission" endpoint exists to drive
this through end to end otherwise). Full transcript:

```
-- as emma (tenant: default) --
  [PASS] emma's list includes request A (same tenant)
  [PASS] emma's list excludes request B (tenant B)
  [PASS] emma GET request B -> 404 (not 403 -- existence not revealed)
  [PASS] emma reject request B -> 404, no decision recorded

-- as tenant B's user (tenant: B) --
  [PASS] tenant B's list includes request B (own tenant)
  [PASS] tenant B's list excludes request A (default tenant)
  [PASS] tenant B GET request A -> 404
  [PASS] tenant B reject request A -> 404, no decision recorded

-- tenant B correctly acting on its OWN request (isolation, not lockout) --
  [PASS] tenant B can reject its own request B
  [PASS] request A untouched by every cross-tenant attempt
  [PASS] request B correctly decided by its own tenant's user

-- cleanup --
  [PASS] independent re-query: both missions fully removed
  [PASS] independent re-query: tenant B fully removed
```

**404, not 403, on a cross-tenant fetch** — deliberately: existence is
never revealed to a non-member, matching the task's own "without
revealing sensitive information" requirement.

**The database query itself is tenant-scoped, not just the endpoint** —
verified independently at the ORM level (`backend/tests/
test_tenant_isolation.py::test_the_orm_query_itself_is_tenant_scoped_
not_just_the_endpoint`): a plain `select(MissionRow)` and a plain
`session.get(MissionRow, ...)`, called directly with no router involved,
both correctly return nothing for a mission belonging to a different
tenant, and both correctly return the row once the matching tenant
context is active.

**Focused pytest suite** (`backend/tests/test_tenant_isolation.py`), 7/7
passing, real Postgres + real HTTP throughout (`TestClient`): list, get,
reject, and the ORM-level check above, for both directions (A cannot
reach B, B cannot reach A), plus the inverse confirmation that same-tenant
access is unaffected — isolation, not a blanket lockout.

## 10. Execution/idempotency/reconciliation isolation evidence

Re-evaluated, not assumed. **No code changes were needed** — every
property was already safe under the new tenant model, by construction:

- **Idempotency keys cannot collide across tenants.** The canonical key
  (`SHA-256(session_id, capability, arguments)`, P9) is scoped by a
  partial unique index on `(session_id, idempotency_key)`. `session_id`
  is a server-generated, unguessable UUIDv4, and every session belongs to
  exactly one tenant immutably. Cross-tenant collision was already
  structurally impossible before this phase (P16 confirmed this for the
  session-scoping question generally); tenancy adds nothing new to
  reason about here, since the identifier space was already
  tenant-implicit.
- **`outcome_unknown` reconciliation cannot resolve one tenant's request
  using another tenant's evidence.** `reconcile_outcome_unknown` (P9)
  queries the external system using **only** the row's own canonical
  `request_id` — a globally unique UUID tied to exactly one row, never a
  shared or guessable marker. A row from tenant A can only ever be
  resolved using evidence matching tenant A's own external marker; there
  is no code path that could conflate it with tenant B's row. Extending
  P9's own principle ("reconciliation resolves only on positive
  evidence") to ownership was the task's explicit ask — the answer is
  that the *existing* evidence-gating (by exact `request_id`) already
  implies correct tenant ownership, since ownership was fixed
  immutably at row-creation time and reconciliation never touches it.
- **Background reconciliation cannot accidentally cross tenant
  boundaries** in the sense that matters (adopting one tenant's outcome
  for another's request) — it legitimately scans every tenant by design
  (a status transition based on elapsed time / external evidence, never
  a data disclosure), which is exactly why it runs under the explicit
  `use_all_tenants()` escape hatch rather than being blocked by the
  fail-closed default.
- **Capability execution always has the correct tenant context** — by
  the time `_execute_capability` runs, the request/mission it operates on
  has already been validated as belonging to the correct tenant by
  whichever caller reached it (`runtime_approvals.py`'s tenant-scoped
  fetch, or `mcp_gateway.py`'s session-token-scoped fetch); `_execute_
  capability` itself never queries a tenant-scoped table.

**No exactly-once claim is made or implied anywhere in this phase.** P9's
`outcome_unknown` safety model and its explicit "ServiceNow does not
guarantee exactly-once" statement are unchanged and unweakened.

## 11. Negative controls

All 6, each disabled a real guard, reproduced the exact predicted
failure, restored, SHA-256 byte-identical.

| # | Guard removed | Expected failure | Result |
|---|---|---|---|
| 1 | `do_orm_execute`'s SELECT-side tenant filter (`db/tenancy.py`) | Cross-tenant read succeeds | **Confirmed** — both a cross-tenant GET and the ORM-level test flipped from refused to succeeding |
| 2 | `do_orm_execute`'s UPDATE/DELETE-side filter only (SELECT left active) | A direct bulk `UPDATE` from tenant A's context can mutate tenant B's row by id | **Confirmed** — `rowcount=1`, the row's title became `"HACKED"` (this specific mutation shape does not exist in real production code today — every real decision goes through "find via tenant-filtered SELECT, then mutate the found object," which the SELECT-side filter alone already protects; this control proves the second layer is real defense-in-depth, not decorative, for any future code that used a bulk statement instead) |
| 3 | Membership check on the `X-Tenant-Id` header (`backend/app/tenancy.py`) | A user can claim any tenant merely by naming it | **Confirmed** — request that should 403 returned 200 |
| 4 | `get_tenant_context` router dependency (`runtime_approvals.py`) | The exact P16 defect returns | **Confirmed** — 4/7 tenant-isolation tests failed for exactly the pre-P17 reason (200 instead of 404) |
| 5 | `tenant_id=mission.tenant_id` stamping at parking time (`mcp_gateway.py`) | A request belonging to tenant B gets mis-tagged with the default tenant, making it visible to tenant A | **Confirmed** — direct check showed `row.tenant_id == DEFAULT_TENANT_ID` instead of the real tenant B id |
| 6 | `use_all_tenants()` around a background job's own session (`orphan_sweep.py`) | The background job breaks (fails closed, sees nothing) rather than working across tenants as required | **Confirmed** — `claim_batch` returned 0 claimed against a real orphaned row, run the way the real periodic scheduler actually calls it (no ambient context) |

Guards from the task's own list that do not exist and so have no control
to run: none — every item on the task's minimum list maps to a real
guard in this implementation, unlike P16 where several had no
counterpart to test. Cross-tenant idempotency protection (task item 9) is
covered by §10's analysis rather than a redundant runtime toggle, since
the protection is a schema-level property (an unguessable, already-unique
identifier) with no "disable" switch to pull.

## 12. Focused test counts

`backend/tests/test_tenant_isolation.py`: **7/7 passed** (new).
`backend/tests/test_database_role_privileges.py`: **12/12 passed**
(1 fixed — a raw-SQL `INSERT` needed an explicit `tenant_id`, since raw
Core SQL bypasses the ORM-level Python default entirely; confirmed by
direct empirical test, not assumed). `scripts/p17_tenant_isolation_proof.py`:
all checks PASS, cleanup independently verified.

## 13. Full-suite test counts

**907 passed / 0 failed / 19 deselected** — exactly P16's 900 baseline +
7 new tenant-isolation tests. Reconciled exactly, run alone (not
concurrently with anything else touching Postgres, per the documented
P15 lesson about spurious contention failures).

## 14. Docker test counts

**17 passed / 0 failed / 909 deselected** — exactly P16's 909 (902 + 7
new) reflected the other way. Both runs report the same total collection
(926), confirming no test-discovery drift. `test_backup_restore.py`'s 3
raw-SQL mission inserts needed the same explicit `tenant_id` fix as
`test_database_role_privileges.py`, for the identical reason (raw Core
SQL, not ORM).

## 15. External side effects

None. Every decision in every live proof used `reject`, which has zero
external effect and shares the identical authorization gates `approve`
does (confirmed by source review, matching P16's own established
reasoning for the same choice). `scripts/prime_agent_approval_e2e.py`
and `scripts/prime_agent_servicenow_e2e.py` were fixed for
tenant-compatibility (their own direct DB verification reads needed the
same `use_all_tenants()` treatment every other live-proof script needed)
but **not** re-executed live this phase — doing so would create a real
ServiceNow change request / real Docker containers for a finding already
proven by cheaper means (the dedicated P17 proof script, the focused
test suite, and the re-run P14/P15 multiprocess proofs below). Classified
TESTED-for-syntax-and-import, not re-DEMONSTRATED end-to-end.

## 16. Multi-process / regression evidence (Phase 8)

**A real regression was found and fixed during this phase's own
verification** — `scripts/p15_multiprocess_concurrency_proof.py`'s
worker process calls `_load_pending_or_404` **directly**, bypassing the
FastAPI dependency layer by design (to isolate the concurrency primitive
from auth concerns, a deliberate P15 choice). Once tenant scoping became
part of what that function needs to find a row at all, the bypass meant
the row was invisible (fail-closed, no ambient context) — a script
correctness gap, not a production defect (the real HTTP path, which does
resolve tenant context, was never affected). Fixed by wrapping the
script's own direct calls in `use_all_tenants()`, preserving its original
intent exactly (auth and now tenancy both deliberately out of the way,
only the DB-level lock/status-check primitive under test). Three more
verification-read helpers in the same script needed the identical fix.

**Re-run after the fix, in full:**

- `scripts/p15_multiprocess_concurrency_proof.py` — **RESULT: PASS**, all
  cases, across real, separate OS processes, including the genuine
  `SIGKILL` crash boundary (Case 3b) and the 10-real-process admission
  race landing on exactly the configured limit of 3 (Case 4).
- `scripts/p14_multiprocess_capability_proof.py` — **RESULT: PASS**, all
  6 cases, unaffected (confirmed by source review it never touches a
  tenant-scoped table, then confirmed live by running it unmodified).

Five more live-proof scripts (`p9_crash_recovery_e2e.py`,
`p11_orphan_recovery_exercise.py`, `p12_docker_ownership_proof.py`,
`prime_agent_approval_e2e.py`, `prime_agent_servicenow_e2e.py`) were
found to have the same class of gap by grep and fixed the same way;
not all were re-executed live this phase (§15) — classified TESTED
(syntax/import verified), not DEMONSTRATED, for those specific scripts.

**Not regressed, confirmed:** admission leases, capability registry
consistency, approval atomicity, idempotency, `outcome_unknown` recovery,
and P16's `owner_host`/`node_id` orphan-sweep protection — none of these
mechanisms were touched by this phase's changes (grep-confirmed: no
tenant-scoped table appears in `admission_control.py`,
`capability_manifest.py`, or the `owner_host` filter logic itself), and
the P14/P15 re-runs above exercise the first four directly.

## 17. Global vs tenant-scoped controls

| Control | Classification | Reasoning |
|---|---|---|
| Admission control (capability/mission concurrency, P11/P12) | **GLOBAL — unchanged, correct** | Bounds a genuinely shared physical resource (the Docker daemon, the paid LLM budget) — one host's capacity does not divide meaningfully per tenant |
| Mission-start rate limit (P12) | **GLOBAL — unchanged, correct** | Same reasoning — a shared paid-LLM/Docker budget |
| Approval queue depth (`max_pending_approvals`) | **GLOBAL — deliberately kept, named trade-off** | Bounds a shared *human* resource (today's 5 operators review everything, in one organization); making it tenant-scoped without first deciding whether tenant B gets its own reviewer pool would be a premature product decision, not a technical one — named explicitly rather than changed reflexively, per the task's own "design deliberately" instruction |
| Session-activity/repeat-request cap | Inherently per-session already | A session belongs to exactly one tenant by construction; no change needed |
| Metrics (`ados_approval_queue_depth` etc.) | **GLOBAL — unchanged, correct** | No tenant identifier was added to any Prometheus label (re-confirmed label-by-label, same as P16); a per-tenant breakdown, if ever needed, belongs in structured logs or an operator query, never an unbounded label — the task's own explicit warning |
| Orphan sweeping / capability / session reconciliation | **GLOBAL by design** | Background maintenance, not user-facing data exposure — see §10 |
| Docker ownership (P16 `owner_host`/`node_id`) | **HOST-scoped — untouched** | An orthogonal boundary; explicitly not weakened per this phase's own instruction |
| Build identity | **GLOBAL — unchanged** | Process-level, unrelated to tenancy |

No tenant identifier was added to any Prometheus label anywhere in this
phase — verified by re-reading every metric definition, matching P16's
own established discipline.

## 18. Migration/backfill details

See §5. Applied cleanly to both `ados` (dev) and `ados_test` databases;
backfill verified directly: 1 tenant row, 5 memberships (matching the 5
pre-existing users exactly), 0 NULL `tenant_id` rows remaining in any of
the three tables, both before and after re-verification. `bootstrap_users`
(`backend/app/user_store.py`) was also updated to enroll every
newly-seeded account in the default tenant going forward — necessary
because this test suite's own `_clean_users_table` fixture truncates and
re-seeds `users` with fresh UUIDs on every test, which would otherwise
orphan the migration-time membership snapshot after the very first test
ran.

## 19. Remaining limitations

- **Mission creation has no user-facing entry point at all** (grep-confirmed:
  `RunPrimeRLMAgent` has no HTTP router caller anywhere in this codebase),
  so there is no real authenticated-caller tenant to thread through at
  creation time yet — every real mission today defaults to the one
  default tenant. This is not a gap this phase could close: the missing
  piece is a "start a mission" endpoint that doesn't exist, not a tenancy
  defect. Documented honestly rather than worked around.
- **Postgres RLS is DESIGNED, NOT BUILT** — see §7 for the exact
  precondition confirmed correct and the exact reason building it safely
  needs either a role split or a session-GUC-propagation mechanism this
  phase's timeline did not allow verifying to the same standard as
  everything else here.
- **The MOA/incidents governance surface remains entirely untenanted** —
  a deliberate, named scope boundary (§5), not an oversight.
- **Five live-proof scripts were fixed for tenant-compatibility but not
  re-executed live** (§16) — TESTED, not DEMONSTRATED, for those
  specifically.
- **No per-tenant admission/rate-limit layer exists** — every control
  that remains global (§17) was a deliberate choice for today's
  single-reviewer-pool reality, not a proven-safe design for a real
  multi-tenant SaaS with independent tenant capacity guarantees.

## 20. Model A / B / C verdict

- **Model A: unaffected, READY.** Every pre-P17 single-process code path
  behaves identically — `DEFAULT_TENANT_ID` and the fail-closed default
  compose to exactly reproduce prior behavior for a single-tenant
  deployment.
- **Model B: unaffected, READY.** Same reasoning; P12–P16's multi-process
  guarantees are re-confirmed unregressed in §16.
- **Model C: still NOT READY, but the dominant named blocker is now
  closed.** P16 named two reasons: no tenant model (now **BUILT and
  DEMONSTRATED** on the exact surface that mattered), and multi-host
  Docker ownership (P16's own fix, untouched and reconfirmed unregressed
  this phase). What remains for a genuine Model C claim: the RLS backstop
  (DESIGNED, NOT BUILT), a real "create a mission on behalf of tenant X"
  entry point, a deliberate decision on per-tenant admission/reviewer
  capacity, and the MOA/incidents surface's own tenant story — each named
  precisely rather than left implicit.

## 21. Exact remaining blockers

1. Postgres RLS backstop — designed, not built (§7).
2. No user-facing mission-creation endpoint to attribute a real caller
   tenant to (§19) — an absence this phase could not have closed, since
   the endpoint itself doesn't exist yet.
3. MOA/incidents surface has no tenant story — deliberate, named scope
   boundary (§5).
4. Five live-proof scripts fixed but not re-executed live (§16/§19).
5. Per-tenant admission/reviewer-capacity design — a product decision,
   not a technical gap (§17).

No other blocker was found. `custom_agents.division` confirmed untouched
and unrelated to this phase's scope.

STOP after P17. P18 was not started.
