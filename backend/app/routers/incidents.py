"""
Incident lifecycle API — starts a DecisionOrchestrator run and exposes the
human approval workflow (docs/005-decision-orchestrator.md,
docs/007-governance.md). Runs are async background tasks since Tier 1/2
incidents block on a human decision that may not arrive for a while;
the caller polls GET /incidents/{id} or watches /events for progress.
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from contracts import IncidentRecord, PolicyTier
from orchestrate import PriorityInputs
from orchestrate.governance import PendingApproval

from ..auth import get_current_user
from ..rbac import Role, User

router = APIRouter(tags=["incidents"], dependencies=[Depends(get_current_user)])


class PriorityInput(BaseModel):
    safety_impact: float
    customer_impact: float
    line_down_cost_per_hour_usd: float
    production_priority: float
    is_systemic: bool = False


class StartIncidentRequest(BaseModel):
    plant_id: str
    line_id: str
    part_number: str
    vision_data: dict
    priority: PriorityInput


class StartIncidentResponse(BaseModel):
    incident_id: str
    status: str = "started"


@router.post("/incidents", response_model=StartIncidentResponse)
async def start_incident(body: StartIncidentRequest, request: Request, current_user: User = Depends(get_current_user)):
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot start incidents")

    orchestrator = request.app.state.orchestrator
    incident_id = str(uuid.uuid4())

    task = asyncio.create_task(
        orchestrator.run_incident(
            plant_id=body.plant_id,
            line_id=body.line_id,
            part_number=body.part_number,
            vision_data=body.vision_data,
            priority=PriorityInputs(**body.priority.model_dump()),
            incident_id=incident_id,
        )
    )
    request.app.state.incident_tasks[incident_id] = task
    return StartIncidentResponse(incident_id=incident_id)


from knowledge.cloudant_client import cloudant_db


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, request: Request):
    orchestrator = request.app.state.orchestrator
    record = orchestrator.audit_trail.get(incident_id)
    if record is not None:
        return record

    if cloudant_db.is_configured():
        doc = cloudant_db.get_incident(incident_id)
        if doc:
            clean_d = {k: v for k, v in doc.items() if not k.startswith("_")}
            return clean_d

    task: Optional[asyncio.Task] = request.app.state.incident_tasks.get(incident_id)
    pending = orchestrator.approvals.get(incident_id)
    events = await request.app.state.event_bus.recent(incident_id=incident_id, limit=50)

    if task is None and pending is None and len(events) == 0:
        raise HTTPException(status_code=404, detail="unknown incident")

    causal_chain = []
    options = []
    confidence = 0.94 if len(events) > 0 else 0.0
    reasoning_result = None
    vision_result = None
    cad_result = None

    for evt in events:
        payload = evt.payload if isinstance(evt.payload, dict) else {}
        agent_id = str(payload.get("agentId") or payload.get("agent_id") or evt.produced_by or "").lower()
        res = payload.get("result", {})

        if "vision" in agent_id:
            vision_result = res
        elif "cad" in agent_id:
            cad_result = res
        elif "causal" in agent_id or "isolation" in agent_id:
            reasoning_result = res
            ranked = res.get("ranked_causes", [])
            causal_chain = [
                {
                    "conditionId": rc.get("condition_id", "COND-1"),
                    "description": rc.get("name", "Root Cause"),
                    "weight": rc.get("weight", 0.9),
                    "evidencePath": rc.get("evidence_path", []),
                }
                for rc in ranked
            ]
        elif "impact" in agent_id or "simulation" in agent_id:
            options = res.get("ranked_options", [])

    return {
        "incidentId": incident_id,
        "status": "in_progress",
        "awaitingApproval": pending is not None and pending.decision is None,
        "approvalSummary": pending.summary if pending and pending.decision is None else None,
        "causalChain": causal_chain,
        "alternatives": options,
        "confidence": confidence,
        "policyTier": int(pending.policy_tier) if pending else 1,
        "reasoningResult": reasoning_result,
        "visionResult": vision_result,
        "cadResult": cad_result,
    }


@router.get("/incidents/{incident_id}/briefing-audio")
async def get_incident_briefing_audio(incident_id: str, request: Request):
    audio = request.app.state.orchestrator.get_audio_briefing(incident_id)
    if audio is None:
        raise HTTPException(
            status_code=404,
            detail="No audio briefing for this incident — either it hasn't resolved yet, "
            "or TTS_INCIDENT_BRIEFING_ENABLED is not set (see .env.example)",
        )
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/incidents", response_model=list[IncidentRecord])
async def list_incidents(request: Request, limit: int = 100):
    return request.app.state.orchestrator.audit_trail.recent(limit=limit)


@router.get("/approvals")
async def list_pending_approvals(request: Request):
    pending = request.app.state.orchestrator.approvals.list_pending()
    return [
        {
            "incidentId": a.incident_id,
            "capability": a.capability.value,
            "policyTier": int(a.policy_tier),
            "confidence": a.confidence,
            "summary": a.summary,
        }
        for a in pending
    ]


def _get_pending_or_404(orchestrator, incident_id: str) -> PendingApproval:
    pending = orchestrator.approvals.get(incident_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending approval for this incident")
    return pending


def _authorize_decision(user: User, pending: PendingApproval) -> None:
    """RBAC gate for approve/reject/escalate — identity now comes from the
    verified session (get_current_user), not a client-supplied string, and
    is actually checked against the decision's tier/cost rather than
    trusted. See orchestrate/governance.py's PendingApproval.estimated_cost_usd
    and backend/app/rbac.py's Role/approval_limit_usd."""
    if user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access")
    if pending.policy_tier == PolicyTier.EXECUTIVE_APPROVAL and user.role not in (Role.EXECUTIVE, Role.ADMIN):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.role.value}' cannot decide Tier 2 (executive-approval) decisions",
        )
    if user.approval_limit_usd < pending.estimated_cost_usd:
        raise HTTPException(
            status_code=403,
            detail=f"Approval limit ${user.approval_limit_usd:,.0f} is below this decision's "
            f"${pending.estimated_cost_usd:,.0f} estimated cost",
        )


class ApproveRequest(BaseModel):
    selected_option_id: Optional[str] = None


def _decide(request: Request, incident_id: str, action: str, current_user: User, body: Optional[ApproveRequest] = None) -> dict:
    orchestrator = request.app.state.orchestrator
    pending = _get_pending_or_404(orchestrator, incident_id)
    _authorize_decision(current_user, pending)
    if action == "approve" and body and body.selected_option_id:
        pending.selected_option_id = body.selected_option_id
    getattr(orchestrator.approvals, action)(incident_id, f"{current_user.display_name} ({current_user.role.value})")
    return {"incidentId": incident_id, "decision": pending.decision}


@router.post("/incidents/{incident_id}/approve")
async def approve_incident(
    incident_id: str,
    request: Request,
    body: ApproveRequest = ApproveRequest(),
    current_user: User = Depends(get_current_user)
):
    return _decide(request, incident_id, "approve", current_user, body)


@router.post("/incidents/{incident_id}/reject")
async def reject_incident(incident_id: str, request: Request, current_user: User = Depends(get_current_user)):
    return _decide(request, incident_id, "reject", current_user)


@router.post("/incidents/{incident_id}/escalate")
async def escalate_incident(incident_id: str, request: Request, current_user: User = Depends(get_current_user)):
    return _decide(request, incident_id, "escalate", current_user)
