"""
P17 — the tenant identity ADOS previously had none of (see P16's
docs/prime-agent-integration/27-multi-tenancy-and-multi-host-safety.md,
which proved this live). Two tables, deliberately minimal:

    TenantRow             a real organizational boundary
    TenantMembershipRow   which users belong to which tenants

No per-tenant role: `UserRow.role` (backend/app/rbac.py) stays global,
answering "what is this user capable of" — tenancy answers a different
question, "which resources can this user reach at all". Conflating the two
would mean either inventing per-tenant roles (a real IAM system this phase
was explicitly told not to build) or reusing one flat role across every
tenant a user belongs to (the actual, simpler choice made here, matching
the JWT's existing stateless-role precedent from P10).

See db/tenancy.py for how these are enforced, and
docs/prime-agent-integration/28-multi-tenancy-and-tenant-isolation.md for
the full design.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: The tenant every pre-P17 row (and every row/test that constructs a
#: tenant-owned model without specifying one) belongs to. Lives here, not
#: in db/tenancy.py, so both db/tenancy.py (the enforcement mechanism) and
#: db/models/mission.py (the tenant-owned models, which use this as their
#: own column default) can import it without a circular import between
#: those two modules. The migration that backfills existing rows
#: (alembic/versions/e6f7a8b9c0d1_...) hardcodes this exact same literal
#: independently, since a migration must not depend on application code.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class TenantRow(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class TenantMembershipRow(Base):
    """Which users belong to which tenants. A user with zero rows here
    belongs to nothing and (see db/tenancy.py's fail-closed default) can
    reach no tenant-owned resource at all — not even by accident."""

    __tablename__ = "tenant_memberships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
