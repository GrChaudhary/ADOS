"""
Login + session identity — backend/app/routers/auth.py,
backend/app/rbac.py. Runs against user_store's real Postgres-backed store
(backend/tests/conftest.py truncates the users table before every test),
using a dedicated test account created fresh per test rather than the
randomly-passworded seeded demo accounts (backend/app/user_store.py's
bootstrap_users() generates those passwords at runtime; nothing captures
them for tests to log in as).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import user_store
from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from db.engine import async_session_factory


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def known_user():
    async with async_session_factory() as session:
        user = await user_store.create_user(
            session,
            username="test-login-user",
            password="correct-horse-battery-staple",
            display_name="Test Login User",
            role=Role.MANAGER,
            approval_limit_usd=100_000.0,
        )
        await session.commit()
    return user


def test_login_success(client, known_user):
    resp = client.post("/auth/login", json={"username": "test-login-user", "password": "correct-horse-battery-staple"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "test-login-user"
    assert body["user"]["role"] == "manager"
    assert body["user"]["approvalLimitUsd"] == 100_000.0
    assert body["token"]


def test_login_wrong_password_rejected(client, known_user):
    resp = client.post("/auth/login", json={"username": "test-login-user", "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_unknown_username_rejected(client):
    resp = client.post("/auth/login", json={"username": "does-not-exist", "password": "anything"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_logged_in_user(client, known_user):
    token = client.post(
        "/auth/login", json={"username": "test-login-user", "password": "correct-horse-battery-staple"}
    ).json()["token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "test-login-user"


def test_invalid_token_rejected(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


def test_user_management_requires_admin_role(client, known_user):
    # known_user is a manager, not an admin.
    token = client.post(
        "/auth/login", json={"username": "test-login-user", "password": "correct-horse-battery-staple"}
    ).json()["token"]

    resp = client.get("/auth/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_reset_password_requires_admin_role(client, known_user):
    manager_token = client.post(
        "/auth/login", json={"username": "test-login-user", "password": "correct-horse-battery-staple"}
    ).json()["token"]

    resp = client.post(
        "/auth/users/test-login-user/reset-password",
        json={"new_password": "irrelevant"},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert resp.status_code == 403


def test_reset_password_updates_login_and_preserves_user_id(client, known_user):
    admin_token = create_access_token(
        User(user_id="test-admin-2", username="test-admin-2", display_name="Test Admin 2", role=Role.ADMIN, approval_limit_usd=1.0)
    )

    resp = client.post(
        "/auth/users/test-login-user/reset-password",
        json={"new_password": "new-password-123"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # Old password no longer works, new one does, same user_id.
    old_login = client.post("/auth/login", json={"username": "test-login-user", "password": "correct-horse-battery-staple"})
    assert old_login.status_code == 401

    new_login = client.post("/auth/login", json={"username": "test-login-user", "password": "new-password-123"})
    assert new_login.status_code == 200
    assert new_login.json()["user"]["userId"] == known_user.user_id


def test_reset_password_unknown_username_404(client):
    admin_token = create_access_token(
        User(user_id="test-admin-3", username="test-admin-3", display_name="Test Admin 3", role=Role.ADMIN, approval_limit_usd=1.0)
    )
    resp = client.post(
        "/auth/users/does-not-exist/reset-password",
        json={"new_password": "x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
