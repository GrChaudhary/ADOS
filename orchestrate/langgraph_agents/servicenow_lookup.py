"""
Read-only ServiceNow incident lookup — reuses the SAME credentials as the
governed integrations/connectors/servicenow.py connector
(SERVICENOW_INSTANCE_URL/SERVICENOW_USERNAME/SERVICENOW_PASSWORD), so there
is exactly one ServiceNow credential configuration surface in the app now
that watsonx is being removed (orchestrate/servicenow_itsm_tools.py used a
second, IBM-ADK-specific connection registry pointed at a different
hardcoded dev instance).

Deliberately NOT routed through IntegrationHub/Capability: it's a pure
read with no governance-relevant side effects (vision doc §5.2's
blast-radius/reversibility factors — a lookup has neither), and the
Capability enum has no lookup capability defined today. Ticket *creation*
(the actual write) does go through the Hub — see itsm_agent.py.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

import httpx


def get_incident(number: str, transport: Optional[httpx.BaseTransport] = None) -> Dict[str, Any]:
    """Looks up a ServiceNow incident by its number (e.g. "INC0010023").
    `transport` is injectable so tests can use httpx.MockTransport instead
    of hitting a real instance, matching ServiceNowConnector's convention."""
    instance_url = os.environ.get("SERVICENOW_INSTANCE_URL")
    username = os.environ.get("SERVICENOW_USERNAME")
    password = os.environ.get("SERVICENOW_PASSWORD")
    if not instance_url or not username or not password:
        return {
            "error": "ServiceNow not configured: set SERVICENOW_INSTANCE_URL, "
            "SERVICENOW_USERNAME, SERVICENOW_PASSWORD (see .env.example)"
        }

    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    with httpx.Client(transport=transport, base_url=instance_url, timeout=15.0) as client:
        try:
            response = client.get(
                "/api/now/table/incident",
                params={"sysparm_query": f"number={number}", "sysparm_limit": "1"},
                headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
            )
        except httpx.HTTPError as e:
            return {"error": f"ServiceNow request failed: {e}"}

    if response.status_code >= 400:
        return {"error": f"ServiceNow returned {response.status_code}: {response.text[:500]}"}

    records = response.json().get("result", [])
    if not records:
        return {"error": "not found"}
    return records[0]
