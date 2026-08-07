"""add thinking_enabled to llm_provider_settings

Revision ID: e7b8c9d0f1a2
Revises: fdc5105d8038
Create Date: 2026-08-07 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b8c9d0f1a2'
down_revision: Union[str, Sequence[str], None] = '9066dad719e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'llm_provider_settings',
        sa.Column('thinking_enabled', sa.Boolean(), server_default='false', nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('llm_provider_settings', 'thinking_enabled')
