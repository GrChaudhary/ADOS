"""
Postgres-backed LangGraph checkpointer — what makes a paused MOA/ITSM
approval survive a restart, and what lets a second replica resume a task it
did not start.

See docs/DESIGN_DURABLE_MOA_STATE.md for why the official
langgraph-checkpoint-postgres was chosen over hand-rolling BaseCheckpointSaver
(9 abstract methods, including undocumented internal versioning, guarding the
state we least want corrupted).

TWO CONNECTION FACTS THIS MODULE EXISTS TO HANDLE:

1. **psycopg, not asyncpg.** The rest of the app talks to Postgres through
   SQLAlchemy + asyncpg; this checkpointer requires psycopg 3. So the same
   database is reached over two drivers, and DATABASE_URL's
   "postgresql+asyncpg://" prefix has to be translated to the plain
   "postgresql://" libpq form. That is `psycopg_dsn()` below.

2. **No long-lived pool — a fresh connection per use.** This mirrors, for the
   same reason, the NullPool decision documented at length in db/engine.py:
   an async connection is bound to the event loop that opened it, and reusing
   it from a different loop raises "attached to a different loop" / "Event
   loop is closed". That is not a test artifact -- pytest-asyncio gives each
   async test its own loop, and FastAPI's TestClient runs the app through a
   separate internal anyio portal even for sync tests. A pooled
   AsyncPostgresSaver held on app.state would break across ordinary test runs
   and, in production, across anything that touches more than one loop.

   The cost is one connection setup per MOA request. That is the same
   tradeoff db/engine.py already accepted, at the same traffic scale, for the
   same correctness reason.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.app.config import settings


def psycopg_dsn() -> str:
    """DATABASE_URL rewritten for psycopg/libpq.

    SQLAlchemy wants a driver-qualified URL ("postgresql+asyncpg://..."),
    libpq wants a plain one. Derived from the single DATABASE_URL rather than
    introducing a second setting, so the two drivers can never be pointed at
    different databases by a half-updated .env -- which would be a genuinely
    nasty failure: checkpoints written somewhere the rest of the app can't
    see.
    """
    dsn = settings.database_url
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix):]
    return dsn


@asynccontextmanager
async def checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """A checkpointer bound to this call's event loop.

    Use per request, around graph construction AND invocation -- the saver
    must outlive the ainvoke() that reads and writes through it:

        async with checkpointer() as saver:
            graph = build_graph(hub, breaker, checkpointer=saver)
            result = await graph.ainvoke(...)
    """
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn()) as saver:
        yield saver


async def setup_checkpointer_tables() -> None:
    """Creates the checkpointer's four tables if absent
    (checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations).

    Called once from main.py's lifespan. These tables are managed by the
    library's own migration mechanism, NOT by Alembic -- a deliberate split
    worth knowing about when reasoning about schema provenance: `alembic
    upgrade head` alone does not fully prepare a database for this app.
    Re-running is safe; it no-ops when already current.
    """
    async with checkpointer() as saver:
        await saver.setup()
