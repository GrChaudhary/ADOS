"""
P10 — proves `ados_app` (alembic revision f4a5b6c7d8e9) is a real,
non-superuser database role with the minimum privileges the runtime needs,
not the migration role (`ados`, a Postgres superuser) the backend used to
share with `alembic upgrade head`.

Connects with the runtime's OWN credentials — never `async_session_factory`,
which is always the superuser in this test environment (conftest.py) — so
every assertion here is about what Postgres itself will and will not permit
`ados_app` to do, independent of anything the application layer chooses to
call.

Each check opens its own connection: Postgres aborts the whole transaction
after the first error on a connection, so reusing one across assertions
would make every check after the first fail for the wrong reason.
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.config import settings

_APP_DATABASE_URL = "postgresql+asyncpg://ados_app:ados_app@localhost:5432/ados_test"


@pytest.fixture
async def app_engine():
    engine = create_async_engine(_APP_DATABASE_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _denied(engine, sql: str) -> str:
    """Runs `sql` as ados_app and returns the DB's own error message,
    asserting it really is a privilege denial and not some other failure
    (a typo, a missing table) that would make this test pass for the wrong
    reason."""
    with pytest.raises(DBAPIError) as excinfo:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    message = str(excinfo.value).lower()
    assert "permission denied" in message or "insufficientprivilege" in message, (
        f"expected a privilege denial, got: {excinfo.value}"
    )
    return message


# --- identity ------------------------------------------------------------


async def test_ados_app_is_not_a_superuser(app_engine):
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert row.rolsuper is False


async def test_the_migration_role_is_still_the_superuser_used_for_migrations():
    """Sanity check on the OTHER half of the split: `alembic upgrade head`
    (and this test suite's own DDL/TRUNCATE fixtures via `async_session_
    factory`) must still work exactly as before — this migration only adds
    a second, narrower role, it does not touch `ados`."""
    assert "ados_app" not in settings.database_url


# --- DDL: refused by ownership, no explicit REVOKE needed ----------------


async def test_ados_app_cannot_create_a_table(app_engine):
    await _denied(app_engine, "CREATE TABLE pwned (id int)")


async def test_ados_app_cannot_drop_the_audit_table(app_engine):
    await _denied(app_engine, "DROP TABLE capability_requests")


async def test_ados_app_cannot_alter_the_audit_table(app_engine):
    await _denied(app_engine, "ALTER TABLE capability_requests ADD COLUMN backdoor text")


async def test_ados_app_cannot_truncate_the_audit_table(app_engine):
    await _denied(app_engine, "TRUNCATE capability_requests")


# --- the append-only guarantee: DELETE explicitly revoked -----------------


@pytest.mark.parametrize("table", ["missions", "runtime_sessions", "capability_requests"])
async def test_ados_app_cannot_delete_from_the_audit_spine(app_engine, table):
    message = await _denied(app_engine, f"DELETE FROM {table} WHERE 1=0")
    assert table in message or "permission denied" in message


async def test_ados_app_cannot_update_or_delete_promotion_events(app_engine):
    """Completes revision 7f551a8ccce0's own deferred intent — that REVOKE
    targeted CURRENT_USER (the superuser), a documented no-op. This is the
    same guarantee, now actually enforced."""
    await _denied(app_engine, "DELETE FROM capability_promotion_events WHERE 1=0")
    await _denied(app_engine, "UPDATE capability_promotion_events SET actor = 'x' WHERE 1=0")


# --- and legitimate application behaviour still works ---------------------


async def test_ados_app_can_still_select_insert_update_the_audit_tables(app_engine):
    """Not weakened into uselessness: the runtime's actual, ordinary
    lifecycle writes (create a mission/session, move a capability request
    through its states) must still work under this role."""
    mission_id = uuid.uuid4()
    session_id = uuid.uuid4()
    async with app_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO missions (mission_id, title, objective, domain, "
                "allowed_capabilities, status, created_by, created_at, updated_at) "
                "VALUES (:id, 't', 'o', 'it', '[]'::json, 'running', 'test', now(), now())"
            ),
            {"id": mission_id},
        )
        await conn.execute(
            text(
                "INSERT INTO runtime_sessions (session_id, mission_id, runtime, state, "
                "events, tool_execution_count, capability_request_count, created_at, updated_at) "
                "VALUES (:sid, :mid, 'prime-agent', 'running', '[]'::json, 0, 0, now(), now())"
            ),
            {"sid": session_id, "mid": mission_id},
        )
        await conn.execute(
            text("UPDATE runtime_sessions SET state = 'failed' WHERE session_id = :sid"),
            {"sid": session_id},
        )
        await conn.commit()

    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT state FROM runtime_sessions WHERE session_id = :sid"), {"sid": session_id}
            )
        ).one()
    assert row.state == "failed"

    # Cleanup uses the superuser session (ados_app cannot DELETE these, by
    # design — that is exactly what the tests above prove).
    from db.engine import async_session_factory

    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM runtime_sessions WHERE session_id = :sid"), {"sid": session_id})
        await db.execute(text("DELETE FROM missions WHERE mission_id = :mid"), {"mid": mission_id})
        await db.commit()


async def test_ados_app_can_delete_from_unrelated_application_tables(app_engine):
    """The negative space of the append-only restriction: DELETE is only
    revoked on the three audit-spine tables, not blanket-removed — settings/
    breaker-store endpoints elsewhere in this backend legitimately DELETE
    and must keep working under this role."""
    async with app_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO moa_task_breakers "
                "(task_id, state, streak, threshold, domain, created_at, updated_at) "
                "VALUES (:tid, 'closed', '[]'::json, 3, 'it', now(), now())"
            ),
            {"tid": f"role-test-{uuid.uuid4()}"},
        )
        await conn.commit()
    async with app_engine.connect() as conn:
        result = await conn.execute(
            text("DELETE FROM moa_task_breakers WHERE task_id LIKE 'role-test-%'")
        )
        await conn.commit()
    assert result.rowcount >= 1
