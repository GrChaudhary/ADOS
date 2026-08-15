# 31 — Model-C Decision Gate

Status: decision record only. No production code, tests, migrations, or configuration
changed in this task. HEAD unchanged at `7464902`.

This document exists to answer one question about each of the four remaining Model-C
blockers: **is it engineering work, a product decision, an architecture decision, or a
legitimate permanent deferral** — before any further implementation is authorized.

---

## Phase 1 — State verification

```
HEAD                 7464902fb07efdef590493e92f0dec27be8b88d6  (unchanged)
Branch                prime-agent-runtime ... [ahead 9 of origin/prime-agent-runtime]
Staged changes        0
Working tree          122 entries, all traced to known P11-P18 work + this task's own
                       two doc files (30-..., README.md) from the prior stabilization pass
Protected paths        db/models/custom_agent.py — unchanged since prior review (+4 lines,
                       pre-existing, not touched)
n8n                    0 dirty files, HEAD 7b64b947..., untouched
```

No modification made in this phase.

---

## Phase 2 — Dead-host recovery decision

**Re-verified directly from source (`backend/app/main.py:107-164`,
`orchestrate/runtime/orphan_sweep.py:241-282`):**

- `main.py`'s periodic task calls `sweep_once(async_session_factory, node_id=node_id)`
  with `node_id = effective_node_id(settings.node_id)` — i.e. every host always passes
  *its own* identity.
- `orphan_sweep.claim_batch` (line 280-282): when `node_id` is given, it restricts the
  claim to rows where `owner_host IS NULL OR owner_host == node_id`. This is deliberate
  (documented in the code): a host must not touch another host's Docker/workspace
  resources, because it can only verify container/workspace state against its *own*
  local Docker daemon — claiming a different host's row on unverifiable state risks
  marking a still-running resource `absent`, which is a terminal, never-reclaimed status.

**Answers:**

1. **Worker process dies (same host, host survives):** Already handled. The host's own
   sweep sees `owner_host == node_id`, verifies against the local Docker daemon, and
   reclaims/marks-absent correctly. Not a gap.
2. **Host disappears permanently:** No other host will ever claim its rows —
   `owner_host` never matches, is never NULL. Confirmed gap.
3. **Its Docker containers/workspaces:** Remain recorded as owned by the dead host
   forever. If the host is physically gone, the containers are gone too, but nothing in
   ADOS ever records that — the rows sit in a non-terminal state indefinitely.
4. **Can another host safely reclaim them today?** No — and, correctly, it also
   *shouldn't* under the current claim logic, because no host can verify a dead host's
   Docker state. Widening the claim without a heartbeat/declared-dead signal would let a
   *temporarily* partitioned host's still-running containers be falsely marked absent.
5. **Could reclamation cause duplicate execution?** Only if reclamation is interpreted as
   "re-run the work." It should never be — reclamation here means "close out the
   bookkeeping row," not "re-invoke the external call." Session/lease-level recovery
   (`session_reconcile.py`, `admission_lease_reclaim.py`) already treats this correctly:
   both mark rows `failed`/reclaimed by elapsed time, never re-execute. The design below
   preserves that: it is strictly a cleanup/reclassification path, not a retry path.
6. **Can existing token expiry/fencing prevent unsafe reuse?** Yes, partially and
   already: `mcp_gateway._resolve_session` refuses any session whose token has expired,
   regardless of which host presents it. This fences new capability calls from a zombie
   process on a "dead" host. It does **not** solve exactly-once for a call already
   in-flight before expiry — that limitation is pre-existing, documented, and out of
   scope here (no design claims to close it).
7. **Smallest safe design for permanent dead-host cleanup:**
   - A `host_heartbeat` table (or reuse an existing periodic-task table) where every live
     host upserts `(node_id, last_seen_at)` on each sweep cycle.
   - A conservative "declared dead" threshold (e.g. no heartbeat for N × sweep interval,
     N large enough to rule out ordinary restarts/deploys/network blips — an operational
     constant, not a guess baked into this doc).
   - `claim_batch`'s widened path activates *only* for rows whose `owner_host` matches a
     node_id that is declared dead by the heartbeat table (not "any non-local owner") —
     this is the one and only change to the claim predicate.
   - Reclaimed rows are marked with an explicit `outcome_unknown`-style terminal state
     (never silently `absent`, since the reclaiming host still cannot verify the dead
     host's actual Docker state) — consistent with the existing pattern used elsewhere
     in the runtime for uncertain outcomes.
   - Existing token-expiry fencing is unchanged and still the mechanism that prevents a
     revived "dead" host from completing stale in-flight work against current state.

**Required failure tests before this can be called READY** (not run, not written):
worker SIGKILL (existing coverage, confirmed no gap); host disappears permanently across
a full declared-dead cycle; heartbeat stops but DB stays reachable; network partition
that self-heals *before* the declared-dead threshold (must NOT be reclaimed); a
"declared dead" host that reconnects *after* reclamation (must not double-act); two
surviving hosts racing to reclaim the same dead host's rows (must be safely
idempotent/exclusive); a reclaimed row where the external action may already have
happened (must land in `outcome_unknown`, never a false `absent` or false `success`).

**Does this block Model C?** **Yes — genuinely, not speculatively.** This is the one
blocker in this set that is a real, demonstrated gap in the runtime's own current logic
(not a hypothetical), with a concrete failure mode (a permanently dead host's resources
are invisible forever) and a bounded, minimal design. Classification: **Engineering —
must build**, but small and well-scoped, not a redesign.

---

## Phase 3 — Two-host decision

```
$ docker context ls
default          ...  unix:///var/run/docker.sock
desktop-linux *  ...  unix:///Users/gauravchaudhary/.docker/run/docker.sock
```

Only one real Docker daemon is reachable in this environment. Both contexts point at
the same local machine.

**Conclusion: NOT DEMONSTRATED DUE TO ENVIRONMENT LIMITATION.** Not simulated, not
claimed as proven. P11-P18's "multi-host" evidence is real for what it tests — separate
OS processes with independent ContextVars, ownership fields correctly stamped and
correctly scoped in code — but it is not two independent hosts talking to a shared
Postgres over a real network.

**Acceptance test required when two hosts/VMs become available** (defined now, not
executed):

1. Both hosts point at the same shared Postgres instance (not local sqlite/containers).
2. Start a capability session owned by host A (`owner_host` stamped correctly).
3. Start concurrent capability sessions from host B against the same tenant and a
   different tenant — verify tenant isolation holds across the two real hosts (not just
   across processes on one host).
4. Verify host A's sweep never touches host B's `owner_host` rows and vice versa
   (confirms the node_id-scoping is real under a genuine second host, not just
   process-simulated).
5. Kill host A hard (power off / kill the VM, not just the process) while it holds
   in-flight sessions and admission leases.
6. Confirm host B's session/lease reconciliation (`session_reconcile.py`,
   `admission_lease_reclaim.py`) correctly ages out host A's rows on its own timers —
   this part should already pass today, since it's host-agnostic; the two-host run is
   confirming, not discovering.
7. With the Phase-2 heartbeat design in place, confirm host B correctly declares host A
   dead only after the threshold and reclaims Docker/workspace rows without
   double-acting if host A later comes back online.
8. Confirm approval/execution safety (no duplicate external execution, correct
   `outcome_unknown` handling) holds under this real two-host failure, not just the
   single-host chaos tests already run in P14/P15/P18.

**Is the missing evidence a temporary gap or a production blocker?** **Temporary
evidence gap, not a design blocker.** The code paths being tested (ownership scoping,
tenant ContextVar propagation, token-expiry fencing) do not contain host-count-dependent
logic that only manifests with 2+ hosts — they are written to be host-count-agnostic.
The two-host run is confirmatory verification, not a discovery exercise expected to
surface new bugs in the ownership/tenancy design itself. It should still be run before
a genuine multi-host production claim, but its absence does not indicate unfinished
design. Classification: **Environmental — must demonstrate when infrastructure exists**,
not a code blocker today.

---

## Phase 4 — Tenant capacity product decision

**Re-confirmed via grep:** zero references to `tenant` anywhere in
`integrations/admission_control.py`, `integrations/rate_limiter.py`,
`db/models/admission_lease.py`, `db/models/rate_limit_event.py`. Capacity/admission is
entirely global today.

1. **Global physical ceiling enforced?** Yes — `admission_control.py` /
   `rate_limiter.py` gate total concurrency and request rate regardless of tenant.
2. **Any tenant-specific capacity today?** None.
3. **Is tenant fairness required by an actual product requirement?** Unknown from the
   codebase — there is exactly one real tenant in the current system, so nothing in the
   product today exercises multi-tenant contention.
4. **Could a single tenant consume all global capacity?** Yes, by design, today.
5. **Is that currently acceptable?** With one real tenant, yes — there's no other tenant
   to starve. This becomes a live question only once a second real tenant with
   meaningful concurrent load exists.
6. **What would tenant quotas change?** Would require: a per-tenant counter alongside
   the existing global counter, a decision on quota granularity (concurrency? RPS?
   both?), and a decision on what happens at the boundary (reject vs. queue vs.
   degrade).
7. **Can tenant quotas coexist with a global ceiling safely?** Yes, straightforwardly —
   tenant quotas are a strictly tighter sub-constraint checked in addition to, never
   instead of, the existing global ceiling. This ordering (global ceiling always wins)
   is the only safety-relevant property that needs to be preserved if this is ever
   built; it is not currently at risk because no tenant-layer exists to violate it.

**Model A — Global physical capacity only (current state):**
- Behavior: total system concurrency/rate bounded; no tenant can be blocked by another
  except incidentally via shared global exhaustion.
- Complexity: none — already built.
- Risk: one noisy/malicious tenant can degrade service for all others. Currently
  theoretical (one tenant).
- Operational implications: none beyond today.
- Testing required: none beyond existing coverage.

**Model B — Tenant quotas + global physical ceiling:**
- Behavior: each tenant bounded individually, all tenants additionally bounded in
  aggregate by the existing global ceiling.
- Complexity: moderate — new per-tenant counters/tables, admission-check changes,
  operator-facing quota configuration, a rejection/backpressure UX decision.
- Risk: if implemented incorrectly, could either (a) fail to cap aggregate usage
  (violates the global ceiling — unacceptable) or (b) under-utilize capacity by being
  overly conservative per-tenant.
- Operational implications: requires a real quota-setting process (who sets tenant
  quotas, how, and against what plan/tier) — a product/business input, not a technical
  one.
- Testing required: per-tenant enforcement tests, aggregate-never-exceeds-global tests
  under concurrent multi-tenant load, boundary/backpressure behavior tests.

**Recommendation:** **PRODUCT DECISION REQUIRED.** The engineering shape of Model B is
straightforward and low-risk *if* it's ever needed (Phase 7's answer to "can quotas
coexist with a global ceiling" is yes). But building it now, against a single-tenant
system with no stated fairness requirement, no pricing/tier model, and no rejection-UX
decision, would be speculative — precisely what this task is scoped to avoid. Nothing
is implemented. This is not classified as an engineering blocker for Model C; it's a
product question that has not yet been asked of the business.

---

## Phase 5 — RLS architectural decision

**Re-verified unregressed** (`backend/app/routers/runtime_approvals.py:280-430`):
`approve_capability_request` commits at line 336, 345, 380, 429 and calls
`session.refresh(row)` (which triggers SQLAlchemy session autobegin, opening a new
transaction) at lines 359, 380, 430 — i.e. the function spans **at least three separate
Postgres transactions** on one logical operation, with an external call (no open
transaction at all) in between phases.

1. **Can RLS be safely added without architectural changes?** No. A naive
   `SET LOCAL app.tenant_id = ...` issued once at session/request start only survives
   until that transaction ends — by the second `commit()` it has silently stopped
   applying, and any subsequent query in that same logical operation would either see
   no tenant filter (if RLS policy fails open — unacceptable) or be incorrectly denied
   (if it fails closed — breaks the approval flow). Neither is safe to ship.
2. **If yes, what exact architecture is required?** N/A (answer to 1 is no).
3. **If no, what prerequisite changes are required?** The tenant-context-setting
   mechanism needs to be re-issued (or otherwise guaranteed active) at the start of
   *every* transaction within a logical multi-phase operation, not just the first — e.g.
   an ORM-level hook that re-applies `SET LOCAL` on each new transaction/autobegin
   within a session, or restructuring multi-phase endpoints to hold a single transaction
   for their duration (which conflicts with the deliberate P-phase durable-commit design
   that exists precisely so a partial failure doesn't lose the `executing` state — see
   the comment at `runtime_approvals.py:299-307`). Either path is a real architectural
   change, not a config tweak.
4. **Would those changes be disproportionate?** Given that application-layer tenant
   scoping (`db/tenancy.py`'s `do_orm_execute` + `with_loader_criteria`) is fail-closed
   by default, already covers every ORM query path including this one, and has been
   demonstrated under multi-process and concurrent-asyncio conditions in P18 — yes,
   restructuring the durable multi-phase-commit design (which exists for a real, already
   -solved safety reason) solely to enable RLS as a second enforcement layer would be
   disproportionate to the incremental safety gained.
5. **Is application-layer isolation + Postgres role security sufficient for the
   Model-C threat model?** For the threat model actually in scope — preventing one
   ADOS tenant's application code path from reading/writing another tenant's rows via
   the ORM — yes. The fail-closed `ContextVar` + `do_orm_execute` mechanism is
   demonstrated (multi-process, concurrent, background-job, negative-control tests all
   pass per P18). RLS's incremental value is specifically against a *different* threat:
   a bug or a future raw-SQL/non-ORM code path that bypasses the ORM layer entirely.
   That threat is real in the abstract but not demonstrated as present in this codebase
   today (no raw-SQL tenant-data access paths were found in review).
6. **Hard Model-C requirement or defense-in-depth?** **Defense-in-depth**, not a hard
   requirement, given the threat model above. The application-layer mechanism is the
   actual enforcement boundary today and is demonstrated; RLS would be a second,
   independent layer against ORM-bypass bugs, valuable but not gating.

**Recommendation: DEFER.** Not "architecture change required" as an active work item —
the prerequisite change (re-issuing tenant context across every transaction phase of a
deliberately multi-phase durable-commit design, or restructuring that design) is
disproportionate to the incremental risk it closes, given a working, demonstrated
primary enforcement layer already exists. No partial/superficial RLS should be added.
This should be revisited only if a genuine raw-SQL or ORM-bypass code path is
introduced, at which point the calculus changes.

---

## Phase 6 — Model-C requirement matrix

| Requirement | Evidence | Status | Hard Model-C requirement? | If not, why | Required action | Owner/type |
|---|---|---|---|---|---|---|
| Tenant isolation (ORM layer) | P18 multi-process + concurrent-asyncio + negative-control tests | DEMONSTRATED | Yes | — | None | — |
| Cross-process safety | `p18_multiprocess_tenant_isolation_proof.py` | DEMONSTRATED | Yes | — | None | — |
| Multi-host ownership (code logic) | `owner_host`/`node_id` scoping reviewed, correct in single-real-host testing | DESIGNED / TESTED (single host) | Yes | — | Two-host confirmatory run (Phase 3) | Environment |
| Dead-host recovery (temporary) | `session_reconcile.py`, `admission_lease_reclaim.py` | DEMONSTRATED | Yes | — | None | — |
| Dead-host recovery (permanent, Docker/workspace) | `orphan_sweep.py` node_id-scoped claim, `main.py:133` | NOT BUILT | Yes | Real, demonstrated gap | Build heartbeat + declared-dead + widened-claim design (Phase 2) | Engineering |
| Global capacity ceiling | `admission_control.py`, `rate_limiter.py` | DEMONSTRATED | Yes | — | None | — |
| Tenant-specific capacity | grep confirms none exists | NOT BUILT | No | No stated product requirement; single real tenant today | Ask product; only build if answered "yes" | Product |
| Rate limiting | `rate_limiter.py`, tested | DEMONSTRATED | Yes | — | None | — |
| Background-job isolation | P18 background-job ContextVar tests | DEMONSTRATED | Yes | — | None | — |
| No tenant-context leakage | `do_orm_execute` fail-closed default + negative controls | DEMONSTRATED | Yes | — | None | — |
| Observability | Prior P11-P18 review (metrics/admission control per memory) | DEMONSTRATED | Yes | — | None | — |
| Docker ownership | `owner_host` stamping reviewed in P18 diff | DEMONSTRATED | Yes | — | None | — |
| Approval safety | `runtime_approvals.py` durable multi-phase commit design reviewed | DEMONSTRATED | Yes | — | None | — |
| Execution safety | Token-expiry fencing (`mcp_gateway._resolve_session`) | DEMONSTRATED (partial: fencing yes, exactly-once no — never claimed) | Yes | — | None beyond existing, documented limitation | — |
| Idempotency | Existing `outcome_unknown` pattern | DEMONSTRATED | Yes | — | None | — |
| Reconciliation | `session_reconcile.py`, `capability_reconcile.py` | DEMONSTRATED | Yes | — | None | — |
| Build identity | Confirmed in P18 review (per memory) | DEMONSTRATED | Yes | — | None | — |
| Database security (app-layer) | `db/tenancy.py` fail-closed scoping | DEMONSTRATED | Yes | — | None | — |
| Row-Level Security (Postgres) | Reviewed against `runtime_approvals.py` transaction structure | DEFERRED (defense-in-depth) | No | App-layer isolation already demonstrated sufficient for the actual threat model | Revisit only if a raw-SQL/ORM-bypass path is introduced | Architecture (deferred, not active) |
| Two-real-host live proof | `docker context ls` — one daemon only | NOT DEMONSTRATED | Yes (as evidence), No (as a design gap) | Code is host-count-agnostic by design; this is confirmatory, not discovery | Run acceptance test (Phase 3) when hardware/VMs available | Environment |

---

## Phase 7 — Smallest Model-C closure path

**1. Must build (Engineering):**
- Permanent dead-host Docker/workspace reclamation: heartbeat table, declared-dead
  threshold, narrowly-widened `claim_batch` predicate gated on declared-dead (not
  "any non-local owner"), `outcome_unknown`-style terminal state for reclaimed rows.
  This is the *only* item in this entire gate that requires new production code. Scope
  is small and bounded — it does not touch the session/lease reconciliation paths,
  which are already correct.

**2. Must decide (Product):**
- Whether per-tenant capacity/fairness is an actual product requirement. Until answered,
  Model A (global-only) remains correct and nothing should be built speculatively.

**3. Must demonstrate (Environment, once available):**
- Two-real-host acceptance test (Phase 3's 8-step procedure), run against real,
  independent hardware/VMs sharing one Postgres instance.

**4. Can remain deferred indefinitely without blocking Model C:**
- PostgreSQL RLS — defense-in-depth only; the primary enforcement layer is already
  demonstrated. No partial RLS should ever be added; either build it correctly against a
  transaction architecture that supports it, or don't build it at all.
- Tenant quotas — unless and until Phase 4's product decision comes back "yes," this
  stays exactly where it is (global-only), which is Model A, already built.

**5. Environmental prerequisites:**
- A second real host or VM (not a second Docker context on the same machine) reachable
  from the same Postgres instance, for Phase 3.
- An operational decision on the declared-dead threshold constant for Phase 2's design
  (an ops/runbook parameter, not a research question — can be set conservatively at
  build time and tuned later).

**Explicitly what should NOT be built right now:**
- Tenant quotas of any shape, until Phase 4 is answered by the business.
- Any RLS policy, partial or otherwise, until/unless a genuine ORM-bypass threat
  emerges that changes the Phase 5 calculus.
- Any simulated "second host" (e.g. a second Docker context or container on this same
  machine) presented as satisfying the two-host requirement.
- Any redesign of the durable multi-phase commit structure in `runtime_approvals.py`
  purely to accommodate RLS — that structure exists for a separate, already-solved
  safety reason (surviving partial failure without losing `executing` state) and
  should not be compromised for a defense-in-depth layer.

---

## Verdicts

- **Model A:** READY (unchanged).
- **Model B:** READY (unchanged).
- **Model C:** **NOT READY.** One genuine engineering blocker (permanent dead-host
  Docker/workspace reclamation), one environmental prerequisite (two-real-host proof),
  one open product question (tenant capacity), one deliberately deferred
  defense-in-depth item (RLS). Of these four, only the first is actual required
  engineering work before Model C can honestly be called READY; the others are,
  respectively, an evidence-gathering step, a business question, and a legitimate
  permanent deferral.
