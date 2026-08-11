# Final Acceptance Report — Prime Agent Integration

Phase P6-E. Compiled 2026-08-11 from the repository at `96b9447`, branch
`prime-agent-runtime`.

This report supersedes nothing: [13-acceptance-report.md](13-acceptance-report.md)
and [16-external-side-effect-run.md](16-external-side-effect-run.md) remain the
traces of their own runs, recorded on the day. This one states what is proven
*now*, and by what.

The categories are used strictly:

| Category | Means |
|---|---|
| **DEMONSTRATED** | proven by a real live run, with identifiers |
| **TESTED** | committed automated tests and negative controls prove the mechanism; the relevant live path did not exercise it |
| **DESIGNED / PARTIAL** | the implementation exists; the required demonstration does not |
| **NOT BUILT** | outside implemented scope |
| **OPEN DEFECT** | known issue affecting correctness, security, traceability, or reliability |

---

## 1. Test state — reconciled, not copied

Measured at `96b9447`:

```
704   tests collected in total
696   selected by the default suite   (addopts: -m 'not external and not docker')
691   passed
  5   failed      — all environmental, see OPEN DEFECTS
  8   deselected  = 6 docker-marked + 2 external-marked
  6   docker-marked  — run separately, 6 passed
  2   external-marked — NOT run in P6-C/D/E; no external record was created
```

The five failures are all in `backend/tests/test_agents_registry.py` and all
raise `asyncpg.exceptions.UndefinedColumnError: column "division" of relation
"custom_agents" does not exist`. They belong to unrelated in-flight work whose
migration (`alembic/versions/c3d4e5f6a7b8_add_division_vibe_to_custom_agents.py`)
is present but unapplied. Nothing in the Prime Agent integration touches that
table. They were failing before P6-C began and were deliberately not fixed.

The two external tests are `test_notify_it_helpdesk_creates_a_real_servicenow_incident`
and `test_the_external_test_refuses_to_run_without_servicenow`. The real
external verification in this programme came from the marked acceptance
*scripts* (P6-A, P6-B), not from these two.

---

## 2. The 14 acceptance requirements

The canonical list is the P6-A verification set. Status reflects the current
repository, not the state on the day of the run.

| # | Requirement | Status | Implementation | Tests | Live evidence | Remaining gap |
|---|---|---|---|---|---|---|
| 1 | Prime Agent actually ran in the container | **DEMONSTRATED** | `orchestrate/runtime/prime.py` | `test_prime_agent.py` | P6-A container `ados-prime-ed7f5c47-c6e`; `runtime_session_id 019fecf7-d57a-75db-8975-391a579d4946` recovered from the session file; 2 kernel executions | — |
| 2 | The runtime used the P5 restricted network | **DEMONSTRATED** | `orchestrate/runtime/egress.py` | `test_runtime_egress_boundary.py` (3 docker) | P6-A, measured inside the live container: `ROUTE_COUNT 1` (on-link only), `DNS_EXTERNAL NO-RESOLVE(gaierror)` | — |
| 3 | Only configured gateway/model destinations reachable | **DEMONSTRATED** | same | same + `test_two_session_isolation.py` | P6-A: `IP_DIRECT_1111 BLOCKED`, `IP_DIRECT_8888 BLOCKED`, `HOST_POSTGRES_5432 BLOCKED`, `HOST_SSH_22 BLOCKED`, `ALLOWED_GATEWAY REACHABLE`, `ALLOWED_MODEL REACHABLE` | — |
| 4 | `FetchIncidentEvidence` executed through the governed MCP path, returning real stored evidence | **DEMONSTRATED** | `backend/app/mcp_gateway.py` | `test_capability_grant_authorization.py` | P6-A request `7c6c4a2f-f9f3-4fe8-ac27-e1c3ea131103`, `status=executed`, `connector=mission-evidence`; the model printed `SYN-4417` evidence it could not have held | — |
| 5 | `NotifyITHelpdesk` executed through the governed path and selected ServiceNow | **DEMONSTRATED** | `integrations/connectors/servicenow.py` | `test_notify_it_helpdesk_servicenow.py` | P6-A request `cfaa6599-837d-42bb-800b-5e22644d0d7d`, `connector=servicenow connector_status=succeeded` | — |
| 6 | The ServiceNow incident was actually created | **DEMONSTRATED** | same | mocked-transport tests | P6-A `INC0010028`, `sys_id d457ce3683ae0b10be487765eeaad386`, `opened_at 2026-08-10 18:43:45` | — |
| 7 | The incident/change_request carries the canonical `request_id` and mission provenance | **DEMONSTRATED** (both paths) | `servicenow_fields.py` | `test_servicenow_fields.py` (18), `test_capability_request_provenance.py` (7) | P6-A `INC0010028` body: `Capability request: cfaa6599-…`; **P7-A** `CHG0030638` body: `Capability request: df6538b2-a3ec-4a4f-8258-b6e483650503`, resolving to that exact row | — |
| 8 | The ADOS audit row records the same request ID and successful execution | **DEMONSTRATED** | `db/models/mission.py` | `test_capability_request_provenance.py` | P6-A: ticket id resolved to the executing row; `the audit row's sys_id matches the live record: True` | — |
| 9 | Kernel status classified from `details.status`, not `isError` | **DEMONSTRATED** | `prime.py:classify_tool_execution` | `test_kernel_execution_semantics.py` (21) | P6-A: `verdict=ok details.status=ok isError=False` ×2, printed side by side | — |
| 10 | `evaluate_mission()` accepts only from recorded state, never the model's answer | **DEMONSTRATED** | `orchestrate/runtime/acceptance.py` | `test_mission_acceptance.py` (8) incl. a signature test | P6-A: ACCEPTED on `tool_successes 2`, `capabilities_executed_by_ados == required_capabilities` | — |
| 11 | Independently GET the incident and verify contents | **DEMONSTRATED** | acceptance script | — | P6-A section 5: `sys_id`, `number`, marker, mission id all matched on re-read | — |
| 12 | Close the incident and independently GET it again | **DEMONSTRATED** | acceptance script | — | P6-A: `state=7`, `close_code=Resolved by caller` on re-read | — |
| 13 | Sweep for test-marker records; zero remain open | **DEMONSTRATED** | acceptance script | — | P6-A closed `INC0010028`; P6-B pre-flight found incident 6/0 open, change_request 2/0 open, and closed `CHG0030499` to `state=4` | — |
| 14 | Record the complete timeline | **DEMONSTRATED** | acceptance scripts | — | P6-A `PASS 431.7s`; P6-B `PASS 202.0s` with a per-second timeline | — |

### P6-B's approval checklist (its own 14 points)

Mission `d00ff47c-6c1a-46d0-802f-e4f4ed3d4b96`, session
`aba3c6cf-9af0-4f33-a253-31b3ec9b2c82`, request
`01dcf9c3-0cb4-4954-bf79-b9bb6c4b8e01`, `CreateChangeRequest` tier 2 risk high,
approver `user:sophia`, `CHG0030499` (`sys_id 41221e7e83ee0b10be487765eeaad3f2`).

| # | Point | Status | Live evidence |
|---|---|---|---|
| 1 | Runs in the real per-session container | **DEMONSTRATED** | `ados-prime-aba3c6cf-9af` |
| 2 | Requests a genuinely Tier 1/2 capability | **DEMONSTRATED** | `tier=2 risk=high` |
| 3 | Recorded as `pending_approval` | **DEMONSTRATED** | `+65.3s PENDING` |
| 4 | Does NOT execute while pending | **DEMONSTRATED** | 15 status polls **and 15 independent ServiceNow queries** across a 90s hold, all empty |
| 5 | The live agent keeps polling and sees the pending state | **DEMONSTRATED** | session state `waiting_approval`; one kernel call spanned 19:29:23.115 → 19:31:05.540 |
| 6 | Approved through the real HTTP endpoint with a user JWT | **DEMONSTRATED** | `+163.3s APPROVED` |
| 7 | Correct approver identity | **DEMONSTRATED** | `decidedBy=user:sophia` |
| 8 | Grant re-checked at decision time | **TESTED** | `test_the_grant_is_rechecked_at_decision_time` — the live run did not narrow a grant mid-hold |
| 9 | Executes exactly once after approval | **DEMONSTRATED** | one `CHG0030499`; second approval `409` |
| 10 | Approval and execution in durable audit records | **DEMONSTRATED** | `psql`: `status=executed decided_by=user:sophia` |
| 11 | Prime Agent receives the actual result | **DEMONSTRATED** | the agent reported `CHG0030499`, a number that did not exist before approval |
| 12 | Independently inspect ADOS rows | **DEMONSTRATED** | fresh `psql` queries outside the runner |
| 13 | Rejection/timeout as a secondary control | **TESTED** | `test_rejection_produces_no_side_effect_and_no_success_shaped_result`; not exercised live |
| 14 | Cleanup, no leftover containers/networks | **DEMONSTRATED** | 0 containers, 0 `ados-rt` networks after the run |

**Live negative controls in the same run:** self-approval with the agent's own
token → `401`; auditor → `403`; second approval → `409`. **pending → approved:
98.1 seconds.**

---

## 3. DEMONSTRATED

* **P6-A** — one autonomous mission, `qwen3-4b-16k` local provider, behind the
  P5 boundary: evidence fetched through the governed path, reasoned over in the
  kernel, a real `INC0010028` created, independently read back, closed, swept.
  `PASS 431.7s`.
* **P6-B** — a human held a live agent for **98.1 seconds** and then released a
  Tier 2 capability through the real approval endpoint. `PASS 202.0s`.
* **P6-D** — **two concurrent live sessions**, probed from inside both
  containers: each reached its own permitted destination by name (`HTTP 200`
  through its own relay) and its own relay by address, while the other
  session's runtime, relay and upstream were all `BLOCKED(OSError)` **by
  address**, and the other's destination name did not resolve. `DEFAULT_ROUTES 0`
  on both.
* **P7-A** — the `CreateChangeRequest` provenance fix, against a real
  ServiceNow record. Mission `7e6004ec-f687-4efe-a38e-b74f58ba929b`, request
  `df6538b2-a3ec-4a4f-8258-b6e483650503`, Tier 2, approved by `user:sophia`
  through the real HTTP endpoint. `CHG0030638`
  (`sys_id 5a2ba04b83e28b10be487765eeaad3b2`) read back independently carries
  `Capability request: df6538b2-…`, which resolves to exactly that
  `capability_requests` row — same session, same mission,
  `status=executed`. Closed, re-read to confirm `state=4`, and swept: 0 open
  records across both tables afterward, exactly one new record created.
  Full trace: [17-final-acceptance-report.md §P7-A](#p7-a-live-provenance-verification-2026-08-11)
  below.

## 4. TESTED (mechanism proven, live path did not exercise it)

* Token expiry lifecycle and failure-safe terminal state — 22 tests including an
  abandoned session whose row still reads `running`.
* Teardown resilience and orphan recording — including a `docker rm` that times
  out mid-teardown.
* Rejection path, decision-time grant re-check, concurrent double approval
  (`SELECT … FOR UPDATE`), auditor and below-limit refusals.
* The whole P6-C refusal surface: **42 regression tests** across MCP token
  authentication (26), server-side capability authorization (12), provenance
  (2) and kernel result shapes (2), with **10 negative controls**.
* **19 negative controls total** (10 in P6-C, 9 in P6-D). Every one: guard
  removed → targeted tests fail → guard restored → source verified
  byte-identical by sha256.

## 5. DESIGNED / PARTIAL

* **Orphan sweeping.** Teardown now records what it could not remove onto the
  session row as `orphaned …`. Nothing consumes that record — there is no
  sweeper, no alert, no reconciliation job.
* **Token expiry under a long real mission.** The lifetime rule is implemented
  and unit-tested; no live run has yet outlived its own token or come close to
  the 300s grace.
* **Rejection and approval timeout** as live events.

## 6. NOT BUILT

Session resume after an ADOS restart; heartbeats; scheduled or recurring
missions; subagents; agent-to-agent messaging; multi-session missions; a build
identity endpoint; automated cleanup of orphaned Docker resources or workspaces.

## 7. OPEN DEFECTS AND LIMITATIONS

1. ~~`CreateChangeRequest` provenance is fixed but not live-verified.~~
   **Closed 2026-08-11 (P7-A).** `CHG0030638` read back `PRESENT`, resolving to
   its exact `capability_requests` row. See §3 above.
2. **P7-A discovered a script-level defect in
   `scripts/prime_agent_approval_e2e.py`, unrelated to the provenance path.**
   Its post-execution assertion checks `marker not in short_description` with
   a case-sensitive Python `in`, while `_servicenow_matches()` earlier in the
   same script finds candidate records via a case-**insensitive** ServiceNow
   `LIKE` query. The live model wrote `[ados PRIME-AGENT…]` (lowercase) in the
   capability arguments it composed — legal input — and the case-sensitive
   check raised `RunFailed`, exiting the script with code 1 *after* the mission
   had already completed successfully and the record had already been
   correctly created, provenance-stamped, and (by the script's own `finally`
   block) cleaned up. Every fact used to confirm P7-A was independently
   re-derived from Postgres and ServiceNow directly, not from the script's exit
   status or printed narrative. Left unfixed: out of scope for a verification
   pass, and not part of the provenance fix under test.
3. ~~Stale gateway process — five occurrences.~~ **Closed 2026-08-11 (P7-B).**
   `uvicorn` without `--reload` serves the code it imported at start; caught in
   pre-flight five times, manually, by comparing process start time against
   `git log -1`. `orchestrate/runtime/build_identity.py` now computes a
   build's identity (git commit + dirty flag) once, at process import time,
   from real `.git` metadata — never from an env var, never from a caller —
   and reports it on `GET /healthz`. `verify_gateway_matches_source()` fetches
   it, compares against the caller's own source tree, and raises
   `StaleGatewayError` naming both sides on any mismatch;
   `prime_agent_approval_e2e.py` now runs this as the first action in
   `main()`, before any external side effect. Live-verified the same day: the
   gateway process already running at the start of P7-B (predating this fix)
   answered `/healthz` with no `build` key at all; restarted, it reported
   `7a40c8b…+dirty`, matching a fresh independent computation; pointed at a
   real second build (a `git worktree` checkout of the previous commit,
   `96b9447`) it correctly refused with `StaleGatewayError`. 13 new tests, 2
   negative controls (both restored byte-identical). See §P7-B below.
4. **Five environmental test failures** — `custom_agents.division`, unapplied
   migration from unrelated in-flight work.
5. **Three orphaned workspace directories from Aug 9** remain under
   `/var/folders/34/…/T/ados-mission-*`. They predate the teardown fix and are
   exactly the leak it now prevents; nothing sweeps them.
6. **Model narrative is unreliable, repeatedly and measurably.** In P6-B the
   agent's final answer said "Human approval is pending per the policy tier
   requirements" *after* approval had happened and the ticket existed. P7-A adds
   a third instance of a different kind: the model's own generated *capability
   arguments* varied in ways a downstream script did not anticipate (see #2).
   This is a property of the model, not a defect ADOS can fix — and it is
   precisely why `evaluate_mission()` takes no `final_answer` parameter and why
   every acceptance claim here derives from rows and external reads.
7. **Approval polling is not free.** The agent holds a kernel cell open for the
   whole human decision (98.1s in P6-B, 102.5s in P7-A), against a 900s skill
   budget inside an 1800s wall clock. A slow approver still fails the mission.
8. **Single-process approval state**, single-session missions, no resume.
9. **The kernel is not a security sandbox** — the container is the boundary.
10. **`close_code` is version-dependent** on ServiceNow, and its failure is
    silent-shaped.
11. **Two external pytest tests were not run** in P6-C/D/E/P7-A.

---

## 8. Evidence ledger

| Commit | Established | Kind |
|---|---|---|
| `10c51bb` | P1 — `RunPrimeRLMAgent` runs the real container; the simulated facade deleted | implementation + tests |
| `122b49b` | P3 — `runtime_session_id` populated from the session file (was always NULL) | implementation + tests |
| `e0f2261` | Architecture diagram colour-coded by what is actually proven | documentation |
| `4139b76` | P2 — `NotifyITHelpdesk` creates a real ServiceNow incident instead of a console simulation | implementation + tests |
| `ae4fc10` | The first end-to-end run through the whole chain — real incident `INC0010027` | **live** |
| `4edbb6b` | Two defects that run exposed: kernel verdicts read from `details.status`, and one request id instead of two | implementation + tests + negative control |
| `fed759f` | P4 — the human half of the approval round trip (nothing could previously move a row out of `pending_approval`) | implementation + tests |
| `38f432e` | P5 — an enforced egress allowlist replacing network placement | implementation + tests (3 docker) |
| `023192a` | P6-A — the acceptance runner verifies the boundary and the canonical id; mission `af0db406`, `INC0010028` | **live** |
| `258074a` | P6-B — a 98.1s human approval hold; mission `d00ff47c`, `CHG0030499`; plus the `CreateChangeRequest` provenance fix | **live** (approval) + tests (provenance fix) |
| `49f2156` | P6-C — 42 regression tests for refusals nothing had exercised; 10 negative controls | tests only |
| `96b9447` | P6-D — token expiry + failure-safe terminal state + teardown resilience; two live concurrent sessions | **live** (isolation) + tests (lifecycle) |

---

## 9. Production-readiness verdict

**Not production ready, and not described as such.**

What is genuinely true: the governed execution path is real end to end. A
containerized Prime Agent, behind an enforced per-session egress boundary,
authenticated by an opaque identity-only token, asks ADOS for capabilities it
cannot widen; ADOS decides tier and risk server-side, parks what needs a human,
executes through one choke point, writes a durable audit row, and stamps
provenance that resolves back to it. Acceptance derives from those rows and from
independently re-read external records — never from what the agent said. Three
separate live runs demonstrate that (P7-A brings this to four), and 19 negative
controls show the guards are load-bearing rather than decorative.

What that is not: a system anyone should point at production traffic. It runs
single-session missions in a single process with no resume, no heartbeats and no
orphan reconciliation; its approval model occupies a kernel cell for the
duration of a human decision; its cleanup records orphans that nothing sweeps;
and the most persistent operational hazard in the whole programme — a stale
gateway process the system could not detect on its own, caught five times by
hand — is now mechanically detectable rather than merely recorded (P7-B).

The honest summary is that the *architecture* has been demonstrated and the
*operations* have not.

---

## P7-A: Live Provenance Verification (2026-08-11)

Closes the one gap §7 flagged: the `CreateChangeRequest` provenance fix (landed
in `258074a`) had tests but no live ServiceNow record since. Tested at HEAD
`7a40c8b`; every file on the provenance/approval path (`servicenow_fields.py`,
`servicenow.py`, `mcp_gateway.py`, `runtime_approvals.py`, `prime.py`,
`egress.py`, `prime_agent_approval_e2e.py`, `mission.py`, `governance.py`)
confirmed byte-identical to that commit before the run — this pass made **zero**
code changes.

**Pre-flight.** The running gateway was 16 minutes older than HEAD — the fifth
occurrence of this class — restarted and confirmed DB-backed before proceeding.
Docker, Postgres, both runtime images, and ServiceNow auth all healthy.
ServiceNow swept clean: 0 open marker records in either table. 38 existing
provenance/approval regression tests passed pre-run.

**The live run.** Mission `7e6004ec-f687-4efe-a38e-b74f58ba929b`, session
`68691b58-96ef-4f39-8027-8436faa69f03`, request
`df6538b2-a3ec-4a4f-8258-b6e483650503`, `CreateChangeRequest` tier=2 risk=high,
approved by `user:sophia`. The runtime session (`runtime_sessions.state`) and
mission both reached `completed`; the single kernel event carries
`kernel_verdict=ok kernel_status=ok isError=False`, spanning
06:37:59.496 → 06:39:42.038 (102.5s) — the human decision inside it, exactly as
in P6-B.

**Independent chain, verified directly against Postgres and ServiceNow —**
not the runner's own printed verdict:

```
CHG0030638 (sys_id 5a2ba04b83e28b10be487765eeaad3b2)
  description contains: "Capability request: df6538b2-a3ec-4a4f-8258-b6e483650503"
    ↓ resolves to
capability_requests WHERE request_id = 'df6538b2-…'
  session_id  = 68691b58-96ef-4f39-8027-8436faa69f03   (matches)
  mission_id  = 7e6004ec-f687-4efe-a38e-b74f58ba929b   (matches)
  capability  = CreateChangeRequest
  status      = executed
  decided_by  = user:sophia
  result.outcome.output.number  = CHG0030638             (matches, byte-for-byte)
  result.outcome.output.sys_id  = 5a2ba04b83e28b10be487765eeaad3b2   (matches)
```

`evaluate_mission()` re-run against the DB-observed facts (not the log's
narrative) independently returns `succeeded=True, summary="mission accepted"`.
No record existed before approval (14 independent ServiceNow checks during the
90s hold, all empty). Closed to `state=4`, re-read fresh afterward to confirm —
not the PATCH response. Post-run sweep: **0 open** in both tables, exactly one
new record. Runtime container, both per-session networks, and the workspace
directory independently confirmed absent (not merely "reported removed").

**One defect found, precisely scoped.** The verification *script's own*
end-of-run assertion raised (`RunFailed`, exit 1) because it matches its sweep
marker against `short_description` with a case-sensitive Python `in`, while an
earlier ServiceNow-side query in the same script matches case-**insensitively**.
The live model wrote `[ados PRIME-AGENT…]` (lowercase) — valid input — and
tripped the mismatch, *after* the mission and the record were already correct.
Confirmed via `git diff HEAD` on the script: unmodified since `258074a`, so this
is pre-existing, newly exposed by this run's particular model output, not
introduced by anything here. It is a defect in the test harness, not in the
provenance path under test, and it is not fixed here — out of scope for a
verification pass.

**Regression.** 38 provenance/approval tests pass both before and after. Full
default suite: 697 passed, 0 failed, 8 deselected — measured against the
current working tree, which also carries an unrelated, uncommitted registry fix
from other in-flight work; the provenance/approval files themselves are
untouched.

**Verdict: the provenance fix is DEMONSTRATED, not merely TESTED.** Requirement
7 in the matrix above is updated accordingly.

---

## P7-B: Stale-Gateway / Build-Identity Hardening (2026-08-11)

Closes §7 item 3: five occurrences of a gateway process serving code older
than HEAD, detected only by comparing `ps` start time to `git log -1` by hand.

**Mechanism.** `orchestrate/runtime/build_identity.py`:
`compute_build_revision(repo_root)` reads real `.git` metadata (`git
rev-parse HEAD`, `git status --porcelain --untracked-files=no`) and returns a
`BuildRevision(commit, dirty, source)`; `CURRENT_BUILD_REVISION` is computed
once, at process import time, against the real repo — the instant uvicorn
loads the module is the instant "the code it imported at start" becomes
fixed, so that is the only correct point to read it, not per-request (a
per-request `git rev-parse` would report the *current* repo, not what the
process actually loaded). `GET /healthz` now returns it under `build`
(`commit`, `dirty`, `label`) — no new authenticated surface, no secrets, an
additive field on an endpoint that was already unauthenticated by design (the
same one the Docker `HEALTHCHECK` already calls with no auth header).
`verify_gateway_matches_source(base_url, repo_root)` fetches the gateway's
report, computes the caller's own expected identity independently, and raises
`StaleGatewayError` — naming both sides — the instant they differ.
`scripts/prime_agent_approval_e2e.py` calls it as the first action inside
`main()`, ahead of the ServiceNow-configured check and every external side
effect; an uncaught `StaleGatewayError` is handled distinctly from
`RunFailed` at the top level (`*** PREFLIGHT FAILED`, not `*** RUN FAILED`) —
a run that never started is not a run that failed.

**Why not an env var or a caller-supplied value.** Both were explicitly
excluded up front: an env var can be set to any string irrespective of what
is actually on disk, and an endpoint that let a caller assert its own commit
would let a stale process simply be told it is current — exactly the failure
mode this exists to close. Verified directly:
`test_caller_cannot_spoof_the_reported_identity` sends `commit`/`build`/
`git_sha` as query params and matching headers, all `"0"*40`; the response's
`build.commit` is unchanged.

**Two-build fixture.** Rather than fabricate an "old commit" string, the test
suite uses `git worktree add --detach` against this repository's own real
history — HEAD and HEAD's parent — producing two genuine, independently
verifiable commit identities. This exercises the real subprocess-based git
calls end to end rather than only the comparison operator. Two full gateway
processes (Docker/uvicorn on two ports) were considered and rejected as
disproportionate: they would additionally prove uvicorn's import-once
behaviour, a Python/uvicorn property this suite is not in the business of
re-verifying; `git worktree` is the smallest fixture that still exercises the
actual mechanism.

**Tests — 13 new, `backend/tests/test_build_identity.py`, all passing:**
current identity reported correctly; two real checkouts produce two distinct
verifiable identities; expected≠actual raises `StaleGatewayError` naming both
commits; expected==actual passes; an unverifiable ("unknown") identity never
satisfies the check, even against itself; dirty tracked changes are detected
and change the label; `/healthz` reports the real identity, not a
placeholder; a caller cannot spoof it; `/healthz`'s only keys are
`status`/`env`/`event_bus_backend`/`build`, and `build`'s only keys are
`commit`/`dirty`/`label` — no tokens, credentials, or connection strings;
existing `/healthz` fields are unchanged; `fetch_gateway_build_revision`
reads only the server's own report over a real HTTP round trip (FastAPI
`TestClient`, itself an `httpx.Client` subclass, running the real app and its
real lifespan); `verify_gateway_matches_source` passes against this repo and
fails against a real different checkout.

**Negative controls, both restored byte-identical (`shasum -a 256` before and
after):**
1. Disabled the actual comparison in `verify_build_matches` (`if True: return`
   ahead of the real check) — the 3 tests that depend on mismatch detection
   failed exactly as expected; the other 10 were unaffected.
2. Removed the guard binding `/healthz`'s reported identity to the process by
   adding a `commit` query param that overrides `CURRENT_BUILD_REVISION` —
   `test_caller_cannot_spoof_the_reported_identity` failed exactly as
   expected; the other 12 were unaffected.

**Live operator workflow, run against the real gateway, not simulated.** The
gateway already running at the start of this phase (PID 66626, started
12:04, predating every file this phase touched) answered `GET /healthz` with
`{"status":"ok","env":"local","event_bus_backend":"memory"}` — no `build` key
at all, itself an honest signal that this process had never loaded the new
code. Killed and relaunched (PID 75825); it then reported
`7a40c8bf7bc8fd4320c3cfa888a32c925110394b+dirty`
(`dirty=true` is correct: `backend/app/routers/health.py` and
`scripts/prime_agent_approval_e2e.py` carry real uncommitted tracked
changes from this phase). Running `verify_gateway_matches_source` against it
from a fresh Python process — independent of pytest, independent of the
E2E script — passed: expected and actual both
`7a40c8bf7bc8fd4320c3cfa888a32c925110394b+dirty`. A `git worktree` was then
checked out to the parent commit `96b9447` and used as a *wrong* expected
source against that same, correctly-running gateway:
`verify_gateway_matches_source` raised `StaleGatewayError`, printing
`expected: 96b9447…` / `actual: 7a40c8b…+dirty` — refusing to treat the
current, correct gateway as a match for a revision it was never told to
expect. The worktree was removed immediately after (`git worktree list`
confirms only the primary tree remains).

**Regression.** The 38 provenance/approval tests from P7-A still pass. Full
default suite: **710 passed, 0 failed, 8 deselected** (697 + the 13 new tests
here, exactly). No `custom_agents.division` failures reproduced in this run —
that migration fix, made as unrelated in-flight work before P7-A, remains
uncommitted and untouched by this phase; it is reported here as observed
fact, not claimed as part of this phase's scope.

**Not done, deliberately (per explicit scope):** no orphan sweeping, no
resume, no heartbeats, no scheduling, no subagents, no multi-session
missions, no ServiceNow behavior change, no governance semantics change, no
`--reload`, no silent auto-restart on mismatch. `StaleGatewayError` always
stops and reports; it never guesses or fixes the environment for the caller.

**Verdict: the stale-gateway defect is CLOSED as a detection gap.** It was
never claimed to be closed as an operational inconvenience — a human (or a
script wrapper) must still act on the diagnostic by restarting the gateway;
what changed is that this is now a machine-verifiable fact instead of a
manual comparison someone might skip.
