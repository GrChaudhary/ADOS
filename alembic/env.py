import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# db.models re-exports every model so Base.metadata is fully populated
# before autogenerate runs — see db/models/__init__.py.
from backend.app.config import settings
from db.base import Base
from db import models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Read from the same Settings() the app itself uses, not a hardcoded
# alembic.ini URL — one source of truth for DATABASE_URL, consistent with
# every other config value in this codebase.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables owned by langgraph-checkpoint-postgres, created by its own .setup()
# from db/checkpointer.py rather than by a migration in this directory.
#
# They are not in Base.metadata, so without this filter autogenerate reads
# them as tables that were deleted from the models and emits drop_table() for
# each one — which, applied, would destroy every paused MOA approval in the
# database. That is not hypothetical: revision 914fa0dfe821 was generated with
# exactly those four drops in it and had to be edited by hand.
_LIBRARY_OWNED_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(object, name, type_, reflected, compare_to):
    """Keeps autogenerate from touching tables this project doesn't own."""
    if type_ == "table" and name in _LIBRARY_OWNED_TABLES:
        return False
    # Indexes come through separately and would otherwise still be dropped.
    if type_ == "index" and getattr(object, "table", None) is not None:
        return object.table.name not in _LIBRARY_OWNED_TABLES
    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

    # P10: runs here, under whatever role is actually running `alembic
    # upgrade head` (the Postgres superuser in both the docker-compose
    # `migrate` service and the bare-.venv workflow) -- NOT from the app's
    # own lifespan any more. The checkpointer's tables are DDL
    # (`CREATE TABLE IF NOT EXISTS`), and the app now connects with
    # `ados_app`, a non-superuser role with no CREATE grant on the schema
    # (alembic revision f4a5b6c7d8e9) -- it could never have run this
    # itself. Safe to call unconditionally: setup() no-ops once current,
    # and every documented workflow runs `alembic upgrade head` before
    # starting the app regardless (the rest of the schema doesn't exist
    # without it either), so this adds no new precondition, only moves an
    # existing one to the role that can actually satisfy it.
    from db.checkpointer import setup_checkpointer_tables

    await setup_checkpointer_tables()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
