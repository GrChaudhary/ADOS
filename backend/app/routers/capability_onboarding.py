"""
API surface for orchestrate/onboarding/ — the "Bring Your Own Capability"
onboarding pipeline (orchestration-platform-vision.md §8.4/§8.5). Five
conversational turns, each a real review checkpoint per §8.5's table:
inspect -> synthesize (domain+manifest) -> risk-proposal -> sandbox-test ->
activate. MCP-native and OpenAPI tracks only this pass — see
orchestrate/onboarding/__init__.py for why raw-code is deferred.

`proposed_by` is always the fixed constant "onboarding-agent", never the
acting admin's own username — matches backend/tests/test_capabilities.py's
existing convention. This is load-bearing, not incidental:
CapabilityManifestRegistry.activate() raises if
`actor == manifest.proposed_by` (§8.3 "never self-approve"). If the risk-
proposal step here recorded the admin's own identity as proposer, that
same admin — who necessarily ran every earlier turn — could never activate
the session they just walked through.

Two activation paths exist and must both leave a capability equally live:
this router's own /activate, and the pre-existing generic
POST /capabilities/manifests/{id}/promote (capabilities.py). Both call
orchestrate.onboarding.runtime_registry.register_runtime() after a
successful activation — see capabilities.py's promote handler for its
matching hook.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow
from integrations.policy_engine import PolicyViolation
from orchestrate.onboarding import cleanup, inspector, risk_proposal, runtime_registry, sandbox_runner, wrapper_generator
from orchestrate.onboarding.models import DiscoveredTool, InspectionReport, OnboardingSessionStatus, OnboardingTrack, SynthesizedAction

from ..auth import get_current_user
from ..rbac import Role, User, require_role

router = APIRouter(prefix="/capability-onboarding", tags=["capability-onboarding"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------
# Serialization helpers — dataclasses/enums <-> JSONB-storable plain dicts.
# ---------------------------------------------------------------------

def _tool_to_dict(tool: DiscoveredTool) -> dict:
    return {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema, "runtime": tool.runtime}


def _report_to_dict(report: InspectionReport) -> dict:
    return {
        "source": report.source,
        "track": report.track.value if report.track else None,
        "confidence": report.confidence,
        "local_path": report.local_path,
        "resolved_ref": report.resolved_ref,
        "language": report.language,
        "tools": [_tool_to_dict(t) for t in report.tools],
        "warnings": report.warnings,
        "launch_command": report.launch_command,
        "openapi_spec_path": report.openapi_spec_path,
        "raw_code_entrypoint": report.raw_code_entrypoint,
    }


def _action_to_dict(action: SynthesizedAction) -> dict:
    return {
        "key": action.key,
        "description": action.description,
        "capability_id": action.capability_id,
        "domain": action.domain,
        "version": action.version,
        "estimated_cost_usd": action.estimated_cost_usd,
        "track": action.track.value,
        "runtime": action.runtime,
    }


def _sandbox_result_to_dict(result: sandbox_runner.SandboxResult) -> dict:
    return {
        "passed": result.passed,
        "evidence_summary": result.evidence_summary,
        "raw_output": result.raw_output,
        "duration_ms": result.duration_ms,
    }


def _audit_entry(turn: int, user: User, detail: str) -> dict:
    return {
        "turn": turn,
        "actor": user.username,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }


def _session_to_wire(row: OnboardingSessionRow) -> dict:
    return {
        "id": row.id,
        "track": row.track,
        "status": row.status,
        "source_url": row.source_url,
        "domain": row.domain,
        "capability_id": row.capability_id,
        "selected_tool_name": row.selected_tool_name,
        "inspection_report": row.inspection_report,
        "synthesized_manifest": row.synthesized_manifest,
        "sandbox_result": row.sandbox_result,
        "audit_log": row.audit_log,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "failure_reason": row.failure_reason,
        "workdir_cleaned_up": row.workdir_cleaned_up,
    }


async def _get_session_or_404(session_id: str) -> OnboardingSessionRow:
    async with async_session_factory() as session:
        row = (await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no onboarding session {session_id}")
    return row


async def _update_session(session_id: str, **fields: Any) -> OnboardingSessionRow:
    async with async_session_factory() as session:
        row = (
            await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no onboarding session {session_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


# ---------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------

class StartOnboardingRequest(BaseModel):
    source_url: str
    track_hint: Optional[str] = None
    entrypoint_path: Optional[str] = None  # required when track_hint == "raw_code"


class SynthesizeRequest(BaseModel):
    selected_tool_name: str
    domain: str
    capability_id: str
    version: str = "1.0.0"
    estimated_cost_usd: float = 0.0
    test_base_url: Optional[str] = None  # required for the OpenAPI track
    production_base_url: Optional[str] = None  # OpenAPI only; falls back to the spec's own default
    install_dependencies: bool = False  # raw_code only — see wrapper_generator.synthesize_raw_code_action


class SandboxTestRequest(BaseModel):
    sample_input: Dict[str, Any] = {}
    acknowledge_live_call: bool = False  # OpenAPI only — see sandbox_runner.run_openapi_sandbox_test


# ---------------------------------------------------------------------
# Turn 1 — Inspect
# ---------------------------------------------------------------------

@router.post("/sessions", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def start_onboarding_session(body: StartOnboardingRequest, current_user: User = Depends(get_current_user)):
    if body.track_hint == OnboardingTrack.RAW_CODE.value and not body.entrypoint_path:
        raise HTTPException(status_code=400, detail="entrypoint_path is required when track_hint='raw_code'")

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        report = await inspector.inspect(body.source_url, track_hint=body.track_hint, entrypoint_path=body.entrypoint_path)
    except Exception as e:  # noqa: BLE001 — Turn 1 inspects an arbitrary,
        # untrusted external repo/spec; inspector.py normalizes its own
        # known failure modes to ValueError/RuntimeError, but this is the
        # boundary where an exception type nobody anticipated (a library
        # bug, a genuinely weird repo) must still degrade to the
        # documented clean 422, never an unhandled 500 — matches this
        # codebase's own established connector convention (a degraded
        # environment produces a clean FAILED-shaped result, not a raise
        # the caller has to guess how to handle).
        async with async_session_factory() as session:
            session.add(
                OnboardingSessionRow(
                    id=session_id, track=None, status=OnboardingSessionStatus.FAILED.value,
                    source_url=body.source_url, domain=None, capability_id=None, selected_tool_name=None,
                    audit_log=[_audit_entry(1, current_user, f"inspection failed: {e}")],
                    created_by=current_user.username, created_at=now, updated_at=now, failure_reason=str(e),
                )
            )
            await session.commit()
        raise HTTPException(status_code=422, detail=f"inspection failed: {e}")

    status = OnboardingSessionStatus.INSPECTED.value if report.track is not None else OnboardingSessionStatus.FAILED.value
    report_dict = _report_to_dict(report)
    async with async_session_factory() as session:
        session.add(
            OnboardingSessionRow(
                id=session_id,
                track=report.track.value if report.track else None,
                status=status,
                source_url=body.source_url,
                domain=None, capability_id=None, selected_tool_name=None,
                inspection_report=report_dict,
                audit_log=[_audit_entry(1, current_user, "inspected source")],
                created_by=current_user.username, created_at=now, updated_at=now,
                failure_reason=None if report.track else "could not classify source as MCP-native or OpenAPI",
            )
        )
        await session.commit()

    if status == OnboardingSessionStatus.FAILED.value:
        # A source that failed classification has nothing further in this
        # pipeline that will ever need its clone again — reclaim it now
        # rather than waiting on the stale-workdir sweep.
        await cleanup.cleanup_if_no_longer_needed(async_session_factory, session_id)

    return {"id": session_id, "status": status, "report": report_dict}


# ---------------------------------------------------------------------
# Turn 2 — Domain + manifest
# ---------------------------------------------------------------------

@router.post("/sessions/{session_id}/synthesize", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def synthesize_session(session_id: str, body: SynthesizeRequest, current_user: User = Depends(get_current_user)):
    row = await _get_session_or_404(session_id)
    if row.status != OnboardingSessionStatus.INSPECTED.value:
        raise HTTPException(status_code=409, detail=f"session must be INSPECTED to synthesize, is {row.status}")

    report = row.inspection_report or {}
    matching_tool = next((t for t in report.get("tools", []) if t["name"] == body.selected_tool_name), None)
    if matching_tool is None:
        raise HTTPException(status_code=400, detail=f"tool {body.selected_tool_name!r} not found in this session's inspection report")

    try:
        if row.track == OnboardingTrack.MCP_NATIVE.value:
            action = wrapper_generator.synthesize_mcp_action(
                DiscoveredTool(name=matching_tool["name"], description=matching_tool["description"], input_schema=matching_tool["input_schema"]),
                capability_id=body.capability_id, domain=body.domain, version=body.version,
                estimated_cost_usd=body.estimated_cost_usd,
                launch_command=report["launch_command"], local_path=report["local_path"],
            )
        elif row.track == OnboardingTrack.OPENAPI.value:
            if not body.test_base_url:
                raise HTTPException(status_code=400, detail="test_base_url is required for the OpenAPI track")
            action = await wrapper_generator.synthesize_openapi_action(
                report["openapi_spec_path"], body.selected_tool_name,
                capability_id=body.capability_id, domain=body.domain, version=body.version,
                estimated_cost_usd=body.estimated_cost_usd,
                test_base_url=body.test_base_url, production_base_url=body.production_base_url,
            )
        elif row.track == OnboardingTrack.RAW_CODE.value:
            action = wrapper_generator.synthesize_raw_code_action(
                DiscoveredTool(name=matching_tool["name"], description=matching_tool["description"], input_schema=matching_tool["input_schema"]),
                capability_id=body.capability_id, domain=body.domain, version=body.version,
                estimated_cost_usd=body.estimated_cost_usd,
                local_path=report["local_path"], entrypoint_path=report["raw_code_entrypoint"],
                install_dependencies=body.install_dependencies,
            )
        else:
            raise HTTPException(status_code=409, detail=f"unsupported track {row.track!r}")
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    action_dict = _action_to_dict(action)
    updated = await _update_session(
        session_id,
        status=OnboardingSessionStatus.SYNTHESIZED.value,
        domain=body.domain,
        capability_id=body.capability_id,
        selected_tool_name=body.selected_tool_name,
        synthesized_manifest=action_dict,
        audit_log=[*row.audit_log, _audit_entry(2, current_user, f"synthesized manifest for {body.capability_id} (domain={body.domain})")],
    )
    # A no-op for MCP_NATIVE/RAW_CODE (their clone is a permanent runtime
    # dependency once activated — see cleanup.workdir_no_longer_needed);
    # for OPENAPI this is the clone's last possible use, so it's reclaimed
    # immediately rather than waiting on the stale-workdir sweep.
    await cleanup.cleanup_if_no_longer_needed(async_session_factory, session_id)
    return {"id": session_id, "status": updated.status, "synthesized_manifest": updated.synthesized_manifest}


# ---------------------------------------------------------------------
# Turn 3 — Risk proposal (this is where CapabilityManifestRegistry.propose()
# fires — the first point a real manifest row exists)
# ---------------------------------------------------------------------

@router.post("/sessions/{session_id}/risk-proposal", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def risk_proposal_session(session_id: str, request: Request, current_user: User = Depends(get_current_user)):
    row = await _get_session_or_404(session_id)
    if row.status != OnboardingSessionStatus.SYNTHESIZED.value:
        raise HTTPException(status_code=409, detail=f"session must be SYNTHESIZED to propose risk, is {row.status}")

    synthesized = row.synthesized_manifest
    entry = risk_proposal.propose_risk(synthesized["key"], synthesized["description"], synthesized["estimated_cost_usd"])

    manifests = request.app.state.integration_hub.manifests
    try:
        await manifests.propose(
            row.capability_id, domain=row.domain, version=synthesized["version"], source=row.source_url,
            risk_profile=[entry], proposed_by="onboarding-agent",
        )
    except PolicyViolation as e:
        raise HTTPException(status_code=409, detail=str(e))

    risk_profile_wire = [{"action": entry.action, "tier": entry.tier.value, "reasoning": entry.reasoning}]
    updated = await _update_session(
        session_id,
        status=OnboardingSessionStatus.RISK_REVIEWED.value,
        audit_log=[*row.audit_log, _audit_entry(3, current_user, f"proposed risk tier {entry.tier.name}: {entry.reasoning}")],
    )
    return {"id": session_id, "status": updated.status, "risk_profile": risk_profile_wire}


# ---------------------------------------------------------------------
# Turn 4 — Sandbox test (mandatory, no skip — §8.4). Failure keeps the
# session at RISK_REVIEWED (retriable, e.g. with different sample_input)
# rather than a terminal FAILED, since a bad sample input isn't evidence
# the capability itself is untrustworthy.
# ---------------------------------------------------------------------

@router.post("/sessions/{session_id}/sandbox-test", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def sandbox_test_session(session_id: str, body: SandboxTestRequest, request: Request, current_user: User = Depends(get_current_user)):
    row = await _get_session_or_404(session_id)
    if row.status != OnboardingSessionStatus.RISK_REVIEWED.value:
        raise HTTPException(status_code=409, detail=f"session must be RISK_REVIEWED to sandbox test, is {row.status}")

    runtime = row.synthesized_manifest["runtime"]
    if row.track == OnboardingTrack.MCP_NATIVE.value:
        result = await sandbox_runner.run_mcp_sandbox_test(
            local_path=runtime["local_path"], launch_command=runtime["launch_command"],
            tool_name=runtime["tool_name"], sample_input=body.sample_input,
        )
    elif row.track == OnboardingTrack.OPENAPI.value:
        result = await sandbox_runner.run_openapi_sandbox_test(
            test_base_url=runtime["test_base_url"], method=runtime["method"], path_template=runtime["path_template"],
            sample_input=body.sample_input, acknowledge_live_call=body.acknowledge_live_call,
        )
    elif row.track == OnboardingTrack.RAW_CODE.value:
        result = await sandbox_runner.run_raw_code_sandbox_test(
            local_path=runtime["local_path"], entrypoint_path=runtime["entrypoint_path"],
            function_name=runtime["function_name"], sample_input=body.sample_input,
            install_dependencies=runtime.get("install_dependencies", False),
        )
    else:
        # Real pre-existing bug, fixed here regardless of raw_code: this
        # branch used to be a bare `else: # openapi`, so any future/
        # unexpected track value would have silently fallen into the
        # OpenAPI path and KeyError'd on a missing test_base_url instead
        # of failing clearly — matches synthesize_session's existing
        # fail-safe else above.
        raise HTTPException(status_code=409, detail=f"unsupported track {row.track!r}")

    result_dict = _sandbox_result_to_dict(result)
    if not result.passed:
        await _update_session(
            session_id, sandbox_result=result_dict,
            audit_log=[*row.audit_log, _audit_entry(4, current_user, f"sandbox test FAILED: {result.evidence_summary}")],
        )
        raise HTTPException(status_code=422, detail=result.evidence_summary)

    manifests = request.app.state.integration_hub.manifests
    await manifests.record_sandbox_evidence(row.capability_id, result.evidence_summary, actor="onboarding-agent")

    updated = await _update_session(
        session_id, status=OnboardingSessionStatus.SANDBOX_TESTED.value, sandbox_result=result_dict,
        audit_log=[*row.audit_log, _audit_entry(4, current_user, f"sandbox test PASSED: {result.evidence_summary}")],
    )
    return {"id": session_id, "status": updated.status, "sandbox_result": updated.sandbox_result}


# ---------------------------------------------------------------------
# Turn 5 — Activate (last explicit human gate — §8.5)
# ---------------------------------------------------------------------

@router.post("/sessions/{session_id}/activate", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def activate_session(session_id: str, request: Request, current_user: User = Depends(get_current_user)):
    row = await _get_session_or_404(session_id)
    if row.status != OnboardingSessionStatus.SANDBOX_TESTED.value:
        raise HTTPException(status_code=409, detail=f"session must be SANDBOX_TESTED to activate, is {row.status}")

    manifests = request.app.state.integration_hub.manifests
    reason = f"activated via onboarding pipeline by {current_user.display_name} ({current_user.role.value})"
    try:
        await manifests.activate(row.capability_id, actor=current_user.username, reason=reason)
    except PolicyViolation as e:
        raise HTTPException(status_code=409, detail=str(e))

    updated = await _update_session(
        session_id, status=OnboardingSessionStatus.ACTIVATED.value,
        audit_log=[*row.audit_log, _audit_entry(5, current_user, "activated")],
    )

    await runtime_registry.register_runtime(
        async_session_factory, row.capability_id, request.app.state.integration_hub.dynamic_capability_connector
    )

    return {"id": session_id, "status": updated.status, "capability_id": row.capability_id}


# ---------------------------------------------------------------------
# Maintenance — reclaim cloned-repo workdirs for sessions abandoned
# mid-flow (orchestrate/onboarding/cleanup.py). Deliberately a manual,
# admin-triggered action rather than a hidden background timer — this
# codebase has no periodic-task infrastructure anywhere yet (see
# backend/app/main.py's lifespan), and the two event-triggered cleanup
# call sites above already handle the common terminal cases inline; this
# only exists for genuinely abandoned sessions.
# ---------------------------------------------------------------------

@router.post("/sessions/sweep-stale-workdirs", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def sweep_stale_workdirs(stale_after_hours: Optional[int] = None):
    cleaned = await cleanup.sweep_stale_workdirs(async_session_factory, stale_after_hours=stale_after_hours)
    return {"cleaned_session_ids": cleaned, "count": len(cleaned)}


# ---------------------------------------------------------------------
# Read endpoints — authenticated-only, no extra role gate (matches
# GET /capabilities/manifests).
# ---------------------------------------------------------------------

@router.get("/sessions")
async def list_onboarding_sessions() -> List[dict]:
    async with async_session_factory() as session:
        rows = (await session.execute(select(OnboardingSessionRow).order_by(OnboardingSessionRow.created_at.desc()))).scalars().all()
    return [_session_to_wire(r) for r in rows]


@router.get("/sessions/{session_id}")
async def get_onboarding_session(session_id: str) -> dict:
    row = await _get_session_or_404(session_id)
    return _session_to_wire(row)
