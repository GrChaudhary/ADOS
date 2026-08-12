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
    ["gate"],  # capability_concurrency | mission_concurrency | approval_queue | session_activity
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
    ["result"],  # cleaned | absent | failed | refused
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
    ],  # role_readonly | tier_role_mismatch | over_approval_limit | inactive_account | not_in_grant | policy_violation
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
