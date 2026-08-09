"""
API surface for orchestrate/moa/ — the Main Orchestrating Agent's HR
domain vertical slice (orchestration-platform-vision.md §3/§11 step 2).
Mirrors backend/app/routers/langgraph_agents.py's exact shape (same
pending-dict-on-app.state pattern, same pop-once approve/reject), since
that's the proven "pause an in-flight LangGraph loop for governance, then
resume it" REST convention already in this codebase.

Unlike langgraph_agents.py's ITSM endpoints — which only ever pause at one
fixed tier and so only need a blanket auditor block — MOA actions
genuinely span three governance tiers (see orchestrate/moa/hr_domain.py),
so _authorize_decision() below also mirrors incidents.py's
_authorize_decision() (Tier-2 role gate + approval_limit_usd check),
applied uniformly to both approve and reject.
"""

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import PolicyTier
from db.checkpointer import checkpointer
from db.session import get_db_session
from orchestrate.cascade_breaker import CascadeCircuitBreaker
from orchestrate.moa import graph as moa_graph
from orchestrate.async_approvals import publish_pending_approval_event, publish_approval_decision_event

from .. import moa_breaker_store
from ..auth import get_current_user
from ..rbac import Role, User

router = APIRouter(prefix="/moa", tags=["moa"], dependencies=[Depends(get_current_user)])


class MOATaskRequest(BaseModel):
    # Plain str, not Literal["hr"] — only the HR pod is implemented today,
    # but the 400 below (not a generic 422) is a deliberate, readable
    # "not implemented yet" message, and stays useful once a second domain
    # pod is added instead of needing a type change too.
    domain: str
    employee_name: str
    instruction: str


class MOAApprovalRequest(BaseModel):
    # Lets a human correct the LLM-chosen arguments (see
    # orchestrate/moa/graph.py's proposed_action["arguments"]/
    # ["input_schema"]) before a paused action actually executes, rather
    # than only ever being able to run exactly what the model proposed.
    # None (the default, and what every pre-existing caller still sends —
    # an empty body) means "run it as proposed," not "run it with no
    # arguments."
    edited_arguments: Optional[Dict[str, Any]] = None


def _app_bus(request: Request):
    """The app's real event bus, so governance events reach live consumers
    (the Obsidian projection listener wired up in backend/app/main.py) rather
    than orchestrate/async_approvals.py's module-level fallback bus, which
    nothing subscribes to. None when the lifespan never ran (unit tests
    building a bare app) — publish_* falls back to its own bus then."""
    return getattr(request.app.state, "event_bus", None)


@router.post("/tasks")
async def create_moa_task(
    body: MOATaskRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot start MOA tasks")
    valid_domains = {"hr", "it", "finance", "manufacturing", "mfg", "cross-domain", "all", "multi"}
    domain_clean = body.domain.lower()
    if domain_clean not in valid_domains:
        raise HTTPException(status_code=400, detail=f"Unsupported domain '{body.domain}'. Supported domains: hr, it, finance, manufacturing, cross-domain")

    hub = request.app.state.integration_hub
    cascade_breaker = CascadeCircuitBreaker()
    # The saver has to stay open across ainvoke(), not just graph construction
    # — see db/checkpointer.py on why this is a fresh connection per request
    # rather than a pool held on app.state.
    async with checkpointer() as saver:
        result, graph, config = await moa_graph.run_moa_task(
            body.employee_name, body.instruction, domain=domain_clean, hub=hub,
            cascade_breaker=cascade_breaker, checkpointer=saver,
        )

        if result is None:
            task_id = config["configurable"]["thread_id"]
            snapshot = await graph.aget_state(config)
            proposed = snapshot.values.get("proposed_action") or {}
            trajectory_log = snapshot.values.get("trajectory_log", [])
            # A row here is what makes the task resumable by ANY replica; the
            # graph's own state is already in the checkpointer above.
            await moa_breaker_store.save(session, task_id, cascade_breaker, domain=domain_clean)
        else:
            task_id = None

    if task_id is not None:
        asyncio.create_task(
            publish_pending_approval_event(
                task_id=task_id,
                domain=domain_clean,
                action_key=proposed.get("action_key", "unknown"),
                capability=proposed.get("capability", "unknown"),
                policy_tier=proposed.get("policy_tier", 1),
                estimated_cost_usd=proposed.get("estimated_cost_usd", 0.0),
                summary=proposed.get("summary", ""),
                bus=_app_bus(request),
            )
        )
        return {
            "status": "pending_approval",
            "taskId": task_id,
            "proposedAction": proposed,
            "trajectoryLog": trajectory_log,
        }

    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "modelUsed": result.get("model_used"),
        "trajectoryLog": result.get("trajectory_log", []),
    }


async def _load_breaker_or_404(session: AsyncSession, task_id: str) -> CascadeCircuitBreaker:
    """The presence of a breaker row is what "this task is paused" means now
    — the durable equivalent of finding an entry in the old pending dict.

    Unlike that dict this does NOT pop: the row is removed only once the task
    actually reaches a final answer. That difference is what makes the two
    failure paths below (unauthorized, invalid edit) safe without explicitly
    putting anything back — the session rolls back and the task is left
    exactly as paused as it was."""
    breaker = await moa_breaker_store.load(session, task_id)
    if breaker is None:
        raise HTTPException(status_code=404, detail="no pending MOA task for this task id")
    return breaker


def _authorize_decision(user: User, proposed_action: dict) -> None:
    if user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot decide MOA tasks")
    if proposed_action.get("policy_tier") == PolicyTier.EXECUTIVE_APPROVAL.value and user.role not in (
        Role.EXECUTIVE,
        Role.ADMIN,
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.role.value}' cannot decide Tier 2 (executive-approval) MOA actions",
        )
    estimated_cost = proposed_action.get("estimated_cost_usd", 0.0)
    if user.approval_limit_usd < estimated_cost:
        raise HTTPException(
            status_code=403,
            detail=f"Approval limit ${user.approval_limit_usd:,.0f} is below this action's "
            f"${estimated_cost:,.0f} estimated cost",
        )


async def _decide(
    request: Request,
    session: AsyncSession,
    task_id: str,
    decision: str,
    current_user: User,
    edited_arguments: Optional[Dict[str, Any]] = None,
) -> dict:
    hub = request.app.state.integration_hub
    # The RESTORED breaker, carrying this task's accumulated auto-approval
    # streak. Constructing a fresh CascadeCircuitBreaker here instead would
    # zero the count vision §5.3 exists to keep, with nothing to show for it
    # in any log or response.
    cascade_breaker = await _load_breaker_or_404(session, task_id)

    async with checkpointer() as saver:
        graph = moa_graph.build_graph(hub, cascade_breaker, checkpointer=saver)
        config = {"configurable": {"thread_id": task_id}}
        proposed = (await graph.aget_state(config)).values.get("proposed_action") or {}
        _authorize_decision(current_user, proposed)

        asyncio.create_task(
            publish_approval_decision_event(
                task_id=task_id,
                decision=decision,
                approved_by=current_user.username,
                role=current_user.role.value,
                bus=_app_bus(request),
            )
        )

        try:
            result, graph, config = await moa_graph.resume_moa_task(
                task_id, decision=decision,
                approved_by=f"{current_user.display_name} ({current_user.role.value})",
                edited_arguments=edited_arguments,
                hub=hub, cascade_breaker=cascade_breaker, checkpointer=saver,
            )
        except ValueError as e:
            # Invalid edited_arguments (bad shape, missing a required param) —
            # resume_moa_task validates BEFORE ever calling graph.ainvoke(), so
            # the task is still genuinely paused exactly as before. Nothing to
            # restore: the breaker row was never deleted, and raising rolls the
            # session back, so the human can just retry with a corrected edit.
            raise HTTPException(status_code=422, detail=str(e))

        if result is None:
            next_proposed = (await graph.aget_state(config)).values.get("proposed_action") or {}
            next_trajectory = (await graph.aget_state(config)).values.get("trajectory_log", [])
            # Still paused, one action further along — persist the breaker's
            # advanced streak over the previous snapshot.
            await moa_breaker_store.save(session, task_id, cascade_breaker, domain=next_proposed.get("domain", "hr"))
        else:
            # Reached a final answer: the task is no longer live, so it stops
            # counting toward the governance aggregate. Same moment the old
            # code left the popped dict entry unrestored.
            await moa_breaker_store.delete(session, task_id)

    if result is None:
        asyncio.create_task(
            publish_pending_approval_event(
                task_id=task_id,
                domain=next_proposed.get("domain", "hr"),
                action_key=next_proposed.get("action_key", "unknown"),
                capability=next_proposed.get("capability", "unknown"),
                policy_tier=next_proposed.get("policy_tier", 1),
                estimated_cost_usd=next_proposed.get("estimated_cost_usd", 0.0),
                summary=next_proposed.get("summary", ""),
                bus=_app_bus(request),
            )
        )
        return {
            "status": "pending_approval",
            "taskId": task_id,
            "proposedAction": next_proposed,
            "trajectoryLog": next_trajectory,
        }

    return {
        "status": result.get("status"),
        "answer": result.get("final_answer"),
        "toolsCalled": result.get("tools_called", []),
        "approvalDecision": result.get("approval_decision"),
        "trajectoryLog": result.get("trajectory_log", []),
    }


async def _parse_approval_body(request: Request) -> MOAApprovalRequest:
    """Deliberately reads the raw body instead of declaring `body:
    MOAApprovalRequest` as a normal FastAPI parameter — every existing
    caller (this router's own tests, the current frontend) sends approve/
    reject with NO body at all, and this must keep working unchanged
    rather than starting to 422 on an empty request."""
    raw = await request.body()
    if not raw:
        return MOAApprovalRequest()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="request body must be valid JSON")
    try:
        return MOAApprovalRequest.model_validate(parsed)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/approve")
async def approve_moa_task(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    body = await _parse_approval_body(request)
    return await _decide(request, session, task_id, "approved", current_user, edited_arguments=body.edited_arguments)


@router.post("/tasks/{task_id}/reject")
async def reject_moa_task(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await _decide(request, session, task_id, "rejected", current_user)
