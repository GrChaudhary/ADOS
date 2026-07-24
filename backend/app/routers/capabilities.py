from fastapi import APIRouter, Depends, Request

from contracts import CapabilityCall, CapabilityResponse

from ..auth import require_service_auth

router = APIRouter(
    prefix="/capabilities", tags=["capabilities"], dependencies=[Depends(require_service_auth)]
)


@router.post("/invoke", response_model=CapabilityResponse)
async def invoke_capability(call: CapabilityCall, request: Request):
    """Runs Capability Registry -> Connector Policy Engine -> Connector,
    per docs/006-integration-hub.md. Governance clearance (policy tier,
    approver) must already be set on `call.governance` by the caller —
    this endpoint executes, it doesn't decide whether to (docs/007-governance.md)."""
    return await request.app.state.integration_hub.invoke(call)
