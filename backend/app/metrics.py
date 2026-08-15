"""
P11 — the metrics export surface. Prometheus text exposition, in-process
only: no Prometheus/Alertmanager/Grafana is deployed by this repository (see
docs/prime-agent-integration/19-metrics-and-alerting.md for the alerting
contract an operator's own stack is expected to consume this against).

observability.py's original docstring refused a /metrics endpoint on the
grounds that nothing scrapes it. This is the revisit that docstring itself
called for — see its own updated text.

WHY THESE ARE MODULE-LEVEL, UNLIKE AdmissionControl
-----------------------------------------------------
integrations/admission_control.py's AdmissionControl is deliberately
per-IntegrationHub-instance, because concurrency ceilings are live process
state that must not leak between the ~800 tests that each construct their own
hub. A Counter is different: it is a lifetime-of-process count by definition,
the same thing a real Prometheus client library is for, and every test that
asserts against one reads a BEFORE and AFTER value and asserts the DELTA —
never an absolute value — for exactly that reason (this registry is shared
across the whole pytest session).

LABEL DISCIPLINE
-----------------
Every label on every metric below is a fixed, closed enum: a Capability name
(contracts.Capability, 33 values), or a small outcome/result/reason/gate
string this module itself defines. Nothing here ever takes a request_id,
mission_id, token, ServiceNow number, or agent-authored free text as a label
value — see backend/tests/test_metrics.py's
test_no_sensitive_or_high_cardinality_data_in_metrics for the proof, not just
this paragraph's word for it.
"""

from prometheus_client import Counter, Gauge, Histogram

missions_started_total = Counter(
    "ados_missions_started_total",
    "Prime Agent missions started (integrations/connectors/prime_runtime.py::_run).",
)

missions_completed_total = Counter(
    "ados_missions_completed_total",
    "Prime Agent missions reaching a terminal state.",
    ["outcome"],  # completed | failed
)

capability_executions_total = Counter(
    "ados_capability_executions_total",
    "Every capability call that reached a connector, by outcome "
    "(integrations/hub.py::IntegrationHub.invoke — the one choke point for "
    "both mission-starting and in-mission capability calls).",
    ["capability", "outcome"],  # outcome: executed | failed | outcome_unknown
)

capability_execution_duration_seconds = Histogram(
    "ados_capability_execution_duration_seconds",
    "Wall-clock time inside connector.execute() for one capability call.",
    ["capability"],
)

admission_rejections_total = Counter(
    "ados_admission_rejections_total",
    "Requests refused by admission control before any external side effect.",
    # capability_concurrency | mission_concurrency | approval_queue |
    # session_activity | mission_start_rate (P12 -- a fixed-window rate
    # limit, not a concurrency ceiling; see integrations/rate_limiter.py)
    ["gate"],
)

outcome_unknown_total = Counter(
    "ados_outcome_unknown_total",
    "Transitions of a capability_requests row into outcome_unknown — a "
    "connector could not confirm whether its action happened (P9).",
)

reconciliation_runs_total = Counter(
    "ados_reconciliation_runs_total",
    "Completed passes of orchestrate/runtime/capability_reconcile.py's two "
    "reconciliation functions, by whether the pass itself completed cleanly.",
    ["result"],  # success | failure
)

orphan_discovered_total = Counter(
    "ados_orphan_discovered_total",
    "Docker/workspace resource candidates claimed by one orphan sweep pass "
    "(orchestrate/runtime/orphan_sweep.py::sweep_once).",
)

orphan_cleanup_total = Counter(
    "ados_orphan_cleanup_total",
    "Orphan sweep outcomes, by result.",
    ["result"],  # cleaned | absent | failed | refused | unverifiable
)

authentication_failures_total = Counter(
    "ados_authentication_failures_total",
    "Failed /auth/login attempts (bad username or password).",
)

authorization_denials_total = Counter(
    "ados_authorization_denials_total",
    "Requests refused by an authorization check, by which one.",
    [
        "reason"
    ],  # role_readonly | tier_role_mismatch | over_approval_limit | inactive_account | not_in_grant |
    # policy_violation | already_decided (P15 -- a capability_requests row
    # already resolved when a second decision attempt raced it; see
    # backend/app/routers/runtime_approvals.py::_load_pending_or_404)
)

build_identity_drift_refusals_total = Counter(
    "ados_build_identity_drift_refusals_total",
    "Refusals from orchestrate/runtime/build_identity.py::verify_build_matches "
    "— the running process's source no longer matches what it loaded at import.",
)

token_expiry_refusals_total = Counter(
    "ados_token_expiry_refusals_total",
    "Refusals caused by a runtime session token that has expired or was "
    "never given a recorded expiry.",
)

# P14 — the two execution-boundary authoritative capability-manifest checks
# (integrations/hub.py::invoke(), integrations/connectors/dynamic.py::
# execute()). Both call CapabilityManifestRegistry.refresh_from_db(), a
# fresh Postgres read immediately before a capability may run, replacing
# a process-local in-memory cache that a DIFFERENT worker's hot_disable/
# activate/resume call would otherwise leave silently stale forever.
capability_registry_authoritative_lookups_total = Counter(
    "ados_capability_registry_authoritative_lookups_total",
    "Fresh, non-cached capability_manifests reads performed immediately "
    "before a capability may run, by result.",
    ["result"],  # allowed | hot_disabled | not_active | not_found | lookup_failed
)

capability_registry_stale_cache_detected_total = Counter(
    "ados_capability_registry_stale_cache_detected_total",
    "A capability's authoritative Postgres status disagreed with this "
    "process's own previously cached copy — direct evidence that a "
    "hot_disable/resume/deprecate/activate issued through a DIFFERENT "
    "worker's registry instance was just detected and picked up here, "
    "live, with no restart.",
)

# --- Scrape-time gauges -------------------------------------------------
#
# These four are set inside GET /metrics's own handler (backend/app/routers/
# metrics.py), from a fresh COUNT/MIN query, immediately before
# generate_latest() renders the registry. Postgres — not an in-process
# running total — is the source of truth for "how many rows are pending
# right now": an in-process counter would drift the moment a row is
# resolved by a path other than the one that incremented it (an approval
# decided via the API, a reconciliation pass, a direct SQL fix), and would
# reset to zero on every restart regardless of what is actually still
# sitting in the table.

approval_queue_depth = Gauge(
    "ados_approval_queue_depth",
    "Capability requests currently at status=pending_approval.",
)

approval_queue_oldest_age_seconds = Gauge(
    "ados_approval_queue_oldest_age_seconds",
    "Age of the oldest pending_approval row, in seconds. 0 when the queue is empty.",
)

outcome_unknown_open = Gauge(
    "ados_outcome_unknown_open",
    "Capability requests currently at status=outcome_unknown.",
)

outcome_unknown_oldest_age_seconds = Gauge(
    "ados_outcome_unknown_oldest_age_seconds",
    "Age of the oldest still-unresolved outcome_unknown row, in seconds. "
    "0 when none are open.",
)

# P12 — same "live COUNT/MIN query per scrape" pattern as the two gauge
# pairs above, for admission_leases (db/models/admission_lease.py). A
# non-zero, aging count is the operator-relevant signal: leases are held for
# at most one hub.invoke() call under normal operation, so anything still
# open past a normal call's duration is either genuine sustained load (see
# ADOSAdmissionSaturation) or a crashed process's leak waiting on the next
# periodic reclaim pass (see ADOSAdmissionLeaseStuck, both alert_rules.yml).
admission_leases_active = Gauge(
    "ados_admission_leases_active",
    "Currently-held admission_leases rows (Postgres-backed global admission "
    "control slots in use right now).",
    ["gate"],  # capability_concurrency | mission_concurrency
)

admission_lease_oldest_age_seconds = Gauge(
    "ados_admission_lease_oldest_age_seconds",
    "Age of the oldest currently-held admission lease, in seconds. 0 when none are held.",
    ["gate"],
)
