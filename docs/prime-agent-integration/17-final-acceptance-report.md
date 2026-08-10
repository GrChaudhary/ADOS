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
| 7 | The incident carries the canonical `request_id` and mission provenance | **DEMONSTRATED** (incident) / **TESTED** (change_request) | `servicenow_fields.py` | `test_servicenow_fields.py` (18), `test_capability_request_provenance.py` (7) | P6-A ticket body: `Capability request: cfaa6599-…`, `Mission: af0db406-…`, `Requested by: prime-runtime:mission:af0db406-…` | The `CreateChangeRequest` passthrough path was **ABSENT** in P6-B, fixed after; not live-verified since |
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

## 4. TESTED (mechanism proven, live path did not exercise it)

* `CreateChangeRequest` canonical provenance after the fix — 6 unit tests, 2
  integration tests through the real approval endpoint, negative-controlled. **No
  external record has been created since the fix.**
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

1. **`CreateChangeRequest` provenance is fixed but not live-verified.** P6-B
   measured it `ABSENT` on `CHG0030499`; the fix landed after, with tests. The
   next external run should show `PRESENT`.
2. **Stale gateway process — four occurrences.** `uvicorn` without `--reload`
   serves the code it imported at start. Caught in pre-flight four times; twice
   it would have invalidated the run. Nothing reports the commit a running
   gateway started from, so the check is manual. The fix is a build-identity
   endpoint, which is a feature, not coverage.
3. **Five environmental test failures** — `custom_agents.division`, unapplied
   migration from unrelated in-flight work.
4. **Three orphaned workspace directories from Aug 9** remain under
   `/var/folders/34/…/T/ados-mission-*`. They predate the teardown fix and are
   exactly the leak it now prevents; nothing sweeps them.
5. **Model narrative is unreliable, repeatedly and measurably.** In P6-B the
   agent's final answer said "Human approval is pending per the policy tier
   requirements" *after* approval had happened and the ticket existed. In P6-A's
   predecessor run a broken kernel produced a confident root-cause report
   blaming a database server that appeared nowhere in the incident. This is a
   property of the model, not a defect ADOS can fix — and it is precisely why
   `evaluate_mission()` takes no `final_answer` parameter and why every
   acceptance claim here derives from rows and external reads.
6. **Approval polling is not free.** The agent holds a kernel cell open for the
   whole human decision (98.1s in P6-B), against a 900s skill budget inside an
   1800s wall clock. A slow approver still fails the mission.
7. **Single-process approval state**, single-session missions, no resume.
8. **The kernel is not a security sandbox** — the container is the boundary.
9. **`close_code` is version-dependent** on ServiceNow, and its failure is
   silent-shaped.
10. **Two external pytest tests were not run** in P6-C/D/E.

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
separate live runs demonstrate that, and 19 negative controls show the guards
are load-bearing rather than decorative.

What that is not: a system anyone should point at production traffic. It runs
single-session missions in a single process with no resume, no heartbeats and no
orphan reconciliation; its approval model occupies a kernel cell for the
duration of a human decision; its cleanup records orphans that nothing sweeps;
one provenance fix is untested against a live instance; and the most persistent
operational hazard in the whole programme has been a stale gateway process that
the system cannot detect on its own.

The honest summary is that the *architecture* has been demonstrated and the
*operations* have not.
