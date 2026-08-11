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
2. An ADOS crash **during** human approval can roll the decision back to
   `pending_approval` **after** the external side effect already happened,
   making the request approvable a second time — a real double-execution
   path, not merely a theoretical one. (§9, §4B)
3. The idempotency-key replay guard in the gateway is real and tested, but
   the one prompt template that teaches the model the `ados` skill's API
   never mentions the parameter — so in practice, no live mission has ever
   supplied one. The guard exists but is not reachable from the only caller
   that would need it. (§9, §6F)
4. The P7-D build-identity drift guard protects the **start** of a mission
   (before a container exists) but is not called anywhere in
   `mcp_gateway.py`'s capability-execution path — a commit landing while a
   mission is already in flight is not caught for that mission's remaining
   capability calls. (§5.2, §4B)
5. `docs/prime-agent-integration/17-final-acceptance-report.md`'s own
   regression paragraph for P7-D miscounts the test suite: it states "8
   `external`" and "7 `docker`" deselected. Direct re-collection in this
   review finds **2** external-marked tests and **13** docker-marked tests,
   both fully consistent with every *other* number in that same report.
   (§15)

None of these are exotic. All five follow directly from reading the code the
existing reports already point at. They are the difference between "the
happy path is proven" and "the system is production-ready."

**Verdict: NOT READY**, for any operating model that involves a real,
unattended external side effect. See §17 for the full reasoning and §16 for
what would have to change first.

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

### 5.7 Remaining stale-session ambiguity — found in this review
**HIGH RISK for B and C.** Not the gateway-staleness kind — a `capability_
requests` row stuck at `pending_approval` after a crash. See §9 in full;
this is the review's most important single finding.

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
| Build-identity guard (capability path) | Absent | Code-verified gap | Medium-High | High for B/C | **Yes, for B/C** | One added call in `_execute_capability` | High |
| `capability_requests` crash reconciliation | Absent | Code-verified gap | High | High for B/C | **Yes, for B/C** | Detect+flag ambiguous rows; require external re-verification before re-decision | High |
| Approval crash → double-execution | Possible | Code-verified gap | High | High for B/C | **Yes, for B/C** | Persist "external call started" before the call, or move the write inside a compensating saga | High |
| Idempotency-key reachability | Designed, unused in practice | Prompt-template gap, code-verified | Medium | Medium-High for B/C | **Yes, for B/C** | Auto-generate a key per `run_capability` call in the `ados` skill, or teach it in the prompt | Medium |
| Metrics/alerting | Absent | NOT BUILT | Medium | High for B, Critical for C | **Yes, for B/C** | Minimum-viable Prometheus + `trace_id` wiring (already scoped in `docs/PRODUCTIZATION.md`) | High |
| Postgres non-superuser role | Absent | Self-acknowledged gap | Medium | High (undermines the audit claim) | **Yes, for B/C** | Provision a least-privilege role for the app; keep superuser for migrations only | High |
| Rate limiting / admission control | Absent | NOT BUILT | Medium | High for C, Medium for B | **Yes, for B/C** | Bound concurrent sessions; throttle per-caller | Medium |
| Backups/restore | Absent | NOT BUILT | Medium | High for B/C | **Yes, for B/C** | Standard Postgres backup/restore procedure | Medium |
| Session resume | Absent | NOT BUILT | High for long missions | High for B/C | Not strictly required — see §16 | Checkpoint/resume design (large) | Low (defer) |
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
Two changes: (1) close the approval-path double-execution window (§9,
recommendation 2 — a durable "call started" marker), since even a trusted
internal operator can double-click or retry after a crash; (2) fix the
Postgres role, since "the audit ledger is append-only" is a claim the
product makes, not an implementation detail an internal deployment gets to
quietly skip. Everything else in §6 is genuinely acceptable for A as
currently built.

**→ Ready for production (model B):** model A's two items, plus: (3) the
`capability_requests` reconciliation/flagging pass (§9, recommendation 1);
(4) the build-identity guard extended onto the capability-execution path
(§5.2); (5) minimum-viable observability — structured logs already exist,
so this is specifically metrics + alerting, not a rebuild; (6) backups.
**Resume/heartbeats/subagents/scheduling are explicitly not on this list.**
They are real future functionality, not blockers: nothing in B's definition
requires a crashed mission to continue rather than restart, only that a
crash not silently corrupt or duplicate the audit trail — which is what
items 1–4 actually fix.

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
