"""moa task cascade breakers

Durable per-task cascade circuit breaker state (db/models/moa_task_breaker.py),
replacing the process-local app.state.moa_pending_tasks dict so a paused MOA
approval keeps its streak across a restart and across replicas.

NOTE — autogenerate produced more than this. It also emitted drop_table() for
`checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and
`checkpoint_migrations`, because those are created by
langgraph-checkpoint-postgres' own .setup() (db/checkpointer.py) and so are
absent from Base.metadata, which makes them look like tables someone deleted
from the models. Applying that would have destroyed every paused approval in
the database. Those statements are deliberately removed here, and
alembic/env.py now filters the tables out so no future autogenerate can
reintroduce them.

Revision ID: 914fa0dfe821
Revises: e7b8c9d0f1a2
Create Date: 2026-08-09 12:23:56.905438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '914fa0dfe821'
down_revision: Union[str, Sequence[str], None] = 'e7b8c9d0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'moa_task_breakers',
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('streak', sa.JSON(), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('task_id', name=op.f('pk_moa_task_breakers')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('moa_task_breakers')
