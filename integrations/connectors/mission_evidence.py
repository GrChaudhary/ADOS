"""
Mission evidence connector — serves ADOS's own case file for a mission, and
nothing else.

WHY A CONNECTOR AND NOT A CONVENIENCE
-------------------------------------
The obvious alternative is to drop the incident data into the runtime's
workspace at start-up. That is simpler, and it quietly destroys the property
that makes the whole boundary worth having.

A runtime holding its evidence up front can produce a confident report whether
or not its tools work. One did: with every kernel execution failing, it wrote a
detailed root-cause analysis blaming disk-space exhaustion on a database server
that appears nowhere in the incident it was given, and there was nothing in the
observable record to distinguish that from real analysis except reading the
prose and knowing the answer.

Make the facts reachable only through a governed capability and the situation
becomes decidable without reading a word of the report: no capability row, no
evidence retrieved, no possible analysis. ADOS can tell the difference in SQL.

SCOPE
-----
Read-only, and scoped server-side to the mission the calling session belongs to.
`call.incident_id` carries the mission id, set by the gateway from the resolved
session row — never from anything the runtime sent. A runtime cannot read
another mission's case file by asking nicely, or at all.
"""

import logging
import uuid

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .base import Connector

logger = logging.getLogger("ados.integrations.mission_evidence")


class MissionEvidenceConnector(Connector):
    name = "mission-evidence"
    capabilities = {Capability.FETCH_INCIDENT_EVIDENCE}

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        # Imported here rather than at module scope: integrations/ is imported
        # by contracts-level code and must not drag the database layer in with it.
        from db.engine import async_session_factory
        from db.models.mission import MissionRow
        from db.tenancy import all_tenants_session

        try:
            mission_id = uuid.UUID(str(call.incident_id))
        except (TypeError, ValueError):
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"not a mission id: {call.incident_id!r}",
            )

        # P17 — reached via the runtime's session-token boundary (see
        # module docstring: "scoped server-side to the mission the calling
        # session belongs to"), never a user JWT/tenant context. That
        # scoping (call.incident_id set server-side by the gateway from the
        # resolved session, never runtime-supplied) is already narrower
        # than tenant membership, so a single targeted get-by-id here is
        # safe under db/tenancy.py's ALL_TENANTS escape hatch.
        async with all_tenants_session(async_session_factory) as db:
            mission = await db.get(MissionRow, mission_id)

        if mission is None:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"no such mission: {mission_id}",
            )

        # An empty case file is a FAILED read, not an empty success. Success
        # here is the agent's warrant for saying "I have the facts", so
        # returning SUCCEEDED with nothing in it would hand out that warrant
        # for free — the precise mistake this connector exists to prevent.
        if not mission.evidence:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"mission {mission_id} has no evidence attached",
            )

        logger.info(
            "Mission evidence served",
            extra={"mission_id": str(mission_id), "keys": sorted(mission.evidence)},
        )
        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output={"mission_id": str(mission_id), "evidence": mission.evidence},
        )
