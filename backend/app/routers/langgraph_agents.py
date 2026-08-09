"""
API surface for orchestrate/langgraph_agents/ — the LangGraph replacements
for the two agents formerly hosted on IBM watsonx Orchestrate (see that
package's __init__.py). Neither agent was reachable from anywhere before
this router; this is what actually makes them "working" rather than just
tested in isolation.

The ITSM agent's create-incident flow has to hold a paused LangGraph between
the initial "ask" call and the human's later approve/reject decision. That
used to be request.app.state.itsm_pending_proposals, a plain dict of live
graph objects — which meant a restart silently discarded every proposal
awaiting a human, and a second replica could not see one at all.

It now pauses into the shared Postgres checkpointer (db/checkpointer.py) and
resumes by request_id, so any process can finish what any other started.
Unlike MOA (backend/app/routers/moa.py) there is no cascade breaker to
restore here, so no companion table is needed: the checkpoint alone is the
whole of the state, and "is this still pending?" is answered by asking the
graph whether that thread is interrupted.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from db.checkpointer import checkpointer
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
    async with checkpointer() as saver:
        result, graph, config = await itsm_agent.ask_itsm_agent(body.query, hub=hub, checkpointer=saver)

        if result is None:
            # Paused on a create-incident proposal. Nothing to stash: the
            # pause itself is a durable checkpoint keyed by this thread_id,
            # which is also the id the caller decides against, so there is
            # exactly one identifier across the whole ask -> decide round trip.
            request_id = config["configurable"]["thread_id"]
            proposed_incident = (await graph.aget_state(config)).values.get("proposed_incident")
            return {
                "status": "pending_approval",
                "requestId": request_id,
                "proposedIncident": proposed_incident,
            }

    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "modelUsed": result.get("model_used"),
    }


class ItsmDecisionRequest(BaseModel):
    selected_option_id: Optional[str] = None  # unused today, kept for symmetry with incidents.py's ApproveRequest


async def _assert_pending_or_404(graph, config) -> None:
    """A thread is decidable only while it is actually interrupted.

    `next` is the tuple of nodes the graph would run on resume: non-empty
    while paused at interrupt(), empty both for a thread that finished and
    for one that never existed. Collapsing those two into the same 404 is
    correct and is what the old pop-once dict did implicitly — it stops a
    duplicated or retried approval from resuming an already-decided
    proposal."""
    snapshot = await graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=404, detail="no pending ITSM proposal for this request id")


async def _decide(request: Request, request_id: str, decision: str, current_user: User) -> dict:
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot decide ITSM proposals")

    hub = request.app.state.integration_hub
    async with checkpointer() as saver:
        config = {"configurable": {"thread_id": request_id}}
        await _assert_pending_or_404(itsm_agent.build_graph(hub, checkpointer=saver), config)

        result, graph, config = await itsm_agent.resume_itsm_agent(
            request_id, decision=decision,
            approved_by=f"{current_user.display_name} ({current_user.role.value})",
            hub=hub, checkpointer=saver,
        )
    if result is None:
        # Shouldn't happen for this graph (only one interrupt point). The
        # proposal stays resumable regardless — it is still checkpointed —
        # so there is nothing to put back.
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
