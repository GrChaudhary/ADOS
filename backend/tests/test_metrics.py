"""
P11 — every metric in backend/app/metrics.py fires at the lifecycle point it
claims to, with the label values it claims to use, and never carries a
token, password, mission/request id, or agent-authored free text.

WHY DELTA, NEVER ABSOLUTE
--------------------------
prometheus_client's default REGISTRY is process-global — shared across the
entire pytest session, not reset per test. Every test here reads a metric's
value BEFORE its action and asserts the DELTA after, exactly the discipline
this file exists to prove is followed (see test_not_vacuous below, which
would pass trivially against an absolute non-zero check even if the metric
had been wired to the wrong call site).

Reuses the same fixtures/patterns test_observability_logging.py already
built for the P10 log lines these metrics sit right next to — the two files
are proving the same lifecycle points are observable, one for logs, one for
metrics.
"""

import uuid

import httpx
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text

from backend.app import mcp_gateway, metrics
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.rbac import Role, User, authorize_governance_decision, create_access_token, get_current_user
from contracts import Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from fastapi import HTTPException
from integrations.connectors.prime_runtime import PrimeRuntimeConnector
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import IntegrationHub, default_hub
from orchestrate.runtime import build_identity
from orchestrate.runtime.base import SessionOutcome, SessionState
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown, reconcile_outcome_unknown

EXPENSIVE = {"_estimated_cost_usd": 300_000.0}
SECRET_PASSWORD = "S3cr3t-ServiceNow-Password-p11"
FREE_TEXT_MARKER = "definitely-not-a-label-value-p11-xyz"


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", SECRET_PASSWORD)


@pytest.fixture(autouse=True)
async def _clean_capability_tables():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


def _counter_value(counter, **labels) -> float:
    child = counter.labels(**labels) if labels else counter
    return child._value.get()


def _histogram_count(hist, **labels) -> float:
    # prometheus_client stores each bucket's EXACT (non-cumulative) count
    # internally — cumulative summing only happens at collect()/export
    # time — so the total observation count is the sum across all buckets,
    # not any single bucket's value.
    child = hist.labels(**labels) if labels else hist
    return sum(b.get() for b in child._buckets)


async def _mission_and_session(capability="NotifyITHelpdesk", allowed=None):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="metrics test", objective="o", domain="it",
            allowed_capabilities=allowed or [capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


def _install_servicenow_transport(monkeypatch, handler):
    hub = default_hub()
    monkeypatch.setattr(
        hub.registry, "connectors_for",
        lambda cap: [ServiceNowConnector(transport=httpx.MockTransport(handler))],
    )
    monkeypatch.setattr("integrations.hub.default_hub", lambda: hub)


# --- missions ----------------------------------------------------------------

class _StubRuntime:
    """Mirrors PrimeAgentRuntime's contract without touching Docker — same
    pattern test_runtime_session_lifecycle.py's _StandInRuntime uses."""

    def __init__(self, **_kw):
        self.container_name = None
        self.workspace = None

    async def start(self, spec, token):
        self.container_name = f"ados-prime-{spec.session_id[:12]}"
        self.workspace = f"/tmp/ados-mission-{spec.mission_id[:8]}"

    async def run_objective(self, spec):
        return SessionOutcome(
            state=SessionState.COMPLETED, final_answer="root cause found",
            tool_execution_count=1, tool_success_count=1,
        )

    async def teardown(self):
        return []


def _mission_call():
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input={"prompt": "explain the outage", "domain": "it"},
        requested_by="user:metrics-test",
        incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def test_missions_started_and_completed_totals(monkeypatch):
    monkeypatch.setattr("orchestrate.runtime.prime.PrimeAgentRuntime", _StubRuntime)

    before_started = _counter_value(metrics.missions_started_total)
    before_completed = _counter_value(metrics.missions_completed_total, outcome="completed")

    await PrimeRuntimeConnector()._run(_mission_call(), "explain the outage")

    assert _counter_value(metrics.missions_started_total) == before_started + 1
    assert _counter_value(metrics.missions_completed_total, outcome="completed") == before_completed + 1


async def test_missions_completed_total_records_failed_outcome(monkeypatch):
    class _FailingStub(_StubRuntime):
        async def run_objective(self, spec):
            return SessionOutcome(state=SessionState.FAILED, tool_execution_count=0, tool_success_count=0)

    monkeypatch.setattr("orchestrate.runtime.prime.PrimeAgentRuntime", _FailingStub)
    before = _counter_value(metrics.missions_completed_total, outcome="failed")

    await PrimeRuntimeConnector()._run(_mission_call(), "explain the outage")

    assert _counter_value(metrics.missions_completed_total, outcome="failed") == before + 1


# --- capability executions + duration + outcome_unknown ----------------------

async def test_capability_executions_total_and_duration_executed(monkeypatch):
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"result": {"sys_id": "abc123", "number": "INC0000001"}})

    _install_servicenow_transport(monkeypatch, ok_handler)

    before_exec = _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="executed")
    before_dur = _histogram_count(metrics.capability_execution_duration_seconds, capability="NotifyITHelpdesk")

    result = await request_capability.fn("NotifyITHelpdesk", {"summary": FREE_TEXT_MARKER})
    assert result["status"] == "executed"

    assert _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="executed") == before_exec + 1
    assert _histogram_count(metrics.capability_execution_duration_seconds, capability="NotifyITHelpdesk") == before_dur + 1


async def test_capability_executions_total_failed_and_outcome_unknown(monkeypatch):
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _install_servicenow_transport(monkeypatch, boom)
    before_failed = _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="failed")
    result = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert result["status"] == "failed"
    assert _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="failed") == before_failed + 1

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_servicenow_transport(monkeypatch, timeout_handler)
    before_unknown_exec = _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="outcome_unknown")
    before_unknown_total = _counter_value(metrics.outcome_unknown_total)

    result = await request_capability.fn("NotifyITHelpdesk", {"summary": "y"})
    assert result["status"] == "outcome_unknown"

    assert _counter_value(metrics.capability_executions_total, capability="NotifyITHelpdesk", outcome="outcome_unknown") == before_unknown_exec + 1
    assert _counter_value(metrics.outcome_unknown_total) == before_unknown_total + 1


# --- reconciliation ------------------------------------------------------------

async def test_reconciliation_runs_total_success(monkeypatch):
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_servicenow_transport(monkeypatch, timeout_handler)
    await request_capability.fn("NotifyITHelpdesk", {"summary": "z"})

    before_stall = _counter_value(metrics.reconciliation_runs_total, result="success")
    before_stalled_unknown = _counter_value(metrics.outcome_unknown_total)
    await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)
    assert _counter_value(metrics.reconciliation_runs_total, result="success") == before_stall + 1

    def no_match(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": []})

    before_recon = _counter_value(metrics.reconciliation_runs_total, result="success")
    await reconcile_outcome_unknown(async_session_factory, connector=ServiceNowConnector(transport=httpx.MockTransport(no_match)))
    assert _counter_value(metrics.reconciliation_runs_total, result="success") == before_recon + 1


async def test_reconciliation_runs_total_failure():
    def broken_factory():
        raise RuntimeError("simulated Postgres failure")

    before = _counter_value(metrics.reconciliation_runs_total, result="failure")
    with pytest.raises(RuntimeError):
        await mark_stalled_executions_unknown(broken_factory, stall_seconds=0)
    assert _counter_value(metrics.reconciliation_runs_total, result="failure") == before + 1


# --- orphan sweep ---------------------------------------------------------------

async def test_orphan_metrics_move_by_the_report_returned():
    """Doesn't require a live Docker daemon: whatever `sweep_once` actually
    reports (cleaned/absent/failed/refused — see orphan_sweep.py, already
    proven correct by P7-C's own docker-marked tests), the metric hook must
    move by exactly that amount. This proves the HOOK, not orphan_sweep's own
    correctness — that's out of scope here."""
    from orchestrate.runtime.orphan_sweep import sweep_once

    async with async_session_factory() as db:
        mission = MissionRow(title="orphan metrics test", objective="o", domain="it", allowed_capabilities=[], status="failed")
        db.add(mission)
        await db.flush()
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="failed",
            failure_reason="orphaned container ados-prime-deadbeef",
        )
        db.add(sess)
        await db.commit()

    before_discovered = _counter_value(metrics.orphan_discovered_total)
    before_by_result = {
        r: _counter_value(metrics.orphan_cleanup_total, result=r)
        for r in ("cleaned", "absent", "failed", "refused")
    }

    report = await sweep_once(async_session_factory)

    assert report.claimed > 0, "this session's failure_reason should have produced claimable candidates"
    assert _counter_value(metrics.orphan_discovered_total) == before_discovered + report.claimed
    for result_name, count in (
        ("cleaned", report.cleaned), ("absent", report.absent),
        ("failed", report.failed), ("refused", report.refused),
    ):
        assert _counter_value(metrics.orphan_cleanup_total, result=result_name) == before_by_result[result_name] + count


# --- auth / authz ----------------------------------------------------------------

async def test_authentication_failures_total(client):
    before = _counter_value(metrics.authentication_failures_total)
    resp = client.post("/auth/login", json={"username": "no-such-user-p11", "password": "wrong"})
    assert resp.status_code == 401
    assert _counter_value(metrics.authentication_failures_total) == before + 1


def _user(role=Role.MANAGER, approval_limit=100.0, active=True):
    return User(
        user_id="u1", username="u1", display_name="U1",
        role=role, approval_limit_usd=approval_limit, active=active,
    )


def test_authorization_denials_total_role_readonly():
    before = _counter_value(metrics.authorization_denials_total, reason="role_readonly")
    with pytest.raises(HTTPException):
        authorize_governance_decision(_user(role=Role.AUDITOR), policy_tier=0)
    assert _counter_value(metrics.authorization_denials_total, reason="role_readonly") == before + 1


def test_authorization_denials_total_tier_role_mismatch():
    before = _counter_value(metrics.authorization_denials_total, reason="tier_role_mismatch")
    with pytest.raises(HTTPException):
        authorize_governance_decision(_user(role=Role.MANAGER), policy_tier=2)
    assert _counter_value(metrics.authorization_denials_total, reason="tier_role_mismatch") == before + 1


def test_authorization_denials_total_over_approval_limit():
    before = _counter_value(metrics.authorization_denials_total, reason="over_approval_limit")
    with pytest.raises(HTTPException):
        authorize_governance_decision(_user(role=Role.MANAGER, approval_limit=10.0), policy_tier=0, estimated_cost_usd=999.0)
    assert _counter_value(metrics.authorization_denials_total, reason="over_approval_limit") == before + 1


def test_authorization_denials_total_inactive_account():
    token = create_access_token(_user(active=False))
    before = _counter_value(metrics.authorization_denials_total, reason="inactive_account")
    with pytest.raises(HTTPException):
        get_current_user(request=None, credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert _counter_value(metrics.authorization_denials_total, reason="inactive_account") == before + 1


async def test_authorization_denials_total_not_in_grant(monkeypatch):
    mission_id, session_id, token = await _mission_and_session(allowed=["FetchIncidentEvidence"])
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    before = _counter_value(metrics.authorization_denials_total, reason="not_in_grant")
    result = await request_capability.fn("NotifyITHelpdesk", {})
    assert result["status"] == "denied"
    assert _counter_value(metrics.authorization_denials_total, reason="not_in_grant") == before + 1


async def test_authorization_denials_total_policy_violation():
    bare_hub = IntegrationHub()  # no connectors registered — see hub.py's own docstring
    call = CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR,
        input={}, requested_by="test", incident_id=str(uuid.uuid4()),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )
    before = _counter_value(metrics.authorization_denials_total, reason="policy_violation")
    response = await bare_hub.invoke(call)
    assert response.status.value == "failed"
    assert _counter_value(metrics.authorization_denials_total, reason="policy_violation") == before + 1


# --- build identity + token expiry -----------------------------------------------

def test_build_identity_drift_refusals_total(monkeypatch):
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", build_identity.BuildRevision("a" * 40, False, "t"))
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision("b" * 40, False, "t"),
    )
    before = _counter_value(metrics.build_identity_drift_refusals_total)
    with pytest.raises(build_identity.StaleGatewayError):
        build_identity.verify_no_drift_since_process_start()
    assert _counter_value(metrics.build_identity_drift_refusals_total) == before + 1


async def test_token_expiry_refusals_total_mcp_gateway(monkeypatch):
    from datetime import datetime, timedelta, timezone

    async with async_session_factory() as db:
        mission = MissionRow(title="expiry metrics test", objective="o", domain="it", allowed_capabilities=["FetchIncidentEvidence"], status="running")
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            token_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db.add(sess)
        await db.commit()

    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})
    before = _counter_value(metrics.token_expiry_refusals_total)
    result = await request_capability.fn("FetchIncidentEvidence", {})
    assert result["status"] == "denied"
    assert _counter_value(metrics.token_expiry_refusals_total) == before + 1


# --- /metrics endpoint -------------------------------------------------------------

def test_metrics_endpoint_renders_valid_prometheus_text(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for name in (
        "ados_missions_started_total", "ados_missions_completed_total",
        "ados_capability_executions_total", "ados_capability_execution_duration_seconds",
        "ados_admission_rejections_total", "ados_approval_queue_depth",
        "ados_approval_queue_oldest_age_seconds", "ados_outcome_unknown_total",
        "ados_outcome_unknown_open", "ados_outcome_unknown_oldest_age_seconds",
        "ados_reconciliation_runs_total", "ados_orphan_discovered_total",
        "ados_orphan_cleanup_total", "ados_authentication_failures_total",
        "ados_authorization_denials_total", "ados_build_identity_drift_refusals_total",
        "ados_token_expiry_refusals_total",
    ):
        assert name in body, f"{name} missing from /metrics output"


async def test_approval_queue_and_outcome_unknown_gauges(client, monkeypatch):
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    client.get("/metrics")  # prime the gauges once so "before" reflects reality
    before_depth = metrics.approval_queue_depth._value.get()

    parked = await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))
    assert parked["status"] == "pending_approval"

    client.get("/metrics")
    assert metrics.approval_queue_depth._value.get() == before_depth + 1
    assert metrics.approval_queue_oldest_age_seconds._value.get() >= 0.0


# --- no sensitive or high-cardinality data ------------------------------------------

async def test_no_sensitive_or_high_cardinality_data_in_metrics(client, monkeypatch):
    """The metrics analogue of test_observability_logging.py's
    test_no_token_or_password_ever_reaches_a_log_line: a realistic mixed
    pass through park -> connector failure -> reconciliation -> stale build,
    each carrying identifying content that must never surface as a metric
    label or value."""
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    await request_capability.fn("NotifyITHelpdesk", {**EXPENSIVE, "summary": FREE_TEXT_MARKER})

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _install_servicenow_transport(monkeypatch, boom)
    await request_capability.fn("NotifyITHelpdesk", {"summary": FREE_TEXT_MARKER})

    await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)

    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", build_identity.BuildRevision("c" * 40, False, "t"))
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision("d" * 40, False, "t"),
    )
    try:
        build_identity.verify_no_drift_since_process_start()
    except build_identity.StaleGatewayError:
        pass

    body = client.get("/metrics").text
    assert token not in body
    assert SECRET_PASSWORD not in body
    assert str(mission_id) not in body
    assert str(session_id) not in body
    assert FREE_TEXT_MARKER not in body
