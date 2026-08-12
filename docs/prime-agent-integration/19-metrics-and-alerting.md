# P11 — Metrics and Alerting

Closes the last item in [18-production-readiness-review.md](18-production-readiness-review.md)
§6/§11 that was still `NOT BUILT` after P10: "Metrics/alerting." Everything
else in that blocker set (Postgres role, build-identity coverage, six
observability log lines, backups) was already closed.

## What this is, and what it is deliberately not

`backend/app/observability.py` originally declined a `/metrics` endpoint on
the grounds that "there is no scraper to serve" — a stated, deliberate rule
against building infrastructure with no consumer. This document is the
revisit that decision itself called for, prompted by P11's explicit
instruction to close the metrics/alerting gap.

**Built:** an in-process metrics registry (`backend/app/metrics.py`, using
`prometheus_client`, a pure-Python library with no server component) and a
`GET /metrics` endpoint (`backend/app/routers/metrics.py`) exporting it in
Prometheus text format.

**Not built:** a Prometheus server, an Alertmanager, a Grafana dashboard, or
any alert-delivery mechanism. This repository still runs no monitoring stack
of its own. `GET /metrics` is the **export surface** — the thing an
operator's own Prometheus deployment scrapes. The "alerting contract" below
is a specification for wiring that scrape target into rules and routing that
live outside this repository, not a claim that paging or notification is
implemented here. **Do not read this document as "alerting is implemented."
Metric emission is implemented and tested; alert delivery is an external
dependency.**

This satisfies the instruction's own conditional: "If Prometheus/client
metrics are appropriate and infrastructure exists, use it. If not, do not
invent an elaborate monitoring stack: establish the metric interface/export
surface and document the external infrastructure dependency." No Prometheus
infrastructure exists in this repository (confirmed: no such service in
`docker-compose.yml`, no such dependency in `requirements.txt` before this
phase) — so the export surface is what got built, and the dependency is
named here rather than invented.

## Access

`GET /metrics` (and its `/api/v1/metrics` alias, mounted like every other
router) is **unauthenticated**, matching `/healthz`'s existing posture — a
scraper does not carry a session JWT, and the endpoint returns only counts,
durations, and label values, never a secret. Keeping this endpoint off a
public network boundary is an operator responsibility — see
[20-operator-runbook.md](20-operator-runbook.md)'s "metrics/alert
interpretation" entry.

## Metric catalog

Every metric name is prefixed `ados_`. Every label is a **fixed, closed
enum** defined in `backend/app/metrics.py` — never a `request_id`,
`mission_id`, session token, ServiceNow number, or agent-authored free-text
argument. `backend/tests/test_metrics.py::
test_no_sensitive_or_high_cardinality_data_in_metrics` proves this by
running a realistic pass carrying a token, a ServiceNow password, distinct
mission/request UUIDs, and a distinctive free-text argument, then asserting
none of them appear anywhere in `GET /metrics`'s rendered output.

| Metric | Type | Labels | Meaning | Hook point |
|---|---|---|---|---|
| `ados_missions_started_total` | Counter | none | A Prime Agent mission (container session) started | `integrations/connectors/prime_runtime.py::_run` |
| `ados_missions_completed_total` | Counter | `outcome`={completed,failed} | A mission reached a terminal state | `prime_runtime.py::_finalize_session` |
| `ados_capability_executions_total` | Counter | `capability` (33-value closed enum from `contracts.Capability`), `outcome`={executed,failed,outcome_unknown} | A capability call reached a connector | `integrations/hub.py::IntegrationHub.invoke()` — the one choke point for every capability execution in the system, mission-starting and in-mission alike |
| `ados_capability_execution_duration_seconds` | Histogram | `capability` | Wall-clock time inside `connector.execute()` | same hook |
| `ados_admission_rejections_total` | Counter | `gate`={capability_concurrency,mission_concurrency,approval_queue,session_activity} | A request was refused by admission control before any external side effect | the four gates — see §2 below and [18](18-production-readiness-review.md)'s admission-control section |
| `ados_approval_queue_depth` | Gauge | none | Capability requests currently `pending_approval`, queried live at scrape time | `GET /metrics` handler |
| `ados_approval_queue_oldest_age_seconds` | Gauge | none | Age of the oldest pending approval, 0 when empty | same |
| `ados_outcome_unknown_total` | Counter | none | A `capability_requests` row transitioned into `outcome_unknown` (P9) | `mcp_gateway.py` (synchronous UNKNOWN), `capability_reconcile.py::mark_stalled_executions_unknown` (stall detection) |
| `ados_outcome_unknown_open` | Gauge | none | `outcome_unknown` rows not yet resolved, queried live | `GET /metrics` handler |
| `ados_outcome_unknown_oldest_age_seconds` | Gauge | none | Age of the oldest unresolved one, 0 when none | same |
| `ados_reconciliation_runs_total` | Counter | `result`={success,failure} | A pass of `mark_stalled_executions_unknown` or `reconcile_outcome_unknown` completed (success) or raised (failure) | `orchestrate/runtime/capability_reconcile.py` |
| `ados_orphan_discovered_total` | Counter | none | Docker/workspace resource candidates claimed by an orphan sweep pass | `orchestrate/runtime/orphan_sweep.py::sweep_once` |
| `ados_orphan_cleanup_total` | Counter | `result`={cleaned,absent,failed,refused} | Outcome of an orphan-sweep candidate | same |
| `ados_authentication_failures_total` | Counter | none | A failed `/auth/login` attempt | `backend/app/routers/auth.py::login` |
| `ados_authorization_denials_total` | Counter | `reason`={role_readonly,tier_role_mismatch,over_approval_limit,inactive_account,not_in_grant,policy_violation} | A request was refused by an authorization check | `rbac.py` (3 sites), `mcp_gateway.py` (grant check), `integrations/hub.py` (policy violation) |
| `ados_build_identity_drift_refusals_total` | Counter | none | The running process refused to proceed because its source no longer matches what it loaded at import | `orchestrate/runtime/build_identity.py::verify_build_matches` — the single raise site for all three callers |
| `ados_token_expiry_refusals_total` | Counter | none | A runtime session token was expired or never given a recorded expiry | `mcp_gateway.py::_resolve_session`, `runtime_approvals.py::_confirm_token_expiry_recorded_or_409` |

### Why these labels are safe

- `capability` — one of `contracts.Capability`'s 33 fixed enum members, never
  the free-text `capability_id` a dynamically-onboarded capability carries
  (that value lives in `CapabilityCall.input`, never read for a label).
- `outcome`, `result`, `reason`, `gate` — each a small, hand-enumerated set
  of fixed strings defined in `backend/app/metrics.py` itself; nothing here
  is interpolated from a database row, an argument, or an error message.
- No metric anywhere takes a `request_id`, `mission_id`, `session_id`,
  username, or ServiceNow record number as a label — those are exactly the
  high-cardinality/identifying values P11's own instructions named as
  unsafe, and doing so would also make every label set unbounded (a new
  time series per request), which is the standard operational reason to
  avoid them independent of the sensitivity argument.

## Alerting contract

No Alertmanager is deployed by this repository. The table below is the
specification an operator wires into their own Prometheus + Alertmanager
(or equivalent) against the `/metrics` scrape target above. "Condition" is
written as a PromQL-shaped expression for concreteness, not a literal rule
file shipped here.

| Condition | Why it matters | Operator action |
|---|---|---|
| `rate(ados_missions_started_total[10m]) > 0` and no corresponding `ados_missions_completed_total` within `max_wall_clock_seconds` | A mission may be stuck — no resume exists (§5 below), so a hung mission needs a human, not a retry | Check `GET /metrics`, `docker ps` for the session's container, and the mission row's `runtime_sessions.state`; see runbook "mission failure" |
| `ados_approval_queue_depth > 20` sustained | Approvals are backing up faster than a human is clearing them — Tier 1/2 work is stalled | Check `/runtime/capability-requests?status=pending_approval`; assign an approver; see runbook "stuck approval" |
| `ados_approval_queue_oldest_age_seconds > 3600` | A specific request has waited over an hour — likely nobody is watching the queue | Same as above, prioritized by age |
| `increase(ados_outcome_unknown_total[1h]) > 0` | A capability execution's real-world outcome is genuinely unknown (P9) — this is the anomaly the whole exactly-once design exists to surface, never silently retried | Run `scripts/reconcile_capability_requests.py`; see runbook "outcome_unknown" |
| `ados_outcome_unknown_open > 0` sustained for hours | Reconciliation is not resolving the backlog — either nobody has run it, or the external system genuinely has no matching record | Run reconciliation by hand; if still unresolved, this needs a human decision, not automation (see [18](18-production-readiness-review.md) §8 on why auto re-execution is deliberately not built) |
| `increase(ados_reconciliation_runs_total{result="failure"}[1h]) > 0` | A reconciliation pass itself raised (most likely Postgres) rather than completing | Check application logs around the same timestamp; see runbook "reconciliation" |
| `increase(ados_orphan_discovered_total[1h]) > 0` with `ados_orphan_cleanup_total{result="failed"}` also increasing | Docker/workspace resources are leaking and the automatic sweep can't clean them | `docker ps`/`docker network ls` by hand; see runbook "orphaned resources" |
| `increase(ados_authentication_failures_total[5m]) > 20` | Possible credential-guessing activity against `/auth/login` | Review who is failing to log in; consider whether an account needs a password reset (`scripts/reset_user_password.py`) |
| `increase(ados_authorization_denials_total{reason="policy_violation"}[15m]) > 0` | A capability has no connector registered, or its manifest was hot-disabled — a caller is being refused work that should be running | Check `integrations/hub.py` registration and `GET /capabilities/manifests` for hot-disabled entries |
| `increase(ados_build_identity_drift_refusals_total[5m]) > 0` | The running process is serving stale code relative to its own source tree — every refusal here is a mission or capability call that did NOT proceed under drifted code, which is correct, but the process itself needs a restart | Restart the ADOS process from the current commit; see runbook "gateway stale or build mismatch" |
| `increase(ados_token_expiry_refusals_total[5m]) > 5` | An unusually large burst of expired/malformed sessions — possibly a client retrying against dead credentials, or a wave of long-running missions all hitting their wall-clock budget at once | Check whether this correlates with a specific mission batch or a client bug |
| `increase(ados_admission_rejections_total{gate="mission_concurrency"}[5m]) > 0` sustained | The Prime Agent mission ceiling (`max_concurrent_prime_missions`, default 3) is genuinely being hit — real demand for missions exceeds Model A's configured envelope | Either this is expected (a burst) and self-resolves, or it recurs — in which case raise the limit deliberately (`Settings.max_concurrent_prime_missions`) after confirming the Docker host has headroom; see [18](18-production-readiness-review.md) §5 for the single-Docker-host constraint this bounds against |
| `increase(ados_admission_rejections_total{gate="capability_concurrency"}[5m]) > 0` sustained | The general capability-execution ceiling is saturated | Same as above, for `max_concurrent_capability_executions` |
| `increase(ados_admission_rejections_total{gate="approval_queue"}[5m]) > 0` | New Tier 1/2 requests are being refused outright because the approval backlog is already at `max_pending_approvals` | This compounds with the queue-depth alert above — an operator needs to clear the backlog, not just raise the limit | 
| `increase(ados_admission_rejections_total{gate="session_activity"}[5m]) > 0` for one session | One mission is hammering the gateway with capability requests — either a runaway agent loop or a mission that has genuinely outgrown the per-session budget | Inspect that session's `capability_requests` rows for a repeating pattern; consider whether the mission needs to be stopped, not just have its limit raised |
| No successful scrape of `/metrics` at all | The process is down, or `/metrics` is unreachable — this is itself the last-resort "the app might be down" signal, since it shares fate with every other endpoint | Check `GET /healthz`; see runbook "gateway unhealthy" |

## Scope boundary

This is **single-process, in-process metrics**. There is no metrics
aggregation across replicas, no push gateway, and no long-term storage —
`GET /metrics` reflects only the state of the one ADOS process answering the
request, at that moment (counters since process start; gauges computed live
from Postgres at scrape time). This is the correct-sized mechanism for
Model A (§5 of [18](18-production-readiness-review.md) — single ADOS
process); it is explicitly not a distributed-observability platform, and
building one would be over-building for an architecture that has no second
process to aggregate across. Revisit if and when Model B/C's multi-process
or multi-host requirements are actually being built.

See [20-operator-runbook.md](20-operator-runbook.md) for what to do when any
of the above fires.
