"""
Module-level engine + session factory, eager at import time — safe,
because SQLAlchemy engines are lazy (no connection opens until first use).
Same eager-singleton pattern the old (now-removed) Cloudant client used.

NullPool, deliberately, not a real connection pool: an eagerly-constructed
module singleton engine gets used from whichever asyncio event loop
happens to be running when a query fires, and a real pool would hand out
a connection whose underlying asyncpg transport is bound to whichever
loop first checked it out — reused from a *different* loop later raises
"attached to a different loop" / "Event loop is closed". This is a real
condition, not just a test artifact: pytest-asyncio gives async def tests
their own event loop per test by default, and FastAPI's TestClient runs
the ASGI app through a *separate* internal loop (an anyio blocking
portal) even for synchronous test functions — so a real pool breaks
across ordinary test runs, not just unusual ones. NullPool opens a fresh
connection per checkout and closes it on checkin, so there's never a
connection object straddling two loops. Given ADOS's actual traffic scale
(single-deployment, not a high-QPS multi-tenant SaaS), the per-query
connection-setup cost this trades away is a reasonable, deliberate
tradeoff for correctness — revisit if/when real load ever makes pooling
matter.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.config import settings

engine: AsyncEngine = create_async_engine(settings.database_url, poolclass=NullPool)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# P17 — importing this here (rather than trusting some later call site to
# do it first) registers db/tenancy.py's do_orm_execute tenant filter
# before any session from the factory above can run a query. Every module
# that reaches the database already imports this one.
from db import tenancy as _tenancy  # noqa: E402,F401
