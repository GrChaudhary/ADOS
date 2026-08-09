"""
First-boot account seeding — backend/app/user_store.py's bootstrap_users().

The behaviour under test is the fix for a real lockout: seeded passwords were
always random, printed once to the console, and kept only as a bcrypt hash.
Recreating the Postgres volume therefore replaced the password everyone was
using with a new one nobody saw, and the only way back in was shell access to
the database (scripts/reset_user_password.py). settings.seed_password makes
that reproducible, and the third test below pins the property that keeps it
from becoming a backdoor.

backend/tests/conftest.py truncates the users table before every test, so the
store is empty here and bootstrap_users actually seeds.
"""

import pytest

from backend.app import user_store
from backend.app.config import settings
from backend.app.rbac import Role, verify_password
from db.engine import async_session_factory
from db.models.users import UserRow
from sqlalchemy import select


async def _hash_for(username: str) -> str:
    async with async_session_factory() as session:
        row = (await session.execute(select(UserRow).where(UserRow.username == username))).scalar_one()
        return row.password_hash


async def _bootstrap() -> dict:
    async with async_session_factory() as session:
        generated = await user_store.bootstrap_users(session)
        await session.commit()
    return generated


@pytest.mark.asyncio
async def test_seed_password_is_used_for_every_account(monkeypatch):
    monkeypatch.setattr(settings, "seed_password", "known-pilot-password")

    generated = await _bootstrap()

    assert set(generated) == {a["username"] for a in user_store.SEED_ACCOUNTS}
    for account in user_store.SEED_ACCOUNTS:
        username = account["username"]
        assert generated[username] == "known-pilot-password"
        # Reported and stored must agree — the whole failure mode being fixed
        # is a password that is announced but doesn't actually work.
        assert verify_password("known-pilot-password", await _hash_for(username))


@pytest.mark.asyncio
async def test_unset_seed_password_still_generates_a_distinct_random_one(monkeypatch):
    """The safe default is preserved: no fixed password appears anywhere
    unless an operator opts in."""
    monkeypatch.setattr(settings, "seed_password", "")

    generated = await _bootstrap()

    assert len(set(generated.values())) == len(generated), "accounts must not share one random password"
    for username, password in generated.items():
        assert len(password) >= 12
        assert verify_password(password, await _hash_for(username))


@pytest.mark.asyncio
async def test_seed_password_cannot_overwrite_an_existing_account(monkeypatch):
    """Setting SEED_PASSWORD on an instance that already has users must not
    grant access to them — otherwise it would be a way to reset any deployed
    instance's admin password by editing .env and restarting."""
    async with async_session_factory() as session:
        await user_store.create_user(
            session,
            username="admin",
            password="the-real-admin-password",
            display_name="System Administrator",
            role=Role.ADMIN,
            approval_limit_usd=1_000_000_000.0,
        )
        await session.commit()

    monkeypatch.setattr(settings, "seed_password", "attacker-chosen")
    assert await _bootstrap() is None, "seeding must be skipped when any user exists"

    stored = await _hash_for("admin")
    assert verify_password("the-real-admin-password", stored)
    assert not verify_password("attacker-chosen", stored)
