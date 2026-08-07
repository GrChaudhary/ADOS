"""
ORM model for backend/app/user_store.py — see that module for the actual
login/session logic this backs. Postgres is the only persistence path for
this domain now: main.py's lifespan already fails the app at startup if
Postgres is unreachable, so there's no remaining "not configured" case to
gracefully degrade for, unlike the knowledge/*_client.py convention this
replaces (built for genuinely optional external services).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    role: Mapped[str]
    approval_limit_usd: Mapped[float]
    password_hash: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
