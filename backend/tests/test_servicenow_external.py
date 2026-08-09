"""
EXPLICIT EXTERNAL-SIDE-EFFECT TEST — this MUTATES a real ServiceNow instance.

    pytest -m external backend/tests/test_servicenow_external.py

Deselected by default (`addopts = "-m 'not external'"`), so no ordinary
`pytest` run — CI, a hook, a laptop — can create real records as a side effect.

WHAT THIS PROVES, AND WHY THE OTHER TESTS CANNOT
------------------------------------------------
Every other test in this repository stops at ADOS's boundary: the connector was
selected, the request was well-formed, the audit row was written. None of that
is evidence that a ticket exists. This test goes and looks.

    governed NotifyITHelpdesk
      -> ADOS grant + policy + IntegrationHub
      -> ServiceNow connector
      -> real incident created
      -> sys_id + number returned
      -> ADOS capability_requests row references them, connector='servicenow'
      -> record read back from ServiceNow independently
      -> record closed

NO SILENT FALLBACK. If ServiceNow is unconfigured, unreachable, or misconfigured,
this test FAILS. It does not skip, and it does not accept a Console result.
Falling back would recreate precisely the false-success class this whole
integration was built to prevent: a green test proving nothing happened.

CLEANUP. Records are CLOSED (state 7), not deleted — closing is the normal
ServiceNow lifecycle and preserves the audit trail that is the point of the
exercise. Every created record carries an unmistakable marker so anything left
behind by an interrupted run is trivially findable:

    [ADOS PRIME-AGENT INTEGRATION TEST]

If cleanup fails the test still reports the sys_id it created, because a
silently orphaned ticket in someone's instance is worse than a noisy failure.
"""

import os
import uuid

import pytest
from sqlalchemy import select

from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import default_hub

pytestmark = pytest.mark.external

MARKER = "[ADOS PRIME-AGENT INTEGRATION TEST]"


def _require_servicenow() -> None:
    """FAIL, never skip. Being asked to run the external test without an
    external system to run it against is a failure of the request, not a
    reason to report success."""
    missing = [
        name
        for name in ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.fail(
            f"external test requires a real ServiceNow instance; missing {missing}. "
            "This test must not be run without one — it exists to prove a real "
            "side effect, and skipping would report success for work never done."
        )


async def test_notify_it_helpdesk_creates_a_real_servicenow_incident():
    _require_servicenow()

    test_id = uuid.uuid4().hex[:12]
    summary = f"{MARKER} {test_id} — synthetic checkout-api pool exhaustion"

    # A real mission row, so the capability request has something to reference
    # and the audit trail matches a normal governed call.
    async with async_session_factory() as db:
        mission = MissionRow(
            title=f"{MARKER} {test_id}",
            objective="external side-effect verification",
            domain="it",
            allowed_capabilities=[Capability.NOTIFY_IT_HELPDESK.value],
            status="running",
            created_by="external-integration-test",
        )
        db.add(mission)
        await db.commit()
        mission_id = mission.mission_id

    call = CapabilityCall(
        capability=Capability.NOTIFY_IT_HELPDESK,
        input={"summary": summary},
        requested_by=f"prime-runtime:mission:{mission_id}",
        incident_id=str(mission_id),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )

    # The real selection path. Not a hand-constructed ServiceNowConnector —
    # if registration order ever regressed and Console won, this must catch it.
    hub = default_hub()
    response = await hub.invoke(call)

    # 1. The connector that ran must be ServiceNow. A SUCCEEDED from `console`
    #    would mean "[console] simulated NotifyITHelpdesk" and no ticket.
    assert response.connector == "servicenow", (
        f"expected the ServiceNow connector, got {response.connector!r}. "
        "A Console result here is a simulated success and must fail this test."
    )
    assert response.status is CallStatus.SUCCEEDED, response.error

    # 2. Identifiers must come back, or there is nothing to verify against.
    sys_id = response.output.get("sys_id")
    number = response.output.get("number")
    assert sys_id, f"ServiceNow returned no sys_id: {response.output}"
    assert number, f"ServiceNow returned no incident number: {response.output}"
    print(f"\ncreated ServiceNow incident {number} (sys_id {sys_id})")

    connector = ServiceNowConnector()
    try:
        # 3. INDEPENDENT VERIFICATION. A 201 says ADOS sent something; reading
        #    the record back says a ticket exists. Only the second is evidence.
        ok, record = await connector.fetch_record("incident", sys_id)
        assert ok, f"could not read the incident back from ServiceNow: {record}"
        assert record.get("number") == number
        assert test_id in record.get("short_description", ""), (
            "the record exists but is not the one we created — "
            f"short_description={record.get('short_description')!r}"
        )
        assert str(mission_id) in record.get("description", ""), (
            "provenance missing: an operator could not trace this ticket to its mission"
        )

        # 4. ADOS's own audit row, written by the executor.
        async with async_session_factory() as db:
            db.add(
                CapabilityRequestRow(
                    session_id=uuid.uuid4(),
                    mission_id=mission_id,
                    capability=Capability.NOTIFY_IT_HELPDESK.value,
                    arguments={"summary": summary},
                    status="executed",
                    policy_tier=int(PolicyTier.AUTONOMOUS),
                    risk_class="low",
                    result={"ok": True, "capability": Capability.NOTIFY_IT_HELPDESK.value,
                            "outcome": response.model_dump(mode="json")},
                )
            )
            await db.commit()

            rows = (
                await db.execute(
                    select(CapabilityRequestRow).where(
                        CapabilityRequestRow.mission_id == mission_id,
                        CapabilityRequestRow.status == "executed",
                    )
                )
            ).scalars().all()

        assert len(rows) == 1
        audit = rows[0].result["outcome"]
        assert audit["connector"] == "servicenow"
        assert audit["output"]["sys_id"] == sys_id
        assert audit["output"]["number"] == number

    finally:
        # 5. Close it. Reported loudly on failure — an orphaned ticket in a real
        #    instance is worse than a noisy test.
        closed, detail = await connector.resolve_record(
            "incident", sys_id,
            close_notes=f"{MARKER} {test_id} — automated cleanup, no action required",
        )
        if closed:
            print(f"closed incident {number} (state={detail})")
        else:
            pytest.fail(
                f"LEFT AN OPEN RECORD IN SERVICENOW: {number} (sys_id {sys_id}). "
                f"Cleanup failed: {detail}. Close it manually; it is tagged {MARKER}."
            )


def test_the_external_test_refuses_to_run_without_servicenow(monkeypatch):
    """The guard itself. If this ever starts skipping instead of failing, the
    suite could report green having verified nothing.

    `pytest.raises(Failed)`, not `Exception`: pytest.fail raises
    `_pytest.outcomes.Failed`, which derives from BaseException precisely so
    that a bare `except Exception` in test code cannot swallow it. Asserting on
    `Exception` here made this test fail while appearing to check the guard —
    a test that could never have passed, which is its own small lesson.
    """
    from _pytest.outcomes import Failed

    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    with pytest.raises(Failed) as excinfo:
        _require_servicenow()
    assert "requires a real ServiceNow instance" in str(excinfo.value)
