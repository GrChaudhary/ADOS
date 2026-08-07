"""
Executive copilot tools — same two endpoints orchestrate/watsonx_tools.py
called, minus the IBM ADK's @tool decorator (that decorator exists so the
ADK can package the file independently onto IBM's infrastructure; this
agent now runs inside the ADOS process itself, so that packaging step no
longer applies). httpx instead of urllib, matching
knowledge/local_llm_client.py's convention elsewhere in this codebase.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

_DEFAULT_BACKEND_URL = "http://localhost:8000"


def _get(path: str) -> Dict[str, Any]:
    base_url = os.environ.get("ADOS_BACKEND_URL", _DEFAULT_BACKEND_URL)
    token = os.environ.get("ADOS_SERVICE_TOKEN", "dev-local-only-token")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


def get_ados_executive_kpis() -> Dict[str, Any]:
    """Fetches ADOS's current executive KPIs: MTTR, Revenue Protected,
    Supplier Resilience, Autonomy Index, and Recommendation Acceptance
    Rate, computed over the live incident audit trail."""
    return _get("/executive/kpis")


def get_ados_pending_approvals() -> Dict[str, Any]:
    """Lists ADOS incidents currently awaiting a Tier 1/2 human approval
    decision — capability, confidence, and a human-readable summary of
    the recommendation."""
    return {"pending_approvals": _get("/approvals")}


TOOLS = {
    "get_ados_executive_kpis": get_ados_executive_kpis,
    "get_ados_pending_approvals": get_ados_pending_approvals,
}

TOOL_DESCRIPTIONS = "\n".join(f"- {name}: {fn.__doc__.strip().splitlines()[0]}" for name, fn in TOOLS.items())


def in_process_tools(orchestrator) -> Dict[str, Any]:
    """In-process variants of the two tools above, for when this agent runs
    inside the same FastAPI process as the backend it's querying (the real
    case now — the HTTP tools above were carried over unchanged from the
    watsonx-era design, where the agent genuinely ran on separate IBM
    infrastructure and had no other way to reach ADOS).

    Two independent reasons this matters, not just efficiency: the HTTP
    tools authenticate with a static bearer token
    (ADOS_SERVICE_TOKEN/"dev-local-only-token") that predates this
    codebase's move to real JWT/RBAC auth (see backend/app/auth.py's
    docstring — that shared-token scheme was replaced, not kept as a
    fallback) — called against the real backend today, they would 401.
    Reading straight from the orchestrator's own in-memory state sidesteps
    a self-referential network call and a broken auth path at once.

    Shaped identically to TOOLS above (same keys, same return shapes) so a
    caller can swap one dict for the other without the graph code caring
    which it got — see executive_copilot.py's build_graph(tools=...).
    """
    from executive import KPIEngine

    def get_ados_executive_kpis() -> Dict[str, Any]:
        engine = KPIEngine(records=orchestrator.audit_trail.all())
        return engine.compute_kpis().model_dump(by_alias=True)

    def get_ados_pending_approvals() -> Dict[str, Any]:
        pending = orchestrator.approvals.list_pending()
        return {
            "pending_approvals": [
                {
                    "incidentId": a.incident_id,
                    "capability": a.capability.value,
                    "policyTier": int(a.policy_tier),
                    "confidence": a.confidence,
                    "summary": a.summary,
                }
                for a in pending
            ]
        }

    return {
        "get_ados_executive_kpis": get_ados_executive_kpis,
        "get_ados_pending_approvals": get_ados_pending_approvals,
    }
