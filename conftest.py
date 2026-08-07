"""
Root-level shared fixtures — applies to tests/ and backend/tests/.

Some test modules call dotenv.load_dotenv() at import time
(tests/test_asset_model.py, tests/test_operational_intelligence.py,
tests/test_phase4a_integration.py), and the shell that launches pytest may
itself have these exported (e.g. after `set -a && source .env` in a prior
manual session). Either way, real credentials end up in os.environ for
the rest of the pytest process — including NLU_API_KEY/TTS_API_KEY,
LOCAL_LLM_ENABLED/etc. knowledge/nlu_client.py, knowledge/tts_client.py,
and knowledge/local_llm_client.py all gate real network calls behind an
os.environ check for exactly this reason. This autouse fixture keeps
every one of those gates closed for every test regardless of module
import order or ambient shell state, so the suite never makes a live
NLU/TTS/Ollama call unless a test explicitly opts back in via its own
monkeypatch (see tests/test_tts_briefing.py, tests/test_phase2_integration.py's
NLU tests). A connector that reads os.environ directly on every call
(no singleton to monkeypatch) has no other gate available to it — this is
why env vars get deleted here rather than only disabled via a client
method, for any connector built that way in the future.

DATABASE_URL below is a different kind of gate, set for a different
reason: db/engine.py builds its engine from Settings() at IMPORT time
(unlike the clients above, which all re-check os.environ live on every
call), so a monkeypatch fixture fires too late — the engine would already
be pointed at whatever DATABASE_URL existed before the fixture ran. This
line has to be the literal first thing this module does, before any
import below (including `import pytest`) pulls in backend.app.config and
constructs the real Settings() singleton, so every test — DB-focused or
not — runs against ados_test, never the dev database.
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://ados:ados@localhost:5432/ados_test"

# SEED_DEMO_DATA has the same import-time constraint as DATABASE_URL above:
# backend/app/routers/memory.py builds its DecisionMemoryIndex singleton from
# Settings() at import time, so setting this later has no effect.
#
# The product default is now False (a fresh deployment starts empty rather
# than pre-loaded with executive/seed_data.py's 220 fabricated manufacturing
# incidents). The suite predates that flag and was written against a seeded
# world — every /executive/* analytic, Decision Memory search, and learning
# test asserts against those specific records. Forced on here so the flag's
# default flip changes production behaviour without silently rewriting what
# hundreds of existing tests are actually testing.
os.environ["SEED_DEMO_DATA"] = "true"

import pytest

from backend.app.rbac import Role, User, create_access_token
from knowledge.local_llm_client import local_llm_client
from knowledge.nlu_client import nlu_client
from knowledge.tts_client import tts_client


def admin_auth_header() -> dict:
    """Shared by test files under tests/ that build their own auth header
    rather than using backend/tests/conftest.py's auth_headers fixture
    (that fixture is backend/tests-scoped). Same synthetic unrestricted
    admin identity, minted directly - no /auth/login round trip, no
    user_store/database dependency."""
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
    monkeypatch.delenv("NLU_API_KEY", raising=False)
    monkeypatch.delenv("NLU_URL", raising=False)
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    monkeypatch.delenv("TTS_URL", raising=False)
    monkeypatch.delenv("TTS_INCIDENT_BRIEFING_ENABLED", raising=False)
    monkeypatch.delenv("LOCAL_LLM_ENABLED", raising=False)
    monkeypatch.setattr(nlu_client, "is_configured", lambda: False)
    monkeypatch.setattr(tts_client, "is_configured", lambda: False)
    monkeypatch.setattr(local_llm_client, "is_configured", lambda: False)
    yield
