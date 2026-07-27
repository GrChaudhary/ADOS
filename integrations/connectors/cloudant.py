"""
IBM Cloudant Connector.
Fulfills QUERY_DATABASE and PERSIST_INCIDENT capabilities by delegating to CloudantClient.
"""

from typing import Set
from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse
from .base import Connector

_CLOUDANT_CAPABILITIES: Set[Capability] = {
    Capability.QUERY_DATABASE,
    Capability.PERSIST_INCIDENT,
}


class CloudantConnector(Connector):
    """
    Connector adapter for IBM Cloudant NoSQL Database.
    Translates ADOS capability calls into Cloudant execution payloads.
    """
    name = "cloudant_nosql"
    capabilities = _CLOUDANT_CAPABILITIES

    def is_configured(self) -> bool:
        from knowledge.cloudant_client import cloudant_db
        return cloudant_db.is_configured()

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        from knowledge.cloudant_client import cloudant_db

        if not self.is_configured():
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="IBM Cloudant not configured: set CLOUDANT_URL and CLOUDANT_API_KEY in .env"
            )

        try:
            if call.capability == Capability.PERSIST_INCIDENT:
                doc_id = cloudant_db.save_incident(call.input)
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.SUCCEEDED,
                    connector=self.name,
                    output={"document_id": doc_id, "status": "persisted"},
                )

            elif call.capability == Capability.QUERY_DATABASE:
                query_str = call.input.get("query", "")
                docs = cloudant_db.search_incidents(query_str)
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.SUCCEEDED,
                    connector=self.name,
                    output={"total_matches": len(docs), "documents": docs},
                )

            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"Unsupported capability {call.capability}",
            )
        except Exception as e:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"Cloudant error: {e}",
            )
