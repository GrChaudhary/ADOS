"""
Real governance/policy data — replaces the frontend's previously
hardcoded "Enforced Policy Rules" panel (frontend-next/src/app/governance/
page.tsx), which showed 4 items as "ACTIVE" with no backend behind any of
them (confirmed this session: one, "supplier switch requires stock
verification," has no enforcing code anywhere in the repo). Everything
returned here is read directly from the modules that actually enforce it.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db_session
from integrations.connectors.servicenow import ServiceNowConnector
from orchestrate.cascade_breaker import CascadeCircuitBreaker, CascadeState
from orchestrate.governance import CAPABILITY_RISK_CLASS, HIGH_EXPOSURE_MIN_USD, LOW_EXPOSURE_MAX_USD, TIER0_CONFIDENCE_THRESHOLD
from orchestrate.obsidian_projection import generate_obsidian_projection

from .. import moa_breaker_store
from ..auth import get_current_user
from ..rbac import Role, User

router = APIRouter(prefix="/governance", tags=["governance"], dependencies=[Depends(get_current_user)])


@router.get("/policies")
async def get_policies():
    return {
        "financialExposureBands": {
            "lowExposureMaxUsd": LOW_EXPOSURE_MAX_USD,
            "highExposureMinUsd": HIGH_EXPOSURE_MIN_USD,
            "tier0ConfidenceThreshold": TIER0_CONFIDENCE_THRESHOLD,
            "source": "orchestrate/governance.py:assign_policy_tier",
        },
        "capabilityRiskClass": {cap.value: risk for cap, risk in CAPABILITY_RISK_CLASS.items()},
        "rbacApprovalRules": [
            "Tier 1 (approval-required) decisions: manager, executive, or admin role, "
            "within that user's approval_limit_usd.",
            "Tier 2 (executive-approval) decisions: executive or admin role only, "
            "within that user's approval_limit_usd.",
            "Auditor role: read-only everywhere; cannot approve/reject/escalate or start incidents.",
        ],
        "itsmLiveWriteGate": {
            # ServiceNowConnector has one gate, not two: unlike the old
            # watsonx connector (a separate "integration enabled" flag plus
            # a second "live writes enabled" opt-in), it just checks
            # SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD and writes for
            # real the moment those are set — both fields below report
            # that same single, real truth, not two independent gates.
            "connectorEligible": ServiceNowConnector().is_configured(),
            "liveWritesEnabled": ServiceNowConnector().is_configured(),
            "source": "integrations/connectors/servicenow.py",
        },
    }


# ---------------------------------------------------------------------
# Cascade circuit breaker (orchestrate/cascade_breaker.py, vision §5.3).
#
# There is deliberately NO single global breaker in ADOS — the design is
# one CascadeCircuitBreaker per MOA task (see cascade_breaker.py's own
# docstring: "One instance per incident/task"), created by
# backend/app/routers/moa.py and carried in the pending-tasks dict for as
# long as its task is paused awaiting a human. These endpoints therefore
# report an honest AGGREGATE over the currently-live per-task breakers,
# not a fabricated global counter: state is OPEN if any live task's
# breaker is open, auto_approved_count is the longest current streak, and
# active_tasks/open_task_ids make the per-task scoping visible instead of
# hiding it. When no task is live, the honest answer is CLOSED/0 — there
# is nothing being counted, not a hidden global state of zero.
# ---------------------------------------------------------------------


@router.get("/circuit-breaker")
async def get_circuit_breaker_status(request: Request, session: AsyncSession = Depends(get_db_session)):
    # Reads the moa_task_breakers table rather than a process-local dict, so
    # the aggregate covers every paused task in the deployment instead of only
    # the ones this replica happens to have started.
    breakers = await moa_breaker_store.list_live(session)
    open_task_ids = [tid for tid, b in breakers.items() if b.state is CascadeState.OPEN]
    return {
        "state": CascadeState.OPEN.value.upper() if open_task_ids else CascadeState.CLOSED.value.upper(),
        "auto_approved_count": max((len(b.review_batch()) for b in breakers.values()), default=0),
        "threshold": CascadeCircuitBreaker().threshold,
        "active_tasks": len(breakers),
        "open_task_ids": open_task_ids,
    }


@router.post("/circuit-breaker/clear")
async def clear_circuit_breaker(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """The explicit human batch-review sign-off (§5.3) — the only way a
    breaker closes other than a Tier 1/2 human decision inside the task
    itself. No timeout-based auto-recovery, by design.

    Now durable: clearing persists, so a restart can't resurrect a streak a
    human already signed off on, and — the direction that actually matters —
    can't drop one they haven't."""
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot clear the circuit breaker")

    cleared = await moa_breaker_store.clear_all_open(session)
    return {"status": "cleared", "breakers_cleared": cleared}


@router.post("/obsidian-projection")
async def generate_obsidian_vault_projection(current_user: User = Depends(get_current_user)):
    """Triggers on-demand generation of the Obsidian Architecture Graph notes (§9)."""
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot trigger projection generation")

    return generate_obsidian_projection()


@router.get("/obsidian-projection/status")
async def get_obsidian_projection_status(request: Request):
    """Returns background listener status and total vault note metrics."""
    listener = getattr(request.app.state, "obsidian_listener", None)
    if listener:
        stats = listener.get_stats()
    else:
        from orchestrate.obsidian.writer import ObsidianVaultWriter
        writer = ObsidianVaultWriter()
        stats = {
            "queue_depth": 0,
            "projected_count": 0,
            "last_projected_at": None,
            "target_dir": str(writer.target_dir),
            "rest_api_enabled": bool(writer.rest_api_url),
        }

    from pathlib import Path
    target_dir = Path(stats["target_dir"])
    total_notes = len(list(target_dir.rglob("*.md"))) + len(list(target_dir.rglob("*.canvas"))) if target_dir.exists() else 0

    return {
        "status": "active" if listener else "idle",
        "targetDir": stats["target_dir"],
        "totalNotesCount": total_notes,
        "queueDepth": stats["queue_depth"],
        "projectedEventsCount": stats["projected_count"],
        "lastProjectedAt": stats["last_projected_at"],
        "localRestApiEnabled": stats["rest_api_enabled"],
    }


@router.post("/obsidian-projection/sync")
async def sync_obsidian_vault(current_user: User = Depends(get_current_user)):
    """Triggers a full database-to-vault backfill and reconciliation sweep."""
    if current_user.role == Role.AUDITOR:
        raise HTTPException(status_code=403, detail="Auditors have read-only access and cannot trigger vault sync")

    from orchestrate.obsidian.reconciler import ObsidianReconciler
    reconciler = ObsidianReconciler()
    return await reconciler.reconcile_full_vault()


