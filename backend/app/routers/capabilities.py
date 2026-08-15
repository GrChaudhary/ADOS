import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from contracts import CapabilityCall, CapabilityResponse, PolicyTier
from db.engine import async_session_factory
from integrations.capability_manifest import CapabilityManifest, CapabilityStatus
from integrations.policy_engine import PolicyViolation
from orchestrate.onboarding import runtime_registry as onboarding_runtime_registry

from ..auth import get_current_user
from ..rbac import Role, User, require_role
from ..tenancy import get_tenant_context

router = APIRouter(
    prefix="/capabilities", tags=["capabilities"], dependencies=[Depends(get_current_user)]
)


@router.post("/invoke", response_model=CapabilityResponse)
async def invoke_capability(
    call: CapabilityCall,
    request: Request,
    # P18 — this pre-Prime-Agent, generic endpoint (docs/006-integration-hub.md)
    # is the one real, reachable, user-facing path to `RunPrimeRLMAgent`:
    # any authenticated user can POST a call naming that capability here,
    # and PrimeRuntimeConnector._run() (integrations/connectors/
    # prime_runtime.py) creates a real MissionRow. P16/P17's own "no
    # user-facing mission-creation endpoint" conclusion was reached by
    # grepping for a caller of RunPrimeRLMAgent specifically, which missed
    # this generic, capability-agnostic invocation surface. Resolving the
    # caller's tenant here (the same dependency runtime_approvals.py's
    # router already uses) makes it visible to _run() via the same
    # contextvars.ContextVar db/tenancy.py already propagates through an
    # ordinary awaited call chain — no new plumbing through CapabilityCall
    # itself. Every existing seeded/test user has exactly one membership
    # (the default tenant) unless a test deliberately overrides it, so this
    # adds no new failure mode for any of this endpoint's other, unrelated
    # callers (NotifyOperator, etc. — capabilities with nothing to do with
    # tenancy, for which resolving a tenant context is a harmless no-op).
    _tenant=Depends(get_tenant_context),
) -> CapabilityResponse:
    """Runs Capability Registry -> Connector Policy Engine -> Connector,
    per docs/006-integration-hub.md. Governance clearance (policy tier,
    approver) must already be set on `call.governance` by the caller —
    this endpoint executes, it doesn't decide whether to (docs/007-governance.md)."""
    return await request.app.state.integration_hub.invoke(call)


# ---------------------------------------------------------------------
# Capability Manifest Registry (integrations/capability_manifest.py,
# vision §8.4/§8.7) — the governance lifecycle of onboarded capabilities.
# The registry itself predates this REST surface (it was wired into
# IntegrationHub with no routes exposing it); this is read/act access to
# the same instance backend/app/main.py constructs at startup.
#
# The list is empty until something actually calls .propose() — none of
# the built-in Capability enum members go through the §8 onboarding
# pipeline, so an empty list here is the honest current state, not a bug.
# ---------------------------------------------------------------------


def _risk_level(manifest: CapabilityManifest) -> str:
    max_tier = max((entry.tier for entry in manifest.risk_profile), default=PolicyTier.AUTONOMOUS)
    return {PolicyTier.AUTONOMOUS: "LOW", PolicyTier.APPROVAL_REQUIRED: "MEDIUM", PolicyTier.EXECUTIVE_APPROVAL: "HIGH"}[max_tier]


def _display_name(capability_id: str) -> str:
    # "zendesk.read_ticket" -> "Zendesk Read Ticket", "ApproveExpenseReport" -> "Approve Expense Report"
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", capability_id).replace(".", " ").replace("_", " ")
    return " ".join(w.capitalize() if w.islower() else w for w in words.split())


def _manifest_to_wire(manifest: CapabilityManifest) -> dict:
    return {
        "capability_id": manifest.capability_id,
        "display_name": _display_name(manifest.capability_id),
        "domain": manifest.domain,
        "version": manifest.version,
        "source": manifest.source,
        "proposed_by": manifest.proposed_by,
        "status": manifest.status.value,
        "risk_level": _risk_level(manifest),
        "requires_governance": any(entry.tier != PolicyTier.AUTONOMOUS for entry in manifest.risk_profile),
        # The registry stores sandbox evidence as free text describing what
        # was actually run — not a passed/total checks object. Returned
        # honestly as a string (or null), not reshaped into fake counters.
        "sandbox_evidence": manifest.sandbox_evidence,
        "usage_count": manifest.usage_count,
        "failure_count": manifest.failure_count,
        # None means never calibrated -- still fails safe to
        # EXECUTIVE_APPROVAL at invocation time (orchestrate/moa/graph.py's
        # _effective_policy_tier), not implicitly AUTONOMOUS.
        "tier_override": manifest.tier_override.value if manifest.tier_override is not None else None,
        "registered_at": manifest.registered_at.isoformat(),
    }


@router.get("/manifests")
async def list_capability_manifests(request: Request):
    manifests = await request.app.state.integration_hub.manifests.list_manifests()
    return [_manifest_to_wire(m) for m in manifests]


async def _find_manifest_or_404(request: Request, capability_id: str) -> CapabilityManifest:
    # list_manifests() (not manifest_for()) so the lookup also works right
    # after a process restart, when the in-memory cache starts empty but
    # Postgres has the rows.
    for manifest in await request.app.state.integration_hub.manifests.list_manifests():
        if manifest.capability_id == capability_id:
            return manifest
    raise HTTPException(status_code=404, detail=f"no capability manifest registered for {capability_id}")


@router.post("/manifests/{capability_id}/promote", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def promote_capability_manifest(
    capability_id: str, request: Request, current_user: User = Depends(get_current_user)
):
    """Advances one lifecycle step: SANDBOX_TESTED -> ACTIVE (activate) or
    HOT_DISABLED -> ACTIVE (resume). Deliberately does NOT fast-forward a
    PROPOSED manifest past the sandbox gate — §8.4's "sandbox testing is
    always mandatory, no skip option" is enforced structurally by the
    registry, and this endpoint won't fabricate sandbox evidence on the
    admin's behalf to get around it."""
    manifest = await _find_manifest_or_404(request, capability_id)
    registry = request.app.state.integration_hub.manifests
    actor = current_user.username
    reason = f"promoted via admin API by {current_user.display_name} ({current_user.role.value})"
    try:
        if manifest.status is CapabilityStatus.SANDBOX_TESTED:
            updated = await registry.activate(capability_id, actor=actor, reason=reason)
        elif manifest.status is CapabilityStatus.HOT_DISABLED:
            updated = await registry.resume(capability_id, actor=actor, reason=reason)
        elif manifest.status is CapabilityStatus.PROPOSED:
            raise PolicyViolation(
                f"capability {capability_id} has not passed sandbox testing yet — the sandbox gate is "
                "mandatory (§8.4) and cannot be skipped from the admin API"
            )
        elif manifest.status is CapabilityStatus.ACTIVE:
            raise PolicyViolation(f"capability {capability_id} is already active")
        else:  # DEPRECATED
            raise PolicyViolation(f"capability {capability_id} is deprecated and cannot be promoted")
    except PolicyViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    if updated.status is CapabilityStatus.ACTIVE:
        # An admin can reach ACTIVE via this generic endpoint instead of
        # orchestrate/onboarding/'s own /activate step — both must leave
        # the capability equally live (dispatchable + choosable by MOA),
        # not just marked ACTIVE in the registry. Safe no-op if this
        # capability_id has no onboarding_sessions row at all (e.g. a
        # built-in capability proposed outside the pipeline entirely).
        await onboarding_runtime_registry.register_runtime(
            async_session_factory, capability_id, request.app.state.integration_hub.dynamic_capability_connector
        )
    return {"status": updated.status.value, "capability_id": capability_id}


@router.post("/manifests/{capability_id}/disable", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def disable_capability_manifest(
    capability_id: str, request: Request, current_user: User = Depends(get_current_user)
):
    """§8.7's capability-level circuit breaker: hot-disables an ACTIVE
    capability. IntegrationHub.invoke()'s own authoritative check (P14)
    then blocks every invocation of it — a fresh Postgres read on every
    call, not a cache, so this takes effect on every worker immediately,
    not just the one that handled this request — until an explicit
    resume; this endpoint is the missing trigger, the enforcement side
    existed already."""
    await _find_manifest_or_404(request, capability_id)
    registry = request.app.state.integration_hub.manifests
    reason = f"hot-disabled via admin API by {current_user.display_name} ({current_user.role.value})"
    try:
        updated = await registry.hot_disable(capability_id, actor=current_user.username, reason=reason)
    except PolicyViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": updated.status.value, "capability_id": capability_id}


class CalibrateTierRequest(BaseModel):
    target_tier: PolicyTier


@router.post("/manifests/{capability_id}/calibrate-tier", dependencies=[Depends(require_role(Role.ADMIN, Role.EXECUTIVE))])
async def calibrate_capability_tier(
    capability_id: str, body: CalibrateTierRequest, request: Request, current_user: User = Depends(get_current_user)
):
    """Real per-action risk-tier calibration (vision §5.2/§8.6) —
    CapabilityManifestRegistry.calibrate_tier() fails closed unless a
    genuinely clean, sufficient usage track record backs the request (see
    that method's own docstring for the exact bar); this endpoint is just
    the admin-facing trigger, same shape as promote/disable above."""
    await _find_manifest_or_404(request, capability_id)
    registry = request.app.state.integration_hub.manifests
    reason = f"tier calibrated via admin API by {current_user.display_name} ({current_user.role.value})"
    try:
        updated = await registry.calibrate_tier(
            capability_id, target_tier=body.target_tier, actor=current_user.username, reason=reason
        )
    except PolicyViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "capability_id": capability_id,
        "tier_override": updated.tier_override.value if updated.tier_override is not None else None,
    }
