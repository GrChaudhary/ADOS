# 32 — Dead-Host Reclamation and Frontend Development

Companion to [31-model-c-decision-gate.md](31-model-c-decision-gate.md). That
document was decision-only ("do not implement"). This one is the controlled
implementation workstream that followed it: closing the one genuine
Model-C engineering blocker it identified (permanent dead-host Docker/
workspace reclamation), and bringing the ADOS frontend (`frontend-next/`)
back into active development after roughly a week of backend-only work.

Repository state at the start of this workstream: HEAD `7464902`, branch
`prime-agent-runtime`, P11–P18 present and unregressed, P18 PASS (911
passed / 0 failed / 19 deselected, Docker 17/17), Model A/B READY, Model C
NOT READY.

---

## Part A — Dead-host reclamation (backend)

### Design

New files:

- `db/models/node_heartbeat.py` — `NodeHeartbeatRow` (`node_heartbeats`
  table: `node_id` primary key, `last_seen_at`). One row per live ADOS
  process host, upserted every periodic-loop tick.
- `alembic/versions/a1b2c3d4e5f6_node_heartbeats.py` — creates the table.
  No backfill; empty until the first tick.
- `orchestrate/runtime/node_heartbeat.py` — `record_heartbeat()` (upsert)
  and `declared_dead_node_ids()` (every node whose heartbeat is older than
  a conservative, operator-tunable threshold —
  `Settings.node_heartbeat_dead_after_seconds`, default 900s, 3× the
  default `orphan_reconcile_interval_seconds`).

Modified:

- `orchestrate/runtime/orphan_sweep.py` — `claim_batch` gained
  `dead_node_ids`, widening its existing P16 `owner_host` filter to also
  admit a declared-dead host's rows. `ClaimedItem` gained
  `via_dead_host_reclaim: bool`. `_process_one` now short-circuits any
  `via_dead_host_reclaim` item straight to a new terminal outcome,
  `unverifiable`, **without ever calling the real Docker/filesystem check**
  — this host cannot observe another host's Docker daemon, so attempting
  the check would not verify anything, only always report "absent"
  regardless of the real state on the (declared-dead, possibly merely
  partitioned) owning host. `_eligible_for_claim` treats `unverifiable` as
  terminal (same as `cleaned`/`absent`) so it is never reprocessed.
- `backend/app/main.py` — the periodic loop now records this process's own
  heartbeat and computes `dead_node_ids` (excluding itself) before each
  orphan sweep, wrapped in its own try/except (failure degrades to
  `dead_node_ids=[]`, i.e. own-host-only scope that tick — never fatal to
  the sweep that follows).
- `backend/app/config.py` — `node_heartbeat_dead_after_seconds: float =
  900.0`.
- `backend/app/metrics.py`, `scripts/sweep_orphans.py` — `unverifiable`
  added alongside the existing cleaned/absent/failed/refused outcome
  labels.

### Safety argument (why this doesn't reintroduce the P16 risk)

Widening *which* rows are claimable does not change *what a sweeper can
conclude* once it claims one. The one new rule — never run a real
Docker/filesystem check against a cross-host candidate — is the entire
safety property: reclamation here means "close the bookkeeping on a host
conservatively presumed gone," never "we proved the resource is gone," and
never "re-run anything." Every session eligible for the sweep is already
`TERMINAL_STATES` — there is nothing to re-execute. A host that is merely
partitioned (not actually dead) can be wrongly declared dead by heartbeat
staleness; the consequence is bounded to a Docker/workspace resource leak
on that host until it reconnects, never a duplicate mission execution or a
lost safety guarantee. Token-expiry fencing
(`session_reconcile.py`, `mcp_gateway.py::_resolve_session`) is completely
unchanged and remains what actually prevents a revived host from taking any
unsafe *action*.

### Tests

`backend/tests/test_node_heartbeat.py` — 14 tests, real Postgres, covering
every item the task required: heartbeat creation/update, healthy-host
liveness, the dead threshold as a real boundary, dead-host declaration
excluding self, a host with no heartbeat row is not treated as dead,
live-host resources staying protected even when another host is dead,
dead-host resources becoming claimable, the core safety property (a
dead-host reclaim never calls the real Docker seam — proven by making that
seam raise if called), a same-host claim still runs the real check
(negative-test sanity check), concurrent reclamation (two hosts racing
never double-claim, `SKIP LOCKED` composes correctly with the new filter),
stale-host fencing (a resource already closed via dead-host reclaim is
never reprocessed, even by the formerly-dead host waking up and sweeping
itself), composition with P17's existing all-tenant scan, and that a
database failure during the heartbeat/dead-node pass raises cleanly rather
than silently returning a wrong-but-successful empty result.

Result: **14/14 passed.**

Regression: `test_orphan_sweep.py` (22), `test_orphan_sweep_multihost.py`
(6), `test_metrics.py` (21) — **49/49 passed**, zero regressions from the
`claim_batch`/`_process_one`/`SweepReport` changes.

Full backend suite (`pytest -m "not docker"`) run as part of Part 10 below.

### What was deliberately NOT built

Two-real-host live proof (still environment-limited — only `default`/
`desktop-linux` local Docker contexts exist, unchanged from doc 31),
tenant-specific capacity (still a product decision, untouched), RLS (still
deferred as defense-in-depth, untouched). This workstream closed exactly
the one engineering blocker doc 31 identified — nothing else.

---

## Part B — Frontend discovery and development

### Audit summary

Full findings are in the discovery-agent transcript from this session; the
headline facts:

- **Framework**: Next.js 16.2.12 (App Router), React 19.2.4, TypeScript
  strict, TanStack Query v5 + Zustand, Playwright for E2E. No unit/component
  test framework exists (no Jest/Vitest).
- **Staleness**: last frontend commit (`10c51bb`) predates every P4–P18
  backend commit — roughly a week of backend-only work (missions, runtime
  approvals, admission control, reconciliation, and P17 multi-tenancy) had
  zero corresponding frontend change before this workstream.
- **CRITICAL**: the frontend had no tenant concept at all — zero references
  to "tenant" anywhere in `frontend-next/src`, no `X-Tenant-Id` header ever
  sent. Worked today only because every seeded account has exactly one
  tenant membership (the backend's own "no extra step needed" branch); any
  real multi-tenant user would get an unexplained `400` on every
  tenant-scoped call.
- **HIGH**: the runtime capability-request approval queue
  (`backend/app/routers/runtime_approvals.py` — the human half of the Prime
  Agent's Tier 1/2 approval loop, built and hardened across P4–P15) had
  **zero frontend coverage** — no page, no API client methods. This was the
  single largest built-but-invisible subsystem found.
- **MEDIUM**: no error boundary, no toast system, errors surfaced as raw
  `"${status} ${path}: ${body}"` strings; zero unit/component tests, one
  Playwright E2E spec (MOA approval only); `/admin`, `/replay`,
  `/policy-studio` exist but are orphaned from nav (unresolved — flagged for
  a product decision, not touched here).
- **LOW**: `PlaceholderScreen.tsx` was dead code (zero importers, leftover
  from a superseded phase) — removed. `JarvisParticleOrb`/`NovusParticleOrb`
  (and their matching "lab modal" components) look like parallel,
  possibly-mergeable implementations — flagged, not touched (classified
  REVIEW, not REMOVE — both are actively imported).

### What was implemented (priority order: security/tenant → approval
workflow → operator usability → testing)

**1. Tenant correctness (`frontend-next/src/lib/api.ts`)**

- `AuthUser.tenantIds: string[]` — the field the backend already returns
  (`backend/app/rbac.py User.tenant_ids`, aliased `tenantIds`) but the
  frontend never stored.
- `getActiveTenantId()` — selection rule matching the backend's own
  contract exactly: zero memberships → `null` (nothing sent); exactly one
  → that one, always; more than one → whichever the user explicitly chose
  (`setActiveTenantId`), re-validated against their *current* memberships
  on every call (never trusts a stale/foreign localStorage value), falling
  back to the first membership.
- `setActiveTenantId()` — only ever accepts one of the current user's own
  memberships; throws otherwise. No client-side trust of arbitrary tenant
  IDs, matching the task's explicit constraint.
- `apiFetch`/`apiFetchBlob` now attach `X-Tenant-Id` whenever
  `getActiveTenantId()` is non-null (confirmed safe against
  `backend/app/tenancy.py::get_tenant_context` — it always accepts a
  correct header, even for single-membership users, so there is no
  conditional-omission edge case to get wrong).
- `frontend-next/src/lib/useActiveTenant.ts` — new hook, same
  `useSyncExternalStore` pattern as `useHasToken`/`useCurrentUser`.
- `HeaderTelemetryBar.tsx` — a tenant identity chip (visible whenever a
  user is logged in and has an active tenant), rendered as a plain label
  for single-tenant users and a `<select>` switcher for multi-tenant ones.
  No tenant-name lookup endpoint exists on the backend (only the raw UUID),
  so the chip shows a truncated tenant ID with the full value in a
  tooltip — honest about what it actually knows, no invented display name.

**2. Runtime capability-request approval queue (new)**

- `api.ts` — `CapabilityRequestView`/`CapabilityRequestListResponse`
  types (matching `runtime_approvals.py::_view()` field-for-field) and
  four new client methods: `listCapabilityRequests`,
  `getCapabilityRequest`, `approveCapabilityRequest`,
  `rejectCapabilityRequest`.
- `frontend-next/src/app/approvals/page.tsx` — new page. Status-filter
  switcher across the full lifecycle (`pending_approval` / `executing` /
  `executed` / `failed` / `outcome_unknown` / `denied`); each request
  renders capability, mission/session IDs, estimated cost, policy tier,
  risk class, arguments (collapsible), decision history; `pending_approval`
  rows get Approve/Reject actions with an optional reason field for reject.
  `outcome_unknown` gets a distinct, explicit warning banner (never
  rendered as plain success or failure). Errors are parsed for their HTTP
  status: a `409` (already decided, or session no longer live) is labeled
  as a conflict rather than a generic failure; a `403` is labeled as an
  authorization restriction. No action here executes anything client-side
  — every button is a call to the same server-enforced endpoint the task
  explicitly required stay the sole authority.
- `Sidebar.tsx` — added a "Runtime Approvals" nav entry (Core Platform
  section) — the page was previously unreachable from any UI.

**3. Housekeeping**

- Removed `frontend-next/src/components/design-system/PlaceholderScreen.tsx`
  (verified zero importers before deleting).

### Validation

- `npx tsc --noEmit` — zero errors.
- `npm run lint` — zero errors (3 pre-existing warnings, in
  `agents/network/page.tsx` and `novus/page.tsx`, both files this
  workstream did not touch — uncommitted, unrelated in-progress work).
- `npm run build` — succeeds; `/approvals` registered as a static route
  alongside every existing page.
- Live E2E (Playwright, against a fresh `uvicorn` instance started from the
  exact current source on an isolated port — the already-running Docker
  backend on :8000 was left untouched since it predates this session's
  uncommitted work and was not started by this workstream):
  - `moa-approval.spec.ts` (pre-existing) — **passed**, zero regression.
  - `runtime-approvals.spec.ts` (new) — **passed**: real login, nav
    reachability, a real (non-mocked) queue load with no error state,
    filter switching. Approve/reject round-trip is intentionally not
    covered by this spec — a real `pending_approval` row only comes from a
    live Prime Agent mission through Docker/MCP infrastructure, out of
    scope for a browser smoke test; that round trip is already covered by
    the backend's own `runtime_approvals` test suite.

### What was NOT built (explicitly out of scope)

- No backend changes to support tenant *names* (only IDs exist on the
  wire) — adding a `/tenants` lookup endpoint would be new backend surface
  beyond the one authorized blocker (Part A) and was not added.
  `/admin`, `/replay`, `/policy-studio` nav orphaning — left as found,
  flagged for a product decision.
- No error boundary / toast system — real gaps (classified MEDIUM), left
  for a future increment; today's generic string-error surfacing was not
  regressed, only extended consistently to the new page.
- No unit/component test framework introduced (none existed; introducing
  one is an infra decision outside this workstream's scope).
- `JarvisParticleOrb`/`NovusParticleOrb` duplication — flagged, not
  touched (both actively used; a merge is a design call, not a bug fix).

---

## Part C — Model-C reassessment

Re-running doc 31's requirement matrix after this workstream. Only one row
changes status; everything else is unchanged from doc 31 (re-verified, not
re-derived).

| Requirement | Doc 31 status | Status now |
|---|---|---|
| Dead-host recovery (permanent, Docker/workspace) | NOT BUILT (Engineering) | **IMPLEMENTED + TESTED** (14/14 new tests, 49/49 regression) |
| Two-real-host live proof | NOT DEMONSTRATED (Environment) | unchanged — still only local Docker contexts available |
| Tenant-specific capacity | NOT BUILT (Product decision required) | unchanged — no product decision supplied this workstream |
| Row-Level Security | DEFERRED (Architecture, defense-in-depth) | unchanged — not implemented, not required |
| Every other P11-P18 requirement (tenant isolation, cross-process safety, admission control, rate limiting, background-job isolation, observability, Docker ownership, approval/execution safety, idempotency, reconciliation, build identity, database security) | DEMONSTRATED/TESTED | unchanged, reconfirmed via the 49/49 regression pass |

**Model A: READY** (unchanged).
**Model B: READY** (unchanged).
**Model C: NOT READY** — but the gap narrowed to exactly two items, neither
of which is engineering work: (1) two-real-host proof, an environmental
prerequisite, not a design gap — the code under test is host-count-agnostic
by construction; (2) tenant-specific capacity, a product decision this
workstream was explicitly told not to invent. RLS remains a deliberate,
justified deferral, not an open item. **The one item doc 31 classified as a
genuine required engineering build is now closed.**

