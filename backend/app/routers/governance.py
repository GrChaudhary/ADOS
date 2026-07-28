"""
Real governance/policy data — replaces the frontend's previously
hardcoded "Enforced Policy Rules" panel (frontend-next/src/app/governance/
page.tsx), which showed 4 items as "ACTIVE" with no backend behind any of
them (confirmed this session: one, "supplier switch requires stock
verification," has no enforcing code anywhere in the repo). Everything
returned here is read directly from the modules that actually enforce it.
"""

import os

from fastapi import APIRouter, Depends

from orchestrate.governance import CAPABILITY_RISK_CLASS, HIGH_EXPOSURE_MIN_USD, LOW_EXPOSURE_MAX_USD, TIER0_CONFIDENCE_THRESHOLD

from ..auth import get_current_user

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
            "connectorEligible": os.environ.get("WO_ITSM_INTEGRATION_ENABLED") == "true",
            "liveWritesEnabled": os.environ.get("WO_ITSM_LIVE_WRITES_ENABLED") == "true",
            "source": "integrations/connectors/watsonx_itsm.py",
        },
    }
