# P11 — Final Acceptance Report: Controlled Internal Production Operationalization

Compiled 2026-08-12. **Baseline:** `7381122` (P10 — "production readiness
blockers: Postgres role, capability-path build identity, observability,
backups, NULL-expiry approval exposure"). **P11 commit:** `<filled in below,
this section's own self-reference — see the note>`.

This report uses the same taxonomy every prior phase in this programme has
used, applied strictly:

| Category | Means |
|---|---|
| **DEMONSTRATED** | proven by a real, live, independently-checked run |
| **TESTED** | an automated test proves the mechanism; no live run exercised it |
| **CONFIRMED** | re-verified against a specific claim/requirement; no gap found |
| **DESIGNED/PARTIAL** | the implementation exists; proven for part of its scope, not all |
| **NOT BUILT** | outside implemented scope |
| **OPEN DEFECT** | a real, unresolved gap |

---

## 1. Scope, exactly as given

Six items: (1) metrics and alerting, (2) rate limiting / admission control,
(3) operator runbook, (4) a live operator recovery exercise, (5) explicit
production constraints for the Model A envelope, (6) acceptance evidence —
closing exactly the two items P10's own §11/§16 named as Model B's
remaining minimum-blocker set (metrics/alerting, admission control), plus
the runbook and recovery exercise §4D/§11 separately flagged as missing.
Explicitly out of scope, per this phase's own instructions, and not
attempted: resume, heartbeats, scheduling, subagents, multi-tenancy,
distributed architecture.

---

## 2. Files changed

**New (11):**

| File | Lines | Purpose |
|---|---|---|
| `backend/app/metrics.py` | 147 | The metric catalog — 17 metric families |
| `backend/app/routers/metrics.py` | 65 | `GET /metrics` — Prometheus text exposition + live gauge queries |
| `integrations/admission_control.py` | 80 | `AdmissionControl` — the two in-memory concurrency gates |
| `backend/tests/test_metrics.py` | 457 | 19 tests — one per metric, endpoint rendering, no-sensitive-data proof |
| `backend/tests/test_admission_control.py` | 74 | 7 tests — `AdmissionControl` unit behavior |
| `backend/tests/test_integration_hub_admission.py` | 220 | 7 tests — hub-level concurrency, races, rejection-before-side-effect |
| `backend/tests/test_mcp_gateway_admission.py` | 232 | 8 tests — the two Postgres-backed gates, real concurrent races |
| `backend/tests/test_admission_control_docker.py` | 132 | 1 docker-marked test — real Docker proof for the mission gate |
| `scripts/p11_orphan_recovery_exercise.py` | 236 | The live recovery exercise script |
| `docs/prime-agent-integration/19-metrics-and-alerting.md` | 137 | Metric catalog + alerting contract |
| `docs/prime-agent-integration/20-operator-runbook.md` | 485 | The 14-scenario operator runbook |

**Modified (14):**

| File | Δ | What changed |
|---|---|---|
| `backend/app/config.py` | +11 | Four new `Settings` fields for the admission-control limits |
| `backend/app/main.py` | +13/-0 | Wires `AdmissionControl` into `default_hub()`, registers the `metrics` router |
| `backend/app/mcp_gateway.py` | +95 | The two Postgres-backed admission gates, 4 metric hooks |
| `backend/app/observability.py` | +13/-6 | Corrects the docstring claim that no `/metrics` endpoint exists |
| `backend/app/rbac.py` | +7 | 3 authorization-denial metric hooks |
| `backend/app/routers/auth.py` | +2 | 1 authentication-failure metric hook |
| `backend/app/routers/runtime_approvals.py` | +2 | 1 token-expiry-refusal metric hook |
| `integrations/connectors/prime_runtime.py` | +4 | 2 mission-lifecycle metric hooks |
| `integrations/hub.py` | +84 | The two in-memory admission gates, 4 metric hooks (the universal choke point) |
| `orchestrate/runtime/build_identity.py` | +2 | 1 build-identity-drift metric hook |
| `orchestrate/runtime/capability_reconcile.py` | +47 | Reconciliation-run metric wrapping, outcome-unknown metric hook |
| `orchestrate/runtime/orphan_sweep.py` | +16/-1 | Orphan discovery/cleanup metric hooks |
| `requirements.txt` | +7 | `prometheus_client==0.26.0` |
| `tests/test_phase3_cross_integration.py` | +46 | **Separate, out-of-scope fix** (see §6) — mocks ServiceNow, closes a real-effect leak found incidentally |

Also updated: `docs/prime-agent-integration/18-production-readiness-review.md`
(§17 added), `docs/prime-agent-integration/14-known-limitations.md`
(Operations section appended), `docs/prime-agent-integration/README.md`
(index table).

**Untouched, per explicit instruction:** the pre-existing, unrelated
uncommitted working-tree state (an in-progress agents-registry/novus-studio
frontend feature, ~25 untracked scratch scripts) — verified via `git
status` before and after this phase's own work; none of those files appear
in the diff above.

---

## 3. Metrics and alerting

**17 metric families**, cataloged in full in
[19-metrics-and-alerting.md](19-metrics-and-alerting.md): missions started/
completed, capability executions + duration, admission rejections, approval
queue depth/age, `outcome_unknown` count/age, reconciliation success/
failure, orphan discovery/cleanup, authentication failures, authorization
denials, build-identity drift refusals, token-expiry refusals.

**TESTED**, not DEMONSTRATED-via-a-live-alert: every metric's increment
point is proven by a dedicated test in `backend/tests/test_metrics.py`
(19 tests) that triggers the exact lifecycle event and asserts the
counter/gauge/histogram moved by the exact expected delta. `GET /metrics`
itself is exercised via `TestClient`, real (mocked-transport) capability
executions, and real Postgres queries for the two scrape-time gauge pairs
— this is real HTTP + real Postgres, not a unit stub, even though no
external Prometheus scraper was ever pointed at it (none is deployed by
this repository — see the doc's own scope section).

**No sensitive or high-cardinality data**: proven, not asserted —
`test_no_sensitive_or_high_cardinality_data_in_metrics` runs a realistic
mixed pass carrying a real bearer token, a fake ServiceNow password, and
distinct mission/request UUIDs and free-text arguments, then asserts none
of them appear anywhere in `GET /metrics`'s rendered output.

**Alerting: DESIGNED, delivery NOT BUILT.** The alerting contract (14
conditions, each with why-it-matters and operator-action) is a
specification for an operator's own Prometheus + Alertmanager, not
something this repository runs. No alert has ever actually fired and paged
anyone — that would require infrastructure this repository deliberately
does not deploy, named as an external dependency rather than invented.

---

## 4. Rate limiting / admission control

**Four gates, TESTED against real concurrency (both in-memory and
Postgres-transactional), one DEMONSTRATED against real Docker:**

| Gate | Mechanism | Evidence |
|---|---|---|
| Mission concurrency (default 3) | In-memory, `IntegrationHub.invoke()` | TESTED (real asyncio race) + **DEMONSTRATED** (docker-marked: a real second `docker run` never issued) |
| Capability-execution concurrency (default 10) | In-memory, `IntegrationHub.invoke()` | TESTED (real asyncio race, peak-concurrency assertion) |
| Approval-queue depth (default 50) | Postgres advisory lock, `mcp_gateway.request_capability` | TESTED (real Postgres, 8 genuinely concurrent parks against a limit of 3 — exactly 3 admitted) |
| Per-session activity (default 200) | Postgres row lock, `mcp_gateway.request_capability` | TESTED (real Postgres, 6 genuinely concurrent requests against a limit of 2 — exactly 2 admitted) |

**Critical invariant — "rejected before any external side effect" — proven,
not asserted:** every rejection path returns before `connector.execute()`
(the in-memory gates) or before the row is ever committed as
`pending_approval`/executing (the Postgres gates). `test_integration_hub_
admission.py::test_rejection_never_invokes_connector` and `test_mission_
gate_rejection_never_invokes_connector` assert the fake connector's call
count stays at zero for a rejected request. The docker-marked test goes
further: an independent `docker ps` count proves a *real* `docker run` was
never issued for the refused mission.

**Server-side only:** `test_agent_supplied_hints_have_no_effect_on_
admission` and `test_session_activity_server_side_only` pass bogus
`_priority`/`_max_concurrent`/counter-override values in `call.input`/
arguments and confirm zero effect.

**Two real bugs found and fixed while building this** (detailed in
§17.2 of [18](18-production-readiness-review.md) and
[14](14-known-limitations.md)'s Operations section): a SQLAlchemy
identity-map staleness issue and an autoflush-ordering issue, both caught
only by concurrent-race tests asserting an *exact* admitted count against
real Postgres — a below/at/over-limit test run sequentially would have
passed against the broken code.

**Scope boundary:** single-process. Explicitly not a distributed rate
limiter — matches Model A's single-process envelope (§5).

---

## 5. Operator runbook

[20-operator-runbook.md](20-operator-runbook.md) — **DESIGNED**, all 14
required scenarios covered (symptom/verify/remediate/do-NOT/verify-
recovery), zero credentials/secrets in the document, built entirely from
already-existing operator tooling. One scenario ("orphaned resources") is
additionally **DEMONSTRATED** live via §6 below — the runbook's own
procedure is exactly what the recovery exercise executed.

---

## 6. Recovery exercise — DEMONSTRATED

`scripts/p11_orphan_recovery_exercise.py`, run once, **PASS**. Real Docker,
real Postgres, no ServiceNow. Full trace:

```
[1/5] FAILURE      real container ados-prime-3b868885-8d7 started (real `docker run`),
                    abandoned before teardown (simulated ADOS process crash)
[2/5] DETECTION    reconcile_abandoned_sessions() -> session marked `failed`,
                    failure_reason contains "orphaned"
[3/5] DIAGNOSIS    docker ps / docker inspect independently confirm the real
                    container + relay + 2 networks, ownership label matches
[4/5] REMEDIATION  sweep_once() -> claimed=5 cleaned=5 absent=0 failed=0 refused=0
                    (container, relay, 2 networks, 1 workspace directory)
[5/5] VERIFICATION fresh docker ps/network ls: zero resources remain;
                    session's own durable event log shows 5 orphan_sweep.cleaned entries
```

`mission_id=7efaa558-a479-4c79-81d6-994c7dbb39f5`
`session_id=3b868885-8d70-4da2-a00d-a6203b4cf6bc`. Docker state
independently confirmed clean immediately after (`docker ps -a` /
`docker network ls` show only the five persistent compose-stack containers,
zero leaked `ados-rt-*`/`ados-relay-*`/`ados-prime-*`).

The one deliberate shortcut — `reconcile_abandoned_sessions` invoked with
an explicit future `now=` rather than a real 300-second `TOKEN_GRACE_
SECONDS` wait — is documented in the script's own module docstring and
does not shortcut anything about Docker or Postgres: the container is
real, the rows are real, the sweep's `docker rm`/`docker network rm` calls
are real.

**Why no ServiceNow was used:** the orphan-resource scenario needs no
external side effect to demonstrate the full failure → detection →
diagnosis → remediation → independent-verification loop, and P9 already
proved the ServiceNow-crash-recovery scenario exhaustively
(`scripts/p9_crash_recovery_e2e.py`, real `INC0010029`). Repeating it here
would create a real external record for a scenario already proven — not
"genuinely necessary," per this phase's own instructions.

---

## 7. Production constraints — the Model A envelope

Stated explicitly (§17.5 of [18](18-production-readiness-review.md)): one
ADOS process; controlled, known internal users, no multi-tenant isolation
claim; bounded concurrency via the four new admission-control gates
(3/10/50/200 by default, every limit operator-tunable); manual/operator-
assisted recovery (reconciliation and sweep are periodic-automatic or
hand-run, never self-healing without a human able to inspect what
happened); no resume-after-process-death claim; no heartbeat claim; no
scheduling/subagent claim. Framed as scope, matching §5/§12's own prior
"acceptable out-of-scope for Model A" list — P11 did not change what Model
A does or doesn't claim, only made operating within it observable and
bounded.

---

## 8. An unrelated defect found and partially remediated

Detailed in [14-known-limitations.md](14-known-limitations.md)'s Operations
section and §17.6 of [18](18-production-readiness-review.md). Summary:
`tests/test_phase3_cross_integration.py` (Phase 3, predates this
integration) had been silently creating real ServiceNow Change Requests on
every full-suite run for a long time — discovered while gathering P11's own
acceptance evidence, not caused by P11. **Fixed** (mocked, matching every
other test file that can reach ServiceNow) and **the two records this
session's own runs created were closed and independently re-verified**
(`CHG0030986`, `CHG0030987`, both state 4/Canceled). **42+/41+ pre-existing
records deliberately left untouched** — not this phase's to bulk-remediate,
per explicit decision. Classified: **OPEN DEFECT** (the pre-existing
records), **CLOSED** (the leak itself, for this one file).

---

## 9. Acceptance evidence

### Test arithmetic, reconciled exactly

```
P10 baseline:        806 passed + 18 deselected (2 external + 16 docker) = 824 total
P11 new tests:        41 default-suite + 1 docker-marked                =  42 total
P11 final:            847 passed + 19 deselected (2 external + 17 docker) = 866 total

824 + 42 = 866  ✓
806 + 41 = 847  ✓
18 + 1 = 19     ✓
```

Three full, independent `pytest -q` runs after all changes: **847 passed, 0
failed, 19 deselected**, every time. `pytest -m docker -q`: **17 passed, 0
failed** (all docker-marked tests, including the new mission-concurrency
proof). No `pytest -m external` run was needed — no new external-marked
test was added; the recovery exercise is a standalone script, per this
programme's own established convention (external-effect proof lives in
hand-run scripts, not pytest).

**Two isolated, transient failures observed across the several full runs
this evidence-gathering required, both confirmed non-regressions by an
immediate isolated rerun, neither touching any file this phase modified:**
a real-Docker-build test that failed once right after Docker Desktop was
freshly started (image-pull timeout; passed on rerun), and a pre-existing
tight-`timeout=5` test that failed once after several consecutive full-
suite runs (system load; passed at 4.33s on rerun). Neither is counted in
the "847 passed" headline; both are reported here for completeness rather
than silently re-run until clean.

### Negative controls: 7, all confirmed, all byte-identical restored

| # | Guard/hook | File | Result when disabled |
|---|---|---|---|
| 1 | Capability-concurrency gate | `integrations/hub.py` | Real race: peak concurrency hit 10 against limit 3 |
| 2 | Mission-concurrency gate | `integrations/hub.py` | Second mission admitted, hung on shared connector |
| 3 | Approval-queue-depth gate | `backend/app/mcp_gateway.py` | Real race: 8/8 admitted against limit 3 |
| 4 | Session-activity gate | `backend/app/mcp_gateway.py` | Real race: 6/6 admitted against limit 2 |
| 5 | `build_identity_drift_refusals_total` hook | `orchestrate/runtime/build_identity.py` | Metric test failed: counter static |
| 6 | `authentication_failures_total` hook | `backend/app/routers/auth.py` | Metric test failed: counter static |
| 7 | `orphan_discovered_total`/`orphan_cleanup_total` hooks | `orchestrate/runtime/orphan_sweep.py` | Metric test failed: counters static |

Every file's `shasum -a 256` matched its pre-control-disable value after
restoration — verified, not assumed.

### Real infrastructure used

* **Real Postgres**: every DB-backed test (all of `test_mcp_gateway_
  admission.py`, the metrics tests, the recovery exercise) — including two
  genuine concurrent-transaction races proving lock/advisory-lock
  serialization against a real database, not mocked.
* **Real Docker**: 17 docker-marked tests (16 pre-existing + 1 new), plus
  the standalone recovery exercise — real containers, real networks, real
  `docker run`/`docker rm`/`docker network rm`.
* **ServiceNow**: not used by any P11-designed mechanism (deliberately, per
  §6 above). The only real ServiceNow effects during this phase were the
  two incidentally-discovered, now-closed, pre-existing-defect records
  (§8) — not a P11 acceptance artifact.

### Cleanup, independently verified

* Docker: `docker ps -a` shows only the five persistent compose-stack
  containers (`ados-backend-1`, `ados-migrate-1`, `ados-frontend-1`,
  `ados-postgres-1`, `ados-kafka-1`) before and after every test run and
  after the recovery exercise. Zero leaked `ados-rt-*`/`ados-relay-*`/
  `ados-prime-*` networks or containers, confirmed by direct query each
  time, not assumed.
* Workspace: no stray `/tmp/ados-mission-*` directories remain.
* ServiceNow: the two records this session's own test runs created are
  closed and independently re-verified (fresh `GET`, not the `PATCH`
  echo). Zero *new* open records from anything P11 itself built.
* Git: `git status` before and after shows only the files listed in §2
  changed or added — the pre-existing, unrelated dirty working-tree state
  (agents-registry/novus-studio frontend work, ~25 untracked scratch
  scripts) is untouched, confirmed by direct comparison.

---

## 10. Classification summary

| Item | Classification |
|---|---|
| Metric emission (17 families) | **TESTED** |
| No sensitive/high-cardinality metric data | **TESTED** |
| `GET /metrics` endpoint | **TESTED** |
| Alerting contract (specification) | **DESIGNED** |
| Alert delivery (paging, Alertmanager) | **NOT BUILT** (explicit external dependency) |
| Mission-concurrency admission gate | **DEMONSTRATED** (docker-marked, real `docker run` never issued) + TESTED |
| Capability-concurrency admission gate | **TESTED** (real asyncio race) |
| Approval-queue-depth admission gate | **TESTED** (real Postgres race) |
| Session-activity admission gate | **TESTED** (real Postgres race) |
| Rejection-before-side-effect invariant | **TESTED** + **DEMONSTRATED** (docker-marked) |
| Server-side-only enforcement | **TESTED** |
| Operator runbook (14 scenarios) | **DESIGNED**, one scenario also **DEMONSTRATED** |
| Recovery exercise (orphan resources) | **DEMONSTRATED** |
| Model A production constraints | **DESIGNED** (stated explicitly, matches prior scope) |
| Model B blocker closure (as P10 defined it) | **CONFIRMED** closed, narrowly — not a fresh full B audit |
| Model C readiness | **NOT BUILT**, unaffected, explicitly out of scope |
| ServiceNow leak in unrelated legacy test | **OPEN DEFECT** (42+/41+ pre-existing records) / **CLOSED** (the leak mechanism itself, and this session's own 2 records) |

---

## 11. Model A readiness verdict

**YES — ADOS is ready for controlled internal production under the Model A
operating envelope**, and was already so after P10 (§11: "Model A's own
blocker list is now empty"). P11 does not change that underlying verdict —
none of Model A's requirements were ever blocked on metrics, admission
control, a runbook, or a recovery exercise. What P11 changes is the
**operational posture** an internal operator runs Model A with:

* **Observable**: an operator can now see mission/capability throughput,
  approval backlog and age, `outcome_unknown` backlog and age,
  reconciliation health, orphan activity, authentication/authorization
  failures, build-identity drift, and admission-control pressure — all via
  `GET /metrics`, tested to actually move at the right lifecycle point and
  proven never to leak sensitive data.
* **Bounded**: a runaway agent, a burst of missions, or a stuck approval
  queue can no longer consume unbounded Docker/event-loop/human-approval
  capacity — four admission gates refuse cleanly, before any external side
  effect, proven under real concurrent load against real Postgres and (for
  the heaviest resource, Docker containers) a real Docker daemon.
* **Operable**: an operator facing any of the 14 named failure scenarios
  has a written, credential-free procedure to follow, and one of those
  scenarios (orphaned Docker resources) has been demonstrated end to end
  against real infrastructure — not just designed.

**Operational constraints of this verdict, stated explicitly:** single
ADOS process; no multi-tenant isolation; bounded concurrency at
conservative defaults (3 missions / 10 capability executions / 50 pending
approvals / 200 requests-per-session) that an operator must raise
deliberately, with headroom checked, if real demand exceeds them; manual or
operator-triggered recovery for crash scenarios, never fully automatic
self-healing; no resume, no heartbeats, no scheduling, no subagents — all
by design, not omission, and none of them required for this envelope.

**Remaining Model B blockers:** none that P10 itself named — both items in
P10's own stated Model-B minimum blocker set (metrics/alerting, admission
control) are closed by this phase. This is reported narrowly: P11 did not
re-audit Model B's full envelope beyond what P10 already enumerated, so
this is not an independently-derived "Model B: READY" statement.

**Remaining Model C blockers, unchanged and explicitly out of scope for
this phase:** multi-host Docker resource ownership (the current design
assumes one shared Docker daemon), a tenancy concept (does not exist in
the schema), and distributed rate limiting (the four gates built here are
single-process by design). None of these were attempted, per this phase's
own explicit instruction not to broaden scope into distributed
architecture.

**One open item, not P11's to close:** the 42+/41+ pre-existing real
ServiceNow records from the unrelated legacy-test defect found in §8 —
flagged here for whoever owns that ServiceNow instance to decide on, not
bulk-remediated by this phase without that decision being made explicitly.

Stop here. No P12 or further work was undertaken.
