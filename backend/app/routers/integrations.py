"""
Integrations Status Router for Layer 4 Integration Hub.
Provides real-time connector health metrics, live Cloudant document counts, latency, and auth status.
Supports GET /integrations/status and POST /integrations/watsonx/test-connection.
"""

import os
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from integrations import default_hub
from integrations.connectors.watsonx_itsm import WatsonxITSMConnector
from knowledge.cloudant_client import cloudant_db
from knowledge.local_llm_client import local_llm_client
from knowledge.nlu_client import nlu_client
from knowledge.tts_client import tts_client
from ..auth import get_current_user

router = APIRouter(prefix="/integrations", tags=["Integration Hub"], dependencies=[Depends(get_current_user)])


class ConnectorStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    configured: bool
    kind: str
    id: Optional[str] = None
    status: Optional[str] = None
    auth: Optional[str] = None
    module: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    connected: Optional[bool] = None
    latency_ms: Optional[float] = None
    doc_count: Optional[int] = None
    host: Optional[str] = None
    database_name: Optional[str] = None


class WatsonxTestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    connected: bool
    agent_count: Optional[int] = Field(default=None, alias="agentCount")
    agents: Optional[List[str]] = None
    error: Optional[str] = None


@router.get("/status", response_model=List[ConnectorStatusResponse])
async def get_connector_status():
    """Returns real-time status, configuration state, document counts, and latency for all connectors."""
    connectors_meta = [
        {
            "id": "watsonx_itsm",
            "name": "watsonx_itsm",
            "display_name": "IBM watsonx Orchestrate ITSM",
            "kind": "real",
            "auth": "IBM Cloud IAM OAuth 2.0",
            "module": "integrations/connectors/watsonx_itsm.py",
            "description": "Automated IT/OT incident creation, change request logging, and operator notifications.",
            "capabilities": ["CreateIncident", "CreateChangeRequest", "ScheduleMaintenance", "NotifyOperator"],
        },
        {
            "id": "sap",
            "name": "sap",
            "display_name": "SAP S/4HANA ERP Connector",
            "kind": "real",
            "auth": "SAP BAPI / OData REST API",
            "module": "integrations/connectors/sap.py",
            "description": "Automated B2B purchase order dispatch, component soft reservations, and ERP inventory updates.",
            "capabilities": ["CreatePurchaseOrder", "ReserveInventory", "QueryStockBalance"],
        },
        {
            "id": "marketplace",
            "name": "marketplace",
            "display_name": "External B2B Marketplace Connector",
            "kind": "simulated",
            "auth": "REST API + Bearer Secret Token",
            "module": "integrations/connectors/marketplace.py",
            "description": "Real-time query of global tier-1/tier-2 supplier inventory, stock lead times, and freight quotes.",
            "capabilities": ["QueryExternalStock", "CreateExternalPO", "GetFreightQuote"],
        },
        {
            "id": "factory_mes",
            "name": "factory_mes",
            "display_name": "Factory MES & PLC Digital Twin",
            "kind": "unimplemented",
            "auth": "OPC-UA / Modbus TCP Protocol",
            "module": "knowledge/digital_twin.py",
            "description": "Direct machine spindle parameter tuning, telemetry streaming, and preemption locks.",
            "capabilities": ["UpdateMachineFeed", "ApplySoftLock", "StreamTelemetry"],
        },
        {
            "id": "watson_nlu",
            "name": "watson_nlu",
            "display_name": "IBM Watson Natural Language Understanding",
            "kind": "real",
            "auth": "IBM Cloud IAM OAuth 2.0",
            "module": "knowledge/nlu_client.py",
            "description": "Live sentiment, keyword, and category extraction over the Reasoning stage's watsonx.ai explanation text.",
            "capabilities": ["AnalyzeText", "ExtractSentiment", "ExtractKeywords"],
        },
        {
            "id": "watson_tts",
            "name": "watson_tts",
            "display_name": "IBM Watson Text to Speech",
            "kind": "real",
            "auth": "IBM Cloud IAM OAuth 2.0",
            "module": "knowledge/tts_client.py",
            "description": "Live speech synthesis for spoken incident-resolution briefings (opt-in per-incident via TTS_INCIDENT_BRIEFING_ENABLED).",
            "capabilities": ["SynthesizeSpeech"],
        },
    ]

    result: List[ConnectorStatusResponse] = []

    # 1. Add Cloudant NoSQL database status
    cloudant_health = cloudant_db.get_health_status()
    result.append(
        ConnectorStatusResponse(
            name="IBM Cloudant NoSQL Database",
            id="cloudant_nosql",
            configured=cloudant_db.is_configured(),
            kind="real",
            status=cloudant_health.get("status", "Not Configured"),
            auth="IBM Cloud IAM OAuth 2.0",
            module="knowledge/cloudant_client.py",
            description=cloudant_health.get("description", "Production Cloudant NoSQL document database."),
            capabilities=["QueryDatabase", "PersistIncident", "StreamAuditLogs"],
            connected=cloudant_health.get("connected", False),
            latency_ms=cloudant_health.get("latency_ms", 0),
            doc_count=cloudant_health.get("doc_count", 0),
            host=cloudant_health.get("host"),
            database_name=cloudant_health.get("database_name"),
        )
    )

    # 2. Add LLM provider status — one row per backend, since
    # knowledge/local_llm_client.py does automatic failover across all of
    # them (Nemotron, OpenAI, Anthropic, then Ollama) rather than a single
    # active one; showing only "whichever is primary" would hide that the
    # others are standing by. role text on each makes the actual failover
    # order visible instead of identical-looking rows. API keys for the
    # first three are managed from the Settings page, not just .env.
    for status in [*local_llm_client.list_provider_statuses(), local_llm_client.get_ollama_status()]:
        result.append(
            ConnectorStatusResponse(
                name=f"{status.get('name', 'LLM Provider')} — {status.get('role', '')}".rstrip(" —"),
                id=f"local_llm_{status.get('provider', 'ollama')}",
                configured=status.get("configured", False),
                kind="real",
                status=status.get("status", "Not Configured"),
                auth=status.get("auth", "Unknown"),
                module="knowledge/local_llm_client.py",
                description=status.get("description", "Root-cause reasoning generation used by the Reasoning stage."),
                capabilities=["GenerateRootCauseExplanation"],
                connected=status.get("connected", False),
                host=status.get("host"),
            )
        )

    # 3. Add standard connectors checking real environment configuration state
    for meta in connectors_meta:
        c_id = meta["id"]
        is_cfg = False
        if c_id == "sap":
            is_cfg = bool(os.environ.get("SAP_BASE_URL") and os.environ.get("SAP_API_KEY"))
        elif c_id == "watsonx_itsm":
            is_cfg = bool(
                os.environ.get("WO_INSTANCE")
                and os.environ.get("WO_API_KEY")
                and os.environ.get("WO_ITSM_INTEGRATION_ENABLED") == "true"
            )
        elif c_id == "marketplace":
            is_cfg = False
        elif c_id == "watson_nlu":
            is_cfg = nlu_client.is_configured()
        elif c_id == "watson_tts":
            is_cfg = tts_client.is_configured()

        status_text = (
            "Configured"
            if is_cfg
            else ("Simulated (mock data)" if meta["kind"] == "simulated" else ("No connector implemented" if meta["kind"] == "unimplemented" else "Not Configured"))
        )

        result.append(
            ConnectorStatusResponse(
                name=meta["display_name"],
                id=meta["id"],
                configured=is_cfg,
                kind=meta["kind"],
                status=status_text,
                auth=meta["auth"],
                module=meta["module"],
                description=meta["description"],
                capabilities=meta["capabilities"],
                connected=is_cfg or meta["kind"] == "simulated",
            )
        )

    return result


@router.post("/watsonx/test-connection", response_model=WatsonxTestResponse)
async def test_watsonx_connection():
    """Test connection endpoint for IBM watsonx Orchestrate ITSM."""
    connector = WatsonxITSMConnector()
    if hasattr(connector, "test_connection"):
        res = await connector.test_connection()
        return WatsonxTestResponse.model_validate(res)

    inst = os.environ.get("WO_INSTANCE")
    key = os.environ.get("WO_API_KEY")
    if not inst or not key:
        return WatsonxTestResponse(connected=False, error="WO_INSTANCE or WO_API_KEY not set in environment")

    return WatsonxTestResponse(connected=True, agent_count=1, agents=["ados_executive_copilot"])
