"""
Console connector — logs the action and returns success. Stands in for
SAP/ServiceNow/Maximo/etc. (Phase 3) so the full capability -> policy ->
connector -> execute path is exercisable end to end before any real
vendor connector exists. Never select this connector for a real Tier 1/2
production action; it's a dev/demo default only.
"""

import logging

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .base import Connector

logger = logging.getLogger("ados.integrations.console_connector")


class ConsoleConnector(Connector):
    name = "console"
    capabilities = set(Capability)  # fulfills every capability, for MVP demo purposes

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        logger.info(
            "console connector executing capability=%s incident=%s input=%s",
            call.capability.value,
            call.incident_id,
            call.input,
        )
        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output={"message": f"[console] simulated {call.capability.value}"},
        )
