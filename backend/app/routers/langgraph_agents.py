"""
API surface for orchestrate/langgraph_agents/ — the LangGraph replacements
for the two agents formerly hosted on IBM watsonx Orchestrate (see that
package's __init__.py). Neither agent was reachable from anywhere before
this router; this is what actually makes them "working" rather than just
tested in isolation.

The ITSM agent's create-incident flow needs somewhere to hold a paused
LangGraph (checkpointer + thread) between the initial "ask" call and the
human's later approve/reject decision — the graph object itself, not just
a status flag, has to survive that gap so resume_itsm_agent() has
something to resume. request.app.state.itsm_pending_proposals (a plain
dict, set up in main.py's lifespan) is that holding spot, the same
in-memory-dict-keyed-by-id shape as request.app.state.incident_tasks.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from orchestrate.langgraph_agents import executive_copilot, itsm_agent
from orchestrate.langgraph_agents.tools import in_process_tools

from ..auth import get_current_user
from ..rbac import Role, User

router = APIRouter(prefix="/agents", tags=["langgraph-agents"], dependencies=[Depends(get_current_user)])


class AgentAskRequest(BaseModel):
    query: str


@router.post("/executive-copilot/ask")
async def ask_executive_copilot(body: AgentAskRequest, request: Request):
    orchestrator = request.app.state.orchestrator
    result = await executive_copilot.ask_copilot(body.query, tools=in_process_tools(orchestrator))
    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "modelUsed": result.get("model_used"),
    }


@router.post("/itsm/ask")
async def ask_itsm_agent(body: AgentAskRequest, request: Request, current_user: User = Depends(get_current_user)):
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot use the ITSM agent")

    hub = request.app.state.integration_hub
    result, graph, config = await itsm_agent.ask_itsm_agent(body.query, hub=hub)

    if result is None:
        # Paused on a create-incident proposal — stash the live graph/config
        # so a later approve/reject call has something to resume. Keyed by
        # the same thread_id the graph itself used (config's thread_id),
        # not a fresh id, so there's exactly one identifier across the
        # whole ask -> decide round trip.
        request_id = config["configurable"]["thread_id"]
        request.app.state.itsm_pending_proposals[request_id] = (graph, config)
        return {
            "status": "pending_approval",
            "requestId": request_id,
            "proposedIncident": graph.get_state(config).values.get("proposed_incident"),
        }

    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "modelUsed": result.get("model_used"),
    }


class ItsmDecisionRequest(BaseModel):
    selected_option_id: Optional[str] = None  # unused today, kept for symmetry with incidents.py's ApproveRequest


def _pop_pending_or_404(request: Request, request_id: str):
    pending = request.app.state.itsm_pending_proposals.pop(request_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending ITSM proposal for this request id")
    return pending


async def _decide(request: Request, request_id: str, decision: str, current_user: User) -> dict:
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot decide ITSM proposals")

    graph, config = _pop_pending_or_404(request, request_id)
    result, graph, config = await itsm_agent.resume_itsm_agent(
        graph, config, decision=decision, approved_by=f"{current_user.display_name} ({current_user.role.value})"
    )
    if result is None:
        # Shouldn't happen for this graph (only one interrupt point), but
        # if it ever does, keep the proposal resumable rather than
        # dropping it silently.
        request.app.state.itsm_pending_proposals[request_id] = (graph, config)
        return {"status": "pending_approval", "requestId": request_id}

    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "approvalDecision": result.get("approval_decision"),
    }


@router.post("/itsm/{request_id}/approve")
async def approve_itsm_proposal(request_id: str, request: Request, current_user: User = Depends(get_current_user)):
    return await _decide(request, request_id, "approved", current_user)


@router.post("/itsm/{request_id}/reject")
async def reject_itsm_proposal(request_id: str, request: Request, current_user: User = Depends(get_current_user)):
    return await _decide(request, request_id, "rejected", current_user)
