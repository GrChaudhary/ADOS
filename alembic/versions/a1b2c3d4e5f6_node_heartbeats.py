"""node_heartbeats (dead-host reclamation)

Adds `node_heartbeats`: one row per live ADOS process host, upserted every
periodic-loop tick with its `node_id` and current time. This is the entire
persisted state the dead-host reclamation design (Model-C Decision Gate,
docs/prime-agent-integration/31-model-c-decision-gate.md, Phase 2) needs to
answer "is this host still alive" — see db/models/node_heartbeat.py's own
docstring for the full design rationale.

No backfill: a fresh table, empty until the first process tick writes its
own row. Every existing orphan_sweep.py caller that does not pass
`dead_node_ids` is entirely unaffected — this migration changes no runtime
behavior by itself.

Revision ID: a1b2c3d4e5f6
Revises: e6f7a8b9c0d1
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'node_heartbeats',
        sa.Column('node_id', sa.String(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('node_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('node_heartbeats')
