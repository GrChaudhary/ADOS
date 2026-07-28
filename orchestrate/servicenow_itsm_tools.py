"""
IBM watsonx Orchestrate ADK tool(s) for a dedicated ADOS ITSM agent, talking
directly to a ServiceNow instance's Table REST API. Registered against the
live instance via:

    orchestrate tools import -k python -f orchestrate/servicenow_itsm_tools.py \
      -a ados_servicenow_dev397690

See orchestrate/ITSM_AGENT_SETUP.md for the full setup procedure (connection
registration, credentials, agent creation, and how this differs from
integrations/connectors/watsonx_itsm.py's current _INCIDENT_AGENT_ID, the
repurposed ados_executive_copilot agent). Deliberately minimal - two tools,
one purpose - not the 32-tool general ServiceNow suite that agent carries.

Standard library + the ADK's connection-credential helper only, since the
ADK packages this file independently onto IBM's infra - no local
`contracts`/`backend` imports, matching orchestrate/watsonx_tools.py's
existing convention.
"""

import base64
import json
import urllib.error
import urllib.request
from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.connections import (
    ConnectionType,
    ExpectedCredentials,
    get_application_connection_credentials,
)
from ibm_watsonx_orchestrate.agent_builder.tools import ToolPermission, tool

# Must match the --app-id used when the connection was registered
# (orchestrate connections add/configure/set-credentials — see
# orchestrate/ITSM_AGENT_SETUP.md step 1) and the -a flag on `orchestrate
# tools import` below.
_APP_ID = "ados_servicenow_dev397690"
_INSTANCE_URL = "https://dev397690.service-now.com"

_EXPECTED_CREDENTIALS = [ExpectedCredentials(app_id=_APP_ID, type=ConnectionType.BASIC_AUTH)]


def _table_request(method: str, path: str, body: Optional[dict] = None) -> dict:
    creds = get_application_connection_credentials(ConnectionType.BASIC_AUTH, _APP_ID)
    auth = base64.b64encode(f"{creds.username}:{creds.password}".encode()).decode()
    data = json.dumps(body).encode("utf-8") if body is not None else None

    request = urllib.request.Request(
        f"{_INSTANCE_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code}: {e.read().decode(errors='replace')[:500]}"}
    except urllib.error.URLError as e:
        return {"error": f"request failed: {e.reason}"}


@tool(permission=ToolPermission.WRITE_ONLY, expected_credentials=_EXPECTED_CREDENTIALS)
def create_incident(
    short_description: str,
    description: str = "",
    impact: str = "3 - Low",
    urgency: str = "3 - Low",
) -> dict:
    """Creates a ServiceNow incident record via the Table API.

    Args:
        short_description: One-line summary of the incident.
        description: Full incident description/details.
        impact: ServiceNow impact value: "1 - High", "2 - Medium", or "3 - Low".
        urgency: ServiceNow urgency value, same scale as impact.

    Returns:
        {"sys_id": ..., "number": ...} on success, or {"error": ...} on failure.
    """
    result = _table_request(
        "POST",
        "/api/now/table/incident",
        {
            "short_description": short_description,
            "description": description,
            "impact": impact,
            "urgency": urgency,
        },
    )
    if "error" in result:
        return result
    record = result.get("result", {})
    return {"sys_id": record.get("sys_id"), "number": record.get("number")}


@tool(permission=ToolPermission.READ_ONLY, expected_credentials=_EXPECTED_CREDENTIALS)
def get_incident(number: str) -> dict:
    """Looks up a ServiceNow incident by its number (e.g. "INC0010023").

    Args:
        number: The incident number to look up.

    Returns:
        The incident record if found, or {"error": "not found"} / {"error": ...}.
    """
    result = _table_request(
        "GET", f"/api/now/table/incident?sysparm_query=number={number}&sysparm_limit=1"
    )
    if "error" in result:
        return result
    records = result.get("result", [])
    if not records:
        return {"error": "not found"}
    return records[0]
