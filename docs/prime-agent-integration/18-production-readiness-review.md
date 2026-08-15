# P8 — Production Readiness / Architecture Review

Compiled 2026-08-11 from the repository at `d4faf37` (branch `prime-agent-runtime`),
independently re-derived from code, tests, and live state — not copied from
[17-final-acceptance-report.md](17-final-acceptance-report.md). This is a
**review, not a remediation phase**: no implementation code was changed to
produce it. Where this document disagrees with an earlier report, the
disagreement is stated explicitly, with the evidence that produced it.

The categories below are used strictly:

| Category | Means |
|---|---|
| **DEMONSTRATED** | proven by a real, live, independently-checked run |
| **TESTED** | an automated test proves the mechanism; no live run exercised it |
| **DESIGNED** | the implementation exists; no test or live run independently proves it |
| **PARTIAL** | proven for part of its claimed scope, not all of it |
| **NOT BUILT** | outside implemented scope |
| **UNKNOWN** | genuinely not established either way by this review |

---

## 1. Executive summary

ADOS's Prime Agent integration has a real, working, and — for its core path —
genuinely **demonstrated** governed execution chain: a containerized agent,
behind an enforced network boundary, authenticated by an opaque per-session
token, requesting capabilities ADOS decides on server-side, executing through
one choke point, writing durable audit rows, and stamping provenance that
resolves back to them. This was proven against real Docker state and a real
ServiceNow instance across P6 and P7, not merely unit-tested.

P7-B/C/D closed three real, previously-manual operational hazards: a stale
gateway process can no longer start a mission on drifted code (partially —
see §5.2), Docker/workspace orphans are now swept on a fixed interval instead
of by hand, and a session an ADOS process failure abandons is now reconciled
once its own token proves it dead.

This review's own re-derivation surfaces **five gaps not previously
documented** in any P6/P7 report, found by reading the actual crash and
concurrency paths rather than trusting the existing narrative:

1. An ADOS crash **during** a capability's connector call — most importantly
   a ServiceNow write — leaves the `capability_requests` row in a state that
   cannot be distinguished from "still legitimately pending." Nothing
   reconciles that table; only `runtime_sessions` is reconciled. (§9, §4B)
   **CLOSED — P9, §15.**
2. An ADOS crash **during** human approval can roll the decision back to
   `pending_approval` **after** the external side effect already happened,
   making the request approvable a second time — a real double-execution
   path, not merely a theoretical one. (§9, §4B) **CLOSED — P9, §15,
   proven against a real ServiceNow instance.**
3. The idempotency-key replay guard in the gateway is real and tested, but
   the one prompt template that teaches the model the `ados` skill's API
   never mentions the parameter — so in practice, no live mission has ever
   supplied one. The guard exists but is not reachable from the only caller
   that would need it. (§9, §6F) **CLOSED — P9, §15: replaced with an
   automatic, server-computed key nothing needs to be taught.**
4. The P7-D build-identity drift guard protects the **start** of a mission
   (before a container exists) but is not called anywhere in
   `mcp_gateway.py`'s capability-execution path — a commit landing while a
   mission is already in flight is not caught for that mission's remaining
   capability calls. (§5.2, §4B) **CLOSED — P10, §16.4** (with the same
   shipped-image caveat the original P7-B/D guard already carried — a
   production image built without `.git` has nothing to compare against).
5. `docs/prime-agent-integration/17-final-acceptance-report.md`'s own
   regression paragraph for P7-D miscounts the test suite: it states "8
   `external`" and "7 `docker`" deselected. Direct re-collection in this
   review finds **2** external-marked tests and **13** docker-marked tests,
   both fully consistent with every *other* number in that same report.
   (§9)

None of these are exotic. All five follow directly from reading the code the
existing reports already point at. They are the difference between "the
happy path is proven" and "the system is production-ready."

**Verdict at P8: NOT READY**, for any operating model that involves a real,
unattended external side effect, primarily because of findings 1–3 above.
**P9 (§15) closes findings 1–3.** See §15 for the updated verdict — it does
not move all the way to "ready" (findings 4 and the rest of §11's blocker
list are unaffected and remain open), but the specific silent-duplication
risk that drove the original NOT READY verdict is closed, with real
external evidence.

---

## 2. Current architecture — the full lifecycle

```
user/mission → Prime Agent → per-session runtime/container → egress boundary
  → MCP gateway → identity/session token → server-side capability grant
  → policy tier → autonomous execution OR human approval
  → single capability execution choke point → connector → external system
  → durable audit/provenance → acceptance/evaluation → cleanup/reconciliation
```

| # | Boundary | Enforced | Where (file) | Evidence | If this component fails |
|---|---|---|---|---|---|
| 1 | mission → Prime Agent | Capability grant fixed at mission creation, server-side only | `integrations/connectors/prime_runtime.py::_run` | DEMONSTRATED (P6-A…P7-A live missions) | ADOS dies before the row commits → nothing happened, safely retryable. Dies after → see §9 |
| 2 | Prime Agent → container | Build-identity drift check runs first; non-root, resource-limited, disposable workspace | `prime.py::start`, `build_identity.py::verify_no_drift_since_process_start` | DEMONSTRATED for mission-start drift (P7-D negative control); **does not cover mid-mission capability calls** (§5.2) | `docker run` fails → session `FAILED`, no container ever exists |
| 3 | container → egress boundary | Per-session `--internal` network, no default route, destination-pinned relay | `egress.py` | DEMONSTRATED (P6-D: two live containers probed, cross-session blocked by address) | Relay fails to start → boundary tears itself down, container never starts (fails closed) |
| 4 | egress boundary → MCP gateway | Opaque, identity-only bearer token; HTTP MCP, mounted outside JWT auth | `mcp_gateway.py::_resolve_session` | DEMONSTRATED | Gateway unreachable → agent's tool calls fail; no fallback path exists (correct — no silent degrade) |
| 5 | identity/session token | SHA-256 hash stored, expiry = wall-clock budget + 300s grace | `prime.py::token_expiry` | DEMONSTRATED (P7-D: live expiry against the real separate gateway process) | Token never issued (pre-P6-D code path) → session lives at `running` forever unless caught by the (deliberately non-existent) NULL-expiry path |
| 6 | server-side capability grant | `mission.allowed_capabilities`, re-read on every call; runtime cannot widen it | `mcp_gateway.py::request_capability` | DEMONSTRATED | Mission row missing/deleted → `_Denied("mission no longer exists")` |
| 7 | policy tier | `assign_policy_tier`, shared with MOA, computed server-side | `orchestrate/governance.py` | TESTED + DEMONSTRATED (P6-B Tier 2 hold) | N/A — pure function, no external dependency |
| 8 | autonomous execution OR human approval | Non-autonomous tiers parked durably; human decides via a real JWT-authenticated endpoint | `mcp_gateway.py`, `backend/app/routers/runtime_approvals.py` | DEMONSTRATED (P6-B 98.1s hold, P7-A) | See §9 — this is the crash window with the most serious open finding |
| 9 | single capability execution choke point | Exactly two callers of `_execute_capability` in the whole codebase (grep-verified) | `mcp_gateway.py::_execute_capability` | Structurally verified by code reading; not pinned by a test that would fail if a third caller appeared | A third call site would be silently possible; nothing enforces the "exactly one door" property except discipline |
| 10 | connector | `ConnectorPolicyEngine` selects the real connector before falling back to `ConsoleConnector` | `integrations/hub.py` | DEMONSTRATED for `PrimeRuntimeConnector` and `ServiceNowConnector`; other connectors (SAP, Marketplace, SmartFactory) are out of this integration's scope and remain simulated | Real connector not configured → falls back to `ConsoleConnector`, which reports success for a simulated action; this fallback is visible on the audit row (`connector` field) but not blocked |
| 11 | external system | Real ServiceNow Table API POST/PATCH/GET | `integrations/connectors/servicenow.py` | DEMONSTRATED (`INC0010028`, `CHG0030499`, `CHG0030638`, independently read back) | Non-2xx or transport error → `CallStatus.FAILED`, never silently treated as success |
| 12 | durable audit/provenance | `capability_requests`/`missions`/`runtime_sessions`; provenance block appended to the external record | `db/models/mission.py`, `integrations/connectors/servicenow_fields.py` | DEMONSTRATED (P7-A: `CHG0030638` resolves back to its exact row) | See §9 for the write-ordering gap this review found |
| 13 | acceptance/evaluation | `evaluate_mission()` takes no agent-authored input | `orchestrate/runtime/acceptance.py` | DEMONSTRATED + TESTED (signature test + 8 unit tests) | N/A — pure function over already-durable rows |
| 14 | cleanup/reconciliation | Automatic interval-based reconcile + sweep; ownership-labelled, bounded, idempotent | `orphan_sweep.py`, `session_reconcile.py`, `main.py` | DEMONSTRATED (P7-C/D, real Docker) | Covers `runtime_sessions` and their Docker/workspace resources only — **not** `capability_requests` (§9) |

---

## 3. What "production" means here

The instructions for this phase are correct to refuse an undefined target.
Three concrete operating models, in increasing order of what they demand:

**A. Controlled internal/single-node deployment.** One organization, trusted
operators, a human who is actually watching the approval queue and the logs,
one Docker host, restarts are rare and tolerated, no SLA, no external
tenants.

**B. Production long-running mission service.** Still one organization and
one deployment, but real on-call expectations, missions that run for hours
unattended, an expectation that "the audit trail is correct" is actually
true without a human re-verifying it externally, and that a crash does not
silently create or lose a real ServiceNow record.

**C. Distributed/multi-user mission platform.** Multiple tenants and/or
horizontal scale across hosts, many concurrent missions, no single human who
could plausibly watch every approval queue by eye.

Each limitation in §5 is scored against **which of these it blocks**, not
against an assumed "must fix everything" bar.

---

## 4. Category assessments

### A. Security

| Aspect | State | Evidence |
|---|---|---|
| Authentication (runtime) | Opaque, hashed, identity-only session tokens | DEMONSTRATED |
| Authentication (human) | JWT, HS256, 12h TTL | DEMONSTRATED, but see below |
| Authorization | RBAC roles + `approval_limit_usd`, checked server-side | TESTED + DEMONSTRATED (P6-B: auditor 403) |
| Capability grants | Server-side, re-read every call, cannot be widened by the runtime | DEMONSTRATED |
| Approval integrity (steady state) | Double-decision refused (409), dead-session refused (409) | DEMONSTRATED |
| Approval integrity (crash window) | **Not protected** — a crash after the external effect but before commit can roll the decision back to re-approvable | **OPEN — found in this review, §9** |
| Token lifecycle | Expiry tied to wall-clock budget + grace, independent of process liveness | DEMONSTRATED (P7-D live) |
| Egress isolation | Per-session `--internal` network, no default route, pinned relay | DEMONSTRATED (real container probes) |
| Cross-session isolation | Per-session networks + Docker ownership labels | DEMONSTRATED |
| Provenance | Request id resolves from the external ticket back to the exact row | DEMONSTRATED (P7-A) |
| Secret exposure (to the container) | Two secrets only: LLM key, opaque token — no DB URL, no connector credentials | DEMONSTRATED |
| Caller spoofing | Build identity, capability grant, and `approved_by` all independently unspoofable | DEMONSTRATED (dedicated negative-control tests for each) |
| Audit integrity (application layer) | Gateway is the sole writer; agent's self-report never lands in the audit trail | DEMONSTRATED |
| Audit integrity (storage layer) | **Postgres runs as a superuser in the shipped compose stack** — the repository's own comment states this "voids the append-only guarantee on the approval ledger" | **Self-acknowledged, unresolved** (`docker-compose.yml:29-31`) |
| Host boundary | The backend container mounts `/var/run/docker.sock` directly | Confirmed (`docker-compose.yml:149`). A compromise of the ADOS backend process is a compromise of the host's Docker daemon — a materially larger blast radius than "the kernel is not a sandbox, the container is the boundary" advertises, since it is the *container that starts other containers* that holds this access, not the agent's own container |
| Browser-side token handling | JWT in `localStorage` (XSS-readable); SSE token passed as a URL query parameter | Confirmed current (`frontend-next/src/lib/api.ts:11,820`) — both are real, unresolved, independent of the Prime Agent runtime itself but part of the same trust boundary a human approver operates behind |

### B. Reliability

| Failure | Behavior | Evidence |
|---|---|---|
| ADOS process crash, before any row exists | Nothing happened; trivially safe | By construction |
| ADOS process crash, mid-mission (container running) | Session row frozen at `running`; token is the only thing that eventually revokes it; **the row's own authorization check never asks whether the ADOS process that started it is still alive** — only state and token expiry | Verified by code reading (`_resolve_session`); whether the underlying `docker exec` process itself survives the crash was **not live-tested in this review** (would require killing the running backend against a live mission) — see §9 for what is and is not certain here |
| ADOS process crash, mid-capability-execution (autonomous tier) | `capability_requests` row can be left at `pending_approval` forever with an ambiguous real-world outcome | **OPEN — §9** |
| ADOS process crash, mid-approval decision | Transaction rolls back; row returns to `pending_approval`; external effect may have already happened | **OPEN — §9** |
| Gateway crash/restart | Same process as ADOS; not independently restartable | By design — see §8 |
| Runtime/container crash | Teardown attempts every resource independently; leftovers recorded and later swept | DEMONSTRATED (P7-C/D) |
| Docker daemon failure (per-command timeout) | Each `docker` call is individually timeboxed; failures don't cascade | TESTED |
| Docker daemon failure (full outage) | Not live-tested against a genuinely down daemon; design (independent per-resource attempts, no raise from teardown) suggests a clean `FAILED` mission, not a hang | DESIGNED / PARTIAL |
| Database failure (startup) | `check_connectivity_or_raise()` fails loud before serving traffic | DEMONSTRATED |
| Database failure (mid-request) | Not specifically tested; behaves the same as an ADOS crash for the purposes of §9's analysis | PARTIAL |
| Connector failure | Non-2xx / exception never counted as success | DEMONSTRATED |
| Model failure | `classify_tool_execution` correctly separates ok/error/unknown; documented model-specific failure modes (17-call loops, malformed tool calls) | DEMONSTRATED |
| Network failure (egress) | DEMONSTRATED via the boundary itself | DEMONSTRATED |
| Approval timeout (agent side) | Agent raises `CapabilityTimeout` after its own wait budget; the request row is **not** cancelled and can still be approved later, potentially after the agent has stopped listening | TESTED; the "orphaned approval" edge case is real but low-severity (§5) |
| Cancellation | `BaseException` caught, terminal state always written | TESTED |
| Teardown failure | Independent per-resource attempts; leftovers swept later | DEMONSTRATED (P7-D real injected failure + real recovery) |
| Orphan resources | Automatic, bounded, idempotent sweep | DEMONSTRATED |
| Stale processes (mission start) | Refused before any row is created | DEMONSTRATED (negative control) |
| Stale processes (mid-mission) | **Not covered** — the guard is not called on the capability-execution path | **OPEN — §5.2** |
| Duplicate execution | Two independent real paths to it exist (approval crash-rollback; idempotency key never actually supplied) | **OPEN — §9, §6F** |

### C. Recovery — see §9 in full (the four crash windows this phase was specifically asked to analyze)

### D. Operations

| Aspect | State | Evidence |
|---|---|---|
| Deployment/version identity | Git commit + dirty flag, reported on `/healthz`, unspoofable | DEMONSTRATED |
| Migrations | Alembic; automated in the compose path (`ados-migrate-1` one-shot service, confirmed exited 0); manual (`alembic upgrade head`) for a bare `.venv` run | DEMONSTRATED (compose) / DESIGNED (bare) |
| Health checks | `/healthz` is a liveness check (process up, reports build identity); does **not** check Docker daemon or ServiceNow reachability | PARTIAL |
| Monitoring | None. No Prometheus/OpenTelemetry/Sentry anywhere in the codebase; `observability.py` explicitly declines a `/metrics` endpoint ("no scraper to serve") | NOT BUILT |
| Alerting | None (follows from no monitoring) | NOT BUILT |
| Logs | Structured JSON, request-id correlated | DEMONSTRATED — but stdout-only, no shipping/retention policy configured | PARTIAL |
| Metrics | None | NOT BUILT |
| Audit retention | Rows are never deleted by any reviewed code path — unbounded by default, no archival policy | Correct for auditability, a gap for storage management at scale |
| Backups | No backup/restore tooling found for Postgres; compose uses a bare named volume | NOT BUILT |
| Restore procedures | None found | NOT BUILT |
| Cleanup scheduling | Automatic, interval-based, disable-able | DEMONSTRATED (P7-D) |
| Resource quotas (per-container) | Memory/CPU/pids limits set on every container | DEMONSTRATED |
| Resource quotas (concurrency ceiling) | **No limit anywhere on the number of concurrent Prime Agent sessions/containers a process will start** (confirmed by grep — no semaphore, no admission control) | NOT BUILT |
| Rate limiting | None, on any endpoint, including ones that call a paid LLM per request | NOT BUILT |
| Operational runbooks | `scripts/sweep_orphans.py`, `scripts/reset_user_password.py` exist as tools; `14-known-limitations.md` functions as an informal runbook; no formal incident-response document | PARTIAL |

### E. Scalability

| Aspect | State | Evidence |
|---|---|---|
| Multiple simultaneous missions | Proven for 2, live, with real cross-isolation | DEMONSTRATED for n=2; UNKNOWN beyond |
| Multiple simultaneous approvals | Queue endpoint supports many; double-decision on the *same* row is locked | DESIGNED for the queue; TESTED for the lock |
| Long-running missions | No hard ceiling on `max_wall_clock_seconds`; risk grows with mission length because there is no resume (§9) | DESIGNED, with a real and growing exposure window |
| Many concurrent sessions | No admission control (see Operations) | NOT BUILT |
| Concurrent model calls | No ADOS-side throttling; bounded only by the provider's own limits (a hard TPM ceiling was already hit in testing — `14-known-limitations.md`) | NOT BUILT |
| Database contention | `SELECT ... FOR UPDATE SKIP LOCKED` used consistently on every hot path (approvals, sweep, reconciliation); `NullPool` means no connection reuse, so every request opens a fresh Postgres connection | TESTED for the locking pattern; UNKNOWN at real production concurrency against Postgres's connection ceiling |
| Docker/container limits | Per-container limits set; no cap on total containers per host; single-Docker-daemon design (no multi-host awareness anywhere in `egress.py` or `orphan_sweep.py`) | Real constraint for operating model C |
| Connector rate limits | Not mediated by ADOS at all | NOT BUILT |

### F. Maintainability

| Aspect | State | Evidence |
|---|---|---|
| Single execution choke point | Verified: exactly two call sites for `_execute_capability` | Structurally verified, not test-pinned (§2 row 9) |
| Duplicated policy logic | `assign_policy_tier` is genuinely shared between MOA and the runtime gateway (one implementation) | Good — DEMONSTRATED |
| Duplicated *approval* mechanisms | MOA's own incident-approval path still constructs `orchestrate/governance.py::ApprovalQueue` (an in-memory queue, separate from the durable `capability_requests` table the Prime Agent runtime path uses) — two different "Tier 1/2 needs a human" data models coexist for two different callers | Not a Prime Agent-scoped defect, but a real inconsistency worth naming |
| Test quality | 761 tests collected, 759 pass with `external` deselected (this review's own fresh run — §15) | DEMONSTRATED |
| Negative controls | 31 across P6-C/D and P7-B/C/D, each independently restored byte-identical | DEMONSTRATED (per-phase reports) |
| Stale-process detection | Covers mission start; does not cover mid-mission capability calls (§5.2) | PARTIAL |
| Documentation consistency | `docs/prime-agent-integration/README.md` still describes orphan sweeping as "recorded but never consumed" and the stale-gateway hazard as undetectable — both fixed since P7-C/B. The P7-D report's own test-count arithmetic is wrong (§15). Neither was updated by this review, per its no-implementation-changes, no-unrelated-scope-drift instructions; both are named here as findings | Real, and worth a five-minute fix in a future phase |
| Configuration management | Settings are typed, documented inline with their own safety reasoning (`config.py`); `.env` hygiene issues (dead keys, no `DATABASE_URL` set, falling back to a dev-only superuser default) are pre-existing and out of this integration's scope | PARTIAL |

---

## 5. Major architectural limitations, individually assessed

### 5.1 No session resume after ADOS restart
**HIGH RISK for B and C, ACCEPTABLE OUT-OF-SCOPE for A.** Prime Agent has no
suspend primitive (`base.py`'s own docstring says so), so this was never a
gap that could be closed cheaply — it requires checkpointing a live IPython
kernel conversation, which is a different, larger feature. For a
single-operator internal tool where a lost mission just gets re-run, this is
tolerable. For an unattended, hours-long production mission, this is the
single biggest reason a crash is expensive rather than merely inconvenient
— see §9.

### 5.2 The build-identity guard covers mission start, not the capability path
**MEDIUM-HIGH RISK for B and C.** This is the one item in this list that
looks closed in the existing reports but is not, fully. `verify_no_drift_
since_process_start()` is called exactly once, at the top of
`PrimeRuntimeConnector._run()` — before a container exists. It is **not**
called anywhere in `mcp_gateway.py`, meaning a commit landing while a
mission is already in flight is never checked again for that mission's
remaining `request_capability` calls, including ones that reach ServiceNow.
The exposure window requires a commit to land during an in-flight mission —
narrower than the original "gateway idle for hours" hazard P7-B closed, but
real, and inside the literal scope P7-D was asked to close ("wherever a
stale gateway could cause a mission **or external side effect** to run
against the wrong code"). Cheap to close: one call at the top of
`_execute_capability`.

**CLOSED 2026-08-12 (P10).** See §16.4. Same caveat as P7-B/D's original
guard: a no-op inside the shipped Docker image (no `.git` in the build
context), real for a bare-`.venv` deployment.

### 5.3 Approval holds a kernel execution open
**MEDIUM RISK for B, LOW for A, HIGH for C.** Already measured (98.1s, 102.5s
live) and already understood by the existing reports as a cost, not a
defect. See §7 for the full architecture decision on this.

### 5.4 No multi-session mission model / no subagents / no scheduling
**ACCEPTABLE OUT-OF-SCOPE for A and B, NOT BUILT and genuinely a roadmap
item for C.** None of these are half-built; they are simply absent, and
nothing in the current design pretends otherwise. `PrimeRuntimeConnector`
explicitly refuses a nested Prime Agent runtime as a defence-in-depth
measure, which is the right posture for a capability that has no governance
model yet, not a placeholder for one.

### 5.5 Orphan sweeping on an interval, not immediately
**LOW RISK.** Bounded (default 300s), disable-able, and the resource is
already dead by the time it is swept — nothing is *acting* on stale
credentials during the window, only *cleaning up after* them. Acceptable
for all three models as designed.

### 5.6 No automated handling of the NULL-expiry (pre-P6-D) session shape
**ACCEPTABLE OUT-OF-SCOPE.** A closed, non-growing category (three specific
rows), correctly and deliberately left alone because no deterministic proof
of abandonment exists for them. Building a second mechanism for a set that
cannot grow would be effort spent on the wrong thing.

**CORRECTED 2026-08-12 (P10).** This was not accurate: re-derivation from
the live database found 31 such rows, not three, and the category was
still growing — one of P9's own e2e scripts was creating new NULL-expiry
rows by bypassing the real session-creation path. Two pre-existing rows
also had `pending_approval` requests genuinely approvable through the real
endpoint, a live exposure this section did not anticipate because it
reasoned about the session rows' own state, not about what could still be
done *through* them. The rows themselves remain untouched, per this
section's original reasoning (still valid); what closed is the ability to
approve anything through one. See §16.6 for the full account.

### 5.7 Remaining stale-session ambiguity — found in this review
**HIGH RISK for B and C.** Not the gateway-staleness kind — a `capability_
requests` row stuck at `pending_approval` after a crash. See §9 in full;
this is the review's most important single finding.

**CLOSED 2026-08-12 (P9).** See §15 below. `capability_requests` now has a
durable `executing` checkpoint written before any external call, and a
terminal-with-respect-to-automatic-execution `outcome_unknown` state for
whatever a crash or an ambiguous connector response leaves unresolved.
Proven against a real ServiceNow instance, not merely designed.

### 5.8 Deployment/version drift risk beyond the gateway itself
**LOW-MEDIUM RISK.** The Dockerfile's own comment ("`--workers` is
deliberately absent... paused MOA/ITSM approvals live in per-process
state") is now **stale as a stated reason** — that state was made durable
via a Postgres-backed LangGraph checkpointer on 2026-08-09
(`docs/PRODUCTIZATION.md`, Stage 2). The **conclusion** (single process)
still holds for reasons the comment doesn't mention: the default in-memory
event bus does not propagate across replicas, the LLM settings cache is
only eventually consistent across processes, and the whole Docker/egress
design assumes one shared daemon. Worth a comment fix, not a re-architecture
— but a stale *reason* attached to a still-correct *conclusion* is exactly
the kind of drift that eventually gets "fixed" for the wrong reasons.

---

## 6. Production-readiness matrix

| Requirement / Capability | Current state | Evidence | Risk | Production impact | Required before prod? | Recommended remediation | Priority |
|---|---|---|---|---|---|---|---|
| Governed execution path (container→gateway→connector→audit) | Real, proven | DEMONSTRATED | — | Core value proposition | Already met | — | — |
| Egress/cross-session isolation | Real, proven live | DEMONSTRATED | Low | High if absent | Already met | — | — |
| Token lifecycle | Real, proven live | DEMONSTRATED | Low | Medium | Already met | — | — |
| Orphan cleanup | Automatic | DEMONSTRATED | Low | Low (cost/hygiene) | Already met | — | — |
| Build-identity guard (mission start) | Real | DEMONSTRATED | Low | Medium | Already met | — | — |
| Build-identity guard (capability path) | **DEMONSTRATED — P10, §16.4** | One added call in `_execute_capability` | Medium-High | High for B/C | Met | — | — |
| `capability_requests` crash reconciliation | Absent | Code-verified gap | High | High for B/C | **Yes, for B/C** | Detect+flag ambiguous rows; require external re-verification before re-decision | High |
| Approval crash → double-execution | Possible | Code-verified gap | High | High for B/C | **Yes, for B/C** | Persist "external call started" before the call, or move the write inside a compensating saga | High |
| Idempotency-key reachability | Designed, unused in practice | Prompt-template gap, code-verified | Medium | Medium-High for B/C | **Yes, for B/C** | Auto-generate a key per `run_capability` call in the `ados` skill, or teach it in the prompt | Medium |
| Metrics/alerting | Absent (six log-visibility gaps closed — P10, §16.2) | NOT BUILT | Medium | High for B, Critical for C | **Yes, for B/C** | Minimum-viable Prometheus + `trace_id` wiring (already scoped in `docs/PRODUCTIZATION.md`) | High |
| Postgres non-superuser role | **DEMONSTRATED — P10, §16.1** | Real role, real restart | Medium | High (undermines the audit claim) | Met | — | — |
| Rate limiting / admission control | Absent | NOT BUILT | Medium | High for C, Medium for B | **Yes, for B/C** | Bound concurrent sessions; throttle per-caller | Medium |
| Backups/restore | **DEMONSTRATED (mechanism) — P10, §16.3** | Real `pg_dump`/`pg_restore` round trip | Medium | High for B/C | Met (mechanism); retention/offsite/PITR still open, named as ops-owned | — | — |
| Session resume | Absent | NOT BUILT | High for long missions | High for B/C | Not strictly required — see §13 | Checkpoint/resume design (large) | Low (defer) |
| Approval architecture (kernel-held) | Works, costly | DEMONSTRATED | Low-Medium | Medium | Not required — see §7 | See §7's recommendation | Low (defer) |
| Multi-tenancy | Absent | NOT BUILT | — | Blocker only for C | Only for C | Tenant scoping on missions/RBAC | Low (defer unless C) |
| Docker socket exposure | Direct host mount | Confirmed | Medium | Medium-High | Recommended, not strictly blocking for A | Rootless Docker / Docker-in-Docker isolation | Medium |
| JWT in localStorage / SSE token in URL | Present | Confirmed current | Low-Medium | Medium | Recommended for B/C | httpOnly cookie; stream ticket | Medium |

---

## 7. Architecture decision: approval holding a kernel execution open

**A. Keep the current design.** Correctness: highest — the agent's process
is genuinely still there when the decision lands, so "the agent receives the
actual result" (already demonstrated live) is trivial. Complexity: lowest —
no new state machine. Failure modes: the ones this review already names —
a slow approver burns the mission's own wall-clock budget and provider cost
for nothing; an ADOS crash during the hold is just an ordinary mid-mission
crash (§9). Operational implication: approval latency is capped by
`max_wall_clock_seconds`, which makes "how long can a human take" a
capacity-planning question, not an architectural one.

**B. Park durable approval state and terminate/release the execution.**
Correctness: requires the agent to be re-startable with the approval's
result injected — which is exactly the resume primitive Prime Agent does
not have (§5.1). Complexity: high, and mostly *not* in ADOS — it would need
Prime Agent's own kernel/session state to be reconstructable, which is
outside this codebase's control. Failure modes: a released container that
later needs to continue can't, without resume. Operational implication:
this option is not really available until subagents/resume exist; proposing
it now would be designing around a capability the runtime doesn't have.

**C. Introduce checkpoint/resume semantics.** Correctness: best long-term
answer, but large — this is the actual feature request hiding inside "stop
holding the kernel open," not a small variant of it. Complexity: highest.
Failure modes: none new, but the project of building it is itself a
multi-phase effort. Operational implication: this is the right thing to
build *if and only if* mission durations and approval SLAs make (A)'s cost
genuinely unacceptable — which has not been measured, only estimated (98–
102s observed holds against an 900s poll budget).

**Recommendation: keep (A).** The measured cost (under two minutes, twice,
live) is real but not yet shown to be a problem worth (B) or (C)'s
complexity. Revisit only if approval SLAs in practice regularly exceed the
budget headroom — that would be a measured trigger, not a guess.

---

## 8. Architecture decision: recovery / idempotency

Evaluated exactly as asked — four points in the lifecycle of a governed
capability call, using `NotifyITHelpdesk`/`CreateChangeRequest` (real
external effects) as the concrete case, since `RunPrimeRLMAgent` itself
grants no capabilities and so cannot cause an ambiguous *external* effect on
its own.

| ADOS dies... | Outcome for the DB row | Outcome for the external system | Classification |
|---|---|---|---|
| **Before** capability execution | Row not yet created, or created and never picked up | Nothing happened | **Definite outcome.** Safe to retry unconditionally. |
| **During** capability execution | Row stuck at `pending_approval` (autonomous path, already committed) or rolled back to `pending_approval` (approval path, transaction never committed) | May or may not have happened — the HTTP call to ServiceNow is not part of the DB transaction either way | **Ambiguous outcome.** Nothing distinguishes this row from a legitimately-still-pending one. This is the review's central finding. |
| **Immediately after** external execution, before audit persistence | Same as above — this is a sub-case of "during," not a separate window, because both paths write the row's final status only *after* the connector call returns | The external record **exists** | **Definite external outcome, but ADOS does not know it.** Worse than "unknown" — it is wrong-and-confident once the row is naively read as "still pending." |
| **After** audit persistence, before the caller receives the result | Row correctly reads `executed` | Real, correctly recorded | **Safe.** The approval path's re-decision guard (409 on an already-`executed` row) protects a human who retries here. The agent-side retry case depends entirely on whether the agent supplied an idempotency key (§9 below) — and in practice it never does. |

**Can a human determine whether an external side effect happened?** Only by
the same manual method the acceptance scripts themselves already use:
independently query the external system for the provenance-tagged
`request_id`. This is a **proven methodology**, not an **automated
safeguard** — nothing in the running system does this on the row's behalf.

**Can the system distinguish "never executed" / "executed" / "unknown"?**
Not automatically, for the crash-during-execution window. The data to build
a cheap detector already exists on the row (a Tier-0 request sitting at
`pending_approval` for more than a few seconds is itself an anomaly; a
normal autonomous call resolves it inline within one request). Nothing
currently uses that signal.

**Recommendation.** Two independent, additive fixes, neither requiring the
resume feature:
1. A periodic pass — the same shape as `session_reconcile.py` — that flags
   (not resolves) any `capability_requests` row stuck at `pending_approval`
   past a short bound for an autonomous-tier request, or past the owning
   session's terminal state for an approval-tier one. Flag, don't guess:
   resolving the ambiguity for certain still requires querying the external
   system, which is capability-specific and out of this module's business.
2. Make the approval path write a durable "external call started" marker
   *before* invoking the connector, in the same transaction that currently
   only writes the result after. A crash between those two points then
   reads unambiguously as "unknown, needs external verification" instead of
   "silently re-approvable."

**Both recommendations were implemented in P9 — see §15.** Recommendation 2
became the `executing` checkpoint (both paths, not only approval);
recommendation 1 became `mark_stalled_executions_unknown` +
`reconcile_outcome_unknown`, using the row's own canonical `request_id`
rather than a flag a human still has to act on by hand. The table above is
left exactly as measured at the time — it is what motivated the fix, not a
claim about the system as it stands after §15.

---

## 9. Evidence-quality assessment

Applying the same standard this review holds ADOS's own claims to, against
the acceptance reports it inherited:

- **Live-demonstrated, and independently re-verifiable right now:** the
  governed execution chain (P6-A/B, P7-A), cross-session isolation (P6-D),
  build-identity mismatch detection at mission start (P7-B/D), orphan sweep
  against real Docker state (P7-C/D), token expiry against a real separate
  process (P7-D).
- **Unit-tested only, correctly labelled as such by the source reports:**
  rejection/timeout paths, decision-time grant re-check, most negative
  controls. No objection — these are exactly the kind of claim that should
  say TESTED rather than DEMONSTRATED, and does.
- **Single-run evidence, not yet independently reproduced by a second run:**
  every live acceptance run in this programme is one execution against one
  provider/model combination on one day. That is inherent to how expensive
  a live run is (real tickets, real containers), not a criticism, but it
  means "P6-B proved a 98.1s hold" is evidence of *one* successful hold, not
  a distribution.
- **Dependent on manual operator action, not automated:** the "was this
  ServiceNow record actually created" verification methodology (§9), the
  gateway-staleness pre-flight check outside of mission start, the Aug 9
  fossil cleanup (explicitly a one-time manual exception, correctly labelled
  as such in P7-C's own report).
- **A factual error in the existing record, found and corrected by this
  review:** `17-final-acceptance-report.md`'s P7-D regression paragraph
  states "15 deselected (8 `external` + 7 `docker`)." A direct, fresh
  `pytest --collect-only -m external` / `-m docker` run in this review
  finds **2** external-marked tests and **13** docker-marked tests —
  consistent with every *other* number in the same report (which correctly
  says "13 `docker`-marked tests in the repository pass together" one
  sentence earlier) but inconsistent with its own "7 docker" deselected
  figure. This review's own full-suite number (§1, §15) was measured
  fresh rather than copied, specifically to avoid repeating this class of
  error.
- **Vulnerable to stale environment/process state, by the programme's own
  admission:** five separate prior occurrences of exactly this (stale
  gateway process) are what motivated P7-B in the first place — itself
  good evidence that this class of risk is taken seriously here, not
  hand-waved.

---

## 10. Fresh baseline measured in this review

- **HEAD:** `d4faf37cbaf676c463fd6688a38ddeba8ef643ff` — "P7-D: operational
  hardening." Parents: `74542bfef8a83f145ad427191a24642fe6314fe0` (P7-C),
  `30b79779a25d251a319c694cc2c3015fc3aad364` (P7-B).
- **Working tree:** unrelated, uncommitted, pre-existing in-flight work is
  present (`custom_agents.division` plumbing across
  `backend/app/routers/agents_registry.py`, `db/models/custom_agent.py`,
  `docker-compose.yml`, several frontend files, one unapplied Alembic
  migration, and a set of untracked `scripts/*` files plus
  `agency-agents-repo/`). None of it was touched, staged, or attributed to
  this review's findings. No implementation code was modified in this
  phase.
- **Full test suite, run fresh, in one pass, including all Docker-marked
  tests (not run separately):**

  ```
  761 tests collected
    2 deselected  (external — ServiceNow-mutating, correctly excluded by default)
  759 passed, 0 failed
  295.41s wall clock
  ```

  Docker state independently confirmed clean before and after (only the
  five persistent compose-stack containers present; zero leaked
  `ados-rt-*`/`ados-relay-*` networks or test containers).

---

## 11. Minimum blocker set

Not "build everything in §6." The smallest change-set that would move the
verdict, per target model:

**→ Ready for controlled internal production (model A):** already close.
Two changes: ~~(1) close the approval-path double-execution window (§9,
recommendation 2 — a durable "call started" marker), since even a trusted
internal operator can double-click or retry after a crash~~ **DONE — P9,
§15**; ~~(2) fix the Postgres role, since "the audit ledger is append-only"
is a claim the product makes, not an implementation detail an internal
deployment gets to quietly skip~~ **DONE — P10, §16.1**. Model A's own
blocker list is now empty.

**→ Ready for production (model B):** model A's two items, plus: ~~(3) the
`capability_requests` reconciliation/flagging pass (§9, recommendation
1)~~ **DONE — P9, §15**; ~~(4) the build-identity guard extended onto the
capability-execution path (§5.2)~~ **DONE — P10, §16.4**; (5) minimum-viable
observability — structured logs already exist, so this is specifically
metrics + alerting, not a rebuild — **six named log-visibility gaps closed
(P10, §16.2); metrics/alerting itself still open**; ~~(6) backups~~
**mechanism DEMONSTRATED — P10, §16.3** (retention/offsite/PITR remain an
operational decision outside this repository, named not invented).
**Resume/heartbeats/subagents/scheduling are explicitly not on this list.**
They are real future functionality, not blockers: nothing in B's definition
requires a crashed mission to continue rather than restart, only that a
crash not silently corrupt or duplicate the audit trail — which is what
items 1 and 3 actually fixed. Model B's remaining blocker is metrics/
alerting alone.

**→ Ready for a distributed/multi-tenant platform (model C):** everything
above, plus admission control/rate limiting, a multi-host-aware ownership
model for Docker resources (the current design assumes one shared daemon),
and a tenancy concept that does not exist in the schema today. This is a
substantially larger effort than B and should be scoped as its own phase,
not folded into "harden what exists."

---

## 12. Acceptable limitations (explicitly, not by omission)

For model A specifically: single process, no resume, no heartbeats, no
subagents, no scheduling, interval-based (not instant) sweep, the
NULL-expiry fossil rows staying stale forever, no rate limiting, and the
kernel-held approval design (§7) are all **ACCEPTABLE OUT-OF-SCOPE** as
built. None of these were "supposed to" be fixed by this point in the
programme, and treating them as defects would be grading against a target
nobody set.

---

## 13. Recommended next phase

Not a rebuild. A narrowly-scoped P9 covering exactly the four §11 items for
model B — reconciliation/flagging for `capability_requests`, the durable
approval-write-ordering fix, the drift guard's extension onto the capability
path, and minimum-viable metrics/alerting — each with the same discipline
this programme has used throughout: survey first, smallest safe change,
negative controls, live verification where a live verification is possible
without manufacturing unnecessary external side effects. Postgres role and
backups are infrastructure/ops work, not application code, and can proceed
in parallel.

---

## 14. Final verdict

**NOT READY.**

Not because the engineering is weak — the governed execution path is
genuinely proven, live, against real state, repeatedly, and the operational
hardening in P7-B/C/D closed three real hazards for real. It is not ready
because this review found two concrete, evidence-based paths to a **silent
double execution of a real external side effect** (§9), and because the one
mechanism designed to prevent exactly that (the idempotency key) is not
reachable from the only caller that would ever need it (§9, §6F). A system
whose entire pitch is "a governed, audited hand for an AI agent" cannot
carry an unresolved case where the audit trail and reality can disagree
without anyone finding out except by manually checking the external system
— which is precisely the failure mode this integration's own acceptance
methodology was built to catch everywhere else.

For **model A** (controlled internal, a human actually watching), the gap
is real but survivable — the two-item minimum blocker set in §11 is small
and specific, not a re-architecture.

For **model B or C**, this is a genuine blocker, not a hardening
nice-to-have, and should be treated as such before any unattended
production traffic touches it.

*(True as of P8. P9 (§15) closes the double-execution finding specifically;
P10 (§16) closes the Postgres role, the capability-path build-identity gap,
backups, six named observability gaps, and a NULL-expiry approval exposure
P9's own re-derivation had not actually tested. This section is left as
the point-in-time record of what P8 itself established — §16 carries the
final, current verdict.)*

---

## 15. P9 update: External Side-Effect / Exactly-Once Hardening (2026-08-12)

Closes this report's own central finding (§5.7, §8, §14): a real external
side effect could succeed, ADOS could crash before recording it, and the
request could return to an apparently-executable state — a real,
demonstrated path to a silent duplicate.

**Baseline:** `d4faf37` (HEAD at the start of P8/P9), plus `3813ced` (the P8
report commit). **P9 commit:** `6e5ef45` — "P9: external side-effect /
exactly-once hardening."

### What changed

1. **A durable `executing` checkpoint**, written and committed BEFORE any
   external call, in both writers of `capability_requests`
   (`mcp_gateway.py`'s autonomous path and `runtime_approvals.py`'s human
   approval path). This is the fix: `pending_approval` and "a decision to
   act was made" are now mutually exclusive from that commit onward,
   independent of what happens next — including the process dying.
   `orchestrate/runtime/capability_execution.py`.
2. **A terminal-with-respect-to-automatic-execution `outcome_unknown`
   state.** A row stuck `executing` past a stall bound (default 60s,
   generous against every real ServiceNow call latency measured in this
   programme), or a connector reporting `CallStatus.UNKNOWN` directly, both
   land here. Nothing in this codebase transitions it back to something
   executable without an intervening reconciliation that finds positive
   proof. `orchestrate/runtime/capability_reconcile.py`.
3. **ServiceNow's Table API confirmed to have no native idempotency
   mechanism** (no dedup header, no upsert-by-key — a POST always inserts).
   `ServiceNowConnector.execute()` now distinguishes transport errors that
   prove the request never reached the server (`FAILED`, safe to retry) from
   ones where it may have (`CallStatus.UNKNOWN` — the "may already have
   happened, do not guess" case `contracts/capabilities.py` already reserved
   this value for, unused until now).
4. **Idempotency made real, not reachable.** The old caller-supplied
   `idempotency_key` parameter is gone — nothing reachable from a real
   mission ever set one (the exact P8 finding). Replaced with a canonical
   key `mcp_gateway.py` computes itself, server-side, from
   (session, capability, real arguments) — automatic on every call, nothing
   for a model to remember or invent. A genuine concurrent race for the same
   key is resolved by a real database constraint
   (`uq_capability_requests_session_idempotency`, alembic `d1e2f3a4b5c6`),
   not by hoping the application-level check never loses a race.
5. **Reconciliation, keyed only on the row's own canonical `request_id`.**
   `reconcile_outcome_unknown` searches the capability's mapped ServiceNow
   table for a record containing that exact id — never agent-authored text
   — and resolves to `executed` only on a positive match. No match, or a
   query that could not be answered, leaves the row exactly where it was.
   Manual CLI: `scripts/reconcile_capability_requests.py` (deliberately not
   auto-scheduled — see that script's own docstring for why this is a
   deliberate, narrow scope decision, not an oversight).

### The critical proof — real ServiceNow, not mocked

`scripts/p9_crash_recovery_e2e.py`. A Tier 2 `NotifyITHelpdesk` request was
approved; the approval's own `_execute_capability` call was wrapped so the
REAL ServiceNow POST still ran (a real incident, `INC0010029`, sys_id
`edc436478366cb10be487765eeaad390`) and only then raised, before the row's
final commit — exactly the crash window this phase exists to close.

```
DURABLY EXECUTING   request 74493a0b-…  — not reset to pending_approval
REAL RECORD EXISTS  INC0010029          — ADOS's own row does not know this yet
RETRY REFUSED       HTTP 409            — before any reconciliation ran
OUTCOME_UNKNOWN      (after stall detection)
RECONCILED           resolved via existing record INC0010029
```

Independently re-verified OUTSIDE the script's own process: a fresh `psql`
query against Postgres showed `status=executed`, `result.reconciled_match`
naming `INC0010029`; a fresh, separate Python process's `ServiceNowConnector
.fetch_record()` call independently confirmed the same record, `state=7`,
description containing the exact `request_id`. Exactly one real record
existed for the entire run (`external_record_count: 1`); it was closed
(`state=7`) and a final sweep confirmed zero open marked records remained.

**External side effects:** one real ServiceNow incident, created, resolved,
independently verified, and closed. No other live external writes this
phase.

### Tests and negative controls

41 new tests across four files (`test_capability_execution_state.py` 14,
`test_capability_reconcile.py` 10, `test_approval_crash_recovery.py` 6,
`test_ados_skill_run_capability.py` 11), plus one pre-existing test's error
-message assertion updated to match the new, more precise FAILED-vs-UNKNOWN
wording (`test_notify_it_helpdesk_servicenow.py` — its own protection,
"a transport error is a failure not a success," was never weakened, and a
new sibling test now separately pins the UNKNOWN case it used to conflate).

6 negative controls, each: guard disabled in real source, targeted test(s)
confirmed to fail, guard restored, `shasum -a 256` confirmed byte-identical
before and after.

| # | Guard disabled | Targeted result |
|---|---|---|
| 1 | `_load_pending_or_404`'s "must be exactly `pending_approval`" check | 5 tests failed: the 3 new executing/outcome_unknown/reconciled refusal tests, plus 2 pre-existing P6 double-approval regression tests |
| 2 | Reconciliation's `_record_matches_this_row` re-verification | 1 targeted test failed (a record merely returned by ServiceNow's own substring query resolved the row without actually containing its id) |
| 3 | The database unique index itself (dropped directly in Postgres, migration file untouched) | The real concurrency test created 2 real "ServiceNow" calls for one logical request — the exact duplicate this index exists to prevent |
| 4 | Canonical key's exclusion of `_`-prefixed governance hints | 2 targeted tests failed (two calls disagreeing only on claimed cost stopped deduping) |
| 5 | The removed `idempotency_key` skill parameter (re-added) | 1 targeted test failed (a caller could once again pass an explicit, substitutable key) |
| 6 | Stall-detection's time comparison | 3 tests failed, including the critical crash-recovery proof test itself |

### Regression

Full suite, fresh, one pass, all Docker-marked tests included: measured
immediately after P9's changes — see the final P9 report for the exact
passed/deselected counts. One pre-existing test required an update (its
assertion depended on FAILED's exact wording, which P9 deliberately changed
to distinguish two cases that string used to conflate) — not a weakened
guard, confirmed by the new sibling test that pins the case it used to miss.

### What this does and does not mean

**"Exactly once" is not literally true** — ServiceNow itself cannot provide
that guarantee (§ above). What is true: ADOS never *automatically* creates a
second real record for the same logical request, in any of the crash
windows this phase modeled. The `outcome_unknown` state is where "exactly
once" becomes "at-least-once-detected, reconciled without duplication, or
flagged for a human" — the safe-ambiguity design the P9 instructions asked
for in place of a guarantee ServiceNow cannot back.

**Still open, honestly:**
- The NULL-expiry (pre-P6-D) row shape remains out of scope, unchanged.
- Reconciliation is manual (a CLI), not scheduled — an `outcome_unknown` row
  is safe (never auto-retried) but not automatically resolved until an
  operator runs it.
- The build-identity drift guard still does not cover the capability-
  execution path (§5.2) — unrelated to this phase's scope, still open.
- A capability with no ServiceNow table mapping has no automated
  reconciliation path at all; it can only ever be resolved by a human.

### Updated verdict

The P8 blocker — silent double execution of a real external side effect —
is **CLOSED**, proven against real ServiceNow state, not merely designed.
This does not change the overall production-readiness verdict from §14 to
"ready": the remaining §11 items for model B (build-identity coverage,
observability, backups, Postgres role) are unaffected by this phase and
remain open by design — P9 was scoped narrowly, per its own instructions,
to exactly the finding named above. For **model A**, the minimum blocker
set is now down to one item (the Postgres role). For **model B/C**, this
was the load-bearing blocker; what remains is real but no longer of the
same severity — see the final P9 report for the complete, explicit
category-by-category answer.

---

## 16. P10 update: Production Readiness Blockers (2026-08-12)

Closes or narrows six of §11's remaining items for models A/B: the Postgres
role, the build-identity gap on the capability path (§5.2), minimum
operator observability, backups, and a re-derivation of reconciliation
safety and the NULL-expiry row shape (§5.6) that found the prior report's
own "three, closed, non-growing" claim was no longer accurate. **Baseline:**
`e0c5521` (HEAD at the start of P10, the P9-doc follow-up commit).

### 1. Postgres role — DEMONSTRATED

The shipped compose stack's `backend` service used the same role
(`ados`, from `POSTGRES_USER`) that `migrate` uses to run DDL — a Postgres
superuser, which (§4A) "voids the append-only guarantee on the approval
ledger." Alembic revision `f4a5b6c7d8e9` provisions `ados_app`: a
non-superuser role with ordinary DML across the schema (the backend
genuinely needs that outside the Prime Agent tables too — MOA breaker
store, LLM provider settings — restricting further would have broken real
features) but no CREATE on the schema, and no ownership of any table, so
DDL is refused by ownership rules alone. `DELETE` is explicitly revoked on
the three tables that are this integration's actual audit spine
(`missions`, `runtime_sessions`, `capability_requests` — grep-verified, no
reviewed code path deletes a row from any of them) and on
`capability_promotion_events`, completing revision `7f551a8ccce0`'s own
documented, previously-inert intent ("becomes real the moment a
non-superuser application role exists").

`docker-compose.yml`'s `backend` service now connects as `ados_app`.
Discovered along the way: the LangGraph checkpointer's own `.setup()` (DDL,
not an Alembic revision) was running from the app's lifespan — which no
longer has CREATE privilege. Moved to run once, under the superuser, from
`alembic/env.py`'s online migration path instead — the same fix shape,
applied to the one other place schema DDL happens in this codebase.

**Live evidence:** the real `ados-backend-1` container was rebuilt and
restarted against `ados_app` and came up healthy (`/healthz` 200) — not
merely unit-tested. `backend/tests/test_database_role_privileges.py` (12
tests): `ados_app` cannot `CREATE`/`ALTER`/`DROP`/`TRUNCATE`; cannot
`DELETE` from the three audit tables or `UPDATE`/`DELETE`
`capability_promotion_events`; legitimate DML on the audit tables and
`DELETE` on an unrelated table (`moa_task_breakers`) both still work.
Negative control: re-granted `DELETE` on `capability_requests` directly in
Postgres, confirmed the targeted test failed, revoked it back, confirmed
byte-identical migration source throughout (the control was a live grant,
not a source edit, so the invariant checked is "database state matches the
migration," verified before and after).

The bare-`.venv` workflow's default (`backend/app/config.py`) is
unchanged — it still defaults to the `ados` superuser unless `DATABASE_URL`
is exported — a documented, deliberate simplicity trade-off for that path,
not an oversight; the compose path is what actually ships the fix.

### 2. Observability — TESTED (six named gaps), Metrics/alerting still NOT BUILT

Re-reading (not trusting) the P8 claim that logging was "DEMONSTRATED"
found five of the six operator-visibility moments named by this phase had
no log line at all: a mission starting, a capability parking for approval,
an execution landing at `outcome_unknown`, a reconciliation pass
completing, and a build-identity mismatch (`orphan discovered/cleaned` was
already logged, correctly, from `main.py`'s periodic loop — confirmed by
reading it, not touched). One structured log line was added at each,
through the existing `JsonLogFormatter`/request-id-correlation machinery
(`observability.py`, unchanged) — never the arguments, tokens, or raw
connector payloads.

`backend/tests/test_observability_logging.py`: one test proves each new
line actually fires with the field an alert would key on (not vacuous —
disabling the `outcome_unknown` line was used as this area's negative
control and the targeted assertion failed as expected, then the line was
restored, byte-identical); a second test runs a realistic mixed pass
(park → connector failure → reconciliation → stale build) through the
*real* `JsonLogFormatter` and asserts a distinctive bearer token and a
distinctive ServiceNow password never appear in any rendered line.

**Still open, unaffected by this:** this phase closed exactly the six named
log-visibility gaps, not §6's separate "Metrics/alerting" blocker.
`observability.py` still deliberately declines a `/metrics` endpoint ("no
scraper to serve") — that remains **NOT BUILT**, as it was.

### 3. Backups/restore — DEMONSTRATED (mechanism), documented gaps

P8: "No backup/restore tooling found for Postgres; compose uses a bare
named volume" — durability is not a backup. `scripts/backup_postgres.sh` /
`scripts/restore_postgres.sh` are the smallest mechanism this repository
can actually own: `pg_dump`/`pg_restore` through the real, already-running
Postgres container's own bundled tools (no invented infrastructure, no new
dependency). `restore_postgres.sh` requires an explicit target database
with no default, specifically so it cannot silently overwrite the live
database by falling through to one.

**Live evidence:** `backend/tests/test_backup_restore.py` (`docker`-marked,
3 tests), run against the real container: a marker row survives a real
dump → restore into an independent, disposable scratch database,
independently re-queried against the scratch DB rather than assumed; a
second test restores two different dumps in sequence into the same scratch
database and confirms the first restore's row is gone after the second —
`--clean` really replaces, not merges. Negative control: removed `--clean
--if-exists` from the restore script, the replace test failed (the second
`pg_restore` errored outright trying to recreate already-existing objects),
restored, byte-identical hash confirmed.

**Explicitly not built, and not pretended:** point-in-time recovery (WAL
archiving), offsite/off-host storage, a retention policy, and a restore
rehearsal cadence are operational decisions for whoever runs this in
production — named as an explicit dependency, not invented here.

### 4. Build-identity guard on the capability path — TESTED, same inherited limitation as §5.2's origin

`verify_no_drift_since_process_start()` is now called at the top of
`_execute_capability` (`backend/app/mcp_gateway.py`) — the single choke
point both the autonomous and human-approval paths call through — closing
the gap §5.2 named: a commit landing mid-mission was never re-checked for
that mission's remaining capability calls. Raises the same
`StaleGatewayError`, caught by the same pre-existing `except Exception`,
refusing before `default_hub().invoke()` — before any connector, and
therefore any external side effect, is reached.

`backend/tests/test_capability_path_build_identity.py` (3 tests): a stale
build refuses with a stub hub that fails the test if ever reached (proving
zero connector contact, not just a returned error); a matching build
proceeds exactly once; the real repository right now passes with no
mocking. Negative control: commented out the one added call, confirmed the
stale-build test failed with the connector actually being reached, restored,
byte-identical.

**Inherited, not new:** confirmed live (§1 above) that the actual shipped
Docker image reports `commit: "unknown"` (no `.git` in the build context,
by the existing `.dockerignore` design) — meaning this guard, like the
P7-B/D one it extends, is a no-op inside the container as shipped today,
and only real for a bare-`.venv`/uvicorn-without-`--reload` deployment.
This is the same limitation `test_drift_check_is_a_no_op_when_the_frozen_
identity_is_unknown` already documented for the original guard, not a
regression introduced here.

### 5. Reconciliation operational safety — CONFIRMED, no changes required

Re-read `orchestrate/runtime/capability_reconcile.py` and its P9 tests
against each specific P10 requirement rather than assuming they still
held: not auto-scheduled (confirmed — still only reachable via
`scripts/reconcile_capability_requests.py`, unchanged); `outcome_unknown`
transitions only to `executed`, only on a positive match
(`test_a_matching_external_record_resolves_the_row_to_executed`) and never
back to something executable on a negative or unanswerable one
(`test_no_match_leaves_the_row_at_outcome_unknown_but_records_the_attempt`,
`test_a_query_that_could_not_be_answered_is_not_treated_as_a_negative_
answer`); forged/unrelated provenance cannot hijack it
(`test_a_forged_agent_authored_provenance_block_cannot_hijack_
reconciliation`); `mark_stalled_executions_unknown` has exactly one status
write in its source (`STATUS_OUTCOME_UNKNOWN`) and every existing test
asserting its outcome asserts that exact value, which a mistaken write of
`failed`/`executed` would already fail. No gap found; no code or new tests
were needed here.

### 6. NULL-expiry / legacy session state — the count was wrong; now closed for future risk

§5.6 and P9 §15 both describe "three... pre-P6-D... fossil rows,"
"closed, non-growing." Re-deriving from the live dev database (not
trusting that count) found **31** rows with `token_expires_at IS NULL`, 17
non-terminal — and, critically, **one created after P6-D shipped**
(2026-08-11, title `"P9 crash/recovery"`), because `scripts/p9_crash_
recovery_e2e.py` — P9's own tooling — constructed `RuntimeSessionRow`
directly, bypassing the real creation path, without setting
`token_expires_at`, unlike its sibling e2e scripts which deliberately do.
The category was not closed; P9's own script was quietly reopening it.
Fixed: the script now sets `token_expires_at` identically to its siblings.

More seriously: two of the pre-existing (2026-08-09, genuinely dev-era —
mission titles "Synthetic incident investigation") fossil rows had
`pending_approval` capability requests still sitting **live-approvable**
through the real, unmodified `/runtime/capability-requests/{id}/approve`
endpoint right now — `_live_session_or_409` only checks `state`, and the
fossil session's `state` was `running`. Approving either would have created
a real ServiceNow incident for a mission with no runtime behind it. Closed
via the existing, safe `reject` endpoint (no raw SQL, no reinterpretation
of the session row's own `state`/`token_expires_at`) — the same pattern
P7-C's own one-time manual exception used.

**The general class, not just today's two rows:** `runtime_approvals.py`
gained `_confirm_token_expiry_recorded_or_409`, called only from
`approve_capability_request` (never from `reject`, which has no side
effect and must remain the way to safely close a stale request tied to
exactly this kind of row). Every session the real creation path
(`integrations/connectors/prime_runtime.py`) writes has set
`token_expires_at` unconditionally since P6-D — a NULL is proof this row
did not come from a currently-live mission, independent of `state`.
`backend/tests/test_approval_crash_recovery.py::test_a_null_expiry_
session_cannot_authorize_approval`: constructs the exact fossil shape,
confirms approval is refused (409) and reject still succeeds. Negative
control: commented out the one added call, confirmed a real ServiceNow
POST (201) actually fired for the fossil session's request, restored,
byte-identical.

**What is still, deliberately, unchanged:** the session rows themselves —
`state`, `token_expires_at` — were not mutated or reinterpreted; §5.6's
original reasoning (no deterministic abandonment signal exists for a row
that was never given an expiry, so building a second, guessing
reconciliation mechanism would be effort spent on the wrong thing) still
holds and is not revisited here. What changed is narrower and stronger:
these rows can no longer authorize a new external side effect through
approval, regardless of how long they sit there or what `state` claims.

### 7. Production-readiness matrix — this section, plus updates below

Every item below is classified DEMONSTRATED / TESTED / DESIGNED-PARTIAL /
NOT BUILT / OPEN DEFECT, distinguishing live evidence from unit/mock
evidence, per this section's own numbered findings:

| §11 item | State before P10 | State after P10 | Evidence |
|---|---|---|---|
| Postgres non-superuser role | Absent | **DEMONSTRATED** | §16.1 — real container rebuilt/restarted under the role, 12 tests, 1 negative control |
| Build-identity guard (capability path) | Absent | **TESTED** | §16.4 — no-op inside the shipped image, same as the guard it extends; real for bare-`.venv` |
| Minimum-viable observability (6 named gaps) | Absent | **TESTED** | §16.2 — structured logs; Metrics/alerting (the separate, broader §6 item) unaffected, still NOT BUILT |
| Backups/restore | Absent | **DEMONSTRATED** (mechanism) | §16.3 — real round trip, `docker`-marked; retention/offsite/PITR explicitly out of scope |
| `capability_requests` reconciliation safety | Closed (P9) | **CONFIRMED**, unchanged | §16.5 — re-verified against every P10 sub-requirement, no gap found |
| NULL-expiry / legacy session rows | Believed closed (3, non-growing) | **CORRECTED + narrowed** | §16.6 — was actually 31 and growing (via P9's own script); script fixed, 2 live exposures closed, general class closed via a new approval-time guard; the rows themselves remain untouched, undecided legacy state by design |

None of the §11 items outside this list (metrics/alerting beyond the six
log lines, session resume, heartbeats, scheduling, subagents,
multi-tenancy, the kernel-held approval architecture, Docker socket
exposure, JWT-in-localStorage) were in scope for P10 and remain exactly as
§6/§11 described them.

### Regression

806 passed, 0 failed, 18 deselected (2 `external` + 16 `docker` — 13
pre-existing + 3 new backup/restore tests), one full pass, immediately
after P10's changes. Two pre-existing test fixtures required updates
(`test_capability_request_provenance.py`, `test_runtime_approval_round_
trip.py`, alongside `test_approval_crash_recovery.py`'s own new test) —
each constructed a `RuntimeSessionRow` without a token expiry, which is
now what the new approval-time guard correctly refuses; each was updated
to set one identically to the real creation path, not to weaken the guard.

### Updated verdict

Of §11's model-B minimum blocker set, this phase closes the Postgres role
and the six named observability gaps, demonstrates a real backup/restore
mechanism, closes the build-identity gap on the capability path (with the
same shipped-image caveat the original guard already carried), confirms
reconciliation safety was already sound, and corrects and closes a
NULL-expiry exposure this phase's own re-derivation found — one neither P8
nor P9 had actually tested, only asserted. See §17 (final P10 report) for
the complete PASS/NOT READY determination and every remaining honest gap.

---

## 17. P11 update: Controlled Internal Production Operationalization (2026-08-12)

Closes the two items §6/§11 named as the last of Model B's minimum blocker
set after P10 — "Metrics/alerting" and "Rate limiting / admission control"
— and adds the operator runbook and a live recovery exercise §4D/§11 had
also flagged missing. **Baseline:** `7381122` (P10's own commit).

Full evidence ledger, exact commands, and the DEMONSTRATED/TESTED/
CONFIRMED/DESIGNED-PARTIAL/NOT BUILT/OPEN DEFECT classification for every
item is in
[21-p11-acceptance-report.md](21-p11-acceptance-report.md); this section is
the summary that belongs in the running readiness record.

### 1. Metrics and alerting — TESTED (emission), designed contract (delivery not built)

`backend/app/metrics.py` (`prometheus_client`, a new but tiny dependency —
no server component) + `GET /metrics`
(`backend/app/routers/metrics.py`), exporting 17 metric families covering
every signal this phase's own instructions named: missions started/
completed, capability executions + duration, admission rejections, approval
queue depth/age, `outcome_unknown` count/age, reconciliation success/
failure, orphan discovery/cleanup, authentication failures, authorization
denials, build-identity drift refusals, token-expiry refusals. Every label
is a fixed, closed enum (a `Capability` name or a hand-enumerated outcome/
result/reason/gate string) — never a request/mission/session id, token, or
agent-authored free text, proven by
`backend/tests/test_metrics.py::test_no_sensitive_or_high_cardinality_data_in_metrics`
(a realistic pass carrying a real token, a fake ServiceNow password, and
distinct UUIDs/free text, then asserting none of them appear in
`GET /metrics`'s output). One test per metric proves it fires at the exact
lifecycle point it claims, by delta (the registry is process-global across
the whole pytest session — every assertion reads before/after and checks
the difference, never an absolute value).

**Full detail, the metric catalog, and the alerting contract:**
[19-metrics-and-alerting.md](19-metrics-and-alerting.md). **Explicitly not
built:** a Prometheus server, Alertmanager, or any paging/notification path
— this repository runs no monitoring stack of its own. The alerting
contract is a specification for an operator's own Prometheus + Alertmanager
to consume against the `/metrics` scrape target; it is not a claim that
alert delivery exists. Reversing `observability.py`'s original "no
scraper to serve" decision is the explicit revisit its own docstring called
for, updated in the same commit.

### 2. Rate limiting / admission control — TESTED (real Postgres/asyncio concurrency, one docker-marked proof)

Zero admission control existed before this phase (confirmed: the only
concurrency primitive anywhere was `orchestrate/agent_runner.py`'s single
`asyncio.Lock`, a correctness lock for two agents' shared mutable state, not
a resource ceiling — §6/§11's own finding, re-confirmed). Four gates added,
all server-side only (nothing in `CapabilityCall.input` is ever consulted):

* **Mission concurrency** (`max_concurrent_prime_missions`, default 3) and
  **capability-execution concurrency** (`max_concurrent_capability_
  executions`, default 10) — both at `IntegrationHub.invoke()`, the one
  place every capability call in the system reaches a connector (mission-
  starting `RunPrimeRLMAgent` calls **and** in-mission `mcp_gateway`-
  originated calls alike — a stronger choke point than `mcp_gateway.
  _execute_capability`, which only sees the second category).
  `integrations/admission_control.py::AdmissionControl` — synchronous,
  no-`await` check-then-increment, per-`IntegrationHub`-instance (not a
  module singleton, deliberately: ~800 tests each construct their own hub).
* **Approval-queue depth** (`max_pending_approvals`, default 50) and
  **per-session activity** (`max_capability_requests_per_session`, default
  200) — both in `backend/app/mcp_gateway.py::request_capability`, real
  Postgres transactional serialization (a `pg_advisory_xact_lock` for the
  queue-depth COUNT, a `SELECT ... FOR UPDATE` row lock reusing the
  existing `RuntimeSessionRow.capability_request_count` column for
  per-session activity).

**Critical invariant, proven not asserted:** a rejected request never
reaches a connector. `test_integration_hub_admission.py` proves this with a
real concurrent race (`asyncio.gather`, a fake connector holding its slot
open on an `asyncio.Event`) — peak-concurrent connector executions never
exceeds the configured limit, and a rejected call's `execute()` count stays
at zero. A **docker-marked** variant
(`test_admission_control_docker.py`) proves the same for the real
`PrimeRuntimeConnector`: a second concurrent mission attempt is refused
*before* `PrimeAgentRuntime.start()` — an actual `docker run` — ever runs
for it, verified by an independent `docker ps` count, not by trusting the
connector's own return value.

**Two real concurrency bugs found and fixed while building the two
Postgres-backed gates** (both caught only by the concurrent-race tests
asserting an *exact* admitted count against real Postgres, not by a
below/at/over-limit test run sequentially): a SQLAlchemy identity-map
gotcha (`select().with_for_update()` silently returned an already-loaded,
stale Python object rather than the freshly locked row — fixed with
`.execution_options(populate_existing=True)`), and an autoflush ordering
bug (counting `pending_approval` rows *after* `db.add()`'d this request's
own not-yet-committed row counted it against itself — fixed by moving the
check before the row is constructed). Both are written up in
[14-known-limitations.md](14-known-limitations.md)'s new Operations
section for anyone touching a similar `FOR UPDATE`/autoflush pattern later.

**Scope boundary, explicit:** single-process, in-memory-for-the-hot-path
(the two `IntegrationHub` gates) or Postgres-transaction-serialized (the
two `mcp_gateway` gates). This bounds one ADOS process, matching Model A's
single-process envelope (§5 below) — not a distributed rate limiter, and
building one would be over-building for an architecture with no second
process to coordinate with.

### 3. Operator runbook — DESIGNED, one scenario DEMONSTRATED live

[20-operator-runbook.md](20-operator-runbook.md) — the first formal runbook
for this integration (§4D's own prior finding: only scattered scripts and
this limitations doc functioning informally). Covers all fourteen scenarios
this phase's instructions named: Docker/engine unavailable, gateway stale/
build mismatch, gateway unhealthy, mission failure, stuck approval,
`outcome_unknown`, reconciliation, orphaned resources, token/session
expiry, unexpected ServiceNow records, Postgres backup/restore, database
recovery, admission-control rejection, metrics/alert interpretation. Each
entry: symptom / verify / remediation / do-NOT / independent verification.
No credentials or secrets anywhere in it. Built entirely from
already-existing operator tools (`scripts/sweep_orphans.py`, `scripts/
reconcile_capability_requests.py`, `scripts/backup_postgres.sh`/
`restore_postgres.sh`, `scripts/reset_user_password.py`) plus the new
`/metrics` endpoint — no new operator commands invented.

### 4. Recovery exercise — DEMONSTRATED, real Docker + real Postgres, no ServiceNow

`scripts/p11_orphan_recovery_exercise.py` — the complete operator loop this
phase's instructions asked for, against real infrastructure throughout:

1. **Failure**: a real Prime Agent container starts for real (`docker run`,
   a real per-session egress boundary), then the script simply stops
   before teardown — exactly what a real SIGKILL/OOM kill mid-mission
   leaves behind: a real, detached, orphaned container and two real
   networks.
2. **Detection**: `session_reconcile.reconcile_abandoned_sessions()` — the
   exact function `backend/app/main.py`'s periodic loop calls — marks the
   session `failed` with an orphan-bearing `failure_reason`.
3. **Diagnosis**: an independent `docker ps`/`docker network ls`/`docker
   inspect` confirms the flagged resources are real and carry this
   session's own `ados.session_id` label.
4. **Remediation**: `orphan_sweep.sweep_once()` — the exact function
   `scripts/sweep_orphans.py` wraps — issues real `docker rm -f`/`docker
   network rm` calls.
5. **Independent verification**: a *fresh* `docker ps`/`docker network ls`
   (not the sweep's own reported outcome) confirms zero resources remain;
   the session's own durable `events` column shows five real
   `orphan_sweep.cleaned` entries (container, relay, two networks,
   workspace).

Real effect: one real, local Docker container/network set, created and
fully torn down by the exercise itself — nothing external, nothing left
behind, independently confirmed clean (`docker ps -a` shows only the five
persistent compose-stack containers before and after). Chose this scenario
over repeating P9's own real-ServiceNow crash-recovery proof specifically
because it needs no external side effect to demonstrate the full loop —
matching this phase's own bar for when ServiceNow use is "genuinely
necessary" (it wasn't, here).

### 5. Production constraints — Model A envelope, stated explicitly

Single ADOS process; controlled, known internal users (no multi-tenant
isolation claim); bounded concurrency via the four new admission-control
gates (3 missions / 10 capability executions / 50 pending approvals / 200
requests-per-session by default, every one operator-tunable via `Settings`);
manual/operator-assisted recovery for crash scenarios (reconciliation and
sweep are either periodic-automatic or hand-run — never "the system heals
itself" without a human able to inspect what happened); no resume-after-
process-death claim; no heartbeat claim; no scheduling/subagent claim. These
match §5/§12's own prior "acceptable out-of-scope for Model A" list exactly
— P11 did not change what Model A does or doesn't claim, only made
operating within it observable and bounded.

### 6. An unrelated, real defect found incidentally while gathering acceptance evidence

Running the full default suite as P11's own acceptance evidence surfaced a
real, pre-existing, unrelated issue: `tests/test_phase3_cross_integration.py`
(Phase 3, predates this integration) had been silently creating real
ServiceNow Change Requests on every full-suite run for a long time (42+/41+
pre-existing tagged records found on the configured dev instance) because
it never mocks its `ServiceNowConnector` transport. Not caused by P11 —
found because P11's evidence-gathering discipline runs the real full suite
and greps its own httpx logs rather than trusting "0 failed" alone. Fixed
(the test now mocks ServiceNow, matching every other test file that can
reach it) and the two records this session's own runs created were closed
and independently re-verified; the 42+/41+ pre-existing records were
deliberately left untouched — not this phase's defect to bulk-remediate.
Full account in [14-known-limitations.md](14-known-limitations.md)'s
Operations section.

### 7. Regression

Three full, clean `pytest -q` runs after all changes (one immediately after
the ServiceNow-mock fix, one after the full negative-control cycle, one
final confirmation): **847 passed, 0 failed, 19 deselected** (2 `external` +
17 `docker` — 16 pre-existing + 1 new mission-concurrency docker test) each
time. Baseline was 806 passed / 18 deselected (824 total, P10 §16); P11 adds
42 new tests (824 + 42 = 866 = 847 + 19, reconciled exactly). All 17
`docker`-marked tests pass together; Docker state independently confirmed
clean before and after (only the five persistent compose-stack containers;
zero leaked `ados-rt-*`/`ados-relay-*`/`ados-prime-*` networks or
containers).

Two isolated, transient test failures were observed across the several full
runs this phase's evidence-gathering required, **both confirmed non-
regressions by an isolated rerun, neither touching any file this phase
modified**: `test_capability_onboarding.py`'s real-Docker-build test failed
once immediately after Docker Desktop was freshly started (a base-image
pull `DeadlineExceeded` — Docker's own networking still stabilizing),
passed cleanly on rerun; `tests/test_orchestrate.py`'s tier-1-approval test
(pre-existing, tight `asyncio.wait_for(..., timeout=5)`) failed once during
a run immediately following several other full-suite executions in a row,
passed cleanly (4.33s of its 5s budget) on rerun. Neither is claimed as
part of the "847 passed" headline number — both are reported here for
completeness, with their isolated-pass evidence, rather than silently
re-run until clean.

### 8. Negative controls

Seven, each: guard/hook disabled directly in real source (a `False and`
short-circuit, or the metric call commented out), targeted test(s) run and
confirmed to fail for the expected reason, guard restored, `shasum -a 256`
confirmed byte-identical before and after.

| # | Guard/hook disabled | File | Targeted result |
|---|---|---|---|
| 1 | Capability-concurrency admission check | `integrations/hub.py` | Real concurrent-race test: peak concurrent connector executions hit 10 against a configured limit of 3 |
| 2 | Mission-concurrency admission check | `integrations/hub.py` | Targeted test hung/timed out: the second mission was admitted and blocked on the same shared connector instead of being refused |
| 3 | Approval-queue-depth check | `backend/app/mcp_gateway.py` | Both targeted tests failed: 8/8 concurrent parks admitted against a real-Postgres-enforced limit of 3 |
| 4 | Per-session activity check | `backend/app/mcp_gateway.py` | Both targeted tests failed: 6/6 concurrent requests admitted against a real-Postgres-enforced limit of 2 |
| 5 | `ados_build_identity_drift_refusals_total` increment | `orchestrate/runtime/build_identity.py` | Targeted metric test failed: counter did not move on a real drift refusal |
| 6 | `ados_authentication_failures_total` increment | `backend/app/routers/auth.py` | Targeted metric test failed: counter did not move on a real login failure |
| 7 | `ados_orphan_discovered_total`/`ados_orphan_cleanup_total` increments | `orchestrate/runtime/orphan_sweep.py` | Targeted metric test failed: counters did not move on a real (3-candidate) sweep |

All seven files verified `shasum -a 256` byte-identical to their pre-control
state after restoration.

### 9. Updated verdict

Of §11's model-B minimum blocker set as last stated by P10 ("Model B's
remaining blocker is metrics/alerting alone," with §6's own matrix
separately flagging rate limiting "Yes, for B/C"), P11 closes both items
P10 actually named. This is reported narrowly: every P10-named Model-B
blocker is now closed; this is **not** a fresh, independently-derived
"Model B: READY" verdict — P11's mandate was the six operational gaps
listed in its own instructions, not a full re-audit of Model B's entire
envelope (session resume/heartbeat necessity, single-process implications,
etc. were not re-examined here). **Model C** remains **NOT READY**,
unaffected by this phase by explicit instruction: multi-host Docker
ownership, a tenancy concept, and distributed rate limiting are all still
`NOT BUILT`, and building them was explicitly out of scope.

For **Model A** specifically — the target decision this phase was actually
scoped to answer — see [21-p11-acceptance-report.md](21-p11-acceptance-report.md)'s
final section for the complete verdict and its supporting evidence.

---

## 18. P12 update: Production Operational Hardening — Model B Readiness (2026-08-13)

Targets Model B directly, per its own instructions: distributed admission
control, process crash recovery, automatic reconciliation, rate limiting,
Docker resource ownership, and a fresh re-derivation of every claim this
document and doc 21 made about them — not trusted from either. **Baseline:**
`7464902` (P11's own commit). Full evidence ledger, exact commands, and
every negative control's before/after hash in
[23-p12-production-operationalization.md](23-p12-production-operationalization.md);
this section is the summary that belongs in the running readiness record.

### 1. Distributed admission control — TESTED, real multi-process proof

P11's own two `IntegrationHub` gates (`mission_concurrency`,
`capability_concurrency`) were plain in-process counters — accurate to
their own docstring's "does NOT extend across processes" disclosure, but a
real gap for Model B: two ADOS processes sharing one Postgres database
would each independently enforce the ceiling, together admitting up to Nx
the configured limit. Both gates gained an additive, optional Postgres-
backed global layer (`admission_leases`, `pg_advisory_xact_lock`, the same
idiom the two already-global `mcp_gateway.py` gates use) — the local
in-process check still runs first, unchanged, for every one of the ~800
pre-existing tests (`session_factory=None`). Proven with real, separate OS
processes (`multiprocessing`, `spawn` context, a real `Barrier` for
genuinely simultaneous attempts): 6 processes racing a limit of 3 admitted
**6** before the fix, **exactly 3** after — independently confirmed against
the database's own row count, not trusted from return values alone. The two
already-Postgres-backed gates (`approval_queue`, `session_activity`) were
additionally proven with 2 real OS processes calling the real
`request_capability` MCP tool function — exactly at their configured limits
too.

### 2. Docker resource ownership — CONFIRMED, no code changes needed

Re-audited and independently verified against real Docker with real
concurrent OS processes: the claim/lease/ownership-label mechanism P7-C
built already satisfied every case this phase named (owner protection,
legitimate-recovery-only, simultaneous-recovery-exactly-one-claims,
stale-row protection) — proven, not merely re-asserted, in
`scripts/p12_docker_ownership_proof.py`.

### 3. Automatic reconciliation — TESTED, DEMONSTRATED live

`capability_reconcile.py`'s two functions (stall-detection,
outcome-unknown resolution) were manual-only through P11 — a deliberate,
correct-at-the-time decision (the safety guarantee never depended on
automation). Both are now also called from the same centralized periodic
loop session/orphan reconciliation already used — one scheduler, not a
second one. **Live-demonstrated** against a real running backend process: a
genuinely stalled row was automatically detected, marked `outcome_unknown`,
and correctly left there (no ServiceNow evidence available) — zero operator
action, real infrastructure, real log lines, independently re-verified via
`psql`.

### 4. NULL-expiry protection — a real, previously-uncalled-out gap, CLOSED

Re-deriving P10's own claim found it incomplete: `mcp_gateway.py::
_resolve_session` — the function every MCP tool shares, not only the
approval endpoint P10 actually fixed — never checked for a NULL
`token_expires_at`, only for expiry in the past. A NULL-expiry fossil
session with a live `state` could reach **autonomous auto-execution**, no
human involved at all — worse than the approval-only gap P10 closed. Fixed
with the same reasoning P10 already established, extended to the earlier
choke point. Five pre-existing test files needed the same fixture update
P10 itself required for two files (`token_expires_at=token_expiry(1800.0)`,
never a weakened guard); two new dedicated tests pin the fix; the
pre-existing approval-side test was rewritten to construct its scenario
directly, since the new upstream guard makes the old path to it impossible.

### 5. Rate limiting — TESTED, closes doc 18's own §D finding

"None, on any endpoint, including ones that call a paid LLM per request" is
no longer true for the one capability that risk was named against.
`integrations/rate_limiter.py` — a fixed-window limit on `RunPrimeRLMAgent`
starts, distinct from admission control's concurrency ceiling, server-side
only, disableable. Proven with a real concurrent race against real
Postgres (12 tasks, limit 4 → exactly 4 admitted) and hub-level tests
proving a rejected call never reaches the connector.

### 6. Observability and alerting — two new metrics, one proven live

`ados_admission_leases_active`/`ados_admission_lease_oldest_age_seconds`
(both `gate`-labeled, no high-cardinality label added); `ados_admission_
rejections_total` gained a fifth `gate` value. Two new alert rules
(18 total, `promtool`-validated); `ADOSAdmissionLeaseStuck` proven live,
full fire→deliver→resolve→deliver, against the same real local Prometheus/
Alertmanager/webhook chain doc 22 stood up.

### 7. Regression

Fresh, one pass, immediately after all P12 changes: **866 passed, 0
failed, 19 deselected** (17 `docker` + 2 `external`, both counts unchanged
from P11), 274.45s. Baseline immediately before any P12 code changed was
845 passed / 2 failed (both isolated-pass, confirmed non-regressions,
resource-contention artifacts under full-suite load — the same class P11's
own report already documented for two different tests) / 19 deselected =
866 total collected. P12 added 19 new tests; 866 + 19 = 885 = 866 + 19,
reconciled exactly. All 17 `docker`-marked tests re-run separately and pass
together (34.72s). Docker/Postgres state independently confirmed clean
before and after every proof script and every live-container exercise this
phase ran (zero leaked `ados-prime-*`/`ados-rt-*` resources; zero leftover
rows in `admission_leases`/`rate_limit_events`/proof-created missions).

### 8. Negative controls

Six, each: guard disabled in real source, targeted real-infrastructure
evidence gathered and confirmed to fail as expected, guard restored,
`shasum -a 256` confirmed byte-identical before/after — see doc 23 §12 for
the full table.

### 9. Updated verdict

**Model A:** unaffected, still READY — every P12 addition is opt-in/
additive (`session_factory=None`, `limit<=0` preserve P11 behavior exactly),
confirmed by 22 unchanged-passing pre-existing admission tests plus a fresh
58-test P9/build-identity/Postgres-security regression.

**Model B:** the specific target this phase was scoped to answer. See
[23-p12-production-operationalization.md](23-p12-production-operationalization.md)'s
final section for the complete verdict and the evidence supporting it —
**READY**, with one named, not hidden, limitation: true horizontal
scale-out (`--workers 2`+) remains blocked by MOA/ITSM state still being
per-process, a separate, larger concern this phase did not attempt to
close. Model B as evidenced here means one long-running process, bounded,
observable, and recoverable without a human babysitting it — not N
processes.

**Model C:** remains **NOT READY**, unaffected by this phase by explicit
instruction — multi-host Docker ownership, tenancy, and distributed rate
limiting beyond the single-database mechanism built here are still `NOT
BUILT`.

---

## 19. P13 update: Horizontal Scale-Out / Multi-Process Production Readiness (2026-08-14)

Directly answers what P12 left open: can ADOS safely run `--workers 2+`?
P12's own limitation note blamed "MOA/ITSM state... still process-local" —
**re-deriving that claim from the current code (not trusting P12's own
report) found it stale**: MOA and ITSM were already fully Postgres-backed
(proven by the pre-existing `test_moa_durability.py`); the Dockerfile's own
`--workers` comment describing an in-memory dict MOA no longer uses is
itself stale. The REAL blocker was a different, older, un-migrated
pipeline. Full evidence ledger in
[24-p13-horizontal-scale-out.md](24-p13-horizontal-scale-out.md); this
section is the summary that belongs in the running readiness record.
**Baseline:** the same uncommitted P12 working tree, HEAD `7464902`.

### 1. The real blocker — `orchestrate/governance.py::ApprovalQueue` (the manufacturing-incident pipeline) — CLOSED

A plain in-memory dict, one per `DecisionOrchestrator`, one per process.
`POST /incidents/{id}/approve|reject|escalate` on a worker that never ran
that incident 404'd, even though the incident was durably `AwaitingApproval`
in Postgres already. Fixed additively, reusing 100% of the existing
restart-recovery machinery (`resume_pending_approvals`/`resume_after_
decision`, unmodified in logic): a new on-demand `resolve_pending_approval`
(orchestrator.py) and a live Postgres read (`AuditTrail.get_from_db`) close
the visibility gap; a new atomic claim (`AuditTrail.claim_awaiting_
approval`, a single conditional `UPDATE`) closes the double-execution race
that visibility alone would have newly introduced (a race that was
structurally impossible before this fix, since only the originating worker
could ever see the pending decision). Proven with a **real, 2-real-OS-thread
concurrent race** against two independent app instances — exactly one `200`
and one `409`, the underlying capability invoked exactly once, every run
(confirmed non-flaky across 4 repeats) — not a sequential simulation.

### 2. A second, real gap found while re-checking P12's own admission-control claims — CLOSED

`backend/app/mcp_gateway.py::_execute_capability` (the Prime Agent
in-mission capability path) called `default_hub()` fresh on every call —
a brand-new, always-`session_factory=None`, always-zeroed `AdmissionControl`
every time. Pre-existing since P11, not multi-process-specific (broken even
at one worker), found only because this phase re-derived whether admission
control's own claims still held for this specific traffic surface. Fixed
by wiring a module-level `_active_hub` (mirroring this file's own existing
`_mcp_current` pattern) to the real `app.state.integration_hub` for the
lifetime of the real lifespan. Proven functionally: two concurrent
in-mission capability calls through a real app instance, against a
deliberately tiny limit set on the real hub, are now actually bounded —
before this fix, both would have been silently admitted regardless of the
configured limit. **A real regression this fix itself introduced was
found by the full regression suite and fixed before this phase's evidence
was considered final**: the first version unconditionally preferred the
wired hub, breaking 5 pre-existing tests that rely on the established
`monkeypatch.setattr("integrations.hub.default_hub", ...)` convention even
inside a real lifespan. Fixed by only preferring the wired hub when
`default_hub` is still the exact, unpatched original object — see doc 24
§4 for the full account.

### 3. Two further real, narrower gaps — found, precisely characterized, deliberately deferred

`orchestrate/moa/dynamic_registry._ENTRIES` / `DynamicCapabilityConnector.
_dispatch` (a capability activated on one worker is invisible on others
until restart — a designed self-heal `resolver` hook exists but is never
wired) and `hot_disable_policy_rule` reading a possibly-stale manifest
cache (self-heals on a miss, not on present-but-stale data — a real gap in
an explicit safety circuit breaker). Both affect only the newer
dynamic-capability-onboarding feature, not the core mission/incident/
approval/admission-control flows this phase's evidence covers. Named
precisely, with a concrete smallest-fix lead for each, rather than rushed
alongside items 1-2.

### 4. Regression

Full suite, fresh, one pass, after all P13 changes: see doc 24 §7 for the
exact counts and reconciled arithmetic. 10 new tests
(`test_incident_approval_multiworker.py` 7, incl. a real 2-thread
concurrent race and an isolated on-demand-resolution proof;
`test_mcp_gateway_hub_wiring.py` 3). Zero regressions.

### 5. Negative controls

Three, each: guard disabled in real source, targeted evidence (including
the real concurrent-thread race, re-run against the disabled guard)
confirmed to fail as expected, guard restored, `shasum -a 256` confirmed
byte-identical before/after — see doc 24 §6 for the full table.

### 6. Updated verdict

**Model A:** unaffected, still READY — every P13 change is additive and
falls back to prior behavior exactly outside a real lifespan/for any
caller that never reaches the new code paths.

**Model B:** unaffected, still READY — Model B was always a single-process
claim; nothing here changes its own evidence (doc 23).

**Model C (horizontal scale-out):** this was this phase's actual target.
The specific, concrete blockers that would make `--workers 2+` unsafe for
the core mission/incident/approval/admission-control flows are closed and
proven under real concurrent load. **Not a full "Model C: READY" verdict,
honestly** — two narrower, lower-severity gaps remain (§3 above, doc 24
§5), and Model C's full distributed-platform requirements (multi-tenancy,
multi-host Docker ownership, distributed rate limiting beyond the
single-database mechanism P12 built) remain `NOT BUILT`, unattempted, and
out of scope, exactly as every prior phase already said.

---

## 20. P14 update: Dynamic Capability Consistency & Hot-Disable Safety (2026-08-14)

Full report:
[25-p14-capability-registry-consistency.md](25-p14-capability-registry-consistency.md).
Closes both of the two narrower gaps §19/doc 24 §5 deferred:

1. **`hot_disable_policy_rule` cache staleness** — a hot-disabled
   capability could keep executing on a worker whose process-local
   `CapabilityManifestRegistry` cache never learned about a disable issued
   through a *different* worker's own registry instance, with no bound on
   how long the staleness could last. Closed by replacing the synchronous,
   cache-based `PolicyRule` with an authoritative, per-call Postgres read
   (`CapabilityManifestRegistry.refresh_from_db`) at the two real
   execution boundaries (`IntegrationHub.invoke()`,
   `DynamicCapabilityConnector.execute()`) — not a periodic refresh of the
   same cache, a genuine replacement of "trust what's cached" with "ask
   Postgres, every time, right before it matters."
2. **Dynamic capability registry / dispatch-config propagation** — a
   capability activated on one worker stayed uninvokable on every other
   worker until that worker restarted. Closed by wiring
   `DynamicCapabilityConnector`'s own pre-existing, previously-unused
   `resolver` cache-miss fallback to a new
   `orchestrate/onboarding/runtime_registry.resolve_dispatch_config()`.

A real regression was found and fixed during this phase's own live proof
(keeping the old synchronous rule alongside the new authoritative check
"for defense in depth" turned out to actively reintroduce staleness, and
inconsistently across paths) — full account in the P14 report §5.

**Updated Model C verdict:** the concrete, named blockers this program has
found for `--workers 2+` across mission/incident/approval/
admission-control/dynamic-capability flows are now closed and proven
under real concurrent, **multi-process** load (real, separate OS
processes via `multiprocessing`, not simulated within one process — see
the P14 report §7 for why that distinction matters and how P13's own
`TestClient`-sharing-`app.state` limitation was avoided this time). Still
not a full "Model C: READY" verdict — multi-tenancy and multi-host
container ownership remain entirely unattempted and out of scope, exactly
as every prior phase already said.

## 21. P15 update: Distributed Concurrency Semantics & Atomicity Review (2026-08-14)

Full report:
[26-p15-concurrency-atomicity-review.md](26-p15-concurrency-atomicity-review.md).
P14 named one open question explicitly — "the disable-vs-execution race
outcome is an empirical observation, not an atomicity guarantee" — and P15
was chartered to determine exactly what this system guarantees under
concurrent governance changes, approvals, executions, and crashes, fixing
anything that doesn't actually hold rather than re-asserting that it does.

Re-deriving every concurrency-relevant transaction boundary from source
(not from P11–P14's own reports) found two genuine defects, neither an
authorization bypass, both real:

1. **Late autonomous completion could overwrite reconciliation's decision**
   — `backend/app/mcp_gateway.py`'s autonomous-tier completion write had no
   guard against a row the periodic reconciliation pass had already,
   independently resolved while the same call was still genuinely in
   flight (not crashed — no lock is held across the external call, by
   design). `backend/app/routers/runtime_approvals.py`'s approve path
   already had this exact guard; the autonomous path did not. Fixed by
   mirroring it.
2. **Admission-control local-slot leak on a database failure** —
   `integrations/hub.py::IntegrationHub.invoke()` could permanently leak
   its in-process concurrency slot if the global (Postgres) admission
   acquire, or any one of the global release calls in `finally`, raised —
   a transient DB outage during exactly that window. Not an authorization
   bypass (a leak only ever makes the gate stricter), but a real,
   reproducible availability defect. Fixed by wrapping the whole sequence
   in one guaranteed-release try/finally with independently-guarded
   release calls.

Both were caught by this phase's own audit of every crash/DB-unavailable
transition point (nothing here was suspected by any prior report), fixed
with the smallest change that closes them, covered by new focused
regression tests, and proven closed live across real, separate OS
processes — including a genuine `SIGKILL` crash boundary, not merely a
simulated exception. Four negative controls confirm the guards (2 new, 2
pre-existing and independently re-derived: the approval row lock and the
admission advisory lock) are load-bearing. Full report has the complete
invariant-by-invariant classification, the live proof transcript, and the
test-count reconciliation.

**No architecture change.** No Redis/Kafka/new distributed mechanism was
introduced — every fix uses the same Postgres-transactional idioms
(`FOR UPDATE`, `pg_advisory_xact_lock`, a partial unique index, a
try/finally) already established by P9–P14.

## 22. P16 update: Multi-Tenancy & Multi-Host Ownership Safety Review (2026-08-14)

Full report:
[27-multi-tenancy-and-multi-host-safety.md](27-multi-tenancy-and-multi-host-safety.md).
P15 closed Model C's concurrency/atomicity blockers and left two named,
unattempted reasons Model C was still not ready: multi-tenancy and
multi-host Docker ownership. P16 was chartered to determine, honestly,
how not-ready each one is — not to assume the answer or build either one
wholesale.

**Headline finding: ADOS has no tenant isolation model of any kind.**
Confirmed by source review across every table, router, and background
process (no `tenant_id`/`org_id`/`account_id` column exists anywhere;
`MissionRow.created_by` is never set to an end-user identity by the one
real mission-creation path), and then confirmed **live**: two real,
distinct, authenticated seeded users, against the real app and real
Postgres, with one able to read, and unilaterally decide, a capability
request it had zero relationship to — because authorization on this
surface is role-based only, never ownership-based. This is not a defect
in any approval or RBAC check; it is the accurate, evidenced state of a
system that was never built with a tenant concept, exactly as prior
phases already scoped it.

**One real defect found and fixed, in the separate multi-host
direction.** `orchestrate/runtime/orphan_sweep.py`'s cleanup sweep had no
host affinity: a sweeper on one host could claim a session row created on
a *different* host, find nothing on its own local Docker daemon, and
durably record that other host's still-running container as `absent` —
permanently leaking it while the audit trail claimed success. Fixed with
a nullable `RuntimeSessionRow.owner_host` column and a claim-query filter
(`orchestrate/runtime/orphan_sweep.py::claim_batch`'s new `node_id`
parameter) — fully backward-compatible (`node_id=None` preserves every
pre-P16 caller's exact behavior), no distributed control plane, no
leader election. Proven under real Postgres, including a genuine
concurrent-race test; classified TESTED rather than DEMONSTRATED, since
no second real Docker host was available to independently verify the
cross-daemon `docker inspect` assumption.

Three negative controls (the new `node_id` filter, the pre-existing
workspace path-root validation, and the pre-existing auditor read-only
RBAC guard — the one real protection on the exact surface the live proof
exploited the absence of an ownership check on) all failed for exactly
the predicted reason with the guard removed, and were restored
byte-identical (SHA-256 verified).

**No multi-tenancy was built.** Per the task's own explicit instruction,
`tenant_id` was not added reflexively — the evidence shows this is a
genuine architecture decision (which resources are per-tenant vs.
genuinely shared, how a tenant would authenticate, whether
admission/rate-limit ceilings need a tenant-scoped layer *alongside*
their existing intentional global ceiling) for a future, deliberately
scoped phase, not a patch P16 could safely make in place.

**Updated Model C verdict:** unchanged in substance from P15 — still
NOT READY — but now evidenced rather than assumed. Multi-tenancy is
confirmed **NOT BUILT** (not merely unattempted). Multi-host Docker
ownership had one real, open defect, now **fixed and TESTED** at the
database/decision layer, with the two-real-hosts gap that would upgrade
it to DEMONSTRATED named explicitly rather than papered over.

## 23. P17 update: Multi-Tenancy Architecture & Tenant Isolation Implementation (2026-08-15)

Full report:
[28-multi-tenancy-and-tenant-isolation.md](28-multi-tenancy-and-tenant-isolation.md).
P16 confirmed live that ADOS had no tenant isolation model at all. P17
built one and closed the exact defect P16 demonstrated.

**Architecture:** none of the five suggested tenancy libraries fit —
two are Laravel/Django (wrong framework), one additionally needs the
Citus Postgres extension (infrastructure this stack doesn't have), one
is a genuinely SQLAlchemy-native but single-maintainer, 4-star project
whose session-construction pattern would require restructuring how
every one of ~40 existing modules opens a database session, and one is
not a library at all (a demo scaffold). Built a native mechanism
instead, using SQLAlchemy's own documented recipe for exactly this
problem (`Session.do_orm_execute` + `with_loader_criteria`): a single
global filter, fail-closed by default, that makes every existing query
against a tenant-owned table automatically tenant-scoped with zero
changes to how any router already writes its queries.

**Real tenant model:** `tenants` / `tenant_memberships` tables, tenant
membership baked into the login JWT the same stateless way role already
is, an active-tenant-selection header cross-checked against verified
membership (never trusted alone), and a `contextvars.ContextVar` proven
— by a dedicated concurrency spike before any production code was
written — to never leak between concurrent requests carrying different
tenants.

**The exact P16 defect, closed and proven live:** two real tenants, two
real users, real Postgres, real HTTP. A cross-tenant list/get/decide now
404s (existence never revealed); same-tenant access is unaffected. Both
the endpoint and the raw ORM query underneath it were independently
verified. 6/6 negative controls confirm every guard is load-bearing,
each restored byte-identical.

**A real regression was found and fixed in the process**, in P15's own
multiprocess proof script: it deliberately bypasses the FastAPI
dependency layer to isolate a concurrency primitive from auth concerns,
which meant it also bypassed the new tenant-context resolution — fixed
by an explicit, documented opt-out, not by weakening the new guard. Both
P14's and P15's multiprocess proofs — including P15's real `SIGKILL`
crash boundary and 10-real-process admission race — were re-run after
the fix and pass cleanly, confirming no regression to P13–P16's own
concurrency and multi-host guarantees.

**Postgres RLS was fully evaluated, not merely dismissed:** P10's own
role-separation work already means the real deployed backend's
`ados_app` role does not own the tenant-owned tables, the exact
precondition RLS needs to be meaningful. It was not built this phase
because that same role is shared by tenant-scoped HTTP routes AND the
cross-tenant background jobs/gateway — making RLS safe would need either
a role split or a session-GUC-propagation mechanism mirroring the
`ContextVar`, both real engineering beyond this phase's smallest-correct
scope. Documented as DESIGNED, NOT BUILT, with the exact policies ready.

**Deliberately not built:** tenant scoping for the separate MOA/incidents
surface (220 seeded demo records with hundreds of dependent tests — a
named scope boundary, not an oversight) and a user-facing mission-creation
endpoint (doesn't exist yet, so there is no real caller tenant to
attribute a mission to beyond the default).

**Updated Model C verdict:** the dominant blocker P16 named — no tenant
model — is now **BUILT and DEMONSTRATED** on the exact surface P16
proved mattered. Model C is still not fully READY: the RLS backstop, a
real mission-creation entry point, and the MOA surface's own tenant
story all remain, each named precisely rather than left implicit.

## 24. P18 update: Tenant Production Hardening & Model-C Readiness Review (2026-08-15)

Full report:
[29-p18-tenant-production-hardening.md](29-p18-tenant-production-hardening.md).
P17 named "a real mission-creation entry point" as a remaining Model C
requirement, reasoning correctly that `RunPrimeRLMAgent` has no direct
Python caller anywhere in the codebase — but that grep-based search
missed a real, already-reachable one: `POST /capabilities/invoke`, a
generic, pre-Prime-Agent capability-dispatch endpoint
(`docs/006-integration-hub.md`) that any authenticated user can already
reach and that was silently stamping every mission it created with the
default tenant regardless of caller. P18 found this by re-deriving "can a
real authenticated user create a mission today" from source rather than
trusting P16/P17's own conclusion, and closed it: the endpoint now
resolves the caller's tenant via the same `get_tenant_context` dependency
`runtime_approvals.py` already uses, and `PrimeRuntimeConnector._run()`
reads it from the existing `ContextVar` with no new plumbing through
`CapabilityCall`. Proven end to end over real HTTP with a real second
tenant; 4 new tests; full suite 911 passed / 0 failed / 19 deselected
(907 + 4, reconciled exactly).

**Postgres RLS re-evaluated independently, and found genuinely harder
than P17's own reasoning stated**, not merely re-confirmed as deferred:
tracing `approve_capability_request`'s three-phase transaction structure
(a deliberate P9 design — no lock held across the external call) found
that the session it uses spans multiple transactions, so a session-GUC
approach that sets the tenant context once at session-open would
silently stop applying at the first commit, breaking Phase 3's
`session.refresh(row)` under RLS. Still DESIGNED, NOT BUILT, but for a
sharper, more concrete reason than "insufficient time to verify" — a
named, specific prerequisite (a verified per-transaction GUC
re-assertion mechanism, or a role split) for whichever future phase
attempts it.

**Everything else audited independently either held up or was
strengthened with new evidence P17 never gathered:** the MOA/incidents
boundary reconfirmed via an exhaustive full-repo grep (stronger than
P17's own scope-boundary reasoning); global admission/rate-limit
classification reconfirmed unaffected; the multi-host `owner_host`
mechanism reconfirmed unregressed (still TESTED, not DEMONSTRATED — no
second real Docker host available, unchanged from P16); metrics/alerts
reconfirmed to carry no tenant label anywhere; two of P17's five
tenant-compatibility-fixed live-proof scripts were actually re-executed
live (real Docker + real Postgres, both PASS) rather than left at
syntax-verified; and a genuinely new real multi-process tenant-isolation
proof (`scripts/p18_multiprocess_tenant_isolation_proof.py`) was written
and run — real separate OS processes racing on a real
`multiprocessing.Barrier`, 30 genuinely concurrent `asyncio.gather`
requests alternating two tenants' credentials within one process/event
loop, and a background-reconciliation call proven to override an
adversarial ambient tenant context rather than merely "working when
nothing else set one" — the strongest form of that specific proof
anywhere in this programme. All three cases PASS.

**Updated Model C verdict:** still **NOT READY**, but every remaining
requirement is now precisely evidenced (see doc 29 §13's full
requirement-by-requirement table) rather than assumed. The concrete
remaining blockers: the RLS backstop (DESIGNED, DEFERRED, sharper reason
named), dead-host automatic recovery (NOT BUILT — needs a lease/heartbeat
design), two-real-Docker-host verification (unavailable in this
environment), and per-tenant admission/reviewer capacity (a deliberate,
undesigned product decision, not a technical gap). Model A and Model B:
**unaffected, both still READY** — every P18 change is additive and
preserves every pre-existing single-tenant/single-process code path
exactly.
