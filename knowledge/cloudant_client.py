"""
IBM Cloudant Database Manager for ADOS.
Handles real-time document persistence, auto-database creation,
seed dataset synchronization, Lucene/Selector search for Decision Memory RAG,
and live health telemetry.
"""

import os
import time

from typing import Dict, Any, List, Optional
from ibmcloudant.cloudant_v1 import CloudantV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

from backend.app.config import settings
from executive.seed_data import HERO_INCIDENTS


class CloudantClient:
    """
    Singleton client manager for IBM Cloudant NoSQL database.
    Manages ados_incidents, ados_events, and ados_agents JSON document collections.
    """

    def __init__(self):
        self.url = settings.cloudant_url
        self.api_key = settings.cloudant_api_key
        self.db_incidents = settings.cloudant_db_incidents or "ados_incidents"
        self.db_events = settings.cloudant_db_events or "ados_events"
        self.db_agents = "ados_agents"
        self.db_users = settings.cloudant_db_users or "ados_users"
        self.db_settings = "ados_settings"
        self.client: Optional[CloudantV1] = None
        self._initialized = False

    def is_configured(self) -> bool:
        # If env vars were explicitly deleted during monkeypatch tests, report unconfigured
        if "CLOUDANT_URL" not in os.environ or "CLOUDANT_API_KEY" not in os.environ:
            return False

        url = os.environ.get("CLOUDANT_URL") or settings.cloudant_url
        key = os.environ.get("CLOUDANT_API_KEY") or settings.cloudant_api_key or settings.ibm_cloud_api_key
        return bool(url and key)

    def initialize(self) -> bool:
        if not self.is_configured():
            return False

        try:
            url = os.environ.get("CLOUDANT_URL") or settings.cloudant_url
            key = os.environ.get("CLOUDANT_API_KEY") or settings.cloudant_api_key or settings.ibm_cloud_api_key
            authenticator = IAMAuthenticator(key)
            self.client = CloudantV1(authenticator=authenticator)
            self.client.set_service_url(url)

            # Ensure databases exist
            all_dbs = self.client.get_all_dbs().get_result()
            if self.db_incidents not in all_dbs:
                self.client.put_database(db=self.db_incidents)
            if self.db_events not in all_dbs:
                self.client.put_database(db=self.db_events)
            if self.db_agents not in all_dbs:
                self.client.put_database(db=self.db_agents)
                print(f"[Cloudant] Created database '{self.db_agents}' for dynamic agent registry.")
            if self.db_users not in all_dbs:
                self.client.put_database(db=self.db_users)
            if self.db_settings not in all_dbs:
                self.client.put_database(db=self.db_settings)

            self._initialized = True
            self.seed_initial_data_if_empty()
            return True
        except Exception as e:
            print(f"[Cloudant Initialization Error]: {e}")
            self.client = None
            self._initialized = False
            return False

    def seed_initial_data_if_empty(self) -> None:
        """Seeds hero incident fixtures if ados_incidents database is empty."""
        if not self.client or not self._initialized:
            return

        try:
            info = self.client.get_database_information(db=self.db_incidents).get_result()
            doc_count = info.get("doc_count", 0)
            if doc_count == 0:
                print(f"[Cloudant] Seeding initial hero incidents to database '{self.db_incidents}'...")
                for hero in HERO_INCIDENTS:
                    doc = hero.model_dump(by_alias=True)
                    doc["_id"] = hero.incident_id
                    try:
                        self.client.post_document(db=self.db_incidents, document=doc).get_result()
                    except Exception as err:
                        print(f"[Cloudant Seed Error] {hero.incident_id}: {err}")
                print("[Cloudant] Hero dataset seeded successfully.")
        except Exception as e:
            print(f"[Cloudant Seed Check Error]: {e}")

    def save_incident(self, incident_dict: Dict[str, Any]) -> str:
        """Persist or update an incident JSON document in Cloudant."""
        if not self.client:
            return incident_dict.get("incidentId") or incident_dict.get("incident_id") or ""

        incident_id = incident_dict.get("incidentId") or incident_dict.get("incident_id")
        doc = dict(incident_dict)
        doc["_id"] = incident_id

        # If document already exists, retrieve existing _rev for CouchDB document update
        try:
            existing = self.client.get_document(db=self.db_incidents, doc_id=incident_id).get_result()
            if "_rev" in existing:
                doc["_rev"] = existing["_rev"]
        except Exception:
            pass  # New document

        try:
            res = self.client.post_document(db=self.db_incidents, document=doc).get_result()
            return res.get("id", incident_id)
        except Exception as e:
            print(f"[Cloudant] Error saving incident {incident_id}: {e}")
            return incident_id

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an incident document from Cloudant by ID."""
        if not self.client:
            return None
        try:
            doc = self.client.get_document(db=self.db_incidents, doc_id=incident_id).get_result()
            return doc
        except Exception:
            return None

    def list_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve all incident records from Cloudant."""
        if not self.client:
            return []
        try:
            res = self.client.post_all_docs(db=self.db_incidents, include_docs=True, limit=limit).get_result()
            rows = res.get("rows", [])
            docs = [r["doc"] for r in rows if "doc" in r and not r["id"].startswith("_design")]
            return docs
        except Exception as e:
            print(f"[Cloudant] Error listing incidents: {e}")
            return []

    def search_incidents(self, query_text: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Execute Cloudant selector find query for Decision Memory RAG search."""
        if not self.client:
            return []
        if not query_text or query_text.strip() == "":
            return self.list_incidents(limit=limit)

        try:
            selector = {
                "$or": [
                    {"lineId": {"$regex": f"(?i){query_text}"}},
                    {"plantId": {"$regex": f"(?i){query_text}"}},
                    {"causalChain.0.description": {"$regex": f"(?i){query_text}"}},
                    {"incidentId": {"$regex": f"(?i){query_text}"}},
                ]
            }
            res = self.client.post_find(db=self.db_incidents, selector=selector, limit=limit).get_result()
            return res.get("docs", [])
        except Exception as e:
            print(f"[Cloudant] Search find query error for '{query_text}': {e}")
            return self.list_incidents(limit=limit)

    def save_user(self, user_dict: Dict[str, Any]) -> str:
        """Persist or update a user document (backend/app/user_store.py) —
        mirrors save_incident's upsert-by-_id pattern exactly."""
        if not self.client:
            return user_dict.get("userId") or user_dict.get("user_id") or ""

        user_id = user_dict.get("userId") or user_dict.get("user_id")
        doc = dict(user_dict)
        doc["_id"] = user_id

        try:
            existing = self.client.get_document(db=self.db_users, doc_id=user_id).get_result()
            if "_rev" in existing:
                doc["_rev"] = existing["_rev"]
        except Exception:
            pass  # New document

        try:
            res = self.client.post_document(db=self.db_users, document=doc).get_result()
            return res.get("id", user_id)
        except Exception as e:
            print(f"[Cloudant] Error saving user {user_id}: {e}")
            return user_id

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Looks up a user by username (not _id) via a selector query —
        backend/app/user_store.py's login path."""
        if not self.client:
            return None
        try:
            res = self.client.post_find(
                db=self.db_users, selector={"username": username}, limit=1
            ).get_result()
            docs = res.get("docs", [])
            return docs[0] if docs else None
        except Exception as e:
            print(f"[Cloudant] Error looking up user '{username}': {e}")
            return None

    def list_users(self) -> List[Dict[str, Any]]:
        if not self.client:
            return []
        try:
            res = self.client.post_all_docs(db=self.db_users, include_docs=True).get_result()
            rows = res.get("rows", [])
            return [r["doc"] for r in rows if "doc" in r and not r["id"].startswith("_design")]
        except Exception as e:
            print(f"[Cloudant] Error listing users: {e}")
            return []

    def save_event(self, event_dict: Dict[str, Any]) -> None:
        """Persist an SSE audit log event envelope to ados_events."""
        if not self.client:
            return
        event_id = event_dict.get("eventId") or event_dict.get("event_id")
        doc = dict(event_dict)
        if event_id:
            doc["_id"] = event_id

        try:
            self.client.post_document(db=self.db_events, document=doc).get_result()
        except Exception as e:
            print(f"[Cloudant] Error saving audit log event: {e}")

    def get_health_status(self) -> Dict[str, Any]:
        """Returns live connection metrics, host info, document count, and latency."""
        if not self.is_configured():
            return {
                "id": "cloudant_nosql",
                "name": "IBM Cloudant NoSQL Database",
                "status": "Not Configured",
                "auth": "IBM Cloud IAM OAuth 2.0",
                "module": "knowledge/cloudant_client.py",
                "description": "Production JSON document database for persistent decision memory & event logs.",
                "capabilities": ["QueryDatabase", "PersistIncident", "StreamAuditLogs"],
                "connected": False,
                "latency_ms": 0,
                "doc_count": 0,
            }

        start_t = time.time()
        try:
            if not self.client:
                self.initialize()

            info = self.client.get_database_information(db=self.db_incidents).get_result()
            latency_ms = round((time.time() - start_t) * 1000, 1)
            doc_count = info.get("doc_count", 0)

            return {
                "id": "cloudant_nosql",
                "name": "IBM Cloudant NoSQL Database",
                "status": "Connected 🟢",
                "auth": "IBM Cloud IAM OAuth 2.0",
                "module": "knowledge/cloudant_client.py",
                "description": f"IBM Cloudant NoSQL connected ({self.url}). Live document store active.",
                "capabilities": ["QueryDatabase", "PersistIncident", "StreamAuditLogs"],
                "connected": True,
                "latency_ms": latency_ms,
                "doc_count": doc_count,
                "host": self.url.replace("https://", "").split("/")[0],
                "database_name": self.db_incidents,
            }
        except Exception as e:
            latency_ms = round((time.time() - start_t) * 1000, 1)
            return {
                "id": "cloudant_nosql",
                "name": "IBM Cloudant NoSQL Database",
                "status": f"Error: {e}",
                "auth": "IBM Cloud IAM OAuth 2.0",
                "module": "knowledge/cloudant_client.py",
                "description": f"IBM Cloudant error: {e}",
                "capabilities": ["QueryDatabase", "PersistIncident", "StreamAuditLogs"],
                "connected": False,
                "latency_ms": latency_ms,
                "doc_count": 0,
            }


    # ------------------------------------------------------------------
    # Agent Registry CRUD (ados_agents database)
    # ------------------------------------------------------------------

    def save_agent(self, agent_dict: Dict[str, Any]) -> str:
        """Persist or update a custom agent definition in Cloudant ados_agents."""
        if not self.client:
            return agent_dict.get("id", "")

        agent_id = agent_dict.get("id", "")
        doc = dict(agent_dict)
        doc["_id"] = agent_id

        # Fetch existing _rev for CouchDB update semantics
        try:
            existing = self.client.get_document(db=self.db_agents, doc_id=agent_id).get_result()
            if "_rev" in existing:
                doc["_rev"] = existing["_rev"]
        except Exception:
            pass  # New document

        try:
            res = self.client.post_document(db=self.db_agents, document=doc).get_result()
            return res.get("id", agent_id)
        except Exception as e:
            print(f"[Cloudant] Error saving agent {agent_id}: {e}")
            return agent_id

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single custom agent definition from Cloudant by ID."""
        if not self.client:
            return None
        try:
            return self.client.get_document(db=self.db_agents, doc_id=agent_id).get_result()
        except Exception:
            return None

    def list_agents(self) -> List[Dict[str, Any]]:
        """Return all custom agent definitions stored in Cloudant ados_agents."""
        if not self.client:
            return []
        try:
            res = self.client.post_all_docs(
                db=self.db_agents, include_docs=True, limit=200
            ).get_result()
            rows = res.get("rows", [])
            return [r["doc"] for r in rows if "doc" in r and not r["id"].startswith("_design")]
        except Exception as e:
            print(f"[Cloudant] Error listing agents: {e}")
            return []

    def delete_agent(self, agent_id: str) -> bool:
        """Delete a custom agent definition from Cloudant ados_agents."""
        if not self.client:
            return False
        try:
            doc = self.client.get_document(db=self.db_agents, doc_id=agent_id).get_result()
            rev = doc.get("_rev", "")
            self.client.delete_document(db=self.db_agents, doc_id=agent_id, rev=rev)
            return True
        except Exception as e:
            print(f"[Cloudant] Error deleting agent {agent_id}: {e}")
            return False

    # -------------------------------------------------------------------
    # Platform LLM provider settings (backend/app/routers/settings.py) —
    # a single fixed-ID document so there's one shared config per
    # deployment rather than per-user, mirroring how save_agent upserts
    # by ID. knowledge/local_llm_client.py reads this (short-TTL cached)
    # and layers it over the .env-based defaults.
    # -------------------------------------------------------------------
    _LLM_SETTINGS_DOC_ID = "platform_llm_providers"

    def get_llm_settings(self) -> Dict[str, Any]:
        """Returns the stored per-provider overrides, or {} if none saved
        yet / Cloudant unavailable — callers fall back to .env defaults."""
        if not self.client:
            return {}
        try:
            doc = self.client.get_document(db=self.db_settings, doc_id=self._LLM_SETTINGS_DOC_ID).get_result()
            return {k: v for k, v in doc.items() if not k.startswith("_")}
        except Exception:
            return {}

    def save_llm_provider_setting(self, provider: str, fields: Dict[str, Any]) -> None:
        """Upserts one provider's fields (e.g. {"apiKey": ..., "model": ...})
        into the shared settings document, leaving other providers' fields
        untouched. Mirrors save_agent's upsert-by-_id pattern exactly."""
        if not self.client:
            return
        doc: Dict[str, Any] = {"_id": self._LLM_SETTINGS_DOC_ID}
        try:
            existing = self.client.get_document(db=self.db_settings, doc_id=self._LLM_SETTINGS_DOC_ID).get_result()
            doc = dict(existing)
        except Exception:
            pass  # New document
        doc[provider] = {**doc.get(provider, {}), **fields}
        try:
            self.client.post_document(db=self.db_settings, document=doc).get_result()
        except Exception as e:
            print(f"[Cloudant] Error saving LLM provider setting '{provider}': {e}")

    def delete_llm_provider_setting(self, provider: str) -> None:
        """Clears one provider's stored override (falls back to .env again)."""
        if not self.client:
            return
        try:
            doc = self.client.get_document(db=self.db_settings, doc_id=self._LLM_SETTINGS_DOC_ID).get_result()
        except Exception:
            return
        if provider in doc:
            del doc[provider]
            try:
                self.client.post_document(db=self.db_settings, document=dict(doc)).get_result()
            except Exception as e:
                print(f"[Cloudant] Error deleting LLM provider setting '{provider}': {e}")


cloudant_db = CloudantClient()
