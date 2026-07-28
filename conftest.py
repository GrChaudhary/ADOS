"""
Root-level shared fixtures — applies to tests/ and backend/tests/.

Some test modules call dotenv.load_dotenv() at import time
(tests/test_asset_model.py, tests/test_operational_intelligence.py,
tests/test_phase4a_integration.py), and the shell that launches pytest may
itself have these exported (e.g. after `set -a && source .env` in a prior
manual session). Either way, real credentials end up in os.environ for
the rest of the pytest process — including CLOUDANT_URL/CLOUDANT_API_KEY,
NLU_API_KEY/TTS_API_KEY, LOCAL_LLM_ENABLED/etc. knowledge/cloudant_client.py,
knowledge/nlu_client.py, knowledge/tts_client.py, and
knowledge/local_llm_client.py all gate real network calls behind an
os.environ check for exactly this reason. This autouse fixture keeps
every one of those gates closed for every test regardless of module
import order or ambient shell state, so the suite never makes a live
Cloudant/NLU/TTS/Ollama/watsonx-ITSM call unless a test explicitly opts
back in via its own monkeypatch (see tests/test_audit_trail_cloudant.py,
tests/test_tts_briefing.py, tests/test_phase2_integration.py's NLU
tests, tests/test_itsm_connector.py). This isn't hypothetical, twice
over: this fixture originally only covered NLU/TTS, a Cloudant leak
caused backend/app/routers/incidents.py's evt.producedBy bug to surface
non-deterministically, and — most seriously — once WO_ITSM_LIVE_WRITES_
ENABLED was added to .env this same session, the exact same leak made
orchestrator-driving tests actually eligible to fire a REAL ServiceNow
ticket via the live watsonx Orchestrate agent (WatsonxITSMConnector
reads os.environ directly on every call, no singleton to monkeypatch —
deleting the env vars is the only gate available to it). See git
history; this is why every WO_ITSM_* var is deleted below, not just
disabled via a client method.
"""

import pytest

from backend.app.rbac import Role, User, create_access_token
from knowledge.cloudant_client import cloudant_db
from knowledge.local_llm_client import local_llm_client
from knowledge.nlu_client import nlu_client
from knowledge.tts_client import tts_client


def admin_auth_header() -> dict:
    """Shared by test files under tests/ that build their own auth header
    rather than using backend/tests/conftest.py's auth_headers fixture
    (that fixture is backend/tests-scoped). Same synthetic unrestricted
    admin identity, minted directly - no /auth/login round trip, no
    user_store/Cloudant dependency."""
    admin = User(
        user_id="test-admin",
        username="test-admin",
        display_name="Test Admin",
        role=Role.ADMIN,
        approval_limit_usd=1_000_000_000.0,
    )
    return {"Authorization": f"Bearer {create_access_token(admin)}"}


@pytest.fixture(autouse=True)
def _no_live_external_services_by_default(monkeypatch):
    monkeypatch.delenv("CLOUDANT_URL", raising=False)
    monkeypatch.delenv("CLOUDANT_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDANT_USERNAME", raising=False)
    monkeypatch.delenv("NLU_API_KEY", raising=False)
    monkeypatch.delenv("NLU_URL", raising=False)
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    monkeypatch.delenv("TTS_URL", raising=False)
    monkeypatch.delenv("TTS_INCIDENT_BRIEFING_ENABLED", raising=False)
    monkeypatch.delenv("LOCAL_LLM_ENABLED", raising=False)
    monkeypatch.delenv("WO_INSTANCE", raising=False)
    monkeypatch.delenv("WO_API_KEY", raising=False)
    monkeypatch.delenv("WO_ITSM_INTEGRATION_ENABLED", raising=False)
    monkeypatch.delenv("WO_ITSM_LIVE_WRITES_ENABLED", raising=False)
    monkeypatch.setattr(cloudant_db, "is_configured", lambda: False)
    monkeypatch.setattr(nlu_client, "is_configured", lambda: False)
    monkeypatch.setattr(tts_client, "is_configured", lambda: False)
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: False)
    yield
