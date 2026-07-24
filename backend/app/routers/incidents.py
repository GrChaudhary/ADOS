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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from contracts import IncidentRecord
from orchestrate import PriorityInputs

from ..auth import require_service_auth

router = APIRouter(tags=["incidents"], dependencies=[Depends(require_service_auth)])


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


class ApprovalDecisionRequest(BaseModel):
    approved_by: str


@router.post("/incidents", response_model=StartIncidentResponse)
async def start_incident(body: StartIncidentRequest, request: Request):
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


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, request: Request):
    orchestrator = request.app.state.orchestrator
    record = orchestrator.audit_trail.get(incident_id)
    if record is not None:
        return record

    task: Optional[asyncio.Task] = request.app.state.incident_tasks.get(incident_id)
    if task is None:
        raise HTTPException(status_code=404, detail="unknown incident")

    pending = orchestrator.approvals.get(incident_id)
    return {
        "incidentId": incident_id,
        "status": "in_progress",
        "awaitingApproval": pending is not None and pending.decision is None,
        "approvalSummary": pending.summary if pending and pending.decision is None else None,
    }


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


def _resolve_or_404(orchestrator, incident_id: str, action: str, approved_by: str):
    try:
        return getattr(orchestrator.approvals, action)(incident_id, approved_by)
    except KeyError:
        raise HTTPException(status_code=404, detail="no pending approval for this incident")


@router.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, body: ApprovalDecisionRequest, request: Request):
    _resolve_or_404(request.app.state.orchestrator, incident_id, "approve", body.approved_by)
    return {"incidentId": incident_id, "decision": "approved"}


@router.post("/incidents/{incident_id}/reject")
async def reject_incident(incident_id: str, body: ApprovalDecisionRequest, request: Request):
    _resolve_or_404(request.app.state.orchestrator, incident_id, "reject", body.approved_by)
    return {"incidentId": incident_id, "decision": "rejected"}


@router.post("/incidents/{incident_id}/escalate")
async def escalate_incident(incident_id: str, body: ApprovalDecisionRequest, request: Request):
    _resolve_or_404(request.app.state.orchestrator, incident_id, "escalate", body.approved_by)
    return {"incidentId": incident_id, "decision": "escalated"}
