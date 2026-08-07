"""
Declarative base + naming convention for every db/models/ table. The
naming convention gives Alembic autogenerate stable, predictable
constraint/index names (e.g. `ix_incidents_plant_id`) instead of
driver-generated ones that vary run to run and are painful to reference
in a downgrade.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Every `Mapped[datetime]` column is timezone-aware by default (Postgres
    # TIMESTAMPTZ) — every datetime this codebase actually constructs is
    # `datetime.now(timezone.utc)` (aware), and asyncpg refuses to bind an
    # aware value into a naive-typed column, which SQLAlchemy's own
    # `Mapped[datetime]` default (TIMESTAMP WITHOUT TIME ZONE) would be.
    # Set once here instead of `mapped_column(DateTime(timezone=True))`
    # everywhere, so it can't be forgotten model by model.
    type_annotation_map = {datetime: DateTime(timezone=True)}
