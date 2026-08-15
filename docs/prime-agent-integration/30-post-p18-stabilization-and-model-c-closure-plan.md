# 30. Post-P18 Stabilization & Model-C Closure Plan (2026-08-15)

Audit-and-plan task. No production code was changed. No commit was made.
Baseline: `HEAD = 7464902` (branch `prime-agent-runtime`, ahead 9 of
`origin/prime-agent-runtime`), P11-P18 work present as uncommitted
working-tree state, unchanged by this task.

## 1. Repository state verification

```
git status --short --branch  -> ## prime-agent-runtime...origin/prime-agent-runtime [ahead 9]
```

121 dirty entries (55 modified + 66 untracked), all consistent with the
already-known P11-P18 body of work (tenancy, admission/rate-limiting,
metrics, multi-host ownership, capability registry consistency, proof
scripts, docs). Nothing was reset, stashed, or discarded. `git diff --cached
--name-status` is empty — nothing staged, nothing at risk of an accidental
commit.

Two pre-existing, out-of-scope dirty items were specifically checked and
confirmed untouched by any P11-P18 or this-task activity:

- `db/models/custom_agent.py` (+4 lines) and
  `alembic/versions/c3d4e5f6a7b8_add_division_vibe_to_custom_agents.py`
  — the `custom_agents.division` work. **PROTECTED, confirmed untouched.**
- `Hackathon/n8n` — separate git repo, `git status --short` returns zero
  lines, in sync with `origin/master`. **SEPARATE REPOSITORY, confirmed
  untouched.**

## 2. P18 diff re-review

Re-read directly from `git diff`, not from memory of the prior session.

- `backend/app/routers/capabilities.py`: adds one `Depends(get_tenant_context)`
  parameter to `invoke_capability`, with an inline comment explaining why
  P16/P17 missed this path. Reuses the same dependency
  `runtime_approvals.py` already uses. No new mechanism, no duplication.
- `integrations/connectors/prime_runtime.py`: reads `current_tenant.get()`
  (the existing `db/tenancy.py` ContextVar) instead of hardcoding
  `DEFAULT_TENANT_ID`, falling back to the default when no context is set.
  No new plumbing through `CapabilityCall`.

Both changes are minimal, additive, reuse existing infrastructure, and are
the smallest fix that closes the actual gap (a real, reachable
mission-creation path that silently mis-attributed tenancy). Nothing here
warrants a style rewrite. Confirmed not required elsewhere by the same audit.

## 3. Repository consolidation audit

22 git repositories exist under `Hackathon/`. All but `ADOS` itself point at
`origin` remotes on **other** GitHub organizations/authors (e.g.
`n8n-io/n8n`, `PrimeIntellect-ai/prime-agent`, `mishrasanjeev/agentic-org`,
`msitarzewski/agency-agents`, `PrefectHQ/fastmcp`, etc.) — third-party
reference clones, not ADOS forks. A repo-relative grep for cross-repo path
references from ADOS source found exactly one hit, a documentary comment in
`orchestrate/runtime/prime_image.py` noting that the Docker runtime image
was built with `../prime-agent` (the upstream runtime source) as a
reference — no code coupling.

| Path | Relationship to ADOS | Classification |
|---|---|---|
| `ADOS` | itself | — |
| `prime-agent` (PrimeIntellect-ai) | upstream reference for the Prime Agent Docker runtime image; already fully vendored/adapted into ADOS's own runtime code in prior phases | SEPARATE REPOSITORY |
| `agentic-org` | already surveyed in a prior session (`agentic_org_reuse_survey` memory) — confirmed nothing left to merge | SEPARATE REPOSITORY |
| `ADOS/agency-agents-repo` (nested repo, untracked in ADOS's own `.git`) | third-party agent-persona prompt library (`msitarzewski/agency-agents`), consumed read-only by `scripts/sync_agency_agents.py` / `scripts/verify_agents_sync.py` — a pre-existing, unrelated feature, not part of P11-P18 | SEPARATE REPOSITORY (vendored dependency) |
| `n8n` | explicitly out of scope this entire programme; confirmed clean and untouched | PROTECTED / SEPARATE REPOSITORY |
| `MCP-Server-Creator`, `smart-factory-microservices`, `impeccable`, `crm`, `fastmcp`, `gstack`, `OpenLCM`, `speech-to-speech`, `ruflo`, `repomix`, `openapi-mcp-generator`, `openapi-mcp-generator-1`, `jarvis`, `skills`, `taste-skill`, `Agent-Reach`, `Digital-Twin-RL-AI` | unrelated third-party tools/frameworks cloned for reference/experimentation elsewhere in the workspace; no path or import coupling to ADOS found | UNRELATED / SEPARATE REPOSITORY |
| `Videos/ados-video` | a Remotion video project (no remote), likely product-demo video tooling; not source code, no relation to backend/tenancy work | UNRELATED |
| `ados-prime-agent-integration-plan-v2` | not a git repository (no `.git`); a planning/docs directory | REVIEW — not a code repo, out of scope for a code-consolidation audit; left untouched |
| `custom_agents.division` (files, not a repo) | in-progress unrelated work inside ADOS's own working tree | PROTECTED |

**No merge candidates were found.** Every sibling repository is either a
genuinely separate product (own remote, own history, own purpose) or a
reference clone that has already been surveyed and fully accounted for in
prior sessions. This matches the task's own prior expectation for `n8n` and
`custom_agents.division`, and extends the same conclusion to the rest of the
workspace on actual evidence (remote URLs, path-coupling grep) rather than
by assumption.

## 4-5. Cleanup / consolidation plan and execution

**Nothing to remove, nothing to merge.** No destructive or consolidating
action was taken, because none was justified by the audit. This is itself
the correct Phase 4/5 output per the task's own instruction ("Do not delete
or merge anything merely because it looks redundant").

Post-audit `git status --short --branch` / `git diff --stat` /
`git diff --name-status` are identical to Phase 1's baseline — verified
byte-for-byte unchanged (see §1; no edits were made in Phases 3-5).

## 6. Model-C blocker design analysis

No implementation was done in this phase, per the explicit stop condition.

### A. Permanent dead-host recovery

Traced the actual current ownership/reclamation code, not assumptions:

- **`orchestrate/runtime/session_reconcile.py`** — reconciles any session
  stuck non-terminal past its own token's expiry (`token_expires_at <
  now()`) to `state="failed"`. This is **already host-agnostic** — it is
  driven purely by a per-session, bounded time budget
  (`max_wall_clock_seconds + TOKEN_GRACE_SECONDS`), not by which host owned
  the session. A session whose owning host died permanently is correctly
  reconciled by whichever host's periodic task runs this next. **This
  already correctly handles the "session stuck forever" failure mode for a
  dead host — not a gap.**
- **`orchestrate/runtime/admission_lease_reclaim.py`** — reclaims
  `admission_leases` rows older than `admission_lease_max_age_seconds`
  (default 1800s) and prunes old `rate_limit_events`. Also host-agnostic,
  also already correct for a dead host.
- **`orchestrate/runtime/orphan_sweep.py`** — cleans up the *Docker
  containers/networks/workspace directories* a terminal, orphan-marked
  session left behind. This one is **deliberately node_id-scoped**
  (`claim_batch`'s `node_id` filter, confirmed unregressed at
  `orphan_sweep.py`): a sweeper only claims rows whose `owner_host` is NULL
  or its own host, because it can only verify a resource's real state
  against its own local Docker daemon — claiming a different host's row
  would risk recording a still-running container as `absent` (a permanent,
  wrong, terminal status). This is the *correct* design for the case a host
  is temporarily unreachable and will come back.
- **Confirmed at `backend/app/main.py:133`**: the periodic background task
  calls `sweep_once(async_session_factory, node_id=node_id)` — every host's
  own periodic sweep is permanently scoped to its own `owner_host`. There is
  no code path, automatic or manual, by which a *surviving* host ever claims
  a *permanently* dead host's orphaned Docker/workspace resources.
- **Confirmed via grep**: `docs/prime-agent-integration/20-operator-runbook.md`
  contains zero mentions of `node_id`, `owner_host`, or a dead-host
  procedure. There is no documented manual runbook step either.

**The precise, narrow gap**: session-level and admission-lease-level
abandonment recovery are already correct and host-agnostic. The one
genuinely missing piece is Docker/workspace resource reclamation for a host
that is gone *permanently* (not merely partitioned) — today that cleanup
duty is permanently stuck with a host that will never run it again, with no
automatic escalation and no documented manual escape hatch.

**Minimal design to close this (not implemented here)**:

1. A **host heartbeat** table/row (`host_id`, `last_seen_at`), updated by
   each host's existing periodic task loop (the same loop `main.py:107-164`
   already runs every cycle — one more `UPDATE` in it, no new scheduler).
2. A **host-declared-dead threshold** — an operator- or time-bound
   decision, e.g. `last_seen_at` older than N missed cycles. This must be an
   explicit, conservative threshold (favoring false negatives — treating a
   partitioned-but-alive host as still alive — over false positives), because
   claiming a live host's resources from elsewhere is the exact
   double-teardown/false-`absent` hazard `orphan_sweep.py`'s own docstring
   already warns about.
3. Once a host is declared dead, **widen exactly one sweep pass's `node_id`
   filter** to include that dead host's `owner_host` value (not `node_id=None`
   / claim-everything — scope the widening to the specific declared-dead
   host only), so a surviving host's sweeper can then attempt the Docker
   inspect/remove calls itself. Since the dead host's Docker daemon is gone
   with it in the overwhelming majority of real failure modes (VM
   termination, hard host crash), `_docker_label` will almost always return
   `None` ("already gone") — the design must not assume this is guaranteed
   (a network-partitioned-but-alive host is the one case where it is not),
   which is exactly why the declared-dead threshold in step 2 must be
   conservative and probably operator-confirmed rather than fully automatic
   at first.
4. **Fencing**: already effectively provided by the existing token-expiry
   mechanism — `mcp_gateway._resolve_session` already refuses an expired
   token regardless of which host presents it, so a zombie process on a
   "dead" host that wakes up cannot make new capability calls through the
   gateway after its session's token has expired. This does **not** and must
   not be described as solving exactly-once external execution — a call
   already in flight before the token expired can still land; that limitation
   is pre-existing and already documented, not new.

**Required tests before this could be declared READY** (not run, per the
explicit no-implementation stop condition):
- Unit: heartbeat write/read, dead-threshold calculation, widened-filter
  claim query.
- Live multi-process: simulate one "host" process that stops heartbeating
  mid-session while holding an owned, non-terminal session + Docker
  container; confirm a second host process does *not* claim it before the
  threshold, and *does* claim and correctly clean it up after.
- Negative control: a host that pauses briefly (shorter than the threshold)
  and resumes must never have its resources claimed by another host — this
  is the single most safety-critical property of the whole mechanism and
  needs its own explicit adversarial test, not just a happy-path one.
- Idempotency: two hosts racing to declare the same third host dead and
  both attempting the widened claim must not double-process (this already
  falls out of `claim_batch`'s existing `SELECT ... FOR UPDATE SKIP LOCKED`,
  but must be proven for the widened-filter case specifically, not assumed).

Classification: **NOT BUILT.** Design is now precise; implementation was
explicitly out of scope for this task.

### B. Two-real-host verification

`docker context ls` (re-checked, consistent with P16/P18 findings) shows
only `default` / `desktop-linux` — a single Docker host is available in this
environment. **No second real host or VM exists to test against.**

Classification: **NOT DEMONSTRATED.** Not simulated, not claimed as proven.

**Exact procedure required when a second real host is available** (for a
future session, not this one):
1. Provision ADOS backend + Postgres reachable from both hosts (shared DB,
   as production already requires).
2. Set distinct `ADOS_NODE_ID` on each host.
3. Start a mission whose `RuntimeSessionRow.owner_host` is stamped by host A
   (`effective_node_id`).
4. Kill host A's ADOS process (not just the container) — a real process
   kill, not a simulated one.
5. Confirm host B's periodic `sweep_once(node_id=B)` does **not** claim host
   A's orphan-marked resources (today's correct, intentional behavior).
6. Confirm `session_reconcile.py` on host B *does* still reconcile the
   session once its token expires (host-agnostic, should already pass).
7. If/when the §6.A design is implemented: confirm host B can, after the
   declared-dead threshold, successfully widen its claim and finish the
   Docker cleanup that host A never could.

### C. Per-tenant capacity

Re-confirmed by direct grep of `integrations/admission_control.py`,
`integrations/rate_limiter.py`, `db/models/admission_lease.py`, and
`db/models/rate_limit_event.py`: **zero references to `tenant` anywhere in
the capacity/admission/rate-limit layer.** This is unregressed and
deliberate — these are physical/shared-resource limits (Docker daemon
capacity, paid LLM budget, a shared human-reviewer pool), correctly global
regardless of tenant count, exactly as P17/P18 reasoned.

There is currently exactly **one** real tenant in this deployment. Designing
tenant quotas against a single tenant is designing against an assumption,
not a requirement — this is exactly the kind of speculative work the task
explicitly prohibits ("do not invent quotas without a real requirement").

Classification: **PRODUCT DECISION REQUIRED.**

- If the product requirement turns out to be **GLOBAL ONLY** (one tenant, or
  multiple tenants that are expected to trust each other's resource
  consumption / are billed as one unit): no further work is needed here at
  all: the current architecture is already correct and complete for that
  case.
- If the product requirement turns out to be **TENANT QUOTAS + GLOBAL
  CEILING**: the minimal safe addition is a `tenant_id` column on
  `admission_leases` (already tenant-aware missions/sessions exist to derive
  it from) plus a *second*, per-tenant counter check inside
  `admission_control.py`'s existing acquire path, evaluated **in addition
  to**, never instead of, the current global check — so a per-tenant quota
  can only ever tighten admission, never let aggregate usage exceed the
  existing global physical ceiling. This is a bounded, additive change if
  and when it is actually needed; it is not designed further here because no
  real second-tenant capacity requirement exists yet to design against.

### D. PostgreSQL RLS

Re-verified against the current `approve_capability_request` source
(`backend/app/routers/runtime_approvals.py:280`) — unregressed since the
P18 analysis: the function's 3-phase structure (Phase 1 commits
`executing`; Phase 2 makes the external call with no open transaction; Phase
3's `session.refresh(row)` triggers SQLAlchemy's session autobegin, opening
a **new**, second transaction after Phase 1's commit ended the first one)
means a single `SET LOCAL app.tenant_id` issued once at session-open would
silently stop applying by Phase 3 — `SET LOCAL` only lasts for the
transaction it was set in.

None of the six specific safety properties the task asks RLS to demonstrate
before implementation can currently be shown:
- normal requests work: not evaluated, no RLS exists to test
- tenant context cannot be bypassed: blocked on the multi-transaction issue
  above — a naive implementation *can* be bypassed, silently, by Phase 3
- background jobs can intentionally use all-tenants access: `db/tenancy.py`'s
  `use_all_tenants()`/`all_tenants_session()` already provide this at the
  ORM layer; an RLS policy would need its own parallel "all tenants" GUC
  value/role, not yet designed
- multi-phase transactions retain correct tenant context: **demonstrated
  false** for the naive approach, by the trace above
- connection pooling cannot leak tenant state: `NullPool` (db/engine.py)
  already eliminates cross-request connection reuse, which removes the
  classic pooled-GUC-leak risk, but does not by itself solve the
  multi-transaction problem above
- privileged operational paths are explicit: not yet designed

**Prerequisite architecture** (unchanged conclusion from P18, restated with
the exact function/line evidence): before RLS can be safely added, either
(a) `approve_capability_request` needs to re-assert the GUC at the start of
every transaction it opens (Phase 1 and Phase 3 both), not just once at
session-open — which means finding and fixing every other multi-transaction
handler in the codebase the same way, not just this one instance; or (b) a
session-level mechanism that survives `SQLAlchemy` autobegin is used instead
of a transaction-scoped `SET LOCAL`. Neither has been designed in detail —
that is exactly the "larger redesign" this task says to defer rather than
patch around.

Classification: **KEEP RLS DEFERRED.** No fake or partial RLS was added.

## 7. Model-C acceptance matrix

| Requirement | Current Status | Evidence | Remaining Work | READY? |
|---|---|---|---|---|
| Tenant isolation (query-level) | DEMONSTRATED | `db/tenancy.py` `do_orm_execute` + `with_loader_criteria`, P17 `test_tenant_isolation.py`, P18 multi-process/concurrent proof | none | Yes |
| Mission-creation tenant attribution | DEMONSTRATED | P18 fix + `test_mission_creation_tenant_attribution.py` (4/4 passing, real HTTP path) | none | Yes |
| Cross-process safety | DEMONSTRATED | `scripts/p18_multiprocess_tenant_isolation_proof.py`, 3/3 cases PASS, real OS processes | none | Yes |
| Background-job isolation / adversarial override | DEMONSTRATED | same script, Case 3 (ambient tenant A context, `use_all_tenants()` still sees tenant B's row) | none | Yes |
| No tenant-context leakage across concurrent requests | DEMONSTRATED | same script, Case 2 (30-way `asyncio.gather`, alternating tenants) | none | Yes |
| MOA/incident/executive/learning tenancy boundary | CONFIRMED | exhaustive full-repo grep, P18 §8 | none | Yes (by design: out of tenant scope) |
| Multi-host ownership (single host) | DEMONSTRATED | P16/P18, `owner_host`/`node_id` filter, unregressed | none | Yes |
| Multi-host ownership (two real hosts) | NOT DEMONSTRATED | no second real host/VM available | provision 2 real hosts, run §6.B procedure | No |
| Permanent dead-host recovery | NOT BUILT | traced `session_reconcile.py` (host-agnostic, OK), `orphan_sweep.py` (node_id-scoped, correctly so, but no escalation path), `main.py:133` | §6.A design: heartbeat, declared-dead threshold, scoped widened claim, adversarial+idempotency tests | No |
| Global capacity / admission control | DEMONSTRATED | P12/P15/P18, unregressed, correctly global | none | Yes |
| Tenant-specific capacity | PRODUCT DECISION REQUIRED | zero tenant coupling in capacity layer, by design, one real tenant exists today | a real second-tenant capacity requirement, if/when one exists | N/A until decided |
| Rate limiting | DEMONSTRATED | `rate_limiter.py`, global, unregressed | none (pending same product decision as capacity) | Yes (global) |
| Approval safety (single transaction) | DEMONSTRATED | `runtime_approvals.py` `FOR UPDATE SKIP LOCKED`, P15 | none | Yes |
| Approval/execution race safety | DEMONSTRATED | P15 concurrency proofs, unregressed | none | Yes |
| Execution safety / idempotency | DESIGNED, partially DEMONSTRATED | token-expiry fencing (§6.A); no exactly-once claim, correctly not made | none beyond documenting the limitation (already documented) | Yes, as scoped |
| Reconciliation (`outcome_unknown`) | DEMONSTRATED | `capability_reconcile.py::mark_stalled_executions_unknown`, P18 multi-process Case 3 | none | Yes |
| Docker ownership / cleanup (single host) | DEMONSTRATED | `orphan_sweep.py`, P12/P16/P18 | none | Yes |
| Docker ownership / cleanup (dead host) | NOT BUILT | see permanent dead-host recovery row | same as above | No |
| Observability | TESTED | Prometheus metrics, P18 §11, no tenant labels (consistent with global-only capacity design) | tenant labels only if §6.C resolves to TENANT QUOTAS | Yes, as scoped |
| Build identity | DEMONSTRATED | unregressed since P13/P14 | none | Yes |
| Database security (connection/role) | DEMONSTRATED | `test_database_role_privileges.py`, unregressed | none | Yes |
| Database security (RLS / defense in depth) | DEFERRED | §6.D | prerequisite transaction-architecture fix, then RLS design | No |

## 8. Future test plan for Model C closure (not executed here)

Preserving P18's exact counts unchanged — **911 passed, 0 failed, 19
deselected**; Docker: **17/17**. No new test campaign was run in this task
beyond the read-only verification already covered by that regression.

Test groups required before Model C can move past NOT READY (grouped by
§6/§7 blocker, to be executed only once each corresponding design is
actually implemented):

1. **Focused Model-C tests** — a dedicated `test_model_c_*` module exercising
   every row in §7 marked "No", once implemented.
2. **Dead-host/reclamation tests** — heartbeat write/read, declared-dead
   threshold, widened-claim scoping, adversarial (brief-pause-then-resume
   must NOT be claimed), idempotency under two simultaneous claimers.
3. **Multi-process concurrency** — extend the existing
   `p18_multiprocess_tenant_isolation_proof.py` pattern to include the new
   dead-host scenario as a 4th case, rather than writing an unrelated new
   harness.
4. **Two-real-host tests** — the exact 7-step procedure in §6.B, only
   runnable once a second real host/VM exists.
5. **Tenant isolation** — re-run existing `test_tenant_isolation.py` +
   `test_mission_creation_tenant_attribution.py` unchanged as a regression
   gate on every future change to this area.
6. **Capacity/admission** — re-run `test_admission_control_global.py` /
   `test_hub_global_admission.py` unchanged; add tenant-scoped variants only
   if/when §6.C resolves to TENANT QUOTAS.
7. **Approval/execution races** — re-run existing P15 concurrency suite
   unchanged as a regression gate.
8. **Reconciliation** — re-run `test_capability_completion_race.py` /
   `test_incident_approval_multiworker.py` unchanged.
9. **Database security** — re-run `test_database_role_privileges.py`
   unchanged; add RLS-specific tests only once the §6.D prerequisite
   transaction-architecture fix is designed and implemented.
10. **Docker tests** — re-run the existing 17 Docker-marked tests unchanged,
    plus new dead-host-scenario Docker tests once §6.A exists.
11. **Full suite, sequentially** — the standard `pytest -m "not docker and
    not external"` gate, expected to grow from 911 only by however many
    tests each future implementation phase adds; no count is fabricated
    here for work not yet done.

## 9. Summary

No production code changed. No commit made. No merge/removal executed
(none was justified). Model A and Model B: unaffected, still READY. Model
C: still NOT READY, with every remaining gap now traced to specific source
locations (`orphan_sweep.py`, `main.py:133`, `runtime_approvals.py:280`,
the capacity layer's grep-confirmed absence of tenant coupling) rather than
general statements, and a minimal, non-speculative design sketched for each
without being implemented. The next engineering action is to be chosen
manually from §6/§7's precise blocker list.
