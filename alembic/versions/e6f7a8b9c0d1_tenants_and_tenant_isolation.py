"""tenants and tenant_id columns (P17)

Real tenant identity, where none existed before (P16 proved this live --
docs/prime-agent-integration/27-multi-tenancy-and-multi-host-safety.md).
Two new tables (`tenants`, `tenant_memberships`), plus a `tenant_id`
column on the three tables db/tenancy.py enforces against:
`missions`, `runtime_sessions`, `capability_requests`.

BACKFILL STRATEGY -- explicit, safe, three steps in one migration (this
codebase's migrations are not zero-downtime-constrained; db/engine.py's
own docstring already documents "single-deployment, not a high-QPS
multi-tenant SaaS"):

  1. Seed exactly one well-known tenant, DEFAULT_TENANT_ID (the same
     literal UUID db/tenancy.py hardcodes, so code and schema always
     agree without a runtime lookup). Every pre-existing user is enrolled
     as a member of it -- nobody who could already log in and act loses
     access to anything they could already reach; there was only ever
     one tenant's worth of data before this migration.
  2. Add tenant_id as NULLABLE on the three tables, backfill every
     existing row to DEFAULT_TENANT_ID, then ALTER to NOT NULL. A
     genuinely empty table (a fresh clone before any mission has run)
     skips the backfill UPDATE trivially.
  3. Nothing about `custom_agents`, `incidents`, or any other table is
     touched -- P17 deliberately scoped tenant isolation to the exact
     Prime Agent runtime governance surface P16's live proof exploited,
     not a blanket retrofit. See doc 28 for that scope decision in full.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must match db.tenancy.DEFAULT_TENANT_ID exactly.
_DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('tenant_id', name=op.f('pk_tenants')),
        sa.UniqueConstraint('slug', name=op.f('uq_tenants_slug')),
    )
    op.create_table(
        'tenant_memberships',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_memberships')),
        sa.UniqueConstraint('tenant_id', 'user_id', name=op.f('uq_tenant_memberships_tenant_id')),
    )

    op.execute(
        f"""
        INSERT INTO tenants (tenant_id, name, slug, created_at)
        VALUES ('{_DEFAULT_TENANT_ID}', 'Default', 'default', now())
        """
    )
    op.execute(
        f"""
        INSERT INTO tenant_memberships (id, tenant_id, user_id, created_at)
        SELECT gen_random_uuid(), '{_DEFAULT_TENANT_ID}', user_id, now()
        FROM users
        """
    )

    for table in ('missions', 'runtime_sessions', 'capability_requests'):
        op.add_column(table, sa.Column('tenant_id', sa.Uuid(), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = '{_DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL")
        op.alter_column(table, 'tenant_id', nullable=False)


def downgrade() -> None:
    for table in ('missions', 'runtime_sessions', 'capability_requests'):
        op.drop_column(table, 'tenant_id')
    op.drop_table('tenant_memberships')
    op.drop_table('tenants')
