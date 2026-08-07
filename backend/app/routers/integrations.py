"""
Integrations Status Router for Layer 4 Integration Hub.
Provides real-time connector health metrics, live Postgres connectivity, latency, and auth status.
Supports GET /integrations/status.
"""

import os
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from db.health import get_health_status as get_postgres_health_status
from integrations import default_hub
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


@router.get("/status", response_model=List[ConnectorStatusResponse])
async def get_connector_status():
    """Returns real-time status, configuration state, document counts, and latency for all connectors."""
    connectors_meta = [
        {
            "id": "servicenow",
            "name": "servicenow",
            "display_name": "ServiceNow ITSM Connector",
            "kind": "real",
            "auth": "Basic Auth (Table API)",
            "module": "integrations/connectors/servicenow.py",
            "description": "Automated IT/OT incident and change-request creation via the real ServiceNow Table API.",
            "capabilities": ["CreateIncident", "CreateChangeRequest", "ScheduleMaintenance"],
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
            "description": "Live sentiment, keyword, and category extraction over the Reasoning stage's LLM-generated explanation text.",
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

    # 1. Add PostgreSQL database status (db/health.py — replaces the old
    # Cloudant health card now that everything's migrated off it).
    pg_health = await get_postgres_health_status()
    result.append(
        ConnectorStatusResponse(
            name=pg_health["name"],
            id=pg_health["id"],
            configured=True,  # required application infrastructure — always configured, see db/health.py
            kind="real",
            status=pg_health.get("status", "Not Configured"),
            auth=pg_health.get("auth"),
            module=pg_health.get("module"),
            description=pg_health.get("description"),
            capabilities=pg_health.get("capabilities", []),
            connected=pg_health.get("connected", False),
            latency_ms=pg_health.get("latency_ms", 0),
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
        elif c_id == "servicenow":
            is_cfg = bool(
                os.environ.get("SERVICENOW_INSTANCE_URL")
                and os.environ.get("SERVICENOW_USERNAME")
                and os.environ.get("SERVICENOW_PASSWORD")
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
