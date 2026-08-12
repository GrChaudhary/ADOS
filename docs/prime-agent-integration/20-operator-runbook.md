# P11 — Operator Runbook

For the operator of a **Model A** deployment (§5 of
[18-production-readiness-review.md](18-production-readiness-review.md) —
one controlled internal ADOS process, known internal users, bounded
concurrency, no multi-tenant isolation, no resume-after-death, no
heartbeats, no scheduling/subagents). This is the first formal runbook for
this integration; before P11 the closest equivalent was
[14-known-limitations.md](14-known-limitations.md) functioning informally
as one (§4D of doc 18).

**No credentials, tokens, or secrets appear in this document.** Every
procedure below uses commands and column/label names only.

Each entry: **Symptom** (what you observe) → **Verify** (confirm it's real,
independently) → **Remediation** (the safe fix) → **Do NOT** → **Verify
recovery** (independently, not by trusting the remediation step's own
output).

---

## 1. Docker/engine unavailable

**Symptom:** Mission starts fail immediately; `PrimeRuntimeConnector.
is_configured()` returns `False`; capability rows for `RunPrimeRLMAgent`
resolve through `ConsoleConnector` instead (audit row shows
`connector: "console"`, output `"[console] simulated RunPrimeRLMAgent"`).

**Verify:** `docker info` from the host running ADOS. A non-zero exit or a
connection-refused error confirms the daemon is down or unreachable.

**Remediation:** Restart the Docker daemon (Docker Desktop, or the
`docker`/`dockerd` service, depending on host). Confirm the ADOS process
itself does not need restarting — `is_configured()` is checked per-call, not
cached at startup.

**Do NOT:** manually flip a capability's connector registration, or disable
the connector-policy "prefer real over console" ordering (`integrations/hub.
py::default_hub`) to force console through — that produces green audit rows
for missions that never ran, exactly the failure mode this integration was
built to eliminate.

**Verify recovery:** `docker info` succeeds; a fresh mission's audit row
shows `connector: "prime-runtime"`, not `"console"`.

---

## 2. Gateway stale or build mismatch

**Symptom:** `ados_build_identity_drift_refusals_total` increments; log
lines `"Build identity mismatch detected — refusing to proceed"`; missions
or in-flight capability calls fail with `StaleGatewayError`.

**Verify:** `GET /healthz` reports `build.commit` — compare against
`git rev-parse HEAD` on the host. If they differ, the running process is
serving older code than what's checked out.

**Remediation:** Restart the ADOS process from the current commit
(`docker compose restart backend`, or restart the bare-`.venv` `uvicorn`
process). The refusal itself already prevented any mission or capability
call from running under stale code — nothing needs to be rolled back.

**Do NOT:** patch or hot-reload the running process instead of restarting
it; `verify_no_drift_since_process_start()` compares against
`CURRENT_BUILD_REVISION`, frozen at import time — nothing short of a real
process restart changes what it believes it is running.

**Note (inherited limitation, not new to P11):** this guard is a no-op
inside the shipped Docker image, which is built without `.git`
(`CURRENT_BUILD_REVISION.commit == "unknown"`) — it is only load-bearing for
a bare-`.venv`/`uvicorn --reload`-free deployment. If running the shipped
image, this scenario cannot be detected by ADOS itself; rely on your own
deployment pipeline's version tracking instead.

**Verify recovery:** `GET /healthz`'s `build.commit` matches
`git rev-parse HEAD`; a subsequent mission/capability call succeeds without
a `StaleGatewayError`.

---

## 3. Gateway unhealthy

**Symptom:** `GET /healthz` returns non-200, times out, or the process is
not listening at all.

**Verify:** `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/healthz`
(adjust host/port). Also check `docker compose ps` (or process status for a
bare run) for the backend container/process state.

**Remediation:** Check `docker compose logs backend` (or the process's own
stdout/log shipper) for the last lines before failure — the lifespan
function fails loud and fast on a Postgres connectivity problem
(`check_connectivity_or_raise()`), which is the single most common cause.
Confirm Postgres and Kafka (if `EVENT_BUS_BACKEND=kafka`) are themselves
healthy first (§10 below); restarting the backend before its dependencies
are up just repeats the failure. Restart the backend once dependencies are
confirmed healthy.

**Do NOT:** restart in a loop without reading the log line that explains
why the lifespan failed — `check_connectivity_or_raise` and the LangGraph
checkpointer setup both fail loud specifically so this is diagnosable
rather than a silent hang.

**Verify recovery:** `GET /healthz` returns 200 with `status: "ok"`; `GET
/metrics` (also unauthenticated) also returns 200 — a second, independent
endpoint confirming the process is genuinely serving traffic, not just that
one specific route works.

---

## 4. Mission failure

**Symptom:** A `MissionRow.status` reads `"failed"`; the corresponding
`RuntimeSessionRow.failure_reason` is populated.

**Verify:** Read `failure_reason` directly — every failure path (objective
raised, container wouldn't start, teardown left leftovers, cancellation)
writes a specific reason there, not a generic string. Cross-reference
`ados_missions_completed_total{outcome="failed"}` for the rate this is
happening at, and `ados_capability_executions_total{outcome="failed"}` if
the mission's own capability calls (not just the mission-starting call)
are also failing.

**Remediation:** This depends entirely on the reason. A model/provider
failure (see [14-known-limitations.md](14-known-limitations.md)'s provider
section) needs no ADOS-side action — it's a property of the configured
model. A Docker-level failure (`docker run failed`) needs §1/§10's
diagnosis. There is **no resume** (§5 of doc 18) — the only remediation for
a mission that should still happen is to start a **new** mission with the
same objective; the failed one's row stays as the honest historical record.

**Do NOT:** mutate `MissionRow.status`/`RuntimeSessionRow.state` by hand to
make a failed mission look completed — the audit trail's entire value is
that it reflects what actually happened.

**Verify recovery:** if a new mission was started to redo the work, confirm
its own `status` reaches `"completed"` and its capability rows show the
expected `executed` outcomes.

---

## 5. Stuck approval

**Symptom:** `ados_approval_queue_depth` or
`ados_approval_queue_oldest_age_seconds` is elevated (see the alerting
contract in [19-metrics-and-alerting.md](19-metrics-and-alerting.md)); a
mission is sitting at `waiting_approval`.

**Verify:** `GET /runtime/capability-requests?status_filter=pending_approval`
(JWT-authenticated) lists exactly what's waiting, ordered by age.

**Remediation:** An authorized human decides — `POST /runtime/capability-
requests/{id}/approve` or `/reject`, through the real UI/API, by someone
with the appropriate role and `approval_limit_usd`. If the queue is
systemically backed up (not one stuck request but many), check whether
`ados_admission_rejections_total{gate="approval_queue"}` is also firing —
that means `max_pending_approvals` itself is being hit and new Tier 1/2
requests are being refused outright, not merely queued; see §13 below.

**Do NOT:** approve a request you have not actually evaluated just to clear
the count, and do not approve a request whose owning session might already
be dead — the approval endpoint already refuses a request whose session is
not `_LIVE_STATES` (409) or whose token has no recorded expiry (P10's
`_confirm_token_expiry_recorded_or_409`), but it cannot stop you from
approving a request whose agent is technically still live but long past
being useful to notify.

**Verify recovery:** the request's row shows `status` moved to `executed`/
`failed`/`outcome_unknown`/`denied` (never lingering at `executing` — if it
does, see §6); `ados_approval_queue_depth` drops.

---

## 6. `outcome_unknown`

**Symptom:** `ados_outcome_unknown_total` incremented, or
`ados_outcome_unknown_open` is non-zero; a capability row's `status` reads
`outcome_unknown`.

**Verify:** This is not a bug — it's the honest, by-design terminal state
for "ADOS cannot yet say whether the action happened" (P9). Read the row's
`result.reconciliation_attempts` (if any reconciliation has already run
over it) and `reason` for context.

**Remediation:** `python scripts/reconcile_capability_requests.py` — runs
both passes: stall-detection (moves any row stuck `executing` past the
stall bound to `outcome_unknown`) and reconciliation (checks the row's
canonical `request_id` against the real external system's own records). A
positive match resolves the row to `executed`, recording exactly which
external record it found. No match — or a query that could not be answered
— **leaves the row exactly where it was**; this is deliberate, not a bug in
the script.

**Do NOT:** manually flip the row's `status` to `executed` or `failed`
without independently confirming the real-world outcome — that is precisely
the guess this state exists to refuse to make automatically. Do not retry
the original action "just in case" — a capability whose outcome is
genuinely unknown may have already happened once; a manual retry could be
the second time.

**Verify recovery:** re-query the row (`GET /runtime/capability-requests/
{id}`, or `psql`) and confirm `status` moved off `outcome_unknown` — and if
it resolved to `executed`, independently check the named external record
yourself (the `result.reconciled_match` field names the table and
`sys_id`/`number`) rather than trusting the row's own claim.

---

## 7. Reconciliation

**Symptom:** You want to confirm reconciliation is running / ran cleanly, or
`ados_reconciliation_runs_total{result="failure"}` fired.

**Verify:** Reconciliation for `capability_requests` (stall-detection +
outcome-unknown resolution) is **manual only, not scheduled** — deliberately
(see `orchestrate/runtime/capability_reconcile.py`'s own docstring). It only
ever runs when `scripts/reconcile_capability_requests.py` is invoked, by
hand or from an operator's own cron. This is different from
`runtime_sessions` reconciliation (`session_reconcile.py`), which **is**
automatic, on `Settings.orphan_reconcile_interval_seconds` (default 300s) —
see §8.

**Remediation:** Run `python scripts/reconcile_capability_requests.py`. A
`result="failure"` metric means the pass itself raised (most likely a
transient Postgres error) — check application logs around that timestamp
for the exception; the pass is safe to simply re-run (`FOR UPDATE SKIP
LOCKED` makes it safe against concurrent invocations too).

**Do NOT:** assume reconciliation "already happened" just because time has
passed — without a human or a cron job invoking the script, `outcome_unknown`
rows sit exactly where they are indefinitely, by design.

**Verify recovery:** re-run the script and confirm `mark-stalled` and
`reconcile` both report `0` newly-affected rows (nothing left to do), or
that the specific rows you were tracking moved off `outcome_unknown`.

---

## 8. Orphaned resources

**Symptom:** `ados_orphan_discovered_total` or
`ados_orphan_cleanup_total{result="failed"}` incrementing; `docker ps -a`
shows `ados-prime-*`/`ados-relay-*`/`ados-rt-*`/`ados-rt-out-*` resources
you don't expect; a `runtime_sessions.failure_reason` mentions "orphaned."

**Verify:** `docker ps -a --filter name=ados-prime-` and `docker network ls
--filter name=ados-rt-` to see what's actually present. Cross-reference
against `runtime_sessions` rows in a terminal state — a resource is only
ever swept if it traces back to a specific, terminal session row (never
matched by name alone).

**Remediation:** This is normally **automatic** — `_reconcile_and_sweep_
orphans_periodically` in `backend/app/main.py` runs on `Settings.
orphan_reconcile_interval_seconds` (default 300s; `0` disables it). If it's
disabled, or you want an immediate pass: `python scripts/sweep_orphans.py`
(`--limit`, `--lease-seconds` available). A resource that comes back
`refused` means its Docker label didn't match the claiming session — this
is the sweeper correctly declining to touch something it can't prove it
owns; investigate that resource by hand rather than forcing removal.

**Do NOT:** `docker rm -f`/`docker network rm` an `ados-prime-*`/`ados-rt-*`
resource yourself without first checking whether its owning session is
genuinely terminal — a live mission's container looks identical by name.
Check the `ados.session_id` label (`docker inspect -f '{{index
.Config.Labels "ados.session_id"}}' <name>`) against the session row's own
`state` first.

**Verify recovery:** `docker ps -a --filter name=ados-prime-` /
`docker network ls --filter name=ados-rt-` show nothing left for the
session(s) in question; the session's own `events` column (JSON) carries
`orphan_sweep.cleaned` entries for each resource.

---

## 9. Token/session expiry problems

**Symptom:** A runtime session can no longer act (`_Denied("session token
expired")`); `ados_token_expiry_refusals_total` incrementing; or a human
approver gets a 409 with "cannot be confirmed live" when trying to approve
a request.

**Verify:** `SELECT state, token_expires_at FROM runtime_sessions WHERE
session_id = '<id>'`. A `token_expires_at` in the past explains an expired-
session refusal (expected, correct behavior — the mission's wall-clock
budget was exhausted). A **NULL** `token_expires_at` on a row whose `state`
still reads `running`/`waiting_approval` is a legacy/fossil shape (pre-P6-D,
or created by a debugging tool that bypassed the real creation path) — see
[14-known-limitations.md](14-known-limitations.md) and doc 18 §16.6 for the
full history; every session created by the real path has set this
unconditionally since P6-D.

**Remediation:** An expired session is not a bug — start a new mission if
the work still needs doing. A NULL-expiry fossil row cannot be approved
through (P10's `_confirm_token_expiry_recorded_or_409` refuses it) but
**can** still be rejected (no side effect) — use `POST /runtime/capability-
requests/{id}/reject` to close out any parked requests it's carrying.

**Do NOT:** manually set `token_expires_at` on an existing row to "revive"
it — a session whose real container/process is long gone should not be
made to look live again; start a new mission instead.

**Verify recovery:** the fossil row's parked requests all show `status:
"denied"`; no `pending_approval` request remains attached to a session with
a NULL `token_expires_at` (this exact condition is what
`test_a_null_expiry_session_cannot_authorize_approval` pins in the suite).

---

## 10. Unexpected ServiceNow marked records

**Symptom:** A ServiceNow record exists carrying the
`[ADOS PRIME-AGENT INTEGRATION TEST]` marker (or, for real production
traffic, a `Capability request: <uuid>` provenance line) that you did not
expect, or one that should have been closed is still open.

**Verify:** Query ServiceNow directly for records carrying the marker text
or the specific `request_id` from the ADOS-side `capability_requests` row
(`result.reconciled_match` if reconciled, or the row's own `request_id`
otherwise — never trust the row's own claim without an independent read).

**Remediation:** For a genuine production record, this reflects a real
action ADOS took — there's nothing to "fix" beyond normal ServiceNow
lifecycle management (the incident/change is real). For a leftover test
record (should not happen in a controlled internal deployment running only
real missions, but possible if someone ran one of the `scripts/
*_e2e.py`/`servicenow_smoke.py` acceptance scripts against a real
production ServiceNow instance by mistake): **close it** (ServiceNow state
7), matching the pattern every acceptance script in this programme already
uses — closing preserves the audit trail; deleting does not.

**Do NOT:** delete a ServiceNow record to "clean up" — every script and
convention in this programme closes records, never deletes them, specifically
so the record itself remains an honest trace of what happened.

**Verify recovery:** an independent `GET` on the record (not the PATCH's own
echo response) confirms `state=7`; if you were chasing a specific
`request_id`, confirm no other open record still carries it.

---

## 11. Postgres backup/restore

**Symptom:** You need to take a backup, or restore from one (disaster
recovery drill, or a genuine incident).

**Backup:** `scripts/backup_postgres.sh [db-name]` — runs `pg_dump -Fc`
through the real, already-running Postgres container's own tools. Writes to
`./backups/<db>-<timestamp>.dump` by default (`BACKUP_DIR` to override).

**Restore:** `scripts/restore_postgres.sh <dump-file> <target-db>` — the
target database is a **required, explicit** argument with no default,
specifically so a mistyped/omitted argument can never silently overwrite
the live database. `--clean --if-exists` means existing objects in the
target are dropped and recreated — read that as "this really does replace,"
not merge.

**Do NOT:** run `restore_postgres.sh` against the live database name as a
"quick test" — always restore into a scratch/independent database first
(`backend/tests/test_backup_restore.py`'s own pattern) and verify before
ever pointing it at anything live.

**Verify recovery:** after a restore, independently query the target
database for the specific rows/tables you expected to see, rather than
trusting the script's own "restore complete" output. `test_backup_restore.py`
(`docker`-marked) is the reference implementation of this exact check.

**Explicitly out of scope, not invented here:** point-in-time recovery (WAL
archiving), offsite/off-host storage, a retention policy, and a rehearsal
cadence are operational decisions for whoever runs this in production — see
doc 18 §16.3.

---

## 12. Database recovery (beyond backup/restore)

**Symptom:** Postgres itself is down, corrupted, or the container/volume is
gone.

**Verify:** `docker compose ps postgres` / `docker inspect ados-postgres-1`;
`docker exec ados-postgres-1 pg_isready -U ados`.

**Remediation:** If the container is merely stopped: `docker compose up -d
postgres`, wait for its healthcheck (`pg_isready`), then confirm ADOS's own
`GET /healthz` succeeds. If the **volume** (`ados_postgres_data`) is lost or
corrupted, this is not recoverable from within the running system — restore
from the most recent backup (§11) into a fresh volume. Run `alembic upgrade
head` after any fresh volume/restore, before starting the backend (the
compose stack's `migrate` service does this automatically; the bare-`.venv`
workflow needs it run explicitly).

**Do NOT:** start the backend against a freshly-created, unmigrated
database — every documented boot path runs `alembic upgrade head` first;
skipping it produces confusing "relation does not exist" errors rather than
a clean failure.

**Verify recovery:** `GET /healthz` returns 200; `alembic current` reports
the expected head revision; a known-good row (from before the incident, if
restored from backup) is present and correct.

---

## 13. Rate-limit/admission-control rejection

**Symptom:** A capability call or mission start returns `status: "failed"`
with an error containing `"admission control"`, or `status: "denied"` with
a reason mentioning `"approval queue is at capacity"` or `"capability
request limit"`. `ados_admission_rejections_total{gate=...}` incrementing.

**Verify:** The `gate` label tells you which of the four ceilings fired:

| Gate | What it means | Where the limit lives |
|---|---|---|
| `mission_concurrency` | Too many concurrent Prime Agent (Docker container) missions | `Settings.max_concurrent_prime_missions` (default 3) |
| `capability_concurrency` | Too many concurrent capability executions of any kind | `Settings.max_concurrent_capability_executions` (default 10) |
| `approval_queue` | The pending-approval backlog is already at capacity | `Settings.max_pending_approvals` (default 50) |
| `session_activity` | One session has made too many capability requests over its lifetime | `Settings.max_capability_requests_per_session` (default 200) |

**Remediation:** For `mission_concurrency`/`capability_concurrency`: if this
is a transient burst, no action is needed — the rejection is by design
(§2 of this doc's own admission-control section) and the caller should
retry later. If it recurs persistently, confirm the Docker host actually
has headroom (CPU/memory/pids — each container already carries its own
resource limits) before raising the limit; raising it without checking
headroom just moves the failure mode from "refused cleanly" to "the host
runs out of resources." For `approval_queue`: this compounds with §5 above
— clear the backlog (get requests approved/rejected) rather than only
raising the limit, since a bigger queue that nobody is clearing just delays
the same problem. For `session_activity`: investigate whether the flagged
session is a runaway/looping agent (check its `capability_requests` rows
for a repeating pattern) before assuming it just needs a bigger budget.

**Do NOT:** raise any of these four limits reflexively in response to a
single rejection — each exists specifically to protect a real resource
(Docker containers, the event loop, human approval capacity, one session's
fair share). Confirm the underlying resource genuinely has headroom first.

**Verify recovery:** subsequent calls of the same kind succeed (`status`
other than the admission-control failure/denial shape); if a limit was
deliberately raised, confirm via `GET /metrics` that the relevant
concurrency gauge/counter behaves as expected under the new ceiling, not
just that the one blocked call now goes through.

**Scope boundary:** all four gates are single-process, in-memory-for-the-
hot-path (the two `IntegrationHub` gates) or Postgres-transaction-serialized
(the two `mcp_gateway` gates) — see
[19-metrics-and-alerting.md](19-metrics-and-alerting.md)'s scope-boundary
paragraph. They bound one ADOS process, matching Model A's single-process
envelope; they are not a distributed rate limiter.

---

## 14. Metrics/alert interpretation

**Symptom:** You're looking at `GET /metrics` or an alert fired from your
own Prometheus/Alertmanager (P11 does not deploy either — see
[19-metrics-and-alerting.md](19-metrics-and-alerting.md)) and need to know
what it means.

**Verify:** `GET /metrics` (unauthenticated, like `/healthz`) returns
Prometheus text exposition — every metric name, its type, and its label set
are documented in full in
[19-metrics-and-alerting.md](19-metrics-and-alerting.md)'s catalog. That
same document's "Alerting contract" table maps every condition worth
alerting on to why it matters and what to do — this entry exists so this
runbook has a pointer, not a duplicate copy that can drift out of sync.

**Do NOT:** treat the presence of `/metrics` as a claim that alerting is
wired up — metric **emission** is implemented and tested; alert **delivery**
(an actual Prometheus scrape target, Alertmanager rules, paging) is an
external dependency this repository does not run. If nothing is scraping
`/metrics`, nothing pages anyone, ever, regardless of what the counters say.

**Verify recovery:** N/A — this entry is a pointer, not a remediation.

---

## Scope note

This runbook is written for **Model A** (§5 of doc 18) — one ADOS process, a
human operator actually watching, bounded concurrency via the new admission
control. It does not cover multi-host Docker orchestration, cross-replica
metrics aggregation, distributed rate limiting, or automated mission resume
— none of those exist in this codebase (by design, not omission — see doc
18 §5 and §12). If your deployment needs those, this runbook does not apply
to you yet.
