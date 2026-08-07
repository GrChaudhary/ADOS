#!/usr/bin/env python
"""
Prove the ServiceNow connector actually works against a real instance.

This is the difference between "the request shape looks right against a
mocked transport" (what tests/test_connectors.py and
tests/test_servicenow_fields.py check) and "a ticket exists that a human can
open in a browser". Until someone runs this, the connector is unverified --
its own docstring said so for months.

Deliberately drives the REAL code path -- IntegrationHub -> policy engine ->
ServiceNowConnector -> Table API -- rather than making its own HTTP call, so
a pass here means the thing MOA uses works, not that requests can reach
service-now.com.

Setup (about five minutes, no cost): docs/SERVICENOW_PILOT.md

    export SERVICENOW_INSTANCE_URL=https://devXXXXX.service-now.com
    export SERVICENOW_USERNAME=admin
    export SERVICENOW_PASSWORD='...'
    ./.venv/bin/python scripts/servicenow_smoke.py

Creates real records. Point it at a Personal Developer Instance, never at
anything anyone depends on.
"""

import asyncio
import os
import sys
from pathlib import Path

# Same convention as the other scripts here — run directly, not as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.hub import default_hub

_REQUIRED = ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")


def _check_env() -> str:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        print(f"✗ Not configured. Missing: {', '.join(missing)}")
        print("  See docs/SERVICENOW_PILOT.md for how to get a free instance.")
        sys.exit(1)
    return os.environ["SERVICENOW_INSTANCE_URL"].rstrip("/")


async def _read_back(instance_url: str, table: str, sys_id: str) -> dict:
    """Independent confirmation the record is really there. A 201 from the
    create call is good evidence; reading the row back by sys_id is proof."""
    auth = (os.environ["SERVICENOW_USERNAME"], os.environ["SERVICENOW_PASSWORD"])
    async with httpx.AsyncClient(base_url=instance_url, timeout=30.0) as client:
        response = await client.get(
            f"/api/now/table/{table}/{sys_id}",
            auth=auth,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json().get("result", {})


async def main() -> int:
    instance_url = _check_env()
    hub = default_hub()

    print(f"Instance: {instance_url}")
    print()

    # The exact payload orchestrate/moa/graph.py:_action_input() builds for
    # an HR offboarding step -- not a hand-tuned one that happens to already
    # use ServiceNow field names. This is the case that used to silently
    # create a blank ticket.
    call = CapabilityCall(
        capability=Capability.STOP_PAYROLL,
        incident_id="smoke-test",
        requested_by="scripts/servicenow_smoke.py",
        input={"employee_name": "ADOS Smoke Test", "action": "stop_payroll"},
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )

    print("→ Invoking StopPayroll through the real IntegrationHub...")
    response = await hub.invoke(call)

    if response.status is not CallStatus.SUCCEEDED:
        print(f"✗ FAILED via connector '{response.connector}': {response.error}")
        return 1

    if response.connector != "servicenow":
        print(f"✗ Went to connector '{response.connector}', not servicenow.")
        print("  The console fallback ran, so nothing real happened. Check that")
        print("  all three SERVICENOW_* variables are set in THIS process.")
        return 1

    sys_id = response.output.get("sys_id")
    number = response.output.get("number", "(no number returned)")
    if not sys_id:
        print(f"✗ ServiceNow returned no sys_id: {response.output!r}")
        return 1

    print(f"  Created {number}  (sys_id {sys_id})")
    print()
    print("→ Reading it back to confirm it really exists...")
    record = await _read_back(instance_url, "change_request", sys_id)

    short_description = record.get("short_description", "")
    if not short_description:
        print("✗ The record exists but its short_description is EMPTY.")
        print("  This is exactly the blank-ticket bug servicenow_fields.py fixes.")
        return 1

    print(f'  short_description: "{short_description}"')
    print(f'  description:       "{record.get("description", "")[:80]}..."')
    print()
    print("✓ A real ServiceNow ticket exists, created through the real ADOS path.")
    print(f"  Open it: {instance_url}/nav_to.do?uri=change_request.do?sys_id={sys_id}")
    print()
    print("  It is a real record on a real instance -- delete it when you're done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
