import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from db.engine import async_session_factory
from knowledge.local_llm_client import local_llm_client


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
async def _clean_users_table():
    """Postgres enforces a real UNIQUE constraint on username, unlike the
    old in-memory dict (keyed by username, silently overwritten on a
    second create_user() with the same name) — so tests that create a
    fixed-name user (test_auth.py's known_user) need real isolation
    between runs, not just within-process dict reuse."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _clean_custom_agents_table():
    """Same isolation reasoning as _clean_users_table, for
    test_agents_registry.py's created-agent-persists-and-is-listed tests."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE custom_agents CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _clean_capability_manifests_table():
    """Same isolation reasoning as _clean_users_table, for
    test_capabilities.py's manifest tests — propose() raises PolicyViolation
    ("already registered") on a repeated capability_id, and nothing else
    truncates these tables between runs."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE capability_promotion_events, capability_manifests CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _clean_onboarding_sessions_table():
    """Same isolation reasoning as _clean_users_table, for
    test_capability_onboarding.py's session tests."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE onboarding_sessions CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _clean_llm_provider_settings_table():
    """Same isolation reasoning as _clean_users_table, for
    test_settings.py — also resets local_llm_client's in-memory cache,
    since it's a module-level singleton shared across the whole test
    process and would otherwise leak a saved key from one test into the
    next (see knowledge/local_llm_client.py's hydrate_settings_cache)."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE llm_provider_settings CASCADE"))
        await session.commit()
    local_llm_client.hydrate_settings_cache({})
    yield


@pytest.fixture
def auth_headers():
    # Minted directly (no /auth/login round trip, no Cloudant/in-memory
    # user_store dependency) for a synthetic admin identity - unrestricted
    # role + approval limit, so existing tests that predate RBAC and don't
    # care about role/limit enforcement keep working unchanged. Tests that
    # specifically exercise RBAC build their own token via the same
    # create_access_token() helper (see test_rbac_approvals.py).
    admin = User(
        user_id="test-admin",
        username="test-admin",
        display_name="Test Admin",
        role=Role.ADMIN,
        approval_limit_usd=1_000_000_000.0,
    )
    return {"Authorization": f"Bearer {create_access_token(admin)}"}
