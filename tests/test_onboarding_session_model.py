"""
OnboardingSessionRow (db/models/onboarding_session.py) — raw CRUD against
real Postgres, proving the table/migration (alembic/versions/
953a70bde180_onboarding_sessions.py) round-trips correctly before any
higher-level orchestrate/onboarding/ code exists to wrap it. Mirrors
tests/test_capability_manifest_postgres.py's "requires docker compose up -d
postgres + alembic upgrade head applied to ados_test" precondition.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from db.engine import async_session_factory
from db.models.onboarding_session import OnboardingSessionRow


@pytest.fixture(autouse=True)
async def _clean_table():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE onboarding_sessions CASCADE"))
        await session.commit()
    yield


@pytest.mark.asyncio
async def test_session_round_trips_through_postgres_with_nullable_fields_unset():
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        session.add(
            OnboardingSessionRow(
                id=session_id,
                track=None,
                status="submitted",
                source_url="https://github.com/example/zendesk-mcp",
                domain=None,
                capability_id=None,
                selected_tool_name=None,
                inspection_report=None,
                synthesized_manifest=None,
                sandbox_result=None,
                audit_log=[{"turn": 1, "actor": "admin-1", "at": now.isoformat(), "detail": "submitted repo URL"}],
                created_by="admin-1",
                created_at=now,
                updated_at=now,
                failure_reason=None,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        row = (await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id))).scalar_one()
        assert row.status == "submitted"
        assert row.track is None
        assert row.capability_id is None
        assert row.audit_log == [{"turn": 1, "actor": "admin-1", "at": now.isoformat(), "detail": "submitted repo URL"}]


@pytest.mark.asyncio
async def test_session_updates_through_the_onboarding_lifecycle():
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        session.add(
            OnboardingSessionRow(
                id=session_id,
                track="mcp_native",
                status="submitted",
                source_url="https://github.com/example/zendesk-mcp",
                domain=None,
                capability_id=None,
                selected_tool_name=None,
                audit_log=[],
                created_by="admin-1",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        row = (await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id))).scalar_one()
        row.status = "synthesized"
        row.domain = "support"
        row.capability_id = "zendesk.read_ticket"
        row.selected_tool_name = "read_ticket"
        row.synthesized_manifest = {"key": "read_ticket", "estimated_cost_usd": 0.0}
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()

    async with async_session_factory() as session:
        row = (await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.id == session_id))).scalar_one()
        assert row.status == "synthesized"
        assert row.capability_id == "zendesk.read_ticket"
        assert row.synthesized_manifest == {"key": "read_ticket", "estimated_cost_usd": 0.0}


@pytest.mark.asyncio
async def test_two_sessions_can_target_the_same_source_url():
    """No uniqueness constraint on source_url — an admin retrying a failed
    onboarding attempt against the same repo must be able to start a fresh
    session, not collide with the abandoned one."""
    now = datetime.now(timezone.utc)
    for _ in range(2):
        async with async_session_factory() as session:
            session.add(
                OnboardingSessionRow(
                    id=str(uuid.uuid4()),
                    track=None,
                    status="submitted",
                    source_url="https://github.com/example/zendesk-mcp",
                    domain=None,
                    capability_id=None,
                    selected_tool_name=None,
                    audit_log=[],
                    created_by="admin-1",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

    async with async_session_factory() as session:
        rows = (
            await session.execute(select(OnboardingSessionRow).where(OnboardingSessionRow.source_url == "https://github.com/example/zendesk-mcp"))
        ).scalars().all()
        assert len(rows) == 2
