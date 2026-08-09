"""
Tests for the governed evidence-retrieval path.

The point of routing evidence through a capability is that a runtime which
cannot execute cannot obtain facts. That property is only real if the connector
actually reads ADOS's store — a stub that returns SUCCEEDED with a friendly
message would restore the exact hazard the capability exists to remove, while
looking identical in the audit trail.
"""

import uuid

import pytest
from sqlalchemy import text

from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.mission import MissionRow
from integrations.hub import default_hub

EVIDENCE = {
    "incident_id": "SYN-4417",
    "service": "checkout-api",
    "app_log": ["asyncpg.exceptions.TooManyConnectionsError: too many clients already"],
    "release_diff": {"DB_POOL_SIZE": {"before": 10, "after": 100}},
}


@pytest.fixture(autouse=True)
async def _clean_missions():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions CASCADE"))
        await db.commit()
    yield


async def _mission(evidence=EVIDENCE) -> uuid.UUID:
    async with async_session_factory() as db:
        row = MissionRow(
            title="t", objective="o", domain="it",
            allowed_capabilities=[Capability.FETCH_INCIDENT_EVIDENCE.value],
            evidence=evidence,
        )
        db.add(row)
        await db.commit()
        return row.mission_id


def _call(mission_id) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.FETCH_INCIDENT_EVIDENCE,
        input={},
        requested_by="test",
        incident_id=str(mission_id),
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def test_evidence_comes_back_from_ados_own_store():
    mission_id = await _mission()
    response = await default_hub().invoke(_call(mission_id))

    assert response.status is CallStatus.SUCCEEDED
    # The connector identity matters as much as the status: a SUCCEEDED from
    # `console` would mean the agent received "[console] simulated
    # FetchIncidentEvidence" and no facts at all.
    assert response.connector == "mission-evidence"
    assert response.output["evidence"] == EVIDENCE


async def test_console_does_not_win_the_evidence_capability():
    """ConsoleConnector declares set(Capability) and is_configured() is True,
    so registration order in default_hub() is the only thing standing between a
    read capability and a fabricated success. Assert it directly."""
    connectors = default_hub().registry.connectors_for(Capability.FETCH_INCIDENT_EVIDENCE)
    assert connectors[0].name == "mission-evidence", [c.name for c in connectors]


async def test_a_mission_with_no_evidence_is_a_failed_read_not_an_empty_success():
    mission_id = await _mission(evidence=None)
    response = await default_hub().invoke(_call(mission_id))

    assert response.status is CallStatus.FAILED
    assert "no evidence attached" in (response.error or "")


async def test_evidence_is_scoped_to_the_mission_id_ados_supplies():
    """The gateway sets incident_id from the resolved session row, never from
    the runtime's request, so an unknown mission must fail rather than fall
    back to anything."""
    response = await default_hub().invoke(_call(uuid.uuid4()))
    assert response.status is CallStatus.FAILED
    assert "no such mission" in (response.error or "")
