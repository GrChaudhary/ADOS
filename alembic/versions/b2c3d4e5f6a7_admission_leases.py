"""admission_leases -- globally-coordinated admission control (P12)

db/models/admission_lease.py's own docstring has the full rationale: P11's
two in-process AdmissionControl gates (capability/mission concurrency) do
not extend across processes, and P12 found this is a real gap for a
long-running production service. This table is the Postgres-backed slot
each gate now claims/releases, so the configured ceiling is enforced no
matter how many ADOS processes are querying it.

`ados_app` needs INSERT/SELECT/DELETE here (acquire = insert, count =
select, release = delete) -- all three are already covered by the blanket
GRANT + ALTER DEFAULT PRIVILEGES revision f4a5b6c7d8e9 set up for every
table, present and future. No DELETE revocation here, deliberately: this is
not an audit table (see the model docstring for why it must not be
conflated with one), and refusing DELETE would break the release path
entirely.

Revision ID: b2c3d4e5f6a7
Revises: f4a5b6c7d8e9
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'admission_leases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('gate', sa.String(), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('holder', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admission_leases')),
    )
    # The hot-path query on every acquire is COUNT(*) WHERE gate = :gate,
    # under the same advisory lock the approval-queue gate already uses
    # (mcp_gateway.py) -- an index keeps that count cheap regardless of how
    # many stale/live leases accumulate between reclaim passes.
    op.create_index(op.f('ix_admission_leases_gate'), 'admission_leases', ['gate'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_admission_leases_gate'), table_name='admission_leases')
    op.drop_table('admission_leases')
