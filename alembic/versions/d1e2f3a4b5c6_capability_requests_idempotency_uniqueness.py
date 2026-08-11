"""capability_requests idempotency uniqueness

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-08-12 00:00:00.000000

P9: closes a real race in `request_capability`'s idempotency check
(backend/app/mcp_gateway.py). The check was SELECT-then-INSERT, not atomic --
two genuinely concurrent calls carrying the same (session_id, idempotency_key)
could both find no prior row and both proceed, creating two rows and
potentially two real external side effects. A partial unique index makes the
database itself the backstop: the loser's INSERT fails with an IntegrityError
that the gateway catches and turns into a replay of the winner's row, exactly
as a non-concurrent duplicate already is.

Partial (WHERE idempotency_key IS NOT NULL) because historical rows and any
future row for which no key was computed must never collide with each other on
the shared `NULL` value -- Postgres already treats NULL as distinct from NULL
in an ordinary unique index, but being explicit here is cheap and documents the
intent rather than relying on that default silently.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_capability_requests_session_idempotency',
        'capability_requests',
        ['session_id', 'idempotency_key'],
        unique=True,
        postgresql_where='idempotency_key IS NOT NULL',
    )


def downgrade() -> None:
    op.drop_index('uq_capability_requests_session_idempotency', table_name='capability_requests')
