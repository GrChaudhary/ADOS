# P16 — Multi-Tenancy & Multi-Host Ownership Safety Review

## 1. Verdict

**PASS**, with an honest, load-bearing finding: **ADOS has no tenant
isolation model of any kind today.** This is not a bug in any one
component — it is confirmed, consistently, across every table, router, and
background process in the system. Authorization here is **role-based
only** (`backend/app/rbac.py`'s `Role` enum: manager / executive / admin /
auditor), never ownership-based. Any authenticated user can read, list,
approve, reject, and act on every mission, session, and capability request
in the system, regardless of who or what created it. This matches every
prior phase's own stated scope ("single organization, controlled internal
users") and P15's own verdict (Model C: NOT READY, naming multi-tenancy
and multi-host ownership as the two reasons) — P16's job was to determine
*exactly* how not-ready, not to assume the answer.

Separately, a **real, previously-unknown defect** was found and fixed in
the multi-**host** (not multi-tenant) direction: `orchestrate/runtime/
orphan_sweep.py`'s cleanup sweep had no host affinity at all. In a
deployment with more than one ADOS process on separate hosts, each with
its own Docker daemon but sharing one Postgres database (the only
realistic multi-host topology this codebase could grow into without
Kubernetes/a service mesh), any host's sweeper could claim any other
host's session row and durably record its still-running container as
`absent` — a terminal, never-reclaimed status — simply because that
container is invisible from the wrong host's local Docker socket. Fixed
with the smallest correct mechanism: a nullable `owner_host` column and a
claim-query filter, fully backward-compatible with every single-host
deployment that exists today.

**No multi-tenancy was implemented.** Per this phase's own explicit
instruction, `tenant_id` was not added anywhere "because it sounds
right" — the evidence does not show a bounded, minimal fix exists for
"no tenant concept exists at all"; that is an architecture decision for a
future phase to scope deliberately, not a defect P16 can safely patch in
place.

## 2. Baseline

HEAD unchanged: `7464902`. No P11–P16 commit exists yet; nothing was
committed during this phase. Working tree re-verified against the exact
90-line dirty-tree state P15 left behind (its own pre-existing,
uncommitted P11–P15 work, explicitly preserved, untouched) before any P16
edit was made.

## 3. Exact files changed

**New:**
- `alembic/versions/d5e6f7a8b9c0_add_owner_host_to_runtime_sessions.py` —
  the schema migration (nullable `owner_host` on `runtime_sessions`).
- `backend/tests/test_orphan_sweep_multihost.py` — 7 focused regression
  tests for the host-scoping fix, including one real-concurrency race test.
- `scripts/p16_tenant_boundary_proof.py` — live proof (real app, real
  Postgres, real JWT auth, two real distinct seeded users) that no
  ownership boundary exists on the runtime-approval surface.
- This document, and the doc 18 / doc 14 updates below.

**Modified:**
- `db/models/mission.py` — added `RuntimeSessionRow.owner_host`.
- `backend/app/config.py` — added `Settings.node_id`.
- `orchestrate/runtime/orphan_sweep.py` — added `effective_node_id()`, and
  a `node_id` parameter on `claim_batch`/`sweep_once` that filters the
  claim query to `owner_host IS NULL OR owner_host == node_id`.
- `integrations/connectors/prime_runtime.py` — stamps `owner_host` at real
  session-creation time.
- `backend/app/main.py` — the periodic sweep now passes its own
  `effective_node_id()`.
- `scripts/sweep_orphans.py` — same, plus a new `--all-hosts` opt-out flag
  for an operator who deliberately wants the old, unscoped behavior.

**Unrelated pre-existing dirty-tree files were not touched** — confirmed
by `git status --short` before and after: exactly the P15 baseline's 90
lines, plus this phase's own new/modified files, nothing else moved.

## 4. Architecture findings

Traced fresh from source (not from any prior report) for every stateful
object the task named:

| Object | Owner identity | Scope | Enforced where | Readable/mutable by another "tenant"? |
|---|---|---|---|---|
| Authentication (`UserRow`, JWT) | `user_id`, flat namespace | Global | `rbac.py` (role only) | N/A — no tenant claim exists in the token |
| Missions | `created_by` (free-text, defaults `"system"`, **never set to an end user** by the one real creation path) | Global | Nowhere — no router filters by `created_by` | Yes — any authenticated user, any role |
| Runtime sessions | `session_id` (UUID) | Global | Nowhere | Yes |
| Capability requests | `request_id`/`session_id`/`mission_id` (UUIDs) | Global | Role/tier only (`authorize_governance_decision`) | Yes — proven live, §7 |
| Approvals (both surfaces: MOA incidents and runtime capability requests) | none | Global | Role/tier only | Yes |
| Capability execution | — | Global (per-process/global admission ceiling, not per-tenant) | `IntegrationHub.invoke()` | N/A — no tenant concept to check |
| Idempotency keys | `session_id` (part of the DB unique index) | Per-session | **Database-enforced** (`uq_capability_requests_session_idempotency`, partial unique index) | No — structurally impossible to collide across sessions, since `session_id` is a server-generated, unguessable UUIDv4 and is itself part of the uniqueness key |
| Reconciliation | `request_id`/`session_id` | Global (any stalled row, any session) | `mark_stalled_executions_unknown` — no ownership filter, by design (it does not need one: reconciliation only ever moves a row to `outcome_unknown`, never adopts another row's outcome) | Not applicable — see §6 |
| Admission leases | `gate` (fixed 2-value enum) | **Intentionally global** (infrastructure-wide ceiling) | `pg_advisory_xact_lock` + `admission_leases` table | N/A — deliberately shared, not tenant-scoped (§8) |
| Rate limiting (mission-start) | `limiter` (fixed enum) | **Intentionally global** | Postgres-backed fixed window | N/A — deliberately shared (§8) |
| Metrics | fixed closed enums only | Global | `prometheus_client` default registry | N/A — no tenant identifier ever enters a label (§9, re-confirmed) |
| Audit records (`RuntimeSessionRow.events`, capability-request rows) | `session_id` | Global | Append-only, no filter | Yes — readable by anyone with the request/session id, and enumerable via the unfiltered list endpoint |
| Docker containers/networks | `ados.session_id`, `ados.managed_by` labels (P7-C) | Session-scoped, **not host-scoped** | Docker label match, checked against **whichever daemon the checking process can reach** | See §5 — this was the real defect |
| Workspace directories | `RuntimeSessionRow.workspace_path`, OS-random via `tempfile.mkdtemp` | Session-scoped | Root+prefix validation (`_workspace_path_ok`) before any deletion | No — confirmed safe, §6 |
| Background reconciliation / orphan sweep | — | Was global; now optionally host-scoped (§5) | `SELECT ... FOR UPDATE SKIP LOCKED` (claim), Docker label match (verify) | See §5 |
| PostgreSQL connections | — | Process-scoped (`NullPool`, deliberate — no pool ceiling) | N/A | N/A |
| Process-local/global singletons | `IntegrationHub`, `AdmissionControl` | Per-instance (not module-global, by P11's own explicit design) | N/A | N/A — already scoped correctly for its purpose |

**After process restart:** every mechanism above is Postgres-backed except
Docker-daemon-local state (containers/networks) and in-process
singletons — both already covered by existing reconciliation
(`session_reconcile.py`, `orphan_sweep.py`, `admission_lease_reclaim.py`).
No new restart-safety gap was found.

**If two hosts race** (same DB, separate Docker daemons): every
Postgres-mediated race (approval, admission, idempotency, reconciliation)
is safe — proven under real concurrent load in P13/P14/P15 and unaffected
by anything host-specific, since Postgres has no concept of "which host."
The one place host identity actually mattered — Docker/workspace
cleanup — is exactly where the real defect was (§5).

## 5. Docker multi-host ownership — the real defect, found and fixed

**The gap.** `orphan_sweep.py::_process_docker` calls `docker inspect`
against whatever Docker daemon the calling process can reach. `docker
inspect` on a name that genuinely never existed, and on a name that exists
but only on a *different* host's daemon, are indistinguishable — both
return "no such object." Before this phase, `claim_batch`'s claim query
(`SELECT ... FOR UPDATE SKIP LOCKED` on `runtime_sessions`) had **no host
affinity whatsoever**: any sweeper, on any host, could claim any terminal,
orphan-marked session row in the shared database. A sweeper on host A
claiming a session that was actually started (and is still genuinely
running) on host B would see nothing on its own daemon, conclude
`"absent"`, and durably write that as the row's terminal status —
`_eligible_for_claim` never reclaims a terminal outcome. The real
container on host B would then **leak permanently**, recorded in ADOS's
own audit trail as successfully cleaned.

**The fix — the smallest mechanism that closes it, no distributed control
plane:**
- `RuntimeSessionRow.owner_host` (nullable `String`) — set once, at real
  session-creation time, to `Settings.node_id` or (if unset, the default
  for every deployment today) `socket.gethostname()`.
- `claim_batch(..., node_id=...)` — when given, restricts the claim query
  to `owner_host IS NULL OR owner_host == node_id`. `node_id=None` (every
  pre-P16 caller, and every test that doesn't opt in) preserves the exact
  old behavior — this is why the fix changes nothing for Model A/B.
  `backend/app/main.py`'s periodic sweep and `scripts/sweep_orphans.py`
  now pass their own `effective_node_id()` by default (the manual script
  gained `--all-hosts` to opt back out).
- NULL `owner_host` (every row written before this migration, and any
  future caller that doesn't set it) is treated as "claimable by anyone" —
  the same posture a single-host deployment already has, since there is
  only one host anyway.

**What this does NOT do**, per Phase 11's explicit instruction: no leader
election, no distributed lock beyond the row-level one Postgres already
provided, no cross-host Docker API, no service discovery. A host that
crashes permanently and never restarts still leaves its sessions
unclaimed by anyone else — that is an explicit, named, out-of-scope
limitation (§12), not silently papered over.

**Evidence.** Real Postgres throughout (matching this repo's own
established convention for this exact module); Docker calls monkeypatched
at the same seam `test_orphan_sweep.py` already uses for its own
decision-logic tests — no real second Docker host exists to test against,
and none was faked. Classified **TESTED**, not DEMONSTRATED (see §12 for
exactly what a real two-host proof would still need). 7/7 new tests pass,
including one genuine-race test (`asyncio.gather` of two `claim_batch`
calls with different `node_id`s against a shared pool of host-A/host-B/
legacy rows — the same concurrency rigor `test_two_concurrent_sweeps_
never_claim_the_same_resource` already established as sufficient for this
module's own `SKIP LOCKED` claims). One of the new tests reproduces the
exact pre-fix failure mode directly: a session owned by "host-b" is
**never** marked `absent` by a sweeper running as "host-a."

## 6. Tenant boundary model, and the live proof

**Minimum identity boundary chosen, per the task's own instruction not to
invent enterprise IAM:** the closest real analogue this codebase has to
"tenant A vs tenant B" is two distinct, independently-authenticated
`UserRow` accounts. This is not a designed tenant primitive — it is the
honest floor: there is nothing narrower than "a logged-in user" to test
a boundary against, because nothing narrower exists in the schema.

**Live proof — `scripts/p16_tenant_boundary_proof.py`.** Real,
unmodified `backend.app.main:app`; real Postgres; real bcrypt-verified
`/auth/login`; real JWTs; two real, distinct, differently-provisioned
seeded accounts (`emma`, `marcus` — both role MANAGER, deliberately
symmetric, so the result cannot be attributed to a role difference). A
mission/session/capability-request row was seeded directly (standing in
for what a real Prime Agent mission leaves behind — `created_by="system"`,
exactly as every real one is, since no code path ever attributes a
mission to an individual user). Run against the real dev database, full
transcript:

```
-- as emma, who created nothing and has no recorded relationship to this request --
  [PASS] GET /runtime/capability-requests (global list, no filter) includes the request
  [PASS] GET .../{id} returns full detail to an unrelated user
  [PASS] detail includes the mission's real argument content (not redacted)

-- as marcus, an equally unrelated second account --
  [PASS] marcus can independently read the same request in full

-- as emma: decide it (reject — zero external side effect, same auth gates as approve) --
  [PASS] emma's decision is accepted (no ownership check anywhere in the path)
  [PASS] row now durably attributes the decision to emma
  [PASS] independent DB re-read confirms: status=denied, decided_by=user:emma

-- cleanup --
  [PASS] independent re-query: mission fully removed after cleanup
```

`reject` was used deliberately instead of `approve`: both share the
identical three authorization gates (`_load_pending_or_404`,
`_live_session_or_409`, `authorize_governance_decision` — confirmed by
reading `runtime_approvals.py` in full; neither has any additional
ownership check the other lacks), so the finding is identical either way,
and `reject` creates zero external (ServiceNow) side effect, matching this
phase's own preference to avoid unnecessary live external records.
ServiceNow *is* configured in this environment (`.env` carries real
credentials) — confirmed before choosing `reject` over `approve`,
specifically to avoid an avoidable real ticket.

**Classified TESTED** (real app, real Postgres, real auth, in-process ASGI
transport — not a separate network hop). This is the right rigor for an
**authorization-logic** boundary, where the property under test is "does
this code path check ownership," not a concurrency race where process
separation matters (P14/P15's own reason for `multiprocessing`). Nothing
here would look different over a real network hop; RBAC and DB access are
identical either way.

**Checklist against the task's own Phase 2/9 list** — "can tenant A do X
to tenant B's resource":

| Action | Result today |
|---|---|
| Read B's mission/session/capability request | **Yes** (proven live) |
| Approve/reject B's request | **Yes** (proven live) |
| Execute B's capability | **Yes** — same code path as approve; no additional check exists to test separately |
| Reuse B's idempotency key | **No** — structurally prevented; see §4's idempotency row |
| Trigger reconciliation of B's outcome | Reconciliation has no per-actor trigger to begin with — it is a periodic pass over all stalled rows, by design (§4) |
| Consume B's admission capacity | **Yes, by design** — admission is an intentional global ceiling, not tenant-scoped (§8) |
| Consume B's rate-limit budget | **Yes, by design** — same reason |
| Read B's audit records | **Yes** (same as "read", above) |
| Influence B's metrics | No tenant identifier exists in any metric label to influence (§9) |
| Delete B's Docker resources | Not tested live (would need a second real host); at the DB/decision layer, **fixed** in this phase (§5) |
| Access B's workspace | **No** — OS-random paths, validated before any deletion (§7) |
| Cause B's resources to be orphan-cleaned | **Fixed** in this phase for the cross-host case (§5); same-host orphan-marking already required a real label match (P7-C, unchanged) |

## 7. Workspace / filesystem isolation

Re-derived, not assumed. `_prepare_workspace` (`orchestrate/runtime/
prime.py`) creates every workspace via `tempfile.mkdtemp(prefix=f"ados-
mission-{mission_id[:8]}-")` — `mkdtemp` is the OS's own
collision-resistant, securely-created directory primitive (an additional
random suffix beyond the 8-char mission-id prefix), never a
caller-suppliable name. `spec.workspace_files` (the one place a path
`name` could theoretically enable traversal via `ws / name`) is `{}` at
every real call site in this codebase today — confirmed by grep across
every constructor of `AgentSessionSpec` — so this is dead capacity, not a
live vulnerability; worth flagging for whoever eventually populates it,
not a defect to fix now. Cleanup (`orphan_sweep.py::_process_workspace`)
independently re-validates any candidate path resolves under the real
system temp root with the `ados-mission-` prefix before ever calling
`shutil.rmtree` — proven load-bearing by negative control (§10). **No
fix needed; confirmed already correct.**

## 8. Admission control / rate-limit semantics

Determined the *intended* semantics before testing anything, per the
task's own instruction not to reflexively tenant-scope every limit:

- **`admission_leases`** (capability-execution and mission-concurrency
  ceilings, P12): **intentionally global** — an infrastructure-wide bound
  on real Docker containers and real connector calls, the scarcest
  physical resources in the system. `db/models/admission_lease.py`'s own
  docstring states this in as many words. Tenant-scoping this would be
  the wrong semantics even if a tenant concept existed: one organization's
  own physical host still has one Docker daemon.
- **Mission-start rate limit** (`integrations/rate_limiter.py`,
  P12): **intentionally global**, for the same reason — bounding a
  hot-loop's total call rate against a shared paid LLM budget and a
  shared Docker daemon.
- Neither was changed. Both remain correctly global for Model A/B's
  single-organization scope, and Phase 7's own instruction ("do not
  automatically make every limit tenant-scoped... prove the chosen
  semantics") is satisfied by documenting this deliberately rather than
  by adding a per-tenant variant nothing yet needs. **If/when a real
  tenant model is designed, these two mechanisms would need a
  tenant-scoped layer added *alongside*, not instead of, the existing
  global ceiling** — noted as a forward pointer, not built here.

## 9. Observability / metrics

Every metric in `backend/app/metrics.py` re-read label-by-label (11
Counters/Histograms, 6 Gauges). Every label is a fixed, closed enum —
capability name, outcome/result/reason/gate string. **No `owner_host`,
`session_id`, `mission_id`, `request_id`, `username`, or any other
unbounded value was added as a metric label by this phase** — the new
`owner_host` mechanism is deliberately DB-only (§5), never a metric
label, exactly matching the task's own explicit anti-pattern warning. No
new observability gap was found for anything in scope this phase; P15's
own `already_decided` addition already covers the one relevant signal
this surface needed.

## 10. Negative controls

| # | Guard removed | Expected failure | Result | Restored (SHA-256) |
|---|---|---|---|---|
| 1 | `claim_batch`'s `node_id` filter (`orphan_sweep.py`) | Cross-host claim/false-`absent` becomes possible | **Confirmed** — 3 tests failed for exactly this reason, including the targeted "never marked absent by the wrong sweeper" test (`claimed=0` became `claimed=4`, the session incorrectly marked `absent`) | `027c01bf...` — byte-identical |
| 2 | `_workspace_path_ok`'s root/prefix check (`orphan_sweep.py`) | A workspace directory outside the ADOS temp root is deleted instead of refused | **Confirmed** — `test_process_workspace_refuses_and_does_not_delete_a_path_outside_the_ados_root` failed: outcome flipped from `refused` to `cleaned`, and the out-of-root directory (with its marker file) was genuinely removed | `027c01bf...` — byte-identical (same file as #1, restored together, verified after both) |
| 3 | The auditor read-only check in `authorize_governance_decision` (`backend/app/rbac.py`) | An auditor can now decide a governed request | **Confirmed** — isolated at policy_tier=0 (avoiding the separate tier-2 role check from confounding the result): no exception raised, where 403 was raised before; the full HTTP-level test (`test_an_auditor_cannot_decide`) failed too | `55fc218d...` — byte-identical |

**Guards from the task's own list that do not exist, and so have no
control to run:** tenant ownership checks on reads/writes, an approval
ownership check, an execution ownership check, a reconciliation ownership
check, and tenant-scoped admission/rate-limit isolation. Each was
confirmed absent by source review (§4, §6) and by the live proof (§6) —
fabricating a "negative control" for a mechanism that was never built
would be evidence theater, not evidence. Cross-tenant idempotency
protection *does* exist (§4) but as a schema-level partial unique index,
not a runtime toggle — its correctness under real concurrent collision
attempts was already proven live in P9/P15 (a fresh, redundant control
here would duplicate existing evidence, not add to it) and re-confirmed
by source review this phase, not re-demonstrated.

## 11. Tests

**Focused (P16):** `backend/tests/test_orphan_sweep_multihost.py` — 7/7
passed. `backend/tests/test_orphan_sweep.py` — 22/22 passed (unchanged,
confirming no regression from the `claim_batch`/`sweep_once` signature
additions). `scripts/p16_tenant_boundary_proof.py` — ran clean, all
checks PASS, cleanup independently verified (not a pytest-collected file,
same convention as every prior phase's live-proof scripts).

**Full suite** (run alone, after the schema migration was applied to both
`ados` and `ados_test`): **900 passed / 0 failed / 19 deselected** —
exactly the P15 baseline (893) plus this phase's 7 new tests.

**Docker-marked suite** (run alone, sequentially — not concurrently with
the full suite, per the environmental lesson P15 already documented about
spurious contention failures from parallel pytest processes against the
same live database): **17 passed / 0 failed / 902 deselected** — exactly
the P15 baseline (895) plus the same 7 new (non-docker-marked) tests.
Both runs report the same total collection (919), confirming no
test-discovery drift between them.

**Cleanliness, independently re-verified after both runs:** `docker ps -a`
shows only the five persistent compose-stack containers (`ados-backend-1`,
`ados-postgres-1`, `ados-kafka-1`, plus two long-exited, pre-existing,
unrelated containers); `docker network ls` shows only `ados_default` and
Docker's own built-ins — no leaked `ados-rt-*`/`ados-relay-*`/
`ados-prime-*` resources. A fresh Postgres query for any row referencing
this phase's markers (`ILIKE '%p16%'`, and `owner_host IN ('host-a',
'host-b')`) returned zero rows in every table checked.

## 12. Remaining limitations, honestly

- **No tenant model exists.** This phase deliberately did not build one.
  A real multi-tenant ADOS would need, at minimum: a `tenant_id` (or
  equivalent) column on missions/sessions/capability-requests, ownership
  filters on every list/get/decide endpoint, and a decision about whether
  admission/rate-limit ceilings should gain a tenant-scoped layer
  alongside the existing global one (§8). None of this was evidenced as
  safe to build in the smallest-correct-fix style this phase used for the
  Docker-ownership gap — it is a genuine architecture decision (which
  resources are per-tenant vs. genuinely shared, how a tenant is
  authenticated, whether existing single-org assumptions elsewhere in the
  codebase would need to change) that belongs to a scoped future phase,
  not a patch.
- **The `owner_host` fix is TESTED, not DEMONSTRATED against two real
  Docker hosts.** No second real host with its own Docker daemon was
  available in this environment. What was proven: the DB-level claim
  logic (real Postgres, real concurrent races) is correct. What remains
  unproven: that a real `docker inspect` against host A's daemon for a
  container that only exists on host B actually returns the same
  "not found" shape the monkeypatched seam assumes — this is standard,
  well-documented Docker CLI behavior, not exotic, but it was not
  independently re-verified against two live daemons here.
- **A permanently-dead host's sessions are never reclaimed by another
  host.** `owner_host` prevents *misattribution*; it does not add
  liveness detection or failover. An operator managing a real multi-host
  fleet would still need `--all-hosts` (or a deliberate consolidation
  process) to clean up after a host that is never coming back. Named
  explicitly rather than solved, per Phase 11's own restraint
  instruction.
- **Multi-tenancy, Kubernetes, multi-host container orchestration,
  service mesh, and database row-level security remain entirely
  unbuilt.** Unchanged from every prior phase's own statement.

## 13. Model A / B / C readiness impact

- **Model A: unaffected, READY.** No change to any single-process,
  single-host code path's behavior (`node_id=None` preserves exact
  pre-P16 semantics everywhere).
- **Model B: unaffected, READY.** Same reasoning — P12–P15's
  multi-process, single-host guarantees are untouched.
- **Model C: still NOT READY**, but more precisely characterized than
  before. Multi-tenancy remains **NOT BUILT** (confirmed, not assumed —
  the live proof in §6 is the concrete evidence). Multi-host Docker
  ownership was a **real, open defect**, now **fixed and TESTED** at the
  database/decision layer, with the two-real-hosts gap named explicitly
  in §12 as what would upgrade it to DEMONSTRATED.

## 14. Exact remaining blockers

For Model C, unchanged in kind from every prior phase, now evidenced
rather than assumed:

1. **No tenant identity or ownership model** — the dominant blocker.
   Requires a deliberate design phase, not a patch.
2. **Multi-host Docker ownership beyond the misattribution fix** —
   liveness/failover for a permanently-dead host, and independent
   verification against two real Docker daemons.
3. Everything already named as out of scope by this phase's own
   instructions and never attempted: Kubernetes, service mesh, database
   row-level security, a tenant management UI, multi-region.

No other blocker was found. `custom_agents.division` (referenced in prior
memory as an unrelated, pre-existing item) was not touched — confirmed
not caused by, or related to, anything in this phase's scope.

STOP after P16. P17 was not started.
