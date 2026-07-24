"""
IBM watsonx Orchestrate ADK tool(s) exposing ADOS to Orchestrate agents.
Registered against the live instance via:

    orchestrate tools import -k python -f orchestrate/watsonx_tools.py

Each tool is a standalone function — the ADK packages this file
independently onto IBM's infrastructure, so it deliberately uses only the
standard library (no local `contracts`/`backend` imports) and talks to a
running ADOS backend over plain HTTP, configured via env vars set on the
Orchestrate side (ADOS_BACKEND_URL, ADOS_SERVICE_TOKEN) — see
docs/005-decision-orchestrator.md's IBM stack mapping.
"""

import json
import os
import urllib.request

from ibm_watsonx_orchestrate.agent_builder.tools import tool

_DEFAULT_BACKEND_URL = "http://localhost:8000"


def _get(path: str) -> dict:
    base_url = os.environ.get("ADOS_BACKEND_URL", _DEFAULT_BACKEND_URL)
    token = os.environ.get("ADOS_SERVICE_TOKEN", "dev-local-only-token")
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


@tool
def get_ados_executive_kpis() -> dict:
    """Fetches ADOS's current executive KPIs: MTTR, Revenue Protected,
    Supplier Resilience, Autonomy Index, and Recommendation Acceptance
    Rate, computed over the live incident audit trail
    (docs/008-executive-intelligence.md)."""
    return _get("/executive/kpis")


@tool
def get_ados_pending_approvals() -> dict:
    """Lists ADOS incidents currently awaiting a Tier 1/2 human approval
    decision — capability, confidence, and a human-readable summary of
    the recommendation (docs/007-governance.md)."""
    return {"pending_approvals": _get("/approvals")}
