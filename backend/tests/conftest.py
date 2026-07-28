import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


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
