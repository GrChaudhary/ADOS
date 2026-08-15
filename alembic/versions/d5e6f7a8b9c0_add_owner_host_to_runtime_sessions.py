"""add owner_host to runtime_sessions (P16)

Records which ADOS process host created a session's real Docker/workspace
resources. orphan_sweep.py's claim_batch uses this to refuse claiming a
session it did not create: a sweeper can only verify a resource's real
absence against the local Docker daemon and local filesystem it actually
has, so a session created on a different host must never be concluded
"absent" just because it is invisible from here. See
db/models/mission.py's RuntimeSessionRow.owner_host and
docs/prime-agent-integration/27-multi-tenancy-and-multi-host-safety.md.

Nullable, no backfill: every pre-existing row gets NULL, which
claim_batch treats as "claimable by any sweeper" -- the same behavior
this codebase already has today (single-host only), so this migration
changes no runtime behavior by itself.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('runtime_sessions', sa.Column('owner_host', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('runtime_sessions', 'owner_host')
