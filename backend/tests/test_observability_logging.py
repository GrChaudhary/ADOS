"""
P10 — minimum structured observability for the six operator-visibility gaps
found by re-reading (not trusting) the P8/P9 claim that logging was already
"DEMONSTRATED": a mission starting, a capability parking for approval, an
execution landing at outcome_unknown, a reconciliation pass, and a build-
identity mismatch. (Orphan discovery/cleanup was already logged from
backend/app/main.py's periodic loop — confirmed by reading it, not added to
here.)

Two things this file proves, together:

1. The new log lines actually fire, with the fields a real alert would key
   on (`test_the_new_p10_log_lines_actually_fire`) — a caplog assertion that
   matches nothing would pass vacuously and prove nothing.
2. None of them, nor anything else on these same code paths, ever put a
   bearer token, a JWT, or a connector credential into a log record — run
   through the REAL `JsonLogFormatter` (observability.py), not just
   `record.getMessage()`, because `extra={...}` fields only show up in what
   a log shipper actually receives after that formatter runs, not in the
   bare message string.
"""
import json
import logging
import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.observability import JsonLogFormatter
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub
from orchestrate.runtime import build_identity
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown, reconcile_outcome_unknown
from orchestrate.runtime.prime import token_expiry

EXPENSIVE = {"_estimated_cost_usd": 300_000.0}
SECRET_PASSWORD = "S3cr3t-ServiceNow-Password-p10"


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", SECRET_PASSWORD)


async def _mission_and_session(capability="NotifyITHelpdesk", allowed=None):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="observability logging test", objective="o", domain="it",
            allowed_capabilities=allowed or [capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            token_expires_at=token_expiry(1800.0),
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


def _rendered(records) -> str:
    """Every captured record, run through the real production formatter —
    what a log shipper would actually receive, `extra={...}` included."""
    fmt = JsonLogFormatter()
    lines = []
    for r in records:
        # LogRecord is consumed by formatting once in real logging; caplog
        # keeps the object around, so re-formatting here is safe and exactly
        # mirrors what the installed handler would have produced.
        lines.append(fmt.format(r))
    return "\n".join(lines)


@pytest.fixture
def caplog_ados(caplog):
    caplog.set_level(logging.INFO, logger="ados")
    return caplog


async def test_the_new_p10_log_lines_actually_fire(caplog_ados, monkeypatch):
    """Not vacuous: each new log line from this phase is asserted present
    with the field an operator/alert would actually key on."""
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    # 1. capability parks for approval
    parked = await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))
    assert parked["status"] == "pending_approval"

    # 2. execution becomes outcome_unknown (autonomous path, connector UNKNOWN)
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _install_servicenow_transport(monkeypatch, timeout_handler)
    unknown = await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})
    assert unknown["status"] == "outcome_unknown"

    # 3. reconciliation pass completes
    await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)

    def no_match(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": []})

    await reconcile_outcome_unknown(
        async_session_factory, connector=ServiceNowConnector(transport=httpx.MockTransport(no_match)),
    )

    # 4. build-identity mismatch detected
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", build_identity.BuildRevision("a" * 40, False, "t"))
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision("b" * 40, False, "t"),
    )
    with pytest.raises(build_identity.StaleGatewayError):
        build_identity.verify_no_drift_since_process_start()

    joined = " | ".join(r.getMessage() for r in caplog_ados.records)

    assert "Capability request parked for human approval" in joined
    assert "Capability execution outcome unknown" in joined
    assert "Reconciliation pass complete" in joined
    assert "Build identity mismatch detected" in joined

    parked_record = next(r for r in caplog_ados.records if "parked for human approval" in r.getMessage())
    assert parked_record.capability == "NotifyITHelpdesk"
    assert parked_record.policy_tier is not None

    unknown_record = next(r for r in caplog_ados.records if "outcome unknown" in r.getMessage())
    assert unknown_record.request_id


async def test_no_token_or_password_ever_reaches_a_log_line(caplog_ados, monkeypatch):
    mission_id, session_id, token = await _mission_and_session()
    monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})

    # A realistic mixed pass: park, then a connector failure (touches
    # SERVICENOW_PASSWORD via the connector's own env, even though the
    # connector itself never logs), then reconciliation, then a stale build.
    await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _install_servicenow_transport(monkeypatch, boom)
    await request_capability.fn("NotifyITHelpdesk", {"summary": "x"})

    await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)

    def no_match(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": []})

    await reconcile_outcome_unknown(
        async_session_factory, connector=ServiceNowConnector(transport=httpx.MockTransport(no_match)),
    )

    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", build_identity.BuildRevision("c" * 40, False, "t"))
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision("d" * 40, False, "t"),
    )
    try:
        build_identity.verify_no_drift_since_process_start()
    except build_identity.StaleGatewayError:
        pass

    rendered = _rendered(caplog_ados.records)
    assert token not in rendered
    assert f"Bearer {token}" not in rendered
    assert SECRET_PASSWORD not in rendered
    # every emitted line must still be valid JSON (JsonLogFormatter's own contract)
    for line in rendered.splitlines():
        if line.strip():
            json.loads(line)
