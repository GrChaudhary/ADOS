import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from db.engine import async_session_factory
from db.tenancy import use_all_tenants
from knowledge.local_llm_client import local_llm_client


@pytest.fixture(autouse=True)
def _default_all_tenants_scope():
    """P17 — db/tenancy.py fails closed by default (no tenant context ==
    zero rows of any tenant-scoped table), which is exactly right for a
    real request but wrong for the ~900 pre-existing tests in this suite
    that construct/read MissionRow, RuntimeSessionRow, and
    CapabilityRequestRow directly to test something else entirely
    (concurrency, idempotency, reconciliation, ...) and have never had any
    reason to think about tenant scoping.

    This autouse fixture gives every test that same "operate across all
    tenants" posture db/tenancy.py already grants background jobs and
    scripts/mcp_gateway.py, by default -- the same posture a test's own
    setup/teardown SQL already effectively has (TRUNCATE, direct row
    construction). It does NOT weaken tenant-isolation testing: a real
    HTTP request through backend/app/tenancy.py::get_tenant_context calls
    use_tenant(...), which -- via contextvars' normal nesting -- correctly
    SHADOWS this outer ALL_TENANTS for the duration of that one request,
    then reverts back on exit. Every P17 test that specifically proves
    cross-tenant isolation (backend/tests/test_tenant_isolation.py) relies
    on precisely that nesting, not on this fixture being absent.
    """
    with use_all_tenants():
        yield


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
async def _clean_moa_task_breakers_table():
    """Paused-MOA-task state used to live in app.state.moa_pending_tasks,
    which TestClient's lifespan rebuilt for every test, so isolation came
    free. It is now a real table (backend/app/moa_breaker_store.py), so a
    task left paused by one test would otherwise still count as "live" in
    the next one's GET /governance/circuit-breaker aggregate — which is
    exactly how these tests started failing only when run as a file."""
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE moa_task_breakers CASCADE"))
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
