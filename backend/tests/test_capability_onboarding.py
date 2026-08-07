"""
backend/app/routers/capability_onboarding.py — the 5-turn onboarding REST
surface. Same event-loop-affinity reasoning as test_capabilities.py's own
manifest tests: httpx.ASGITransport keeps app lifespan + HTTP calls on one
asyncio loop, safe for these non-streaming endpoints. The MCP-native happy
path drives real inspection/synthesis/sandbox-testing (real Docker) against
tests/fixtures/mcp_native_sample — no mocks in the loop, proving the whole
bridge (sentinel enum, DynamicCapabilityConnector, hot-disable fix,
dynamic_registry merge) end to end. The OpenAPI happy path monkeypatches
only the sandbox step's HTTP call (already covered directly by
tests/test_onboarding_sandbox_runner.py) so this file stays focused on
router/state-machine/RBAC correctness, not re-deriving lower-level HTTP
mechanics.
"""

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from orchestrate.moa import dynamic_registry
from orchestrate.onboarding import sandbox_runner

_MCP_NATIVE_FIXTURE = str(Path(__file__).parent.parent.parent / "tests" / "fixtures" / "mcp_native_sample")
_OPENAPI_FIXTURE_SPEC = str(Path(__file__).parent.parent.parent / "tests" / "fixtures" / "openapi_sample" / "openapi.json")
_RAW_CODE_FIXTURE = str(Path(__file__).parent.parent.parent / "tests" / "fixtures" / "raw_code_sample")
_UNCLASSIFIABLE_FIXTURE = str(Path(__file__).parent.parent.parent / "tests" / "fixtures" / "unclassifiable_sample")

_needs_docker = pytest.mark.skipif(not sandbox_runner.is_docker_available(), reason="Docker required")


def _auth(role: Role) -> dict:
    user = User(user_id=f"test-{role.value}", username=f"test-{role.value}", display_name=f"Test {role.value.title()}", role=role, approval_limit_usd=1_000_000_000.0)
    return {"Authorization": f"Bearer {create_access_token(user)}"}


_ADMIN_AUTH = _auth(Role.ADMIN)
_MANAGER_AUTH = _auth(Role.MANAGER)
_AUDITOR_AUTH = _auth(Role.AUDITOR)


@pytest.fixture(autouse=True)
def _clean_dynamic_registry():
    dynamic_registry.clear()
    yield
    dynamic_registry.clear()


@pytest.mark.asyncio
async def test_start_session_requires_auth():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_start_session_forbidden_for_manager():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_MANAGER_AUTH)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_start_session_inspects_real_mcp_native_fixture():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_ADMIN_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "inspected"
    tool_names = {t["name"] for t in body["report"]["tools"]}
    assert {"echo_message", "add_numbers"} <= tool_names


@pytest.mark.asyncio
async def test_start_session_nonexistent_path_fails_with_422():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions", json={"source_url": "/no/such/path"}, headers=_ADMIN_AUTH)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_start_session_unexpected_inspection_error_is_a_clean_422_not_a_500(monkeypatch):
    """Turn 1 inspects an arbitrary, untrusted external repo — a real bug
    report surfaced a raw 500 here. inspector.py normalizes its own known
    failure modes (bad git, unreadable files) to ValueError/RuntimeError,
    but the router itself must also treat ANY exception from this call as
    a clean, documented 422 — not just the two types someone happened to
    anticipate — since an inspection failure is expected/normal for this
    step (per this file's own module docstring), not exceptional."""
    from orchestrate.onboarding import inspector

    async def _boom(*args, **kwargs):
        raise PermissionError("simulated: something inspector.py didn't anticipate")

    monkeypatch.setattr(inspector, "inspect", _boom)

    marker_source = f"{_MCP_NATIVE_FIXTURE}#unexpected-error-test"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/capability-onboarding/sessions", json={"source_url": marker_source}, headers=_ADMIN_AUTH,
            )
            assert response.status_code == 422
            assert "PermissionError" in response.json()["detail"] or "simulated" in response.json()["detail"]

            # The session is still saved server-side as FAILED — same
            # contract as every other Turn-1 inspection failure (docs/
            # PHASE7's own convention) — not silently dropped just because
            # this particular exception type wasn't ValueError/RuntimeError.
            listed = await client.get("/capability-onboarding/sessions", headers=_ADMIN_AUTH)
    matching = [s for s in listed.json() if s["source_url"] == marker_source]
    assert len(matching) == 1
    assert matching[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_synthesize_rejected_when_session_not_yet_inspected():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions/does-not-exist/synthesize", json={"selected_tool_name": "x", "domain": "hr", "capability_id": "x.y"}, headers=_ADMIN_AUTH)
    assert response.status_code == 404


@_needs_docker
@pytest.mark.asyncio
async def test_full_mcp_native_happy_path_activates_and_is_dispatchable():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120.0) as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_ADMIN_AUTH)
            assert start.status_code == 200
            session_id = start.json()["id"]
            assert start.json()["status"] == "inspected"

            synthesize = await client.post(
                f"/capability-onboarding/sessions/{session_id}/synthesize",
                json={"selected_tool_name": "add_numbers", "domain": "hr", "capability_id": "echo-sample.add_numbers", "estimated_cost_usd": 0.0},
                headers=_ADMIN_AUTH,
            )
            assert synthesize.status_code == 200, synthesize.text
            assert synthesize.json()["status"] == "synthesized"

            risk = await client.post(f"/capability-onboarding/sessions/{session_id}/risk-proposal", headers=_ADMIN_AUTH)
            assert risk.status_code == 200, risk.text
            assert risk.json()["status"] == "risk_reviewed"
            assert risk.json()["risk_profile"][0]["tier"] == 2  # EXECUTIVE_APPROVAL — every onboarded action floors here

            manifests_after_propose = await client.get("/capabilities/manifests", headers=_ADMIN_AUTH)
            proposed_entry = next(m for m in manifests_after_propose.json() if m["capability_id"] == "echo-sample.add_numbers")
            assert proposed_entry["status"] == "proposed"

            sandbox = await client.post(
                f"/capability-onboarding/sessions/{session_id}/sandbox-test",
                json={"sample_input": {"a": 4, "b": 5}}, headers=_ADMIN_AUTH,
            )
            assert sandbox.status_code == 200, sandbox.text
            assert sandbox.json()["status"] == "sandbox_tested"
            assert sandbox.json()["sandbox_result"]["passed"] is True

            # Same admin who ran every prior turn CAN activate — proves the
            # proposed_by="onboarding-agent" fixed-constant design (§8.3
            # "never self-approve" would otherwise block this exact admin).
            activate = await client.post(f"/capability-onboarding/sessions/{session_id}/activate", headers=_ADMIN_AUTH)
            assert activate.status_code == 200, activate.text
            assert activate.json()["status"] == "activated"

            manifests_after_activate = await client.get("/capabilities/manifests", headers=_ADMIN_AUTH)
            active_entry = next(m for m in manifests_after_activate.json() if m["capability_id"] == "echo-sample.add_numbers")
            assert active_entry["status"] == "active"

            # The connector is genuinely wired, not just the manifest status.
            connector = app.state.integration_hub.dynamic_capability_connector
            assert "echo-sample.add_numbers" in connector._dispatch

            # And it's choosable by MOA's HR domain pod (dynamic_registry merge).
            from orchestrate.moa.graph import _get_domain_actions

            hr_actions = _get_domain_actions("hr", app.state.integration_hub.manifests)
            assert "add_numbers" in hr_actions
            assert hr_actions["add_numbers"].capability_id == "echo-sample.add_numbers"

            # A real live invocation through the actual REST invoke endpoint.
            invoke = await client.post(
                "/capabilities/invoke",
                json={
                    "capability": "DynamicCapability",
                    "incidentId": "inc-onboarding-smoke",
                    "requestedBy": "test",
                    "input": {"capability_id": "echo-sample.add_numbers", "a": 10, "b": 32},
                    "governance": {"policyTier": 2, "approvedBy": "test-admin"},
                },
                headers=_ADMIN_AUTH,
            )
            assert invoke.status_code == 200, invoke.text
            assert invoke.json()["status"] == "succeeded"
            assert invoke.json()["output"] == {"result": 42}


@pytest.mark.asyncio
async def test_start_session_raw_code_requires_entrypoint_path():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/capability-onboarding/sessions",
                json={"source_url": _RAW_CODE_FIXTURE, "track_hint": "raw_code"},
                headers=_ADMIN_AUTH,
            )
    assert response.status_code == 400
    assert "entrypoint_path" in response.json()["detail"]


@_needs_docker
@pytest.mark.asyncio
async def test_full_raw_code_happy_path_activates_and_is_dispatchable():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120.0) as client:
            start = await client.post(
                "/capability-onboarding/sessions",
                json={"source_url": _RAW_CODE_FIXTURE, "track_hint": "raw_code", "entrypoint_path": "tool.py"},
                headers=_ADMIN_AUTH,
            )
            assert start.status_code == 200, start.text
            session_id = start.json()["id"]
            assert start.json()["status"] == "inspected"
            assert start.json()["report"]["raw_code_entrypoint"] == "tool.py"

            synthesize = await client.post(
                f"/capability-onboarding/sessions/{session_id}/synthesize",
                json={"selected_tool_name": "add_numbers", "domain": "hr", "capability_id": "raw-code-sample.add_numbers", "estimated_cost_usd": 0.0},
                headers=_ADMIN_AUTH,
            )
            assert synthesize.status_code == 200, synthesize.text
            assert synthesize.json()["status"] == "synthesized"

            risk = await client.post(f"/capability-onboarding/sessions/{session_id}/risk-proposal", headers=_ADMIN_AUTH)
            assert risk.status_code == 200, risk.text

            sandbox = await client.post(
                f"/capability-onboarding/sessions/{session_id}/sandbox-test",
                json={"sample_input": {"a": 4, "b": 5}}, headers=_ADMIN_AUTH,
            )
            assert sandbox.status_code == 200, sandbox.text
            assert sandbox.json()["status"] == "sandbox_tested"
            assert sandbox.json()["sandbox_result"]["passed"] is True

            activate = await client.post(f"/capability-onboarding/sessions/{session_id}/activate", headers=_ADMIN_AUTH)
            assert activate.status_code == 200, activate.text
            assert activate.json()["status"] == "activated"

            connector = app.state.integration_hub.dynamic_capability_connector
            assert "raw-code-sample.add_numbers" in connector._dispatch

            invoke = await client.post(
                "/capabilities/invoke",
                json={
                    "capability": "DynamicCapability",
                    "incidentId": "inc-raw-code-smoke",
                    "requestedBy": "test",
                    "input": {"capability_id": "raw-code-sample.add_numbers", "a": 10, "b": 32},
                    "governance": {"policyTier": 2, "approvedBy": "test-admin"},
                },
                headers=_ADMIN_AUTH,
            )
            assert invoke.status_code == 200, invoke.text
            assert invoke.json()["status"] == "succeeded"
            assert invoke.json()["output"] == {"result": 42}


@pytest.mark.asyncio
async def test_openapi_track_synthesize_requires_test_base_url():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": str(Path(_OPENAPI_FIXTURE_SPEC).parent)}, headers=_ADMIN_AUTH)
            session_id = start.json()["id"]
            assert start.json()["status"] == "inspected"

            synthesize = await client.post(
                f"/capability-onboarding/sessions/{session_id}/synthesize",
                json={"selected_tool_name": "read_ticket", "domain": "support", "capability_id": "zendesk.read_ticket"},
                headers=_ADMIN_AUTH,
            )
    assert synthesize.status_code == 400
    assert "test_base_url" in synthesize.json()["detail"]


@pytest.mark.asyncio
async def test_openapi_track_happy_path_with_mocked_sandbox_http_call(monkeypatch):
    async def _fake_sandbox_test(**kwargs):
        assert kwargs["test_base_url"] == "https://staging.zendesk.example.com"
        return sandbox_runner.SandboxResult(passed=True, evidence_summary="mocked pass", raw_output="{}", duration_ms=5)

    monkeypatch.setattr(sandbox_runner, "run_openapi_sandbox_test", _fake_sandbox_test)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": str(Path(_OPENAPI_FIXTURE_SPEC).parent)}, headers=_ADMIN_AUTH)
            session_id = start.json()["id"]

            synthesize = await client.post(
                f"/capability-onboarding/sessions/{session_id}/synthesize",
                json={
                    "selected_tool_name": "read_ticket", "domain": "support", "capability_id": "zendesk.read_ticket",
                    "test_base_url": "https://staging.zendesk.example.com", "production_base_url": "https://api.zendesk.example.com",
                },
                headers=_ADMIN_AUTH,
            )
            assert synthesize.status_code == 200, synthesize.text

            risk = await client.post(f"/capability-onboarding/sessions/{session_id}/risk-proposal", headers=_ADMIN_AUTH)
            assert risk.status_code == 200

            sandbox = await client.post(
                f"/capability-onboarding/sessions/{session_id}/sandbox-test",
                json={"sample_input": {"ticket_id": "T-1"}, "acknowledge_live_call": True}, headers=_ADMIN_AUTH,
            )
            assert sandbox.status_code == 200, sandbox.text

            activate = await client.post(f"/capability-onboarding/sessions/{session_id}/activate", headers=_ADMIN_AUTH)
            assert activate.status_code == 200, activate.text

    connector = app.state.integration_hub.dynamic_capability_connector
    assert "zendesk.read_ticket" in connector._dispatch
    assert connector._dispatch["zendesk.read_ticket"].runtime["base_url"] == "https://api.zendesk.example.com"


# ---------------------------------------------------------------------
# Workdir cleanup (orchestrate/onboarding/cleanup.py) — a real
# tempfile.mkdtemp(prefix="ados-onboarding-") directory stands in for what
# a real remote clone's local_path looks like, so the cleanup guard (which
# only ever touches its own pipeline's tempdirs, never an arbitrary local
# path like the fixtures used above) actually engages, with no real git
# clone/network needed.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openapi_synthesize_cleans_up_the_cloned_workdir():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    shutil.copy(_OPENAPI_FIXTURE_SPEC, workdir / "openapi.json")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": str(workdir)}, headers=_ADMIN_AUTH)
            assert start.status_code == 200, start.text
            session_id = start.json()["id"]
            assert workdir.is_dir()  # Turn 1 alone never cleans up

            synthesize = await client.post(
                f"/capability-onboarding/sessions/{session_id}/synthesize",
                json={
                    "selected_tool_name": "read_ticket", "domain": "support", "capability_id": "zendesk-cleanup-test.read_ticket",
                    "test_base_url": "https://staging.zendesk.example.com",
                },
                headers=_ADMIN_AUTH,
            )
            assert synthesize.status_code == 200, synthesize.text

            fetched = await client.get(f"/capability-onboarding/sessions/{session_id}", headers=_ADMIN_AUTH)
    assert fetched.json()["workdir_cleaned_up"] is True
    assert not workdir.exists()


@pytest.mark.asyncio
async def test_mcp_native_synthesize_does_not_clean_up_the_workdir():
    """Unlike OpenAPI, an MCP-native capability's clone is a permanent
    runtime dependency once activated (every live call re-hashes it to
    resolve the cached Docker image) — synthesize() must never reclaim it,
    even though the *event* (a successful synthesize) is identical."""
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    shutil.copytree(_MCP_NATIVE_FIXTURE, workdir, dirs_exist_ok=True)

    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                start = await client.post("/capability-onboarding/sessions", json={"source_url": str(workdir)}, headers=_ADMIN_AUTH)
                assert start.status_code == 200, start.text
                session_id = start.json()["id"]

                synthesize = await client.post(
                    f"/capability-onboarding/sessions/{session_id}/synthesize",
                    json={"selected_tool_name": "add_numbers", "domain": "hr", "capability_id": "mcp-cleanup-test.add_numbers", "estimated_cost_usd": 0.0},
                    headers=_ADMIN_AUTH,
                )
                assert synthesize.status_code == 200, synthesize.text

                fetched = await client.get(f"/capability-onboarding/sessions/{session_id}", headers=_ADMIN_AUTH)
        assert fetched.json()["workdir_cleaned_up"] is False
        assert workdir.is_dir()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_start_session_classification_failure_cleans_up_the_workdir():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    shutil.copytree(_UNCLASSIFIABLE_FIXTURE, workdir, dirs_exist_ok=True)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": str(workdir)}, headers=_ADMIN_AUTH)
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "failed"
    assert not workdir.exists()


@pytest.mark.asyncio
async def test_sweep_stale_workdirs_forbidden_for_manager():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capability-onboarding/sessions/sweep-stale-workdirs", headers=_MANAGER_AUTH)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_sweep_stale_workdirs_reclaims_an_abandoned_session():
    workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))
    shutil.copytree(_MCP_NATIVE_FIXTURE, workdir, dirs_exist_ok=True)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": str(workdir)}, headers=_ADMIN_AUTH)
            assert start.status_code == 200, start.text
            session_id = start.json()["id"]

            # Left at INSPECTED (nobody ever came back for Turn 2) — not a
            # case cleanup_if_no_longer_needed's event-triggered path
            # covers at all, exactly what the sweep exists for.
            swept = await client.post(
                "/capability-onboarding/sessions/sweep-stale-workdirs", params={"stale_after_hours": 0}, headers=_ADMIN_AUTH,
            )
            assert swept.status_code == 200, swept.text
            assert session_id in swept.json()["cleaned_session_ids"]

            fetched = await client.get(f"/capability-onboarding/sessions/{session_id}", headers=_ADMIN_AUTH)
    assert fetched.json()["workdir_cleaned_up"] is True
    assert not workdir.exists()


@pytest.mark.asyncio
async def test_sandbox_test_rejected_before_risk_reviewed():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_ADMIN_AUTH)
            session_id = start.json()["id"]
            response = await client.post(f"/capability-onboarding/sessions/{session_id}/sandbox-test", json={}, headers=_ADMIN_AUTH)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_activate_forbidden_for_auditor():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_ADMIN_AUTH)
            session_id = start.json()["id"]
            response = await client.post(f"/capability-onboarding/sessions/{session_id}/activate", headers=_AUDITOR_AUTH)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_and_get_sessions():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            start = await client.post("/capability-onboarding/sessions", json={"source_url": _MCP_NATIVE_FIXTURE}, headers=_ADMIN_AUTH)
            session_id = start.json()["id"]

            listed = await client.get("/capability-onboarding/sessions", headers=_ADMIN_AUTH)
            assert listed.status_code == 200
            assert any(s["id"] == session_id for s in listed.json())

            fetched = await client.get(f"/capability-onboarding/sessions/{session_id}", headers=_ADMIN_AUTH)
            assert fetched.status_code == 200
            assert fetched.json()["id"] == session_id

            missing = await client.get("/capability-onboarding/sessions/does-not-exist", headers=_ADMIN_AUTH)
            assert missing.status_code == 404
