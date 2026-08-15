"""rate_limit_events -- fixed-window rate limiting (P12)

db/models/rate_limit_event.py's own docstring has the full rationale: a
mechanism distinct from admission control's concurrency ceilings, closing
doc 18's separately-named "Rate limiting: None" gap for the one capability
that triggers a real paid LLM call and a real Docker container
(RunPrimeRLMAgent).

`ados_app` needs INSERT (record an admitted start) and SELECT (count the
current window) -- both already covered by the blanket GRANT + ALTER
DEFAULT PRIVILEGES revision f4a5b6c7d8e9 set up for every table. DELETE is
also left granted (the default) so the periodic hygiene prune can run as
`ados_app` too -- this table is not an audit trail (see the model docstring)
and pruning old rows changes nothing about correctness, only storage.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-08-13 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rate_limit_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('limiter', sa.String(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rate_limit_events')),
    )
    op.create_index(op.f('ix_rate_limit_events_limiter'), 'rate_limit_events', ['limiter'])
    op.create_index(op.f('ix_rate_limit_events_occurred_at'), 'rate_limit_events', ['occurred_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_rate_limit_events_occurred_at'), table_name='rate_limit_events')
    op.drop_index(op.f('ix_rate_limit_events_limiter'), table_name='rate_limit_events')
    op.drop_table('rate_limit_events')
