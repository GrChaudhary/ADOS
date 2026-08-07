"""
FastAPI dependency for request-scoped DB access — used by plain-CRUD
routers with no long-lived singleton involved (users, custom agents, LLM
settings). See db/README-equivalent notes in the plan this was built from
for why the two long-lived singletons (AuditTrail, CapabilityManifestRegistry)
use an injected session_factory instead of this.
"""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from .engine import async_session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
